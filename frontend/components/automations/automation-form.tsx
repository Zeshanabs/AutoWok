"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { DryRunPanel } from "@/components/automations/dry-run-panel";
import { ApiError, apiRequest } from "@/lib/api";
import type { WorkspaceMember } from "@/lib/auth-types";
import type { Brand } from "@/lib/brand-types";
import {
  LIST_OPERATORS,
  OPERATOR_LABELS,
  VALUELESS_OPERATORS,
  isConditionGroup,
  type ActionInput,
  type ActionSpec,
  type Automation,
  type AutomationDefinition,
  type Catalog,
  type ConditionRule,
  type DryRunResult,
  type JsonSchemaProperty,
  type TriggerField,
  type TriggerSpec,
  type ValidationResult,
} from "@/lib/automation-types";

const fieldClass = "w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-indigo-500";
const labelClass = "block text-xs font-medium text-slate-600";
const USER_FIELDS = new Set(["user_id", "assignee_user_id"]);

type Props = {
  workspaceId: string;
  initial?: Automation | null;
  onSaved: (automation: Automation) => void;
};

type RuleDraft = { field: string; operator: string; value: string };

function schemaType(property: JsonSchemaProperty): { kind: "string" | "integer" | "boolean" | "enum" | "uuid"; options: string[]; nullable: boolean } {
  const variants = property.anyOf ?? [property];
  let kind: "string" | "integer" | "boolean" | "enum" | "uuid" = "string";
  let options: string[] = [];
  let nullable = false;
  for (const variant of variants) {
    if (variant.type === "null") nullable = true;
    else if (variant.enum) {
      kind = "enum";
      options = variant.enum;
    } else if (variant.type === "integer" || variant.type === "number") kind = "integer";
    else if (variant.type === "boolean") kind = "boolean";
    else if (variant.format === "uuid") kind = "uuid";
  }
  if (property.enum) {
    kind = "enum";
    options = property.enum;
  }
  return { kind, options, nullable };
}

function toRuleDrafts(group: Automation["conditions"] | undefined): { logic: "and" | "or"; rules: RuleDraft[] } {
  if (!group) return { logic: "and", rules: [] };
  const rules: RuleDraft[] = [];
  for (const rule of group.rules) {
    if (isConditionGroup(rule)) continue; // nested groups are supported by the API; the builder edits flat rules
    const value = Array.isArray(rule.value) ? rule.value.join(", ") : rule.value === undefined || rule.value === null ? "" : String(rule.value);
    rules.push({ field: rule.field, operator: rule.operator, value });
  }
  return { logic: group.logic, rules };
}

function ruleValue(field: TriggerField | undefined, operator: string, raw: string): unknown {
  if (VALUELESS_OPERATORS.has(operator)) return undefined;
  const parse = (text: string): unknown => {
    const trimmed = text.trim();
    if (!field) return trimmed;
    if (field.type === "number") return trimmed === "" ? trimmed : Number(trimmed);
    if (field.type === "boolean") return trimmed.toLowerCase() === "true";
    return trimmed;
  };
  if (LIST_OPERATORS.has(operator)) {
    return raw.split(",").map((item) => parse(item)).filter((item) => item !== "");
  }
  return parse(raw);
}

export function AutomationForm({ workspaceId, initial, onSaved }: Props) {
  const { user } = useAuth();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [brandId, setBrandId] = useState(initial?.brand_id ?? "");
  const [triggerType, setTriggerType] = useState(initial?.trigger_type ?? "");
  const [triggerConfig, setTriggerConfig] = useState<Record<string, string>>(
    Object.fromEntries(Object.entries(initial?.trigger_configuration ?? {}).map(([key, value]) => [key, String(value)])),
  );
  const [logic, setLogic] = useState<"and" | "or">(toRuleDrafts(initial?.conditions).logic);
  const [rules, setRules] = useState<RuleDraft[]>(toRuleDrafts(initial?.conditions).rules);
  const [actions, setActions] = useState<ActionInput[]>(
    initial?.actions.map((action) => ({ action_type: action.action_type, configuration: { ...action.action_configuration } })) ?? [],
  );
  const [maxExecutions, setMaxExecutions] = useState(initial?.max_executions ? String(initial.max_executions) : "");
  const [cooldown, setCooldown] = useState(String(initial?.cooldown_seconds ?? 0));
  const [error, setError] = useState<string | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [dryRun, setDryRun] = useState<DryRunResult | null>(null);
  const [busy, setBusy] = useState<"save" | "test" | "validate" | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([
      apiRequest<Catalog>(`/workspaces/${workspaceId}/automations/catalog`),
      apiRequest<WorkspaceMember[]>(`/workspaces/${workspaceId}/members`),
      apiRequest<Brand[]>(`/workspaces/${workspaceId}/brands`).catch(() => [] as Brand[]),
    ])
      .then(([catalogData, memberData, brandData]) => {
        if (!active) return;
        setCatalog(catalogData);
        setMembers(memberData);
        setBrands(brandData);
      })
      .catch((loadError: unknown) => {
        if (active) setError(loadError instanceof ApiError ? loadError.message : "The automation catalogue could not be loaded.");
      });
    return () => {
      active = false;
    };
  }, [workspaceId]);

  const trigger: TriggerSpec | undefined = useMemo(() => catalog?.triggers.find((item) => item.type === triggerType), [catalog, triggerType]);
  const availableActions: ActionSpec[] = useMemo(
    () => (catalog?.actions ?? []).filter((action) => !triggerType || !action.allowed_triggers || action.allowed_triggers.includes(triggerType)),
    [catalog, triggerType],
  );

  const definition = useCallback((): AutomationDefinition => {
    const configuration: Record<string, unknown> = {};
    for (const field of trigger?.configuration_fields ?? []) {
      const raw = triggerConfig[field.name];
      if (raw !== undefined && raw !== "") configuration[field.name] = field.type === "number" ? Number(raw) : raw;
    }
    return {
      name: name.trim(),
      description: description.trim() || null,
      brand_id: brandId || null,
      trigger_type: triggerType,
      trigger_configuration: configuration,
      conditions: {
        logic,
        rules: rules.map((rule): ConditionRule => {
          const field = trigger?.fields.find((item) => item.name === rule.field);
          const value = ruleValue(field, rule.operator, rule.value);
          return value === undefined ? { field: rule.field, operator: rule.operator } : { field: rule.field, operator: rule.operator, value };
        }),
      },
      actions,
      max_executions: maxExecutions ? Number(maxExecutions) : null,
      cooldown_seconds: Number(cooldown) || 0,
    };
  }, [actions, brandId, cooldown, description, logic, maxExecutions, name, rules, trigger, triggerConfig, triggerType]);

  const changeTrigger = (value: string) => {
    setTriggerType(value);
    setRules([]);
    setTriggerConfig({});
    setActions((current) =>
      current.filter((action) => {
        const spec = catalog?.actions.find((item) => item.type === action.action_type);
        return !spec?.allowed_triggers || spec.allowed_triggers.includes(value);
      }),
    );
    setDryRun(null);
    setValidation(null);
  };

  const updateRule = (index: number, patch: Partial<RuleDraft>) =>
    setRules((current) => current.map((rule, position) => (position === index ? { ...rule, ...patch } : rule)));

  const addAction = (type: string) => {
    const spec = catalog?.actions.find((item) => item.type === type);
    if (!spec) return;
    const configuration: Record<string, unknown> = {};
    for (const [key, property] of Object.entries(spec.configuration_schema.properties ?? {})) {
      if (property.default !== undefined && property.default !== null) configuration[key] = property.default;
    }
    setActions((current) => [...current, { action_type: type, configuration }]);
  };

  const updateAction = (index: number, key: string, value: unknown) =>
    setActions((current) =>
      current.map((action, position) => {
        if (position !== index) return action;
        const configuration = { ...action.configuration };
        if (value === "" || value === undefined) delete configuration[key];
        else configuration[key] = value;
        return { ...action, configuration };
      }),
    );

  const moveAction = (index: number, direction: -1 | 1) =>
    setActions((current) => {
      const target = index + direction;
      if (target < 0 || target >= current.length) return current;
      const copy = [...current];
      [copy[index], copy[target]] = [copy[target], copy[index]];
      return copy;
    });

  const handleFailure = (failure: unknown, fallback: string) => {
    if (failure instanceof ApiError) {
      setError(failure.message);
      return;
    }
    setError(fallback);
  };

  const validate = async () => {
    setBusy("validate");
    setError(null);
    try {
      const result = await apiRequest<ValidationResult>(`/workspaces/${workspaceId}/automations/validate`, {
        method: "POST",
        body: JSON.stringify(definition()),
      });
      setValidation(result);
      setErrors(result.errors);
    } catch (failure) {
      handleFailure(failure, "The configuration could not be validated.");
    } finally {
      setBusy(null);
    }
  };

  const test = async () => {
    setBusy("test");
    setError(null);
    try {
      const result = await apiRequest<DryRunResult>(`/workspaces/${workspaceId}/automations/dry-run`, {
        method: "POST",
        body: JSON.stringify({ automation: definition(), payload_source: "sample" }),
      });
      setDryRun(result);
    } catch (failure) {
      handleFailure(failure, "The test could not be run.");
    } finally {
      setBusy(null);
    }
  };

  const save = async () => {
    setBusy("save");
    setError(null);
    setErrors([]);
    try {
      const body = definition();
      const saved = initial
        ? await apiRequest<Automation>(`/workspaces/${workspaceId}/automations/${initial.id}`, {
            method: "PATCH",
            body: JSON.stringify({
              name: body.name,
              description: body.description,
              brand_id: body.brand_id,
              clear_brand: !body.brand_id,
              trigger_type: body.trigger_type,
              trigger_configuration: body.trigger_configuration,
              conditions: body.conditions,
              actions: body.actions,
              max_executions: body.max_executions,
              clear_max_executions: body.max_executions === null,
              cooldown_seconds: body.cooldown_seconds,
            }),
          })
        : await apiRequest<Automation>(`/workspaces/${workspaceId}/automations`, { method: "POST", body: JSON.stringify(body) });
      onSaved(saved);
    } catch (failure) {
      if (failure instanceof ApiError) {
        setError(failure.message);
      } else {
        setError("The automation could not be saved.");
      }
    } finally {
      setBusy(null);
    }
  };

  if (!catalog) {
    return <p className="text-sm text-slate-500">{error ?? "Loading the automation catalogue…"}</p>;
  }

  const memberName = (id: string) => members.find((member) => member.user_id === id)?.full_name ?? id;

  return (
    <form
      className="space-y-8"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      {errors.length > 0 && (
        <ul role="alert" className="list-disc space-y-1 rounded-lg bg-red-50 p-3 pl-7 text-sm text-red-800">
          {errors.map((item) => <li key={item}>{item}</li>)}
        </ul>
      )}

      <section className="rounded-2xl border border-slate-200 bg-white p-5">
        <h2 className="font-semibold">1. Name and trigger</h2>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <label className={labelClass}>
            Name
            <input className={`${fieldClass} mt-1`} value={name} onChange={(e) => setName(e.target.value)} required minLength={2} maxLength={120} />
          </label>
          <label className={labelClass}>
            Brand filter (optional)
            <select className={`${fieldClass} mt-1`} value={brandId} onChange={(e) => setBrandId(e.target.value)}>
              <option value="">All brands</option>
              {brands.map((brand) => <option key={brand.id} value={brand.id}>{brand.name}</option>)}
            </select>
          </label>
          <label className={`${labelClass} md:col-span-2`}>
            Description
            <textarea className={`${fieldClass} mt-1`} rows={2} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} />
          </label>
          <label className={`${labelClass} md:col-span-2`}>
            Trigger
            <select className={`${fieldClass} mt-1`} value={triggerType} onChange={(e) => changeTrigger(e.target.value)} required>
              <option value="">Choose what starts this automation…</option>
              {["content", "publishing", "analytics", "team"].map((category) => (
                <optgroup key={category} label={category[0].toUpperCase() + category.slice(1)}>
                  {catalog.triggers.filter((item) => item.category === category).map((item) => (
                    <option key={item.type} value={item.type}>{item.label}</option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>
          {trigger && <p className="text-sm text-slate-600 md:col-span-2">{trigger.description}</p>}
          {trigger?.configuration_fields.map((field) => (
            <label key={field.name} className={labelClass}>
              {field.label}
              <input
                type="number"
                className={`${fieldClass} mt-1`}
                value={triggerConfig[field.name] ?? ""}
                min={field.min}
                max={field.max}
                required={field.required}
                onChange={(e) => setTriggerConfig((current) => ({ ...current, [field.name]: e.target.value }))}
              />
              {field.description && <span className="mt-1 block text-xs text-slate-500">{field.description}</span>}
            </label>
          ))}
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-semibold">2. Conditions</h2>
          {rules.length > 1 && (
            <label className="text-sm text-slate-600">
              Run when{" "}
              <select aria-label="Condition logic" className="rounded-lg border border-slate-300 px-2 py-1 text-sm" value={logic} onChange={(e) => setLogic(e.target.value as "and" | "or")}>
                <option value="and">all</option>
                <option value="or">any</option>
              </select>{" "}
              of these are true
            </label>
          )}
        </div>
        {!trigger ? (
          <p className="mt-3 text-sm text-slate-500">Choose a trigger first.</p>
        ) : (
          <>
            <ul className="mt-3 space-y-2">
              {rules.map((rule, index) => {
                const field = trigger.fields.find((item) => item.name === rule.field);
                const valueless = VALUELESS_OPERATORS.has(rule.operator);
                return (
                  <li key={index} className="grid gap-2 rounded-xl bg-slate-50 p-3 md:grid-cols-[1fr_1fr_1fr_auto]">
                    <select aria-label={`Condition ${index + 1} field`} className={fieldClass} value={rule.field} onChange={(e) => {
                      const next = trigger.fields.find((item) => item.name === e.target.value);
                      updateRule(index, { field: e.target.value, operator: next?.operators[0] ?? "equals", value: "" });
                    }}>
                      {trigger.fields.map((item) => <option key={item.name} value={item.name}>{item.label}</option>)}
                    </select>
                    <select aria-label={`Condition ${index + 1} operator`} className={fieldClass} value={rule.operator} onChange={(e) => updateRule(index, { operator: e.target.value })}>
                      {(field?.operators ?? []).map((operator) => <option key={operator} value={operator}>{OPERATOR_LABELS[operator] ?? operator}</option>)}
                    </select>
                    {valueless ? (
                      <span className="self-center text-sm text-slate-500">—</span>
                    ) : field?.choices && !LIST_OPERATORS.has(rule.operator) ? (
                      <select aria-label={`Condition ${index + 1} value`} className={fieldClass} value={rule.value} onChange={(e) => updateRule(index, { value: e.target.value })}>
                        <option value="">Choose…</option>
                        {field.choices.map((choice) => <option key={choice} value={choice}>{choice}</option>)}
                      </select>
                    ) : field?.ref === "user" && !LIST_OPERATORS.has(rule.operator) ? (
                      <select aria-label={`Condition ${index + 1} value`} className={fieldClass} value={rule.value} onChange={(e) => updateRule(index, { value: e.target.value })}>
                        <option value="">Choose a member…</option>
                        {members.map((member) => <option key={member.user_id} value={member.user_id}>{member.full_name}</option>)}
                      </select>
                    ) : field?.ref === "brand" && !LIST_OPERATORS.has(rule.operator) ? (
                      <select aria-label={`Condition ${index + 1} value`} className={fieldClass} value={rule.value} onChange={(e) => updateRule(index, { value: e.target.value })}>
                        <option value="">Choose a brand…</option>
                        {brands.map((brand) => <option key={brand.id} value={brand.id}>{brand.name}</option>)}
                      </select>
                    ) : field?.type === "boolean" ? (
                      <select aria-label={`Condition ${index + 1} value`} className={fieldClass} value={rule.value} onChange={(e) => updateRule(index, { value: e.target.value })}>
                        <option value="true">true</option>
                        <option value="false">false</option>
                      </select>
                    ) : (
                      <input
                        aria-label={`Condition ${index + 1} value`}
                        className={fieldClass}
                        type={field?.type === "number" && !LIST_OPERATORS.has(rule.operator) ? "number" : "text"}
                        placeholder={LIST_OPERATORS.has(rule.operator) ? "value1, value2" : field?.description || "Value"}
                        value={rule.value}
                        onChange={(e) => updateRule(index, { value: e.target.value })}
                      />
                    )}
                    <button type="button" className="text-sm font-medium text-red-700" onClick={() => setRules((current) => current.filter((_, position) => position !== index))}>
                      Remove
                    </button>
                  </li>
                );
              })}
            </ul>
            <button
              type="button"
              className="mt-3 rounded-xl border border-slate-300 px-3 py-2 text-sm font-medium"
              disabled={rules.length >= Number(catalog.limits.max_conditions ?? 20)}
              onClick={() => {
                const field = trigger.fields[0];
                setRules((current) => [...current, { field: field.name, operator: field.operators[0], value: "" }]);
              }}
            >
              Add condition
            </button>
            {rules.length === 0 && <p className="mt-2 text-xs text-slate-500">No conditions: the automation runs for every “{trigger.label}” event in its scope.</p>}
          </>
        )}
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-5">
        <h2 className="font-semibold">3. Actions</h2>
        <p className="mt-1 text-xs text-slate-500">
          Actions run in order. Only the allowlisted actions below are available; none of them publish content or bypass approvals.
          Text fields accept placeholders such as {"{title}"} from the trigger&apos;s fields.
        </p>
        <ol className="mt-3 space-y-3">
          {actions.map((action, index) => {
            const spec = catalog.actions.find((item) => item.type === action.action_type);
            const properties = spec?.configuration_schema.properties ?? {};
            const required = new Set(spec?.configuration_schema.required ?? []);
            return (
              <li key={`${action.action_type}-${index}`} className="rounded-xl border border-slate-200 p-4">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="font-medium">{index + 1}. {spec?.label ?? action.action_type}</p>
                    <p className="text-xs text-slate-500">{spec?.description}{spec?.required_role === "ADMIN" ? " Requires an Owner or Admin owner." : ""}</p>
                  </div>
                  <div className="flex gap-3 text-sm">
                    <button type="button" aria-label={`Move action ${index + 1} up`} disabled={index === 0} className="disabled:opacity-30" onClick={() => moveAction(index, -1)}>↑</button>
                    <button type="button" aria-label={`Move action ${index + 1} down`} disabled={index === actions.length - 1} className="disabled:opacity-30" onClick={() => moveAction(index, 1)}>↓</button>
                    <button type="button" className="font-medium text-red-700" onClick={() => setActions((current) => current.filter((_, position) => position !== index))}>Remove</button>
                  </div>
                </div>
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  {Object.entries(properties).map(([key, property]) => {
                    const { kind, options } = schemaType(property);
                    const value = action.configuration[key];
                    const label = (property.title ?? key.replaceAll("_", " ")) + (required.has(key) ? " *" : "");
                    const id = `action-${index}-${key}`;
                    if (USER_FIELDS.has(key) || kind === "uuid") {
                      return (
                        <label key={key} htmlFor={id} className={labelClass}>
                          {label}
                          <select id={id} className={`${fieldClass} mt-1`} value={typeof value === "string" ? value : ""} onChange={(e) => updateAction(index, key, e.target.value)}>
                            <option value="">Choose a member…</option>
                            {members.map((member) => <option key={member.user_id} value={member.user_id}>{member.full_name} ({member.role})</option>)}
                          </select>
                        </label>
                      );
                    }
                    if (kind === "boolean") {
                      return (
                        <label key={key} className="flex items-center gap-2 text-sm text-slate-700 md:col-span-2">
                          <input type="checkbox" checked={Boolean(value)} onChange={(e) => updateAction(index, key, e.target.checked)} />
                          {label}
                        </label>
                      );
                    }
                    if (kind === "enum") {
                      return (
                        <label key={key} htmlFor={id} className={labelClass}>
                          {label}
                          <select id={id} className={`${fieldClass} mt-1`} value={typeof value === "string" ? value : ""} onChange={(e) => updateAction(index, key, e.target.value)}>
                            <option value="">Choose…</option>
                            {options.map((option) => <option key={option} value={option}>{option.replaceAll("_", " ")}</option>)}
                          </select>
                        </label>
                      );
                    }
                    if (kind === "integer") {
                      return (
                        <label key={key} htmlFor={id} className={labelClass}>
                          {label}
                          <input id={id} type="number" className={`${fieldClass} mt-1`} min={property.minimum} max={property.maximum} value={value === undefined ? "" : String(value)} onChange={(e) => updateAction(index, key, e.target.value === "" ? "" : Number(e.target.value))} />
                        </label>
                      );
                    }
                    const long = ["message", "description", "note"].includes(key);
                    return (
                      <label key={key} htmlFor={id} className={`${labelClass} ${long ? "md:col-span-2" : ""}`}>
                        {label}
                        {long ? (
                          <textarea id={id} className={`${fieldClass} mt-1`} rows={2} maxLength={property.maxLength} value={typeof value === "string" ? value : ""} onChange={(e) => updateAction(index, key, e.target.value)} />
                        ) : (
                          <input id={id} className={`${fieldClass} mt-1`} maxLength={property.maxLength} value={typeof value === "string" ? value : ""} onChange={(e) => updateAction(index, key, e.target.value)} />
                        )}
                      </label>
                    );
                  })}
                </div>
              </li>
            );
          })}
        </ol>
        <label className={`${labelClass} mt-4`}>
          Add an action
          <select
            aria-label="Add an action"
            className={`${fieldClass} mt-1`}
            value=""
            disabled={!trigger || actions.length >= Number(catalog.limits.max_actions ?? 10)}
            onChange={(e) => {
              if (e.target.value) addAction(e.target.value);
            }}
          >
            <option value="">{trigger ? "Choose an action…" : "Choose a trigger first"}</option>
            {availableActions.map((item) => <option key={item.type} value={item.type}>{item.label}</option>)}
          </select>
        </label>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-5">
        <h2 className="font-semibold">4. Limits</h2>
        <p className="mt-1 text-xs text-slate-500">
          Server limits always apply: at most {String(catalog.limits.max_executions_per_hour)} executions per hour per automation and {String(catalog.limits.workspace_max_executions_per_day)} per day per workspace.
        </p>
        <div className="mt-3 grid gap-4 md:grid-cols-2">
          <label className={labelClass}>
            Lifetime execution cap (optional)
            <input type="number" min={1} className={`${fieldClass} mt-1`} value={maxExecutions} onChange={(e) => setMaxExecutions(e.target.value)} />
          </label>
          <label className={labelClass}>
            Cooldown between executions (seconds)
            <input type="number" min={0} max={86400} className={`${fieldClass} mt-1`} value={cooldown} onChange={(e) => setCooldown(e.target.value)} />
          </label>
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-5">
        <h2 className="font-semibold">5. Review and test</h2>
        <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
          <div><dt className="text-slate-500">Trigger</dt><dd>{trigger?.label ?? "—"}</dd></div>
          <div><dt className="text-slate-500">Conditions</dt><dd>{rules.length === 0 ? "none" : `${rules.length} (${logic === "and" ? "all" : "any"} must match)`}</dd></div>
          <div className="sm:col-span-2">
            <dt className="text-slate-500">Actions in order</dt>
            <dd>
              {actions.length === 0 ? "none" : (
                <ol className="list-decimal pl-5">
                  {actions.map((action, index) => {
                    const spec = catalog.actions.find((item) => item.type === action.action_type);
                    const who = typeof action.configuration.user_id === "string" ? ` → ${memberName(action.configuration.user_id)}` : "";
                    return <li key={index}>{spec?.label ?? action.action_type}{who}</li>;
                  })}
                </ol>
              )}
            </dd>
          </div>
        </dl>
        {validation && (
          <div className={`mt-3 rounded-lg p-3 text-sm ${validation.valid ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-800"}`} role="status">
            {validation.valid ? "The configuration is valid." : "The configuration has errors."}
            {validation.warnings.map((warning) => <p key={warning} className="mt-1 text-amber-800">{warning}</p>)}
          </div>
        )}
        <div className="mt-4 flex flex-wrap gap-2">
          <button type="button" onClick={() => void validate()} disabled={busy !== null || !triggerType} className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-medium disabled:opacity-50">
            {busy === "validate" ? "Validating…" : "Validate"}
          </button>
          <button type="button" onClick={() => void test()} disabled={busy !== null || !triggerType || actions.length === 0} className="rounded-xl border border-indigo-300 bg-indigo-50 px-4 py-2 text-sm font-medium text-indigo-800 disabled:opacity-50">
            {busy === "test" ? "Testing…" : "Test (dry run)"}
          </button>
          <button type="submit" disabled={busy !== null || !triggerType || !name.trim()} className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:bg-slate-300">
            {busy === "save" ? "Saving…" : initial ? "Save changes" : "Save as draft"}
          </button>
        </div>
        <p className="mt-2 text-xs text-slate-500">
          Saving never enables the automation. {user ? "Enable it from its details page after reviewing the test result." : ""}
        </p>
        {dryRun && <DryRunPanel result={dryRun} className="mt-4" />}
      </section>
    </form>
  );
}

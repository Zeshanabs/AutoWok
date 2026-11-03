"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";

import { AppShell, ProtectedPage } from "@/components/route-guards";
import { useAuth } from "@/components/auth-provider";
import { ApiError, apiRequest } from "@/lib/api";
import type {
  BrandGoal,
  BrandOverview,
  BrandPolicy,
  BrandVoice,
  ContentPillar,
  TargetAudience,
} from "@/lib/brand-types";

type Section = "voice" | "audiences" | "pillars" | "goals" | "policies";
type RecordType =
  | BrandVoice
  | TargetAudience
  | ContentPillar
  | BrandGoal
  | BrandPolicy;

const sectionInfo: Record<Section, { title: string; description: string }> = {
  voice: {
    title: "Brand voice",
    description: "Define tone, language, and phrases that fit this brand.",
  },
  audiences: {
    title: "Target audiences",
    description: "Describe customer groups without storing personal data.",
  },
  pillars: {
    title: "Content pillars",
    description: "Organize the themes this brand communicates about.",
  },
  goals: {
    title: "Brand goals",
    description: "Set strategic outcomes for this brand.",
  },
  policies: {
    title: "Brand policies",
    description: "Record restrictions and claims that content must follow.",
  },
};

function listValue(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function BrandSectionPage({
  brandId,
  section,
}: {
  brandId: string;
  section: Section;
}) {
  const [overview, setOverview] = useState<BrandOverview | null>(null);
  const [records, setRecords] = useState<RecordType[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [updatingActiveId, setUpdatingActiveId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiRequest<BrandOverview>(
        `/brands/${brandId}/overview`,
      );
      setOverview(data);
      if (section === "voice") {
        setRecords(data.voice ? [data.voice] : []);
      } else {
        const collections = {
          audiences: data.audiences,
          pillars: data.pillars,
          goals: data.goals,
          policies: data.policies,
        };
        setRecords(collections[section]);
      }
      setError(null);
    } catch (loadError) {
      setError(
        loadError instanceof ApiError
          ? loadError.message
          : "Brand details could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }, [brandId, section]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const text = (name: string) => String(form.get(name) ?? "").trim();
    let payload: Record<string, unknown>;

    switch (section) {
      case "voice":
        payload = {
          tone: text("tone") || null,
          personality: text("personality") || null,
          writing_style: text("writing_style") || null,
          communication_style: text("communication_style") || null,
          language_preferences: listValue(text("language_preferences")),
          preferred_phrases: listValue(text("preferred_phrases")),
          prohibited_phrases: listValue(text("prohibited_phrases")),
          emoji_policy: text("emoji_policy") || null,
          hashtag_policy: text("hashtag_policy") || null,
          call_to_action_style: text("call_to_action_style") || null,
        };
        break;
      case "audiences":
        payload = {
          audience_name: text("name"),
          description: text("description") || null,
          age_range: text("age_range") || null,
          locations: listValue(text("locations")),
          interests: listValue(text("interests")),
          pain_points: listValue(text("pain_points")),
          goals: listValue(text("goals")),
          preferred_platforms: listValue(text("preferred_platforms")),
        };
        break;
      case "pillars":
        payload = {
          name: text("name"),
          description: text("description") || null,
          objective: text("objective") || null,
          suggested_topics: listValue(text("topics")),
          priority: Number(text("priority") || 3),
        };
        break;
      case "goals":
        payload = {
          goal_type: text("goal_type"),
          title: text("title"),
          description: text("description") || null,
          priority: Number(text("priority") || 3),
          target_metric: text("target_metric") || null,
          target_value: text("target_value") || null,
          target_period: text("target_period") || null,
        };
        break;
      case "policies":
        payload = {
          policy_type: text("policy_type"),
          name: text("name"),
          policy_value: text("policy_value"),
          description: text("description") || null,
          severity: text("severity"),
        };
        break;
    }

    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      if (section === "voice") {
        await apiRequest(`/brands/${brandId}/voice`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        setSuccess("Brand voice saved.");
      } else {
        await apiRequest(
          `/brands/${brandId}/${section}${editingId ? `/${editingId}` : ""}`,
          {
          method: editingId ? "PATCH" : "POST",
          body: JSON.stringify(payload),
          },
        );
        setEditingId(null);
        formElement.reset();
        setSuccess(editingId ? "Brand information updated." : "Brand information added.");
      }
      await load();
    } catch (saveError) {
      setError(
        saveError instanceof ApiError
          ? saveError.message
          : "Brand information could not be saved.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function removeRecord(id: string) {
    setError(null);
    setSuccess(null);
    try {
      await apiRequest(`/brands/${brandId}/${section}/${id}`, {
        method: "DELETE",
      });
      setRecords((current) =>
        current.filter((record) => "id" in record && record.id !== id),
      );
      if (editingId === id) setEditingId(null);
      setSuccess("Brand information removed.");
    } catch (removeError) {
      setError(
        removeError instanceof ApiError
          ? removeError.message
          : "Brand information could not be removed.",
      );
    }
  }

  async function toggleActive(record: RecordType) {
    if (!("id" in record) || !("is_active" in record)) return;
    const nextIsActive = !record.is_active;
    setUpdatingActiveId(record.id);
    setError(null);
    setSuccess(null);
    try {
      const updated = await apiRequest<RecordType>(
        `/brands/${brandId}/${section}/${record.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({ is_active: nextIsActive }),
        },
      );
      setRecords((current) =>
        current.map((item) =>
          "id" in item && item.id === record.id ? updated : item,
        ),
      );
      setSuccess(
        nextIsActive
          ? "Profile information activated."
          : "Profile information deactivated.",
      );
    } catch (updateError) {
      setError(
        updateError instanceof ApiError
          ? updateError.message
          : "Profile information status could not be updated.",
      );
    } finally {
      setUpdatingActiveId(null);
    }
  }

  const { workspaces } = useAuth();
  const workspaceRole =
    workspaces.find((workspace) => workspace.id === overview?.brand.workspace_id)
      ?.role;
  const canManage =
    (workspaceRole === "OWNER" || workspaceRole === "ADMIN") &&
    overview?.brand.status === "ACTIVE";
  const editingRecord = records.find(
    (record) => "id" in record && record.id === editingId,
  );
  const voice =
    (editingRecord && "tone" in editingRecord ? editingRecord : undefined) ??
    (records[0] && "tone" in records[0] ? records[0] : undefined);
  const audience =
    editingRecord && "audience_name" in editingRecord ? editingRecord : undefined;
  const pillar =
    editingRecord && "suggested_topics" in editingRecord
      ? editingRecord
      : undefined;
  const goal =
    editingRecord && "goal_type" in editingRecord ? editingRecord : undefined;
  const policy =
    editingRecord && "policy_type" in editingRecord ? editingRecord : undefined;
  const info = sectionInfo[section];
  return (
    <ProtectedPage>
      <AppShell>
        <p className="text-sm font-medium text-indigo-700">
          {overview?.brand.name ?? "Brand"}
        </p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight">{info.title}</h1>
        <p className="mt-2 text-slate-600">{info.description}</p>
        <Link
          href={`/brands/${brandId}`}
          className="mt-4 inline-block text-sm font-semibold text-indigo-700"
        >
          ← Brand overview
        </Link>
        {error && (
          <p role="alert" className="mt-5 rounded-lg bg-red-50 p-3 text-sm text-red-800">
            {error}
          </p>
        )}
        {success && (
          <p role="status" className="mt-5 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">
            {success}
          </p>
        )}
        {loading ? (
          <p className="mt-6">Loading brand information…</p>
        ) : (
          <div className="mt-7 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <section className="rounded-2xl border border-slate-200 bg-white p-6">
              <h2 className="text-lg font-semibold">
                {section === "voice"
                  ? records.length
                    ? "Update brand voice"
                    : "Set brand voice"
                  : editingRecord
                    ? `Edit ${info.title.toLowerCase()}`
                    : `Add ${info.title.toLowerCase()}`}
              </h2>
              {canManage ? (
              <form
                key={editingId ?? "new"}
                onSubmit={submit}
                className="mt-5 space-y-4"
              >
                {section === "voice" ? (
                  <>
                    <Field label="Tone" name="tone" defaultValue={voice?.tone ?? ""} />
                    <Field label="Personality" name="personality" defaultValue={voice?.personality ?? ""} />
                    <Field label="Writing style" name="writing_style" defaultValue={voice?.writing_style ?? ""} />
                    <Field label="Communication style" name="communication_style" defaultValue={voice?.communication_style ?? ""} />
                    <Field label="Languages (comma-separated)" name="language_preferences" defaultValue={voice?.language_preferences.join(", ") ?? ""} />
                    <Field label="Preferred phrases (comma-separated)" name="preferred_phrases" defaultValue={voice?.preferred_phrases.join(", ") ?? ""} />
                    <Field label="Phrases to avoid (comma-separated)" name="prohibited_phrases" defaultValue={voice?.prohibited_phrases.join(", ") ?? ""} />
                    <SelectField label="Emoji policy" name="emoji_policy" options={["avoid", "sparingly", "contextual", "frequent"]} defaultValue={voice?.emoji_policy ?? ""} />
                    <SelectField label="Hashtag policy" name="hashtag_policy" options={["avoid", "limited", "moderate", "platform_specific"]} defaultValue={voice?.hashtag_policy ?? ""} />
                    <Field label="Call-to-action style" name="call_to_action_style" defaultValue={voice?.call_to_action_style ?? ""} />
                  </>
                ) : section === "audiences" ? (
                  <>
                    <Field label="Audience name" name="name" defaultValue={audience?.audience_name ?? ""} required />
                    <Field label="Description" name="description" defaultValue={audience?.description ?? ""} />
                    <Field label="Age range (optional)" name="age_range" defaultValue={audience?.age_range ?? ""} />
                    <Field label="Locations (comma-separated)" name="locations" defaultValue={audience?.locations.join(", ") ?? ""} />
                    <Field label="Interests (comma-separated)" name="interests" defaultValue={audience?.interests.join(", ") ?? ""} />
                    <Field label="Pain points (comma-separated)" name="pain_points" defaultValue={audience?.pain_points.join(", ") ?? ""} />
                    <Field label="Goals (comma-separated)" name="goals" defaultValue={audience?.goals.join(", ") ?? ""} />
                    <Field label="Preferred platforms (comma-separated)" name="preferred_platforms" defaultValue={audience?.preferred_platforms.join(", ") ?? ""} />
                    <p className="text-xs text-slate-500">Do not enter names, emails, phone numbers, or other personally identifying information.</p>
                  </>
                ) : section === "pillars" ? (
                  <>
                    <Field label="Pillar name" name="name" defaultValue={pillar?.name ?? ""} required />
                    <Field label="Description" name="description" defaultValue={pillar?.description ?? ""} />
                    <Field label="Objective" name="objective" defaultValue={pillar?.objective ?? ""} />
                    <Field label="Suggested topics (comma-separated)" name="topics" defaultValue={pillar?.suggested_topics.join(", ") ?? ""} />
                    <NumberField label="Priority (1–5)" name="priority" min={1} max={5} defaultValue={pillar?.priority ?? 3} />
                  </>
                ) : section === "goals" ? (
                  <>
                    <SelectField label="Goal type" name="goal_type" options={["brand_awareness", "engagement", "lead_generation", "website_traffic", "community_building", "customer_education", "custom"]} defaultValue={goal?.goal_type ?? ""} required />
                    <Field label="Title" name="title" defaultValue={goal?.title ?? ""} required />
                    <Field label="Description" name="description" defaultValue={goal?.description ?? ""} />
                    <NumberField label="Priority (1–5)" name="priority" min={1} max={5} defaultValue={goal?.priority ?? 3} />
                    <Field label="Target metric" name="target_metric" defaultValue={goal?.target_metric ?? ""} />
                    <Field label="Target value" name="target_value" defaultValue={goal?.target_value ?? ""} />
                    <Field label="Target period" name="target_period" defaultValue={goal?.target_period ?? ""} />
                  </>
                ) : (
                  <>
                    <SelectField label="Policy type" name="policy_type" options={["prohibited_claim", "restricted_topic", "required_disclaimer", "competitor_reference", "industry_rule", "legal_compliance", "approval_required", "custom"]} defaultValue={policy?.policy_type ?? ""} required />
                    <Field label="Policy name" name="name" defaultValue={policy?.name ?? ""} required />
                    <Field label="Policy details" name="policy_value" defaultValue={policy?.policy_value ?? ""} required />
                    <Field label="Description" name="description" defaultValue={policy?.description ?? ""} />
                    <SelectField label="Severity" name="severity" options={["LOW", "MEDIUM", "HIGH"]} defaultValue={policy?.severity ?? "MEDIUM"} />
                  </>
                )}
                <button
                  disabled={saving}
                  className="rounded-xl bg-indigo-600 px-4 py-2.5 font-semibold text-white disabled:opacity-60"
                >
                  {saving
                    ? "Saving…"
                    : section === "voice"
                      ? "Save voice"
                      : editingId
                        ? "Save changes"
                        : "Add"}
                </button>
                {editingId && section !== "voice" && (
                  <button
                    type="button"
                    onClick={() => setEditingId(null)}
                    className="ml-3 rounded-xl border border-slate-300 px-4 py-2.5 font-semibold"
                  >
                    Cancel
                  </button>
                )}
              </form>
              ) : (
                <p className="mt-4 text-sm text-slate-600">
                  This profile is read-only for your workspace role or because
                  the brand is archived.
                </p>
              )}
            </section>
            <section className="rounded-2xl border border-slate-200 bg-white p-6">
              <h2 className="text-lg font-semibold">Saved information</h2>
              {records.length === 0 ? (
                <p className="mt-4 text-sm text-slate-600">
                  Nothing has been added yet.
                </p>
              ) : (
                <div className="mt-4 space-y-3">
                  {records.map((record) => (
                    <article
                      key={"id" in record ? record.id : "voice"}
                      className="rounded-xl border border-slate-200 p-4"
                    >
                      <p className="font-medium">
                        {"name" in record
                          ? record.name
                          : "audience_name" in record
                            ? record.audience_name
                            : "title" in record
                              ? record.title
                              : "tone" in record
                                ? record.tone ?? "Brand voice"
                                : "Brand voice"}
                      </p>
                      {"is_active" in record && (
                        <p className="mt-1 text-xs text-slate-500">
                          {record.is_active ? "Active" : "Inactive"}
                        </p>
                      )}
                      <p className="mt-1 whitespace-pre-wrap text-sm text-slate-600">
                        {"description" in record && record.description
                          ? record.description
                          : "policy_value" in record
                            ? record.policy_value
                            : ""}
                      </p>
                      {section !== "voice" && canManage && "id" in record && (
                        <button
                          onClick={() => setEditingId(record.id)}
                          className="mt-3 mr-4 text-sm font-medium text-indigo-700 hover:text-indigo-900"
                        >
                          Edit
                        </button>
                      )}
                      {section !== "voice" && canManage && "id" in record && (
                        <button
                          onClick={() => void removeRecord(record.id)}
                          className="mt-3 text-sm font-medium text-red-700 hover:text-red-900"
                        >
                          Remove
                        </button>
                      )}
                      {"is_active" in record && canManage && "id" in record && (
                        <button
                          disabled={updatingActiveId === record.id}
                          onClick={() => void toggleActive(record)}
                          aria-label={`${record.is_active ? "Deactivate" : "Activate"} ${
                            "name" in record
                              ? record.name
                              : "title" in record
                                ? record.title
                                : "Content pillar"
                          }`}
                          className="mt-3 ml-4 text-sm font-medium text-indigo-700 hover:text-indigo-900 disabled:opacity-60"
                        >
                          {updatingActiveId === record.id
                            ? "Updating…"
                            : record.is_active
                              ? "Deactivate"
                              : "Activate"}
                        </button>
                      )}
                    </article>
                  ))}
                </div>
              )}
            </section>
          </div>
        )}
      </AppShell>
    </ProtectedPage>
  );
}

function Field({
  label,
  name,
  defaultValue,
  required = false,
}: {
  label: string;
  name: string;
  defaultValue?: string;
  required?: boolean;
}) {
  return (
    <label className="block text-sm font-medium">
      {label}
      <input
        name={name}
        defaultValue={defaultValue}
        required={required}
        maxLength={3000}
        className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2.5"
      />
    </label>
  );
}

function NumberField({
  label,
  name,
  min,
  max,
  defaultValue,
}: {
  label: string;
  name: string;
  min: number;
  max: number;
  defaultValue: number;
}) {
  return (
    <label className="block text-sm font-medium">
      {label}
      <input
        type="number"
        name={name}
        min={min}
        max={max}
        defaultValue={defaultValue}
        className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2.5"
      />
    </label>
  );
}

function SelectField({
  label,
  name,
  options,
  defaultValue = "",
  required = false,
}: {
  label: string;
  name: string;
  options: string[];
  defaultValue?: string;
  required?: boolean;
}) {
  return (
    <label className="block text-sm font-medium">
      {label}
      <select
        name={name}
        defaultValue={defaultValue}
        required={required}
        className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5"
      >
        <option value="">Select…</option>
        {options.map((option) => (
          <option value={option} key={option}>
            {option.replaceAll("_", " ")}
          </option>
        ))}
      </select>
    </label>
  );
}

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { AgentsHeader, HumanControlNote } from "@/components/agents/agents-shell";
import { useAuth } from "@/components/auth-provider";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { ApiError, apiRequest } from "@/lib/api";
import type { AgentWorkflowDetail, Catalog, WorkflowPlan } from "@/lib/agent-types";
import type { Brand } from "@/lib/brand-types";
import type { ContentProject } from "@/lib/content-types";
import type { ResearchProject } from "@/lib/research-types";

const fieldClass = "w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm";
const PLATFORMS = [
  { value: "facebook", label: "Facebook" },
  { value: "instagram", label: "Instagram" },
];

function initialType(): string {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get("type") ?? "";
}

export default function WorkflowBuilderPage() {
  const router = useRouter();
  const { selectedWorkspace } = useAuth();
  const workspaceId = selectedWorkspace?.id;
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [research, setResearch] = useState<ResearchProject[]>([]);
  const [content, setContent] = useState<ContentProject[]>([]);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);

  const [workflowType, setWorkflowType] = useState(initialType);
  const [task, setTask] = useState("");
  const [brandId, setBrandId] = useState("");
  const [researchIds, setResearchIds] = useState<string[]>([]);
  const [contentProjectId, setContentProjectId] = useState("");
  const [platforms, setPlatforms] = useState<string[]>(["facebook", "instagram"]);
  const [days, setDays] = useState(30);
  const [runNewResearch, setRunNewResearch] = useState(false);

  const [plan, setPlan] = useState<WorkflowPlan | null>(null);
  const [busy, setBusy] = useState<"plan" | "start" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!workspaceId) return;
    try {
      const [nextCatalog, nextBrands, nextResearch, nextContent] = await Promise.all([
        apiRequest<Catalog>(`/workspaces/${workspaceId}/agent-workflows/catalog`),
        apiRequest<Brand[]>(`/workspaces/${workspaceId}/brands`),
        apiRequest<ResearchProject[]>(`/research?workspace_id=${encodeURIComponent(workspaceId)}`),
        apiRequest<ContentProject[]>(`/content/projects?workspace_id=${encodeURIComponent(workspaceId)}`),
      ]);
      setCatalog(nextCatalog);
      setBrands(nextBrands.filter((brand) => brand.status === "ACTIVE"));
      setResearch(nextResearch);
      setContent(nextContent.filter((project) => project.status === "approved"));
      setWorkflowType((current) => (nextCatalog.workflows.some((item) => item.key === current) ? current : nextCatalog.workflows[0]?.key ?? ""));
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof ApiError ? loadError.message : "The workflow builder could not be loaded.");
    } finally {
      setLoadedFor(workspaceId);
    }
  }, [workspaceId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const definition = useMemo(() => catalog?.workflows.find((item) => item.key === workflowType) ?? null, [catalog, workflowType]);
  const uses = useCallback(
    (input: string) => Boolean(definition && (definition.requires.includes(input) || definition.optional.includes(input))),
    [definition],
  );
  const needs = (input: string) => Boolean(definition?.requires.includes(input));

  const body = useMemo(
    () => ({
      workflow_type: workflowType,
      task: task.trim(),
      brand_id: uses("brand") && brandId ? brandId : null,
      research_ids: uses("research") ? researchIds : [],
      content_project_id: uses("content_project") && contentProjectId ? contentProjectId : null,
      platforms: uses("platforms") ? platforms : ["facebook", "instagram"],
      days,
      run_new_research: workflowType === "content_research" && runNewResearch,
    }),
    [workflowType, task, brandId, researchIds, contentProjectId, platforms, days, runNewResearch, uses],
  );

  function changed<T>(setter: (value: T) => void) {
    return (value: T) => {
      setter(value);
      setPlan(null); // the reviewed plan no longer matches the form
    };
  }

  const problem =
    task.trim().length < 3 ? "Describe the task."
    : needs("brand") && !brandId ? "Select a brand."
    : needs("content_project") && !contentProjectId ? "Select an approved content item."
    : uses("platforms") && platforms.length === 0 ? "Select at least one platform."
    : null;

  async function review(event: FormEvent) {
    event.preventDefault();
    if (!workspaceId || problem) {
      setError(problem);
      return;
    }
    setBusy("plan");
    try {
      setPlan(await apiRequest<WorkflowPlan>(`/workspaces/${workspaceId}/agent-workflows/plan`, { method: "POST", body: JSON.stringify(body) }));
      setError(null);
    } catch (planError) {
      setPlan(null);
      setError(planError instanceof ApiError ? planError.message : "The workflow could not be planned.");
    } finally {
      setBusy(null);
    }
  }

  async function startWorkflow() {
    if (!workspaceId || !plan) return;
    setBusy("start");
    try {
      const created = await apiRequest<AgentWorkflowDetail>(`/workspaces/${workspaceId}/agent-workflows`, { method: "POST", body: JSON.stringify(body) });
      router.push(`/dashboard/ai-agents/workflows/${created.id}`);
    } catch (startError) {
      setError(startError instanceof ApiError ? startError.message : "The workflow could not be started.");
      setBusy(null);
    }
  }

  const loading = Boolean(workspaceId) && loadedFor !== workspaceId;
  const blocked = Boolean(plan && plan.workflow.disabled_agents.length > 0);

  return (
    <ProtectedPage>
      <AppShell>
        <AgentsHeader
          active="/dashboard/ai-agents/workflows"
          title="New workflow"
          description="Choose a predefined workflow, describe the task, review the planned steps, then start it."
        />
        {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}

        {!workspaceId ? (
          <p className="mt-6 rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">Select a workspace.</p>
        ) : loading ? (
          <p className="mt-6 text-sm text-slate-500">Loading workflows…</p>
        ) : (
          <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,24rem)]">
            <form onSubmit={review} className="space-y-5 rounded-2xl border border-slate-200 bg-white p-5">
              <fieldset>
                <legend className="text-sm font-semibold">Workflow</legend>
                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                  {(catalog?.workflows ?? []).map((workflow) => (
                    <label
                      key={workflow.key}
                      className={`cursor-pointer rounded-xl border p-3 text-sm ${workflowType === workflow.key ? "border-indigo-600 bg-indigo-50" : "border-slate-200 hover:border-slate-300"}`}
                    >
                      <input
                        type="radio"
                        name="workflow_type"
                        className="sr-only"
                        value={workflow.key}
                        checked={workflowType === workflow.key}
                        onChange={() => changed(setWorkflowType)(workflow.key)}
                      />
                      <span className="font-semibold">{workflow.name}</span>
                      <span className="mt-1 block text-slate-600">{workflow.description}</span>
                    </label>
                  ))}
                </div>
              </fieldset>

              <div>
                <label htmlFor="task" className="text-sm font-semibold">Task</label>
                <textarea
                  id="task"
                  className={`${fieldClass} mt-2`}
                  rows={3}
                  maxLength={2000}
                  placeholder="For example: promote our new home brewing guide to first-time buyers"
                  value={task}
                  onChange={(event) => changed(setTask)(event.target.value)}
                />
              </div>

              {uses("brand") && (
                <div>
                  <label htmlFor="brand" className="text-sm font-semibold">Brand{needs("brand") ? "" : " (optional)"}</label>
                  <select id="brand" className={`${fieldClass} mt-2`} value={brandId} onChange={(event) => changed(setBrandId)(event.target.value)}>
                    <option value="">{needs("brand") ? "Select a brand" : "No brand"}</option>
                    {brands.map((brand) => <option key={brand.id} value={brand.id}>{brand.name}</option>)}
                  </select>
                  {brands.length === 0 && (
                    <p className="mt-1 text-xs text-slate-500">No active brands. <Link href="/brands/new" className="font-medium text-indigo-700">Create a brand</Link></p>
                  )}
                </div>
              )}

              {uses("content_project") && (
                <div>
                  <label htmlFor="content" className="text-sm font-semibold">Approved content to repurpose</label>
                  <select id="content" className={`${fieldClass} mt-2`} value={contentProjectId} onChange={(event) => changed(setContentProjectId)(event.target.value)}>
                    <option value="">Select approved content</option>
                    {content.map((project) => <option key={project.id} value={project.id}>{project.title}</option>)}
                  </select>
                  {content.length === 0 && <p className="mt-1 text-xs text-slate-500">Only approved content can be repurposed, and none is approved yet.</p>}
                </div>
              )}

              {uses("research") && (
                <fieldset>
                  <legend className="text-sm font-semibold">Relevant research (optional, up to 5)</legend>
                  {research.length === 0 ? (
                    <p className="mt-2 text-xs text-slate-500">No research projects yet. Without sources, claims cannot be verified.</p>
                  ) : (
                    <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto rounded-xl border border-slate-200 p-2 text-sm">
                      {research.map((project) => {
                        const checked = researchIds.includes(project.id);
                        return (
                          <li key={project.id}>
                            <label className="flex items-start gap-2 rounded-lg px-2 py-1 hover:bg-slate-50">
                              <input
                                type="checkbox"
                                className="mt-1"
                                checked={checked}
                                disabled={!checked && researchIds.length >= 5}
                                onChange={() => changed(setResearchIds)(checked ? researchIds.filter((id) => id !== project.id) : [...researchIds, project.id])}
                              />
                              <span>{project.title} <span className="text-slate-500">· {project.status.toLowerCase()}</span></span>
                            </label>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                  {workflowType === "content_research" && (
                    <label className="mt-2 flex items-start gap-2 text-sm">
                      <input type="checkbox" className="mt-1" checked={runNewResearch} onChange={(event) => changed(setRunNewResearch)(event.target.checked)} />
                      <span>Also run new research with the search provider</span>
                    </label>
                  )}
                </fieldset>
              )}

              {uses("platforms") && (
                <fieldset>
                  <legend className="text-sm font-semibold">Platforms</legend>
                  <div className="mt-2 flex flex-wrap gap-4 text-sm">
                    {PLATFORMS.map((platform) => (
                      <label key={platform.value} className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={platforms.includes(platform.value)}
                          onChange={() => changed(setPlatforms)(
                            platforms.includes(platform.value) ? platforms.filter((item) => item !== platform.value) : [...platforms, platform.value],
                          )}
                        />
                        {platform.label}
                      </label>
                    ))}
                  </div>
                </fieldset>
              )}

              {uses("days") && (
                <div>
                  <label htmlFor="days" className="text-sm font-semibold">Analytics period</label>
                  <select id="days" className={`${fieldClass} mt-2`} value={days} onChange={(event) => changed(setDays)(Number(event.target.value))}>
                    {[7, 14, 30, 60, 90].map((value) => <option key={value} value={value}>Last {value} days</option>)}
                  </select>
                </div>
              )}

              <button type="submit" disabled={busy !== null} className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-semibold hover:bg-slate-50 disabled:opacity-50">
                {busy === "plan" ? "Planning…" : "Review planned execution"}
              </button>
            </form>

            <aside className="space-y-4">
              <section className="rounded-2xl border border-slate-200 bg-white p-5">
                <h2 className="font-semibold">Planned execution</h2>
                {!plan ? (
                  <p className="mt-2 text-sm text-slate-600">Fill in the form and review the plan before starting. Nothing runs until you start the workflow.</p>
                ) : (
                  <>
                    <ol className="mt-3 space-y-2 text-sm">
                      {plan.workflow.steps.map((step) => (
                        <li key={step.step_key} className="flex gap-3">
                          <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-slate-100 text-xs font-semibold">{step.step_order}</span>
                          <span>
                            <span className="font-medium">{step.label}</span>
                            <span className="block text-xs text-slate-500">
                              {step.agent_name}{step.parallel_group ? " · independent review" : ""}
                            </span>
                          </span>
                        </li>
                      ))}
                    </ol>
                    <p className="mt-3 text-xs text-slate-500">
                      About {plan.estimated_agent_calls} Groq requests{plan.workflow.supports_revision ? ", more if a revision is needed" : ""}.
                    </p>
                    <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-slate-600">
                      {plan.notes.map((note) => <li key={note}>{note}</li>)}
                    </ul>
                    <p className="mt-3 text-sm font-medium">You will receive</p>
                    <ul className="mt-1 list-disc pl-5 text-sm text-slate-600">
                      {plan.workflow.deliverables.map((item) => <li key={item}>{item}</li>)}
                    </ul>
                    <button
                      type="button"
                      onClick={() => void startWorkflow()}
                      disabled={busy !== null || blocked}
                      className="mt-4 w-full rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
                    >
                      {busy === "start" ? "Starting…" : "Start workflow"}
                    </button>
                  </>
                )}
              </section>
              <HumanControlNote />
            </aside>
          </div>
        )}
      </AppShell>
    </ProtectedPage>
  );
}

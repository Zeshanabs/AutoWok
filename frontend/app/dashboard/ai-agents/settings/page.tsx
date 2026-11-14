"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AgentsHeader } from "@/components/agents/agents-shell";
import { useAuth } from "@/components/auth-provider";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { StatusBadge } from "@/components/status-badge";
import { ApiError, apiRequest } from "@/lib/api";
import type { Agent, Catalog } from "@/lib/agent-types";

export default function AgentSettingsPage() {
  const { selectedWorkspace } = useAuth();
  const workspaceId = selectedWorkspace?.id;
  const canManage = selectedWorkspace?.role === "OWNER" || selectedWorkspace?.role === "ADMIN";
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!workspaceId) return;
    try {
      setCatalog(await apiRequest<Catalog>(`/workspaces/${workspaceId}/agent-workflows/catalog`));
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof ApiError ? loadError.message : "Agent settings could not be loaded.");
    } finally {
      setLoadedFor(workspaceId);
    }
  }, [workspaceId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function toggle(agent: Agent) {
    if (!workspaceId) return;
    setSaving(agent.key);
    try {
      await apiRequest<Agent>(`/workspaces/${workspaceId}/agents/${agent.key}`, { method: "PATCH", body: JSON.stringify({ enabled: !agent.enabled }) });
      await load();
    } catch (saveError) {
      setError(saveError instanceof ApiError ? saveError.message : "The agent could not be updated.");
    } finally {
      setSaving(null);
    }
  }

  const loading = Boolean(workspaceId) && loadedFor !== workspaceId;
  const groq = catalog?.groq;
  const limits = catalog?.limits;

  return (
    <ProtectedPage>
      <AppShell>
        <AgentsHeader
          active="/dashboard/ai-agents/settings"
          title="Agents and settings"
          description="The registered agents, what each one may use, and the limits that apply to every workflow."
        />
        {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}

        {!workspaceId ? (
          <p className="mt-6 rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">Select a workspace.</p>
        ) : loading ? (
          <p className="mt-6 text-sm text-slate-500">Loading agent settings…</p>
        ) : (
          <div className="mt-6 space-y-6">
            <section className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-2xl border border-slate-200 bg-white p-5">
                <h2 className="font-semibold">AI provider</h2>
                <dl className="mt-3 space-y-2 text-sm">
                  <div className="flex justify-between gap-3"><dt className="text-slate-500">Inference</dt><dd>Groq{groq?.configured ? "" : " (not configured)"}</dd></div>
                  <div className="flex justify-between gap-3"><dt className="text-slate-500">Model</dt><dd>{groq?.model_name ?? "Not set"}{groq?.agent_model_override ? " (agent override)" : ""}</dd></div>
                  <div className="flex justify-between gap-3"><dt className="text-slate-500">Key source</dt><dd>{groq?.source ?? "—"}</dd></div>
                  <div className="flex justify-between gap-3"><dt className="text-slate-500">External research</dt><dd>{groq?.search_provider_configured ? "Search provider configured" : "No search provider configured"}</dd></div>
                </dl>
                <p className="mt-3 text-xs text-slate-500">
                  Agents use Groq for inference only. Web research goes through the research engine&apos;s search provider. Choose the model in{" "}
                  <Link href="/settings/ai" className="font-medium text-indigo-700">AI settings</Link>, where the list of models comes live from Groq.
                </p>
              </div>
              <div className="rounded-2xl border border-slate-200 bg-white p-5">
                <h2 className="font-semibold">Workflow limits</h2>
                {limits && (
                  <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                    <dt className="text-slate-500">Agent calls per workflow</dt><dd>{limits.max_calls_per_workflow}</dd>
                    <dt className="text-slate-500">Workflow time limit</dt><dd>{Math.round(limits.max_workflow_seconds / 60)} min</dd>
                    <dt className="text-slate-500">Step time limit</dt><dd>{limits.step_timeout_seconds} s</dd>
                    <dt className="text-slate-500">Attempts per step</dt><dd>{limits.max_step_attempts}</dd>
                    <dt className="text-slate-500">Automatic revisions</dt><dd>{limits.max_auto_revisions}</dd>
                    <dt className="text-slate-500">Revision rounds in total</dt><dd>{limits.max_revisions}</dd>
                    <dt className="text-slate-500">Parallel Groq requests</dt><dd>{limits.max_parallel_calls}</dd>
                    <dt className="text-slate-500">Workflows at once</dt><dd>{limits.max_active_workflows}</dd>
                    <dt className="text-slate-500">Workflows per hour</dt><dd>{limits.max_workflows_per_hour}</dd>
                  </dl>
                )}
                <p className="mt-3 text-xs text-slate-500">Limits are set by the server administrator.</p>
              </div>
            </section>

            <section>
              <h2 className="font-semibold">Registered agents</h2>
              {!canManage && <p className="mt-1 text-sm text-slate-600">Workspace Owners and Admins can switch agents on or off.</p>}
              <ul className="mt-3 space-y-3">
                {(catalog?.agents ?? []).map((agent) => (
                  <li key={agent.key} className="rounded-2xl border border-slate-200 bg-white p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="font-semibold">{agent.name} <span className="text-xs font-normal text-slate-500">v{agent.version}</span></p>
                        <p className="text-sm text-slate-600">{agent.responsibility}</p>
                      </div>
                      <div className="flex items-center gap-3">
                        <StatusBadge status={agent.enabled ? "enabled" : "paused"} />
                        {canManage && (
                          <button
                            type="button"
                            disabled={saving === agent.key}
                            onClick={() => void toggle(agent)}
                            className="rounded-xl border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium hover:bg-slate-50 disabled:opacity-50"
                          >
                            {agent.enabled ? `Disable ${agent.name}` : `Enable ${agent.name}`}
                          </button>
                        )}
                      </div>
                    </div>
                    <dl className="mt-3 grid gap-2 text-xs text-slate-600 sm:grid-cols-3">
                      <div>
                        <dt className="text-slate-500">Tools</dt>
                        <dd>{agent.tools.length === 0 ? "None" : agent.tools.map((tool) => `${tool.name} (${tool.access})`).join(", ")}</dd>
                      </div>
                      <div><dt className="text-slate-500">Model settings</dt><dd>temperature {agent.model.temperature} · up to {agent.model.max_tokens} tokens</dd></div>
                      <div><dt className="text-slate-500">Minimum role</dt><dd>{agent.required_role}</dd></div>
                    </dl>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        )}
      </AppShell>
    </ProtectedPage>
  );
}

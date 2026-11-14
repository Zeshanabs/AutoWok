"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AgentsHeader, HumanControlNote } from "@/components/agents/agents-shell";
import { useAuth } from "@/components/auth-provider";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { StatusBadge } from "@/components/status-badge";
import { ApiError, apiRequest } from "@/lib/api";
import { isActive, reviewLabel, type AgentStats, type Catalog } from "@/lib/agent-types";

export default function AiAgentsDashboardPage() {
  const { selectedWorkspace } = useAuth();
  const workspaceId = selectedWorkspace?.id;
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [stats, setStats] = useState<AgentStats | null>(null);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!workspaceId) return;
    try {
      const [nextCatalog, nextStats] = await Promise.all([
        apiRequest<Catalog>(`/workspaces/${workspaceId}/agent-workflows/catalog`),
        apiRequest<AgentStats>(`/workspaces/${workspaceId}/agent-workflows/stats`),
      ]);
      setCatalog(nextCatalog);
      setStats(nextStats);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof ApiError ? loadError.message : "The AI workspace could not be loaded.");
    } finally {
      setLoadedFor(workspaceId);
    }
  }, [workspaceId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  // Refresh while something is running so statuses stay current.
  const hasActive = Boolean(stats?.recent.some((item) => isActive(item.status)));
  useEffect(() => {
    if (!hasActive) return;
    const timer = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(timer);
  }, [hasActive, load]);

  const loading = Boolean(workspaceId) && loadedFor !== workspaceId;
  const groq = catalog?.groq;

  return (
    <ProtectedPage>
      <AppShell>
        <AgentsHeader
          active="/dashboard/ai-agents"
          title="AI agent workspace"
          description="Specialized agents work together on research, strategy, writing and review. You start each workflow, watch every step and decide what to keep."
          actions={
            <Link href="/dashboard/ai-agents/workflows" className="rounded-xl bg-indigo-600 px-3 py-2 text-sm font-semibold text-white hover:bg-indigo-700">
              Start a workflow
            </Link>
          }
        />

        {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}

        {!workspaceId ? (
          <p className="mt-6 rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">Select a workspace.</p>
        ) : loading ? (
          <p className="mt-6 text-sm text-slate-500">Loading the AI workspace…</p>
        ) : (
          <div className="mt-6 space-y-6">
            {groq && !groq.configured && (
              <p role="alert" className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900">
                Groq is not configured for this workspace, so workflows will fail at the first agent.{" "}
                <Link href="/settings/ai" className="font-medium underline">Open AI settings</Link>
              </p>
            )}
            {catalog && !catalog.limits.enabled && (
              <p role="alert" className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900">AI agent workflows are disabled on this server.</p>
            )}

            {stats && (
              <section aria-label="Usage" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                {[
                  { label: "In progress", value: stats.active },
                  { label: "Succeeded", value: stats.counts.succeeded ?? 0 },
                  { label: "Failed", value: stats.counts.failed ?? 0 },
                  { label: "Agent calls", value: stats.agent_calls },
                  { label: "Tokens used", value: stats.total_tokens.toLocaleString() },
                ].map((item) => (
                  <div key={item.label} className="rounded-2xl border border-slate-200 bg-white p-4">
                    <p className="text-xs text-slate-500">{item.label}</p>
                    <p className="mt-1 text-2xl font-bold">{item.value}</p>
                    <p className="text-xs text-slate-500">last {stats.days} days</p>
                  </div>
                ))}
              </section>
            )}

            <section>
              <h2 className="font-semibold">Available workflows</h2>
              <ul className="mt-3 grid gap-3 md:grid-cols-2">
                {(catalog?.workflows ?? []).map((workflow) => (
                  <li key={workflow.key} className="rounded-2xl border border-slate-200 bg-white p-4">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <p className="font-semibold">{workflow.name}</p>
                      <Link href={`/dashboard/ai-agents/workflows?type=${workflow.key}`} className="text-sm font-medium text-indigo-700">Start</Link>
                    </div>
                    <p className="mt-1 text-sm text-slate-600">{workflow.description}</p>
                    <p className="mt-2 text-xs text-slate-500">
                      {workflow.steps.filter((step) => step.kind === "agent").map((step) => step.agent_name.replace(" Agent", "")).join(" → ")}
                    </p>
                    {workflow.disabled_agents.length > 0 && (
                      <p className="mt-2 rounded-lg bg-amber-50 p-2 text-xs text-amber-900">Unavailable: a required agent is disabled.</p>
                    )}
                  </li>
                ))}
              </ul>
            </section>

            <section>
              <div className="flex items-center justify-between">
                <h2 className="font-semibold">Recent executions</h2>
                <Link href="/dashboard/ai-agents/history" className="text-sm font-medium text-indigo-700">View history</Link>
              </div>
              {!stats || stats.recent.length === 0 ? (
                <p className="mt-3 rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">
                  No workflows yet. <Link href="/dashboard/ai-agents/workflows" className="font-medium text-indigo-700">Start the first one</Link>
                </p>
              ) : (
                <ul className="mt-3 space-y-2">
                  {stats.recent.map((item) => (
                    <li key={item.id} className="rounded-2xl border border-slate-200 bg-white p-4">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0">
                          <Link href={`/dashboard/ai-agents/workflows/${item.id}`} className="font-semibold hover:text-indigo-700">{item.name}</Link>
                          <p className="text-sm text-slate-600">
                            {item.workflow_name} · step {item.steps_done} of {item.steps_total}
                            {item.status === "succeeded" ? ` · ${reviewLabel(item.review_status)}` : ""}
                          </p>
                        </div>
                        <StatusBadge status={item.status} />
                      </div>
                      {item.error_message && item.status === "failed" && <p className="mt-2 text-sm text-red-800">{item.error_message}</p>}
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section>
              <div className="flex items-center justify-between">
                <h2 className="font-semibold">Available agents</h2>
                <Link href="/dashboard/ai-agents/settings" className="text-sm font-medium text-indigo-700">Agents &amp; settings</Link>
              </div>
              <ul className="mt-3 grid gap-3 md:grid-cols-2 lg:grid-cols-4">
                {(catalog?.agents ?? []).map((agent) => (
                  <li key={agent.key} className="rounded-2xl border border-slate-200 bg-white p-4">
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-sm font-semibold">{agent.name}</p>
                      <StatusBadge status={agent.enabled ? "enabled" : "paused"} />
                    </div>
                    <p className="mt-1 text-xs text-slate-600">{agent.description}</p>
                  </li>
                ))}
              </ul>
            </section>

            <HumanControlNote />
          </div>
        )}
      </AppShell>
    </ProtectedPage>
  );
}

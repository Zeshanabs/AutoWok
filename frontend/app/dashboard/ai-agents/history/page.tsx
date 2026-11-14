"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AgentsHeader } from "@/components/agents/agents-shell";
import { useAuth } from "@/components/auth-provider";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { StatusBadge } from "@/components/status-badge";
import { ApiError, apiRequest } from "@/lib/api";
import { reviewLabel, type WorkflowList } from "@/lib/agent-types";

const fieldClass = "rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm";
const STATUSES = ["pending", "running", "succeeded", "failed", "cancelled"];
const TYPES = [
  { value: "content_research", label: "Complete content research" },
  { value: "social_content", label: "High-quality social content" },
  { value: "content_repurposing", label: "Content repurposing" },
  { value: "performance_analysis", label: "Performance analysis" },
];
const PAGE_SIZE = 20;

export default function WorkflowHistoryPage() {
  const { selectedWorkspace } = useAuth();
  const workspaceId = selectedWorkspace?.id;
  const [data, setData] = useState<WorkflowList | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const queryKey = `${workspaceId}|${statusFilter}|${typeFilter}|${offset}`;
  const load = useCallback(async () => {
    if (!workspaceId) return;
    const params = new URLSearchParams({ offset: String(offset), limit: String(PAGE_SIZE) });
    if (statusFilter) params.set("status", statusFilter);
    if (typeFilter) params.set("workflow_type", typeFilter);
    try {
      setData(await apiRequest<WorkflowList>(`/workspaces/${workspaceId}/agent-workflows?${params.toString()}`));
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof ApiError ? loadError.message : "The workflow history could not be loaded.");
    } finally {
      setLoadedKey(`${workspaceId}|${statusFilter}|${typeFilter}|${offset}`);
    }
  }, [workspaceId, statusFilter, typeFilter, offset]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const loading = Boolean(workspaceId) && loadedKey !== queryKey;
  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  return (
    <ProtectedPage>
      <AppShell>
        <AgentsHeader
          active="/dashboard/ai-agents/history"
          title="Workflow history"
          description="Every workflow run in this workspace, with its status, usage and review decision."
          actions={
            <>
              <select aria-label="Filter by workflow" className={fieldClass} value={typeFilter} onChange={(event) => { setTypeFilter(event.target.value); setOffset(0); }}>
                <option value="">All workflows</option>
                {TYPES.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}
              </select>
              <select aria-label="Filter by status" className={fieldClass} value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value); setOffset(0); }}>
                <option value="">All statuses</option>
                {STATUSES.map((status) => <option key={status} value={status}>{status}</option>)}
              </select>
            </>
          }
        />
        {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}

        {!workspaceId ? (
          <p className="mt-6 rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">Select a workspace.</p>
        ) : loading && items.length === 0 ? (
          <p className="mt-6 text-sm text-slate-500">Loading history…</p>
        ) : items.length === 0 ? (
          <p className="mt-6 rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">
            {statusFilter || typeFilter ? "No workflows match these filters." : (
              <>No workflows have run yet. <Link href="/dashboard/ai-agents/workflows" className="font-medium text-indigo-700">Start one</Link></>
            )}
          </p>
        ) : (
          <>
            <div className="mt-6 overflow-x-auto rounded-2xl border border-slate-200 bg-white">
              <table className="min-w-full text-left text-sm">
                <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th scope="col" className="px-4 py-3">Workflow</th>
                    <th scope="col" className="px-4 py-3">Status</th>
                    <th scope="col" className="px-4 py-3">Review</th>
                    <th scope="col" className="px-4 py-3">Agent calls</th>
                    <th scope="col" className="px-4 py-3">Tokens</th>
                    <th scope="col" className="px-4 py-3">Started</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {items.map((item) => (
                    <tr key={item.id}>
                      <td className="px-4 py-3">
                        <Link href={`/dashboard/ai-agents/workflows/${item.id}`} className="font-medium hover:text-indigo-700">{item.name}</Link>
                        <p className="text-xs text-slate-500">{item.workflow_name}{item.brand_name ? ` · ${item.brand_name}` : ""} · {item.created_by_name ?? "former member"}</p>
                        {item.status === "failed" && item.error_message && <p className="mt-1 text-xs text-red-800">{item.error_message}</p>}
                      </td>
                      <td className="px-4 py-3"><StatusBadge status={item.status} /></td>
                      <td className="px-4 py-3 text-slate-600">{item.status === "succeeded" ? reviewLabel(item.review_status) : "—"}</td>
                      <td className="px-4 py-3 text-slate-600">{item.agent_call_count}</td>
                      <td className="px-4 py-3 text-slate-600">{item.total_tokens.toLocaleString()}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-slate-600">{new Date(item.created_at).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-4 flex items-center justify-between text-sm text-slate-600">
              <span>{offset + 1}–{Math.min(offset + items.length, total)} of {total}</span>
              <div className="flex gap-2">
                <button type="button" className={`${fieldClass} disabled:opacity-50`} disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Previous</button>
                <button type="button" className={`${fieldClass} disabled:opacity-50`} disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>Next</button>
              </div>
            </div>
          </>
        )}
      </AppShell>
    </ProtectedPage>
  );
}

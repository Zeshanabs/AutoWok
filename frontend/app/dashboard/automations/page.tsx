"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { StatusBadge } from "@/components/status-badge";
import { ApiError, apiRequest } from "@/lib/api";
import type { Automation } from "@/lib/automation-types";

const fieldClass = "rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm";
const STATUSES = ["draft", "enabled", "paused", "archived"];

export default function AutomationsPage() {
  const { selectedWorkspace } = useAuth();
  const workspaceId = selectedWorkspace?.id;
  const canManage = selectedWorkspace?.role === "OWNER" || selectedWorkspace?.role === "ADMIN";
  const [items, setItems] = useState<Automation[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const queryKey = `${workspaceId}|${statusFilter}`;
  const load = useCallback(async () => {
    if (!workspaceId) return;
    const params = new URLSearchParams();
    if (statusFilter) params.set("status", statusFilter);
    try {
      setItems(await apiRequest<Automation[]>(`/workspaces/${workspaceId}/automations?${params.toString()}`));
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof ApiError ? loadError.message : "Automations could not be loaded.");
    } finally {
      setLoadedKey(`${workspaceId}|${statusFilter}`);
    }
  }, [workspaceId, statusFilter]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const loading = Boolean(workspaceId) && loadedKey !== queryKey;

  return (
    <ProtectedPage>
      <AppShell>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-indigo-700">Automations</p>
            <h1 className="mt-2 text-3xl font-bold tracking-tight">Workflow automations</h1>
            <p className="mt-1 text-sm text-slate-600">
              Rule-based workflows: a trigger, optional conditions, and allowlisted actions. Automations never publish content or bypass approvals.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <select aria-label="Filter by status" className={fieldClass} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">Active (not archived)</option>
              {STATUSES.map((status) => <option key={status} value={status}>{status}</option>)}
            </select>
            <Link href="/dashboard/notifications" className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium">Notifications</Link>
            {canManage && (
              <Link href="/dashboard/automations/new" className="rounded-xl bg-indigo-600 px-3 py-2 text-sm font-semibold text-white hover:bg-indigo-700">
                New automation
              </Link>
            )}
          </div>
        </div>

        {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}

        {!workspaceId ? (
          <p className="mt-6 rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">Select a workspace.</p>
        ) : loading && items.length === 0 ? (
          <p className="mt-6 text-sm text-slate-500">Loading automations…</p>
        ) : items.length === 0 ? (
          <p className="mt-6 rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">
            No automations yet.{" "}
            {canManage ? (
              <Link href="/dashboard/automations/new" className="font-medium text-indigo-700">Create the first one</Link>
            ) : (
              "Workspace Owners and Admins can create automations."
            )}
          </p>
        ) : (
          <ul className="mt-6 space-y-3">
            {items.map((item) => (
              <li key={item.id} className="rounded-2xl border border-slate-200 bg-white p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <Link href={`/dashboard/automations/${item.id}`} className="font-semibold hover:text-indigo-700">{item.name}</Link>
                    {item.description && <p className="text-sm text-slate-600">{item.description}</p>}
                    <p className="mt-1 text-sm text-slate-600">
                      When <span className="font-medium">{item.trigger_label}</span>
                      {item.brand_name ? ` · ${item.brand_name}` : ""} · {item.actions.length} action{item.actions.length === 1 ? "" : "s"}
                    </p>
                  </div>
                  <StatusBadge status={item.status} />
                </div>
                <dl className="mt-3 grid gap-2 text-xs text-slate-600 sm:grid-cols-4">
                  <div>
                    <dt className="text-slate-500">Last execution</dt>
                    <dd>
                      {item.last_execution ? (
                        <>
                          {new Date(item.last_execution.created_at).toLocaleString()} · <StatusBadge status={item.last_execution.status} />
                        </>
                      ) : "Never"}
                    </dd>
                  </div>
                  <div><dt className="text-slate-500">Succeeded / failed</dt><dd>{item.success_count} / {item.failure_count}</dd></div>
                  <div><dt className="text-slate-500">Created by</dt><dd>{item.created_by_name ?? "—"}</dd></div>
                  <div><dt className="text-slate-500">Updated</dt><dd>{new Date(item.updated_at).toLocaleString()}</dd></div>
                </dl>
                {item.issues.length > 0 && item.status !== "archived" && (
                  <p className="mt-2 rounded-lg bg-amber-50 p-2 text-xs text-amber-900">{item.issues[0]}{item.issues.length > 1 ? ` (+${item.issues.length - 1} more)` : ""}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </AppShell>
    </ProtectedPage>
  );
}

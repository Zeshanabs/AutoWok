"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { DryRunPanel } from "@/components/automations/dry-run-panel";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { StatusBadge } from "@/components/status-badge";
import { ApiError, apiRequest } from "@/lib/api";
import {
  OPERATOR_LABELS,
  formatDuration,
  isConditionGroup,
  type AutomationDetail,
  type ConditionGroup,
  type DryRunResult,
  type Execution,
} from "@/lib/automation-types";

type Pending = { kind: "pause" | "archive" | "delete" | "enable" | "resume" } | null;

function describeConditions(group: ConditionGroup, depth = 0): string[] {
  const lines: string[] = [];
  for (const rule of group.rules) {
    if (isConditionGroup(rule)) {
      lines.push(`${"  ".repeat(depth)}${rule.logic === "or" ? "any of:" : "all of:"}`);
      lines.push(...describeConditions(rule, depth + 1));
    } else {
      const value = Array.isArray(rule.value) ? rule.value.join(", ") : rule.value === undefined ? "" : String(rule.value);
      lines.push(`${"  ".repeat(depth)}${rule.field} ${OPERATOR_LABELS[rule.operator] ?? rule.operator} ${value}`.trimEnd());
    }
  }
  return lines;
}

function ExecutionRow({ execution, canManage, onRetry }: { execution: Execution; canManage: boolean; onRetry: (execution: Execution) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="rounded-xl border border-slate-200 p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <span className="font-medium">{new Date(execution.created_at).toLocaleString()}</span>
          <span className="text-slate-500"> · {execution.trigger_type}</span>
          {execution.retry_count > 0 && <span className="text-slate-500"> · retry {execution.retry_count}/{execution.max_retries}</span>}
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge status={execution.status} />
          <button type="button" className="font-medium text-indigo-700" onClick={() => setOpen((value) => !value)}>
            {open ? "Hide steps" : "Steps"}
          </button>
          {canManage && execution.can_retry && (
            <button type="button" className="font-medium text-indigo-700" onClick={() => onRetry(execution)}>Retry</button>
          )}
        </div>
      </div>
      {execution.error_message && <p className="mt-1 text-red-800">{execution.error_message}</p>}
      {execution.next_attempt_at && execution.status === "pending" && (
        <p className="mt-1 text-xs text-slate-500">Next attempt {new Date(execution.next_attempt_at).toLocaleString()}</p>
      )}
      {open && (
        <ol className="mt-2 space-y-1">
          {execution.steps.length === 0 && <li className="text-xs text-slate-500">No steps recorded yet.</li>}
          {execution.steps.map((step) => (
            <li key={step.id} className="rounded-lg bg-slate-50 p-2 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span>{step.execution_order}. {step.action_type}</span>
                <StatusBadge status={step.status} />
              </div>
              {step.result_summary && typeof step.result_summary.summary === "string" && <p className="mt-1 text-slate-700">{step.result_summary.summary}</p>}
              {step.error_message && <p className="mt-1 text-red-800">{step.error_message}</p>}
            </li>
          ))}
        </ol>
      )}
    </li>
  );
}

export default function AutomationDetailPage() {
  const { automationId } = useParams<{ automationId: string }>();
  const router = useRouter();
  const { selectedWorkspace } = useAuth();
  const workspaceId = selectedWorkspace?.id;
  const canManage = selectedWorkspace?.role === "OWNER" || selectedWorkspace?.role === "ADMIN";
  const [automation, setAutomation] = useState<AutomationDetail | null>(null);
  const [executions, setExecutions] = useState<Execution[]>([]);
  const [executionFilter, setExecutionFilter] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<Pending>(null);
  const [dryRun, setDryRun] = useState<DryRunResult | null>(null);
  const [payloadSource, setPayloadSource] = useState<"sample" | "latest_event">("sample");

  const load = useCallback(async () => {
    if (!workspaceId) return;
    try {
      const params = executionFilter ? `?status=${executionFilter}` : "";
      const [detail, history] = await Promise.all([
        apiRequest<AutomationDetail>(`/workspaces/${workspaceId}/automations/${automationId}`),
        apiRequest<Execution[]>(`/workspaces/${workspaceId}/automations/${automationId}/executions${params}`),
      ]);
      setAutomation(detail);
      setExecutions(history);
      setDryRun((current) => current ?? detail.last_dry_run);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof ApiError ? loadError.message : "The automation could not be loaded.");
    } finally {
      setLoaded(true);
    }
  }, [workspaceId, automationId, executionFilter]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const hasActive = executions.some((item) => item.status === "pending" || item.status === "running");
  useEffect(() => {
    if (!hasActive) return;
    const timer = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(timer);
  }, [hasActive, load]);

  const act = async (path: string, success: string, method: "POST" | "DELETE" = "POST") => {
    if (!workspaceId) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await apiRequest(`/workspaces/${workspaceId}/automations/${automationId}${path}`, { method, body: method === "POST" ? JSON.stringify({}) : undefined });
      setNotice(success);
      if (method === "DELETE") {
        router.push("/dashboard/automations");
        return;
      }
      await load();
    } catch (actionError) {
      setError(actionError instanceof ApiError ? actionError.message : "The action could not be completed.");
    } finally {
      setBusy(false);
      setPending(null);
    }
  };

  const duplicate = async () => {
    if (!workspaceId) return;
    setBusy(true);
    try {
      const copy = await apiRequest<AutomationDetail>(`/workspaces/${workspaceId}/automations/${automationId}/duplicate`, { method: "POST", body: JSON.stringify({}) });
      router.push(`/dashboard/automations/${copy.id}`);
    } catch (actionError) {
      setError(actionError instanceof ApiError ? actionError.message : "The automation could not be duplicated.");
    } finally {
      setBusy(false);
    }
  };

  const runDryRun = async () => {
    if (!workspaceId) return;
    setBusy(true);
    setError(null);
    try {
      setDryRun(
        await apiRequest<DryRunResult>(`/workspaces/${workspaceId}/automations/${automationId}/dry-run`, {
          method: "POST",
          body: JSON.stringify({ payload_source: payloadSource }),
        }),
      );
    } catch (actionError) {
      setError(actionError instanceof ApiError ? actionError.message : "The test could not be run.");
    } finally {
      setBusy(false);
    }
  };

  const retry = async (execution: Execution) => {
    if (!workspaceId) return;
    setBusy(true);
    setError(null);
    try {
      await apiRequest(`/workspaces/${workspaceId}/automation-executions/${execution.id}/retry`, { method: "POST", body: JSON.stringify({}) });
      setNotice("Execution queued for retry.");
      await load();
    } catch (actionError) {
      setError(actionError instanceof ApiError ? actionError.message : "The execution could not be retried.");
    } finally {
      setBusy(false);
    }
  };

  const confirmCopy: Record<NonNullable<Pending>["kind"], { title: string; body: string; label: string; tone: "danger" | "primary"; path: string; success: string; method?: "DELETE" }> = {
    enable: { title: "Enable this automation?", body: "It will start running for every matching event until you pause it. It runs with your permissions.", label: "Enable", tone: "primary", path: "/enable", success: "Automation enabled." },
    resume: { title: "Resume this automation?", body: "It will start running again for new matching events.", label: "Resume", tone: "primary", path: "/resume", success: "Automation resumed." },
    pause: { title: "Pause this automation?", body: "New events will be ignored and queued executions will be cancelled until you resume it.", label: "Pause", tone: "danger", path: "/pause", success: "Automation paused." },
    archive: { title: "Archive this automation?", body: "Archived automations never run again and cannot be edited. The execution history is kept.", label: "Archive", tone: "danger", path: "/archive", success: "Automation archived." },
    delete: { title: "Delete this automation permanently?", body: "The automation and its execution history are removed. This cannot be undone.", label: "Delete", tone: "danger", path: "", success: "Automation deleted.", method: "DELETE" },
  };

  return (
    <ProtectedPage>
      <AppShell>
        <Link href="/dashboard/automations" className="text-sm font-semibold text-indigo-700">← Automations</Link>
        {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
        {notice && <p role="status" className="mt-4 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
        {!loaded ? (
          <p className="mt-6 text-sm text-slate-500">Loading…</p>
        ) : automation ? (
          <div className="mt-4 grid gap-6 lg:grid-cols-[3fr_2fr]">
            <div className="space-y-6">
              <section className="rounded-2xl border border-slate-200 bg-white p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h1 className="text-2xl font-bold">{automation.name}</h1>
                    {automation.description && <p className="mt-1 text-sm text-slate-600">{automation.description}</p>}
                  </div>
                  <StatusBadge status={automation.status} />
                </div>
                <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
                  <div><dt className="text-slate-500">Trigger</dt><dd className="font-medium">{automation.trigger_label}</dd></div>
                  <div><dt className="text-slate-500">Brand scope</dt><dd>{automation.brand_name ?? "All brands"}</dd></div>
                  {Object.entries(automation.trigger_configuration).map(([key, value]) => (
                    <div key={key}><dt className="text-slate-500">{key.replaceAll("_", " ")}</dt><dd>{String(value)}</dd></div>
                  ))}
                  <div><dt className="text-slate-500">Cooldown</dt><dd>{formatDuration(automation.cooldown_seconds)}</dd></div>
                  <div><dt className="text-slate-500">Lifetime cap</dt><dd>{automation.max_executions ?? "none"}</dd></div>
                  <div><dt className="text-slate-500">Created</dt><dd>{new Date(automation.created_at).toLocaleString()} by {automation.created_by_name ?? "—"}</dd></div>
                  <div><dt className="text-slate-500">Updated</dt><dd>{new Date(automation.updated_at).toLocaleString()}</dd></div>
                </dl>
                <h2 className="mt-5 text-sm font-semibold">Conditions ({automation.conditions.logic === "or" ? "any" : "all"} must match)</h2>
                {automation.conditions.rules.length === 0 ? (
                  <p className="text-sm text-slate-600">None: runs for every event of this trigger in its scope.</p>
                ) : (
                  <pre className="mt-1 whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-sm">{describeConditions(automation.conditions).join("\n")}</pre>
                )}
                <h2 className="mt-5 text-sm font-semibold">Actions in order</h2>
                <ol className="mt-1 space-y-1">
                  {automation.actions.map((action) => (
                    <li key={action.id} className="rounded-lg bg-slate-50 p-3 text-sm">
                      <span className="font-medium">{action.execution_order}. {action.label}</span>
                      <dl className="mt-1 grid gap-x-4 text-xs text-slate-600 sm:grid-cols-2">
                        {Object.entries(action.action_configuration).map(([key, value]) => (
                          <div key={key} className="flex gap-1"><dt className="text-slate-500">{key.replaceAll("_", " ")}:</dt><dd className="break-all">{String(value)}</dd></div>
                        ))}
                      </dl>
                    </li>
                  ))}
                </ol>
                {automation.issues.length > 0 && automation.status !== "archived" && (
                  <ul role="alert" className="mt-4 list-disc space-y-1 rounded-lg bg-amber-50 p-3 pl-7 text-sm text-amber-900">
                    {automation.issues.map((issue) => <li key={issue}>{issue}</li>)}
                  </ul>
                )}
                {canManage && (
                  <div className="mt-5 flex flex-wrap gap-2 text-sm">
                    {(automation.status === "draft" || automation.status === "paused") && (
                      <button type="button" disabled={busy || !automation.can_enable} onClick={() => setPending({ kind: automation.status === "paused" ? "resume" : "enable" })} className="rounded-xl bg-indigo-600 px-4 py-2 font-semibold text-white disabled:bg-slate-300">
                        {automation.status === "paused" ? "Resume" : "Enable"}
                      </button>
                    )}
                    {automation.status === "enabled" && (
                      <button type="button" disabled={busy} onClick={() => setPending({ kind: "pause" })} className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-2 font-medium text-amber-900">Pause</button>
                    )}
                    {automation.status !== "archived" && (
                      <Link href={`/dashboard/automations/${automation.id}/edit`} className="rounded-xl border border-slate-300 px-4 py-2 font-medium">Edit</Link>
                    )}
                    <button type="button" disabled={busy} onClick={() => void duplicate()} className="rounded-xl border border-slate-300 px-4 py-2 font-medium">Duplicate</button>
                    {automation.status !== "archived" && (
                      <button type="button" disabled={busy} onClick={() => setPending({ kind: "archive" })} className="rounded-xl border border-slate-300 px-4 py-2 font-medium text-red-700">Archive</button>
                    )}
                    {(automation.status === "draft" || automation.status === "archived") && (
                      <button type="button" disabled={busy} onClick={() => setPending({ kind: "delete" })} className="rounded-xl border border-red-300 px-4 py-2 font-medium text-red-700">Delete</button>
                    )}
                  </div>
                )}
              </section>

              <section className="rounded-2xl border border-slate-200 bg-white p-5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h2 className="font-semibold">Execution history</h2>
                  <select aria-label="Filter executions" className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm" value={executionFilter} onChange={(e) => setExecutionFilter(e.target.value)}>
                    <option value="">All</option>
                    {["pending", "running", "succeeded", "failed", "cancelled"].map((status) => <option key={status} value={status}>{status}</option>)}
                  </select>
                </div>
                <p className="mt-1 text-xs text-slate-500">{automation.execution_count} total · {automation.success_count} succeeded · {automation.failure_count} failed</p>
                {executions.length === 0 ? (
                  <p className="mt-3 text-sm text-slate-500">No executions yet.</p>
                ) : (
                  <ul className="mt-3 space-y-2">
                    {executions.map((execution) => <ExecutionRow key={execution.id} execution={execution} canManage={canManage} onRetry={(item) => void retry(item)} />)}
                  </ul>
                )}
              </section>
            </div>

            <aside className="space-y-6">
              <section className="rounded-2xl border border-slate-200 bg-white p-5">
                <h2 className="font-semibold">Test (dry run)</h2>
                <p className="mt-1 text-xs text-slate-500">Evaluates the conditions and lists what each action would do. No notification, task, assignment or Meta request is created.</p>
                {canManage && (
                  <div className="mt-3 flex flex-wrap items-end gap-2">
                    <label className="text-xs text-slate-600">
                      Event data
                      <select aria-label="Dry run data source" className="mt-1 block rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm" value={payloadSource} onChange={(e) => setPayloadSource(e.target.value as "sample" | "latest_event")}>
                        <option value="sample">Built-in sample</option>
                        <option value="latest_event">Latest recorded event</option>
                      </select>
                    </label>
                    <button type="button" disabled={busy} onClick={() => void runDryRun()} className="rounded-xl border border-indigo-300 bg-indigo-50 px-4 py-2 text-sm font-medium text-indigo-800 disabled:opacity-50">
                      Run test
                    </button>
                  </div>
                )}
                {dryRun ? <DryRunPanel result={dryRun} className="mt-4" /> : <p className="mt-3 text-sm text-slate-500">No test has been run yet.</p>}
              </section>
              <section className="rounded-2xl border border-slate-200 bg-white p-5">
                <h2 className="font-semibold">Recent failures</h2>
                {executions.filter((item) => item.status === "failed").length === 0 ? (
                  <p className="mt-2 text-sm text-slate-500">No failed executions.</p>
                ) : (
                  <ul className="mt-2 space-y-2 text-sm">
                    {executions.filter((item) => item.status === "failed").slice(0, 5).map((item) => (
                      <li key={item.id} className="rounded-lg bg-red-50 p-2 text-red-900">
                        <span className="text-xs text-red-700">{new Date(item.created_at).toLocaleString()}</span>
                        <p>{item.error_message}</p>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </aside>
          </div>
        ) : null}

        {pending && (
          <ConfirmDialog
            open
            title={confirmCopy[pending.kind].title}
            confirmLabel={confirmCopy[pending.kind].label}
            tone={confirmCopy[pending.kind].tone}
            busy={busy}
            onCancel={() => setPending(null)}
            onConfirm={() => void act(confirmCopy[pending.kind].path, confirmCopy[pending.kind].success, confirmCopy[pending.kind].method ?? "POST")}
          >
            <p>{confirmCopy[pending.kind].body}</p>
          </ConfirmDialog>
        )}
      </AppShell>
    </ProtectedPage>
  );
}

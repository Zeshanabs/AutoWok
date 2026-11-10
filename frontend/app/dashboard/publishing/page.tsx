"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { StatusBadge } from "@/components/status-badge";
import { ApiError, apiRequest } from "@/lib/api";
import { ACTIVE_PUBLICATION_STATUSES, type Publication } from "@/lib/media-types";

const fieldClass = "rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm";
const STATUSES = ["pending", "processing", "publishing", "published", "failed", "cancelled"];

export default function PublishingHistoryPage() {
  const { selectedWorkspace } = useAuth();
  const workspaceId = selectedWorkspace?.id;
  const canManage = selectedWorkspace?.role === "OWNER" || selectedWorkspace?.role === "ADMIN";
  const [jobs, setJobs] = useState<Publication[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [platformFilter, setPlatformFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [selected, setSelected] = useState<Publication | null>(null);
  const [retryTarget, setRetryTarget] = useState<Publication | null>(null);
  const [confirmNotPublished, setConfirmNotPublished] = useState(false);
  const [busy, setBusy] = useState(false);

  const queryKey = `${workspaceId}|${statusFilter}|${platformFilter}|${sourceFilter}`;
  const load = useCallback(async () => {
    if (!workspaceId) return;
    const params = new URLSearchParams();
    if (statusFilter) params.set("status", statusFilter);
    if (platformFilter) params.set("platform", platformFilter);
    if (sourceFilter) params.set("source", sourceFilter);
    try {
      const data = await apiRequest<Publication[]>(`/workspaces/${workspaceId}/publishing/jobs?${params.toString()}`);
      setJobs(data);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof ApiError ? loadError.message : "Publishing history could not be loaded.");
    } finally {
      setLoadedKey(`${workspaceId}|${statusFilter}|${platformFilter}|${sourceFilter}`);
    }
  }, [workspaceId, statusFilter, platformFilter, sourceFilter]);
  const loading = Boolean(workspaceId) && loadedKey !== queryKey;

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const hasActive = jobs.some((job) => ACTIVE_PUBLICATION_STATUSES.includes(job.status));
  useEffect(() => {
    if (!hasActive) return;
    const timer = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(timer);
  }, [hasActive, load]);

  const openDetails = async (job: Publication) => {
    try {
      setSelected(await apiRequest<Publication>(`/publishing/jobs/${job.id}`));
    } catch (detailError) {
      setError(detailError instanceof ApiError ? detailError.message : "Job details could not be loaded.");
    }
  };

  const runAction = async (job: Publication, action: "retry" | "cancel") => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await apiRequest(`/publishing/jobs/${job.id}/${action}`, {
        method: "POST",
        body: action === "retry" ? JSON.stringify({ confirm_not_published: confirmNotPublished }) : undefined,
      });
      setNotice(action === "retry" ? "Retry queued." : "Job cancelled.");
      setRetryTarget(null);
      setSelected(null);
      await load();
    } catch (actionError) {
      setError(actionError instanceof ApiError ? actionError.message : "The action could not be completed.");
      setRetryTarget(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <ProtectedPage>
      <AppShell>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-indigo-700">Publishing</p>
            <h1 className="mt-2 text-3xl font-bold tracking-tight">Publishing history</h1>
            <p className="mt-1 text-sm text-slate-600">Every publish request, its attempts, and Meta&apos;s result.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <select aria-label="Filter by status" className={fieldClass} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">All statuses</option>
              {STATUSES.map((status) => <option key={status} value={status}>{status}</option>)}
            </select>
            <select aria-label="Filter by platform" className={fieldClass} value={platformFilter} onChange={(e) => setPlatformFilter(e.target.value)}>
              <option value="">All platforms</option>
              <option value="facebook">Facebook</option>
              <option value="instagram">Instagram</option>
            </select>
            <select aria-label="Filter by source" className={fieldClass} value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}>
              <option value="">Manual and scheduled</option>
              <option value="manual">Published immediately</option>
              <option value="schedule">Scheduled</option>
            </select>
            <Link href="/dashboard/publishing/queue" className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium">Queue</Link>
          </div>
        </div>

        {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
        {notice && <p role="status" className="mt-4 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}

        {!workspaceId ? (
          <p className="mt-6 rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">Select a workspace.</p>
        ) : loading && jobs.length === 0 ? (
          <p className="mt-6 text-sm text-slate-500">Loading publishing history…</p>
        ) : jobs.length === 0 ? (
          <p className="mt-6 rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">
            Nothing has been published yet. Approved drafts can be published from the <Link href="/dashboard/content" className="font-medium text-indigo-700">content studio</Link>.
          </p>
        ) : (
          <ul className="mt-6 space-y-3">
            {jobs.map((job) => (
              <li key={job.id} className="rounded-2xl border border-slate-200 bg-white p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <Link href={`/dashboard/content/${job.project_id}`} className="font-semibold hover:text-indigo-700">{job.project_title ?? "Content"}</Link>
                    <p className="text-sm text-slate-600">
                      <span className="capitalize">{job.platform}</span> · {job.account_name ?? "Account removed"} · {job.source === "schedule" ? "Scheduled" : "Manual"}
                    </p>
                    <p className="text-xs text-slate-500">
                      Requested {new Date(job.created_at).toLocaleString()}
                      {job.published_at && ` · Published ${new Date(job.published_at).toLocaleString()}`}
                    </p>
                  </div>
                  <StatusBadge status={job.status} />
                </div>
                {job.error_message && <p className="mt-2 text-sm text-red-800">{job.error_message}</p>}
                <div className="mt-3 flex flex-wrap gap-4 text-sm">
                  <button type="button" onClick={() => void openDetails(job)} className="font-medium text-indigo-700">Details</button>
                  {job.permalink && <a href={job.permalink} target="_blank" rel="noreferrer noopener" className="font-medium text-indigo-700">View post ↗</a>}
                  {canManage && job.can_retry && (
                    <button type="button" onClick={() => { setConfirmNotPublished(false); setRetryTarget(job); }} className="font-medium text-indigo-700">Retry</button>
                  )}
                  {canManage && job.can_cancel && job.source === "manual" && (
                    <button type="button" disabled={busy} onClick={() => void runAction(job, "cancel")} className="font-medium text-red-700">Cancel</button>
                  )}
                  {job.error_category === "token_expired" || job.error_category === "permission" ? (
                    <Link href="/settings/social-accounts" className="font-medium text-amber-800">Reconnect account</Link>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}

        {selected && (
          <div className="fixed inset-0 z-40 flex items-end justify-center bg-slate-900/40 p-4 sm:items-center" onClick={() => setSelected(null)}>
            <div role="dialog" aria-modal="true" aria-label="Job details" className="max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-2xl bg-white p-6" onClick={(e) => e.stopPropagation()}>
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-lg font-semibold">Publishing job</h2>
                <StatusBadge status={selected.status} />
              </div>
              <dl className="mt-4 grid grid-cols-2 gap-2 text-sm">
                <dt className="text-slate-500">Format</dt><dd>{selected.publish_format ?? "—"}</dd>
                <dt className="text-slate-500">Content version</dt><dd>{selected.content_version_number ?? "—"}</dd>
                <dt className="text-slate-500">External ID</dt><dd className="break-all">{selected.external_post_id ?? "—"}</dd>
                <dt className="text-slate-500">Attempts</dt><dd>{selected.attempt_count} of {selected.max_attempts}</dd>
              </dl>
              {selected.caption && <p className="mt-4 whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-sm">{selected.caption}</p>}
              <h3 className="mt-4 text-sm font-semibold">Attempts</h3>
              <ol className="mt-2 space-y-2">
                {selected.attempts.map((attempt) => (
                  <li key={attempt.id} className="rounded-lg border border-slate-200 p-2 text-sm">
                    <div className="flex justify-between"><span>#{attempt.attempt_number} · {attempt.stage ?? "start"}</span><StatusBadge status={attempt.status === "succeeded" ? "published" : attempt.status} /></div>
                    <p className="text-xs text-slate-500">{new Date(attempt.started_at).toLocaleString()}</p>
                    {attempt.error_message && <p className="mt-1 text-red-800">{attempt.error_message} {attempt.error_code ? `(${attempt.error_code})` : ""}</p>}
                  </li>
                ))}
                {selected.attempts.length === 0 && <li className="text-sm text-slate-500">No attempts yet.</li>}
              </ol>
              <button type="button" onClick={() => setSelected(null)} className="mt-4 rounded-xl border border-slate-300 px-4 py-2 text-sm">Close</button>
            </div>
          </div>
        )}

        <ConfirmDialog
          open={retryTarget !== null}
          title="Retry publishing?"
          confirmLabel="Retry"
          busy={busy}
          confirmDisabled={Boolean(retryTarget?.outcome_uncertain && !confirmNotPublished)}
          onCancel={() => setRetryTarget(null)}
          onConfirm={() => retryTarget && void runAction(retryTarget, "retry")}
        >
          <p>The content and account are re-checked before publishing again.</p>
          {retryTarget?.outcome_uncertain && (
            <label className="flex items-start gap-2 text-amber-900">
              <input type="checkbox" className="mt-0.5" checked={confirmNotPublished} onChange={(e) => setConfirmNotPublished(e.target.checked)} />
              Meta never confirmed the previous attempt. I checked {retryTarget.account_name ?? "the account"} and the post is not there.
            </label>
          )}
        </ConfirmDialog>
      </AppShell>
    </ProtectedPage>
  );
}

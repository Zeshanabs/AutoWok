"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { StatusBadge } from "@/components/status-badge";
import { TimezoneSelect } from "@/components/timezone-select";
import { ApiError, apiRequest } from "@/lib/api";
import { HISTORY_LABELS, type ScheduledPost } from "@/lib/scheduling-types";
import { formatInZone, splitLocal } from "@/lib/timezones";

const fieldClass = "w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm";
const ACTIVE = ["queued", "processing"];

export default function ScheduleDetailPage() {
  const { scheduleId } = useParams<{ scheduleId: string }>();
  const [post, setPost] = useState<ScheduledPost | null>(null);
  const [loadedId, setLoadedId] = useState<string | null>(null);
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [timezone, setTimezone] = useState("");
  const [ambiguous, setAmbiguous] = useState<"" | "earlier" | "later">("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [confirmRetry, setConfirmRetry] = useState(false);
  const [notPublished, setNotPublished] = useState(false);

  const apply = useCallback((data: ScheduledPost) => {
    setPost(data);
    const local = splitLocal(data.scheduled_local);
    setDate(local.date);
    setTime(local.time);
    setTimezone(data.timezone);
  }, []);

  useEffect(() => {
    let active = true;
    apiRequest<ScheduledPost>(`/scheduled-posts/${scheduleId}`)
      .then((data) => {
        if (!active) return;
        apply(data);
        setLoadedId(scheduleId);
      })
      .catch((loadError: unknown) => {
        if (!active) return;
        setError(loadError instanceof ApiError ? loadError.message : "The scheduled post could not be loaded.");
        setLoadedId(scheduleId);
      });
    return () => {
      active = false;
    };
  }, [scheduleId, apply]);

  const isActive = Boolean(post && ACTIVE.includes(post.status));
  useEffect(() => {
    if (!isActive) return;
    const timer = window.setInterval(() => {
      void apiRequest<ScheduledPost>(`/scheduled-posts/${scheduleId}`).then(setPost).catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [isActive, scheduleId]);

  const act = async (path: string, body: unknown, success: string) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const data = await apiRequest<ScheduledPost>(`/scheduled-posts/${scheduleId}${path}`, { method: "POST", body: JSON.stringify(body) });
      apply(data);
      setNotice(success);
    } catch (actionError) {
      setError(actionError instanceof ApiError ? actionError.message : "The action could not be completed.");
    } finally {
      setBusy(false);
      setConfirmCancel(false);
      setConfirmRetry(false);
    }
  };

  const reschedule = () =>
    act("/reschedule", { scheduled_local: `${date}T${time}`, timezone, ambiguous: ambiguous || undefined }, "Schedule updated.");

  return (
    <ProtectedPage>
      <AppShell>
        <Link href="/dashboard/calendar" className="text-sm font-semibold text-indigo-700">← Calendar</Link>
        {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
        {notice && <p role="status" className="mt-4 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
        {loadedId !== scheduleId ? (
          <p className="mt-6 text-sm text-slate-500">Loading…</p>
        ) : post ? (
          <div className="mt-4 grid gap-6 lg:grid-cols-[3fr_2fr]">
            <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h1 className="text-2xl font-bold">{post.title ?? "Scheduled post"}</h1>
                  <p className="mt-1 text-sm text-slate-600">
                    {post.platform === "facebook" ? "Facebook Page" : "Instagram"} · {post.account_name ?? "Account"}
                    {post.brand_name ? ` · ${post.brand_name}` : ""}
                  </p>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <StatusBadge status={post.status} />
                  {post.approval_status && <StatusBadge status={post.approval_status} />}
                </div>
              </div>
              <dl className="grid gap-3 text-sm sm:grid-cols-2">
                <div><dt className="text-slate-500">Scheduled for</dt><dd className="font-medium">{formatInZone(post.scheduled_at, post.timezone)} ({post.timezone.replaceAll("_", " ")}, {post.utc_offset})</dd></div>
                <div><dt className="text-slate-500">UTC</dt><dd>{post.scheduled_at}</dd></div>
                <div><dt className="text-slate-500">Content version</dt><dd>{post.content_version_number}{post.content_changed ? ` (current: ${post.current_content_version})` : ""}</dd></div>
                <div><dt className="text-slate-500">Account status</dt><dd>{post.account_status ?? "—"}</dd></div>
              </dl>
              {post.caption_preview && <p className="rounded-lg bg-slate-50 p-3 text-sm">{post.caption_preview}</p>}
              {post.content_changed && (
                <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
                  The content changed after this post was scheduled. Get it approved again, then save the schedule to use the new version. Otherwise it will not publish.
                </p>
              )}
              {post.last_error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-900">{post.last_error}</p>}
              {(post.account_status === "expired" || post.publication?.error_category === "permission") && (
                <Link href="/settings/social-accounts" className="inline-block text-sm font-semibold text-amber-800">Reconnect the account →</Link>
              )}
              {post.permalink && <a href={post.permalink} target="_blank" rel="noreferrer noopener" className="inline-block text-sm font-semibold text-indigo-700">View published post ↗</a>}

              {post.can_edit && (
                <div className="space-y-3 border-t border-slate-100 pt-4">
                  <h2 className="font-semibold">Reschedule</h2>
                  <div className="grid gap-3 sm:grid-cols-3">
                    <input type="date" aria-label="Date" className={fieldClass} value={date} onChange={(e) => setDate(e.target.value)} />
                    <input type="time" aria-label="Time" className={fieldClass} value={time} onChange={(e) => setTime(e.target.value)} />
                    <TimezoneSelect value={timezone} onChange={setTimezone} className="w-full" />
                  </div>
                  {error?.includes("happens twice") && (
                    <div className="flex gap-4 text-sm">
                      {(["earlier", "later"] as const).map((option) => (
                        <label key={option} className="inline-flex items-center gap-1.5">
                          <input type="radio" name="fold" checked={ambiguous === option} onChange={() => setAmbiguous(option)} /> {option}
                        </label>
                      ))}
                    </div>
                  )}
                  <button type="button" disabled={busy} onClick={() => void reschedule()} className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:bg-slate-300">
                    Save schedule
                  </button>
                </div>
              )}
              <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-4">
                {post.can_cancel && (
                  <button type="button" disabled={busy} onClick={() => setConfirmCancel(true)} className="rounded-xl border border-red-300 px-4 py-2 text-sm font-medium text-red-700">Cancel schedule</button>
                )}
                {post.can_retry && (
                  <button type="button" disabled={busy} onClick={() => { setNotPublished(false); setConfirmRetry(true); }} className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-medium">Retry publishing</button>
                )}
                <Link href={`/dashboard/content/${post.project_id}`} className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-medium">Open content</Link>
              </div>
              {post.status === "processing" && <p className="text-sm text-slate-600">Publishing is in progress and can no longer be changed.</p>}
            </section>

            <section className="rounded-2xl border border-slate-200 bg-white p-5">
              <h2 className="font-semibold">History</h2>
              <ol className="mt-3 space-y-3 border-l border-slate-200 pl-4">
                {[...post.history].reverse().map((entry) => (
                  <li key={entry.id} className="text-sm">
                    <p className="font-medium">{HISTORY_LABELS[entry.action] ?? entry.action}</p>
                    <p className="text-xs text-slate-500">
                      {formatInZone(entry.created_at, post.timezone)} · {entry.performed_by_name ?? "System"}
                    </p>
                    {entry.new_scheduled_at && entry.previous_scheduled_at && (
                      <p className="text-xs text-slate-600">
                        {formatInZone(entry.previous_scheduled_at, post.timezone)} → {formatInZone(entry.new_scheduled_at, post.timezone)}
                      </p>
                    )}
                    {typeof entry.details.error === "string" && <p className="text-xs text-red-800">{entry.details.error}</p>}
                  </li>
                ))}
              </ol>
              {post.publication && post.publication.attempts.length > 0 && (
                <>
                  <h3 className="mt-5 text-sm font-semibold">Publishing attempts</h3>
                  <ul className="mt-2 space-y-2">
                    {post.publication.attempts.map((attempt) => (
                      <li key={attempt.id} className="rounded-lg border border-slate-200 p-2 text-xs">
                        <span className="font-medium">#{attempt.attempt_number}</span> {attempt.status} · {attempt.stage ?? "start"}
                        {attempt.error_message && <p className="text-red-800">{attempt.error_message}</p>}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </section>
          </div>
        ) : null}

        <ConfirmDialog open={confirmCancel} title="Cancel this scheduled post?" confirmLabel="Cancel post" cancelLabel="Keep it" tone="danger" busy={busy} onCancel={() => setConfirmCancel(false)} onConfirm={() => void act("/cancel", {}, "Schedule cancelled.")}>
          <p>The post will not be published. You can schedule the content again later.</p>
        </ConfirmDialog>
        <ConfirmDialog
          open={confirmRetry}
          title="Retry publishing?"
          confirmLabel="Retry"
          busy={busy}
          confirmDisabled={Boolean(post?.publication?.outcome_uncertain && !notPublished)}
          onCancel={() => setConfirmRetry(false)}
          onConfirm={() => void act("/retry", { confirm_not_published: notPublished }, "Retry queued.")}
        >
          <p>The content and account are checked again before publishing.</p>
          {post?.publication?.outcome_uncertain && (
            <label className="flex items-start gap-2 text-amber-900">
              <input type="checkbox" className="mt-0.5" checked={notPublished} onChange={(e) => setNotPublished(e.target.checked)} />
              Meta did not confirm the last attempt. I checked {post.account_name} and the post is not there.
            </label>
          )}
        </ConfirmDialog>
      </AppShell>
    </ProtectedPage>
  );
}

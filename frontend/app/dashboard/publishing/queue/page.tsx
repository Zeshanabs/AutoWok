"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { StatusBadge, statusLabel } from "@/components/status-badge";
import { ApiError, apiRequest } from "@/lib/api";
import type { Publication } from "@/lib/media-types";
import type { QueueStatus } from "@/lib/scheduling-types";
import { formatInZone } from "@/lib/timezones";

function JobList({ title, jobs, empty }: { title: string; jobs: Publication[]; empty: string }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5">
      <h2 className="font-semibold">{title}</h2>
      {jobs.length === 0 ? (
        <p className="mt-2 text-sm text-slate-500">{empty}</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {jobs.map((job) => (
            <li key={job.id} className="rounded-lg border border-slate-100 p-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <Link href={`/dashboard/content/${job.project_id}`} className="font-medium hover:text-indigo-700">{job.project_title ?? "Content"}</Link>
                <StatusBadge status={job.status} />
              </div>
              <p className="text-xs text-slate-500">
                <span className="capitalize">{job.platform}</span> · {job.account_name ?? "Account"} · {job.source === "schedule" ? "Scheduled" : "Manual"} · attempt {job.attempt_count}/{job.max_attempts}
                {job.stage ? ` · ${job.stage.replaceAll("_", " ")}` : ""}
              </p>
              {job.next_attempt_at && job.status === "pending" && job.attempt_count > 0 && (
                <p className="text-xs text-slate-500">Next attempt {new Date(job.next_attempt_at).toLocaleString()}</p>
              )}
              {job.error_message && <p className="mt-1 text-xs text-red-800">{job.error_message}</p>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default function PublishingQueuePage() {
  const { selectedWorkspace } = useAuth();
  const workspaceId = selectedWorkspace?.id;
  const [queue, setQueue] = useState<QueueStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchQueue = useCallback(() => apiRequest<QueueStatus>(`/workspaces/${workspaceId}/publishing/queue`), [workspaceId]);

  useEffect(() => {
    if (!workspaceId) return;
    let active = true;
    const load = () =>
      fetchQueue()
        .then((data) => active && (setQueue(data), setError(null)))
        .catch((loadError: unknown) => active && setError(loadError instanceof ApiError ? loadError.message : "The queue could not be loaded."));
    void load();
    const timer = window.setInterval(() => void load(), 10000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [workspaceId, fetchQueue]);

  return (
    <ProtectedPage>
      <AppShell>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-indigo-700">Publishing</p>
            <h1 className="mt-2 text-3xl font-bold tracking-tight">Publishing queue</h1>
            <p className="mt-1 text-sm text-slate-600">Refreshes every 10 seconds.</p>
          </div>
          <div className="flex gap-2 text-sm">
            <Link href="/dashboard/calendar" className="rounded-xl border border-slate-300 bg-white px-4 py-2 font-medium">Calendar</Link>
            <Link href="/dashboard/publishing" className="rounded-xl border border-slate-300 bg-white px-4 py-2 font-medium">History</Link>
          </div>
        </div>
        {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
        {!workspaceId ? (
          <p className="mt-6 text-sm text-slate-600">Select a workspace.</p>
        ) : !queue ? (
          <p className="mt-6 text-sm text-slate-500">Loading queue…</p>
        ) : (
          <div className="mt-6 space-y-6">
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                ["Scheduled", queue.schedule_counts.scheduled ?? 0],
                ["In queue", (queue.counts.pending ?? 0) + (queue.counts.processing ?? 0) + (queue.counts.publishing ?? 0)],
                ["Published", queue.counts.published ?? 0],
                ["Failed", queue.counts.failed ?? 0],
              ].map(([label, value]) => (
                <div key={label} className="rounded-2xl border border-slate-200 bg-white p-4">
                  <dt className="text-xs uppercase text-slate-500">{label}</dt>
                  <dd className="mt-1 text-2xl font-bold">{value}</dd>
                </div>
              ))}
            </dl>
            {queue.next_scheduled_at && (
              <p className="text-sm text-slate-600">Next scheduled post: {new Date(queue.next_scheduled_at).toLocaleString()}</p>
            )}
            <div className="grid gap-6 lg:grid-cols-2">
              <JobList title="Publishing now" jobs={queue.active_jobs} empty="Nothing is publishing right now." />
              <JobList title="Waiting to retry" jobs={queue.retrying_jobs} empty="No automatic retries pending." />
            </div>
            <JobList title="Needs attention" jobs={queue.attention_jobs} empty="No failed jobs need action." />
            <section className="rounded-2xl border border-slate-200 bg-white p-5">
              <h2 className="font-semibold">Upcoming scheduled posts</h2>
              {queue.upcoming.length === 0 ? (
                <p className="mt-2 text-sm text-slate-500">Nothing scheduled.</p>
              ) : (
                <ul className="mt-3 divide-y divide-slate-100">
                  {queue.upcoming.map((post) => (
                    <li key={post.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                      <Link href={`/dashboard/calendar/${post.id}`} className="font-medium hover:text-indigo-700">{post.title ?? "Post"}</Link>
                      <span className="text-slate-600">
                        {formatInZone(post.scheduled_at, post.timezone)} · {post.account_name} · {statusLabel(post.approval_status ?? "")}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        )}
      </AppShell>
    </ProtectedPage>
  );
}

"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { StatusBadge } from "@/components/status-badge";
import { ApiError, apiRequest } from "@/lib/api";
import type { Notification, NotificationList, WorkTask } from "@/lib/automation-types";

const CATEGORY_LABELS: Record<string, string> = {
  automation: "Automation",
  approval_reminder: "Approval reminder",
  publishing_incident: "Publishing incident",
  automation_failure: "Automation failed",
  assignment: "Assignment",
  task: "Task",
  agent_workflow: "AI workflow",
};

function resourceLink(notification: Notification): string | null {
  if (notification.resource_type === "content_project" && notification.resource_id) return `/dashboard/content/${notification.resource_id}`;
  if (notification.resource_type === "automation" && notification.resource_id) return `/dashboard/automations/${notification.resource_id}`;
  if (notification.resource_type === "content_publication") return "/dashboard/publishing";
  if (notification.resource_type === "scheduled_post" && notification.resource_id) return `/dashboard/calendar/${notification.resource_id}`;
  if (notification.resource_type === "analytics_sync_job") return "/dashboard/analytics";
  if (notification.resource_type === "agent_workflow" && notification.resource_id) return `/dashboard/ai-agents/workflows/${notification.resource_id}`;
  return null;
}

export default function NotificationsPage() {
  const { selectedWorkspace } = useAuth();
  const workspaceId = selectedWorkspace?.id;
  const [data, setData] = useState<NotificationList | null>(null);
  const [tasks, setTasks] = useState<WorkTask[]>([]);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [taskFilter, setTaskFilter] = useState<"open" | "done">("open");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!workspaceId) return;
    try {
      const [notifications, taskList] = await Promise.all([
        apiRequest<NotificationList>(`/workspaces/${workspaceId}/notifications${unreadOnly ? "?unread_only=true" : ""}`),
        apiRequest<WorkTask[]>(`/workspaces/${workspaceId}/tasks?status=${taskFilter}`),
      ]);
      setData(notifications);
      setTasks(taskList);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof ApiError ? loadError.message : "Notifications could not be loaded.");
    }
  }, [workspaceId, unreadOnly, taskFilter]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const markRead = async (notification: Notification) => {
    if (!workspaceId || notification.read_at) return;
    setBusy(true);
    try {
      await apiRequest(`/workspaces/${workspaceId}/notifications/${notification.id}/read`, { method: "POST", body: JSON.stringify({}) });
      await load();
    } catch (actionError) {
      setError(actionError instanceof ApiError ? actionError.message : "The notification could not be updated.");
    } finally {
      setBusy(false);
    }
  };

  const markAll = async () => {
    if (!workspaceId) return;
    setBusy(true);
    try {
      await apiRequest(`/workspaces/${workspaceId}/notifications/read-all`, { method: "POST", body: JSON.stringify({}) });
      await load();
    } catch (actionError) {
      setError(actionError instanceof ApiError ? actionError.message : "Notifications could not be updated.");
    } finally {
      setBusy(false);
    }
  };

  const toggleTask = async (task: WorkTask) => {
    if (!workspaceId) return;
    setBusy(true);
    try {
      await apiRequest(`/workspaces/${workspaceId}/tasks/${task.id}/${task.status === "open" ? "complete" : "reopen"}`, { method: "POST", body: JSON.stringify({}) });
      await load();
    } catch (actionError) {
      setError(actionError instanceof ApiError ? actionError.message : "The task could not be updated.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <ProtectedPage>
      <AppShell>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-indigo-700">Inbox</p>
            <h1 className="mt-2 text-3xl font-bold tracking-tight">Notifications and tasks</h1>
            <p className="mt-1 text-sm text-slate-600">Approval reminders, publishing failures, assignments and automation alerts for this workspace.</p>
          </div>
          <Link href="/dashboard/automations" className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium">Automations</Link>
        </div>
        {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
        {!workspaceId ? (
          <p className="mt-6 rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">Select a workspace.</p>
        ) : (
          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            <section className="rounded-2xl border border-slate-200 bg-white p-5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="font-semibold">Notifications {data ? <span className="text-sm font-normal text-slate-500">· {data.unread_count} unread</span> : null}</h2>
                <div className="flex items-center gap-3 text-sm">
                  <label className="flex items-center gap-1 text-slate-600">
                    <input type="checkbox" checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} /> Unread only
                  </label>
                  <button type="button" disabled={busy || !data || data.unread_count === 0} onClick={() => void markAll()} className="font-medium text-indigo-700 disabled:opacity-40">
                    Mark all read
                  </button>
                </div>
              </div>
              {!data ? (
                <p className="mt-3 text-sm text-slate-500">Loading…</p>
              ) : data.items.length === 0 ? (
                <p className="mt-3 text-sm text-slate-500">Nothing here.</p>
              ) : (
                <ul className="mt-3 space-y-2">
                  {data.items.map((item) => {
                    const href = resourceLink(item);
                    return (
                      <li key={item.id} className={`rounded-xl border p-3 text-sm ${item.read_at ? "border-slate-200" : "border-indigo-200 bg-indigo-50/40"}`}>
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <div>
                            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{CATEGORY_LABELS[item.category] ?? item.category}</p>
                            <p className="font-medium">{item.title}</p>
                            <p className="text-slate-700">{item.message}</p>
                            <p className="mt-1 text-xs text-slate-500">{new Date(item.created_at).toLocaleString()}</p>
                          </div>
                          <div className="flex flex-col items-end gap-1 text-xs">
                            {href && <Link href={href} className="font-medium text-indigo-700">Open</Link>}
                            {!item.read_at && (
                              <button type="button" disabled={busy} onClick={() => void markRead(item)} className="font-medium text-indigo-700">Mark read</button>
                            )}
                          </div>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
            <section className="rounded-2xl border border-slate-200 bg-white p-5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="font-semibold">Tasks</h2>
                <select aria-label="Filter tasks" className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm" value={taskFilter} onChange={(e) => setTaskFilter(e.target.value as "open" | "done")}>
                  <option value="open">Open</option>
                  <option value="done">Done</option>
                </select>
              </div>
              {tasks.length === 0 ? (
                <p className="mt-3 text-sm text-slate-500">No {taskFilter} tasks.</p>
              ) : (
                <ul className="mt-3 space-y-2">
                  {tasks.map((task) => (
                    <li key={task.id} className="rounded-xl border border-slate-200 p-3 text-sm">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div>
                          <div className="flex flex-wrap items-center gap-2">
                            <StatusBadge status={task.kind} />
                            {task.severity && <span className="text-xs text-red-800">{task.severity} severity</span>}
                          </div>
                          <p className="mt-1 font-medium">{task.title}</p>
                          {task.description && <p className="whitespace-pre-wrap text-slate-700">{task.description}</p>}
                          <p className="mt-1 text-xs text-slate-500">
                            {task.project_title ? (task.project_id ? <Link href={`/dashboard/content/${task.project_id}`} className="text-indigo-700">{task.project_title}</Link> : task.project_title) : "No content post"}
                            {task.assigned_to_name ? ` · ${task.assigned_to_name}` : " · Unassigned"}
                            {task.due_at ? ` · due ${new Date(task.due_at).toLocaleString()}` : ""}
                          </p>
                        </div>
                        <button type="button" disabled={busy} onClick={() => void toggleTask(task)} className="text-xs font-medium text-indigo-700">
                          {task.status === "open" ? "Mark done" : "Reopen"}
                        </button>
                      </div>
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

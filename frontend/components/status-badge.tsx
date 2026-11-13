const STYLES: Record<string, string> = {
  draft: "bg-slate-100 text-slate-700 ring-slate-200",
  ready_for_review: "bg-amber-50 text-amber-800 ring-amber-200",
  in_review: "bg-amber-50 text-amber-800 ring-amber-200",
  awaiting_approval: "bg-amber-50 text-amber-800 ring-amber-200",
  approved: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  rejected: "bg-red-50 text-red-800 ring-red-200",
  scheduled: "bg-indigo-50 text-indigo-800 ring-indigo-200",
  pending: "bg-sky-50 text-sky-800 ring-sky-200",
  queued: "bg-sky-50 text-sky-800 ring-sky-200",
  processing: "bg-violet-50 text-violet-800 ring-violet-200",
  publishing: "bg-violet-50 text-violet-800 ring-violet-200",
  published: "bg-green-100 text-green-900 ring-green-300",
  failed: "bg-red-100 text-red-900 ring-red-300",
  cancelled: "bg-zinc-100 text-zinc-500 ring-zinc-200 line-through",
  // Phase 10: automations, executions, steps and tasks
  enabled: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  paused: "bg-amber-50 text-amber-800 ring-amber-200",
  archived: "bg-zinc-100 text-zinc-500 ring-zinc-200",
  running: "bg-violet-50 text-violet-800 ring-violet-200",
  succeeded: "bg-green-100 text-green-900 ring-green-300",
  skipped: "bg-slate-100 text-slate-500 ring-slate-200",
  open: "bg-sky-50 text-sky-800 ring-sky-200",
  done: "bg-green-100 text-green-900 ring-green-300",
  task: "bg-slate-100 text-slate-700 ring-slate-200",
  followup: "bg-sky-50 text-sky-800 ring-sky-200",
  reminder: "bg-amber-50 text-amber-800 ring-amber-200",
  incident: "bg-red-50 text-red-800 ring-red-200",
  analytics_followup: "bg-indigo-50 text-indigo-800 ring-indigo-200",
};

const LABELS: Record<string, string> = {
  ready_for_review: "Awaiting approval",
  in_review: "Awaiting approval",
  pending: "Queued",
  followup: "Follow-up",
  analytics_followup: "Analytics follow-up",
};

export function statusLabel(status: string): string {
  const key = status.toLowerCase();
  return LABELS[key] ?? key.replaceAll("_", " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function statusClasses(status: string): string {
  return STYLES[status.toLowerCase()] ?? "bg-slate-100 text-slate-700 ring-slate-200";
}

export function StatusBadge({ status, className = "" }: { status: string; className?: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${statusClasses(status)} ${className}`}
    >
      {statusLabel(status)}
    </span>
  );
}

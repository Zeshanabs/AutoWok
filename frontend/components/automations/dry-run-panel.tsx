import type { ConditionResult, DryRunResult } from "@/lib/automation-types";
import { OPERATOR_LABELS } from "@/lib/automation-types";

function describeValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) return value.length ? value.map(String).join(", ") : "(empty)";
  return String(value);
}

function ConditionTree({ node, depth = 0 }: { node: ConditionResult; depth?: number }) {
  if (node.children !== undefined) {
    return (
      <ul className={depth ? "ml-4 border-l border-slate-200 pl-3" : ""}>
        {depth > 0 && (
          <li className="text-xs uppercase tracking-wide text-slate-500">{node.logic === "or" ? "any of" : "all of"} · {node.passed ? "passed" : "failed"}</li>
        )}
        {node.children.length === 0 && <li className="text-sm text-slate-500">No conditions (always matches).</li>}
        {node.children.map((child) => <li key={child.path}><ConditionTree node={child} depth={depth + 1} /></li>)}
      </ul>
    );
  }
  return (
    <p className={`text-sm ${node.passed ? "text-emerald-800" : "text-red-800"}`}>
      {node.passed ? "✓" : "✗"} {node.field} {OPERATOR_LABELS[node.operator ?? ""] ?? node.operator}
      {node.expected !== undefined && node.expected !== null ? ` ${describeValue(node.expected)}` : ""}
      <span className="text-slate-500"> (actual: {describeValue(node.actual)})</span>
    </p>
  );
}

export function DryRunPanel({ result, className = "" }: { result: DryRunResult; className?: string }) {
  return (
    <section aria-label="Simulated test result" className={`rounded-2xl border border-amber-200 bg-amber-50 p-4 ${className}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold text-amber-900">Simulated result</h3>
        <span className="rounded-full bg-amber-200 px-2.5 py-0.5 text-xs font-semibold text-amber-900">SIMULATION · nothing was executed</span>
      </div>
      <p className="mt-1 text-xs text-amber-900">
        {result.notice} Data source: {result.payload_source === "latest_event" ? "the latest recorded event" : "built-in sample event"} · {new Date(result.generated_at).toLocaleString()}
      </p>
      <p className={`mt-3 text-sm font-semibold ${result.would_execute ? "text-emerald-800" : "text-red-800"}`}>
        {result.would_execute ? "This automation would run for this event." : "This automation would not run for this event."}
      </p>
      {result.errors.length > 0 && (
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-red-800">
          {result.errors.map((error) => <li key={error}>{error}</li>)}
        </ul>
      )}
      <h4 className="mt-3 text-sm font-semibold">Conditions · {result.conditions_passed ? "passed" : "failed"}</h4>
      <div className="mt-1 rounded-lg bg-white p-3"><ConditionTree node={result.condition_results} /></div>
      <h4 className="mt-3 text-sm font-semibold">Actions in execution order</h4>
      <ol className="mt-1 space-y-1">
        {result.actions.map((action) => (
          <li key={action.order} className="rounded-lg bg-white p-3 text-sm">
            <span className="font-medium">{action.order}. {action.label}</span>{" "}
            <span className={action.status === "would_run" ? "text-emerald-800" : "text-red-800"}>{action.status === "would_run" ? "would run" : "blocked"}</span>
            <p className="text-slate-700">{action.detail}</p>
          </li>
        ))}
      </ol>
      <details className="mt-3 text-xs text-slate-700">
        <summary className="cursor-pointer font-medium">Event data used</summary>
        <pre className="mt-1 overflow-x-auto rounded-lg bg-white p-2">{JSON.stringify(result.payload, null, 2)}</pre>
      </details>
    </section>
  );
}

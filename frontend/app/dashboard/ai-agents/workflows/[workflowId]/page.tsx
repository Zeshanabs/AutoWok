"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AgentsHeader } from "@/components/agents/agents-shell";
import { EvidenceList, FinalDeliverable, Section } from "@/components/agents/result-views";
import { useAuth } from "@/components/auth-provider";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { StatusBadge } from "@/components/status-badge";
import { ApiError, apiRequest } from "@/lib/api";
import {
  formatDuration,
  isActive,
  reviewLabel,
  type AcceptResult,
  type AgentWorkflowDetail,
  type WorkflowStep,
} from "@/lib/agent-types";

type Dialog = "cancel" | "accept" | "reject" | "revise" | null;

function StepRow({ step }: { step: WorkflowStep }) {
  const [open, setOpen] = useState(false);
  const execution = step.execution;
  const hasOutput = Boolean(execution?.result && Object.keys(execution.result).length > 0);
  return (
    <li className="rounded-xl border border-slate-200 p-3 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium">
            <span className="text-slate-500">{step.step_order}.</span> {step.label}
          </p>
          <p className="text-xs text-slate-500">
            {step.agent_name}
            {execution?.agent_version ? ` v${execution.agent_version}` : ""}
            {execution?.model_name ? ` · ${execution.model_name}` : ""}
            {execution?.execution_duration_ms != null ? ` · ${formatDuration(execution.execution_duration_ms)}` : ""}
            {execution?.token_usage?.total_tokens ? ` · ${execution.token_usage.total_tokens} tokens` : ""}
            {step.attempt_count > 0 && step.status !== "failed" ? ` · ${step.attempt_count} failed attempt${step.attempt_count === 1 ? "" : "s"} before this` : ""}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge status={step.status} />
          {hasOutput && (
            <button type="button" className="font-medium text-indigo-700" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
              {open ? "Hide output" : "Output"}
            </button>
          )}
        </div>
      </div>
      {step.error_message && step.status !== "succeeded" && <p className="mt-2 text-red-800">{step.error_message}</p>}
      {execution && execution.warnings.length > 0 && (
        <ul className="mt-2 list-disc space-y-1 rounded-lg bg-amber-50 p-2 pl-6 text-xs text-amber-900">
          {execution.warnings.map((warning, index) => <li key={`${index}-${warning.slice(0, 20)}`}>{warning}</li>)}
        </ul>
      )}
      {open && execution && (
        <div className="mt-3 space-y-3">
          {execution.evidence.length > 0 && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Evidence</p>
              <div className="mt-1"><EvidenceList evidence={execution.evidence} /></div>
            </div>
          )}
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Structured output</p>
            <pre className="mt-1 max-h-96 overflow-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100">{JSON.stringify(execution.result, null, 2)}</pre>
          </div>
        </div>
      )}
    </li>
  );
}

export default function WorkflowExecutionPage() {
  const params = useParams<{ workflowId: string }>();
  const workflowId = params.workflowId;
  const { selectedWorkspace } = useAuth();
  const workspaceId = selectedWorkspace?.id;
  const [workflow, setWorkflow] = useState<AgentWorkflowDetail | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ text: string; projectId?: string } | null>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [ideaIndex, setIdeaIndex] = useState<number | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  const path = workspaceId ? `/workspaces/${workspaceId}/agent-workflows/${workflowId}` : null;

  const load = useCallback(async () => {
    if (!path) return;
    try {
      setWorkflow(await apiRequest<AgentWorkflowDetail>(path));
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof ApiError ? loadError.message : "The workflow could not be loaded.");
    } finally {
      setLoaded(true);
    }
  }, [path]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const active = workflow ? isActive(workflow.status) : false;
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => void load(), 3000);
    return () => window.clearInterval(timer);
  }, [active, load]);

  function open(next: Dialog, index: number | null = null) {
    setText("");
    setIdeaIndex(index);
    setDialog(next);
  }

  async function confirm() {
    if (!path || !dialog) return;
    setBusy(true);
    try {
      if (dialog === "accept") {
        const result = await apiRequest<AcceptResult>(`${path}/accept`, { method: "POST", body: JSON.stringify({ idea_index: ideaIndex }) });
        setNotice({ text: "Saved to the content studio as a draft. It still needs approval before it can be published.", projectId: result.project_id });
        await load();
      } else {
        const body = dialog === "revise" ? { feedback: text.trim() } : dialog === "reject" ? { reason: text.trim() || null } : {};
        setWorkflow(await apiRequest<AgentWorkflowDetail>(`${path}/${dialog}`, { method: "POST", body: JSON.stringify(body) }));
        setNotice({
          text:
            dialog === "cancel" ? "Cancellation requested. The workflow stops before its next step."
            : dialog === "revise" ? "Revision requested. The writer and reviewers are running again."
            : "The output was rejected. Nothing was saved to the content studio.",
        });
      }
      setError(null);
      setDialog(null);
    } catch (actionError) {
      setError(actionError instanceof ApiError ? actionError.message : "The action could not be completed.");
      setDialog(null);
    } finally {
      setBusy(false);
    }
  }

  const output = workflow?.final_output ?? null;
  const acceptedIdeas = output?.accepted_idea_projects ?? {};

  return (
    <ProtectedPage>
      <AppShell>
        <AgentsHeader
          active="/dashboard/ai-agents/history"
          title={workflow?.name ?? "Workflow"}
          description={workflow ? `${workflow.workflow_name}${workflow.brand_name ? ` · ${workflow.brand_name}` : ""} · started by ${workflow.created_by_name ?? "a former member"} on ${new Date(workflow.created_at).toLocaleString()}` : "Workflow execution"}
          actions={
            workflow?.can_cancel ? (
              <button type="button" onClick={() => open("cancel")} className="rounded-xl border border-red-300 bg-white px-3 py-2 text-sm font-semibold text-red-800 hover:bg-red-50">
                Cancel workflow
              </button>
            ) : undefined
          }
        />

        {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
        {notice && (
          <p role="status" className="mt-4 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-900">
            {notice.text}{" "}
            {notice.projectId && <Link href={`/dashboard/content/${notice.projectId}`} className="font-medium underline">Open the draft</Link>}
          </p>
        )}

        {!workspaceId ? (
          <p className="mt-6 rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">Select a workspace.</p>
        ) : !loaded ? (
          <p className="mt-6 text-sm text-slate-500">Loading the workflow…</p>
        ) : !workflow ? (
          <p className="mt-6 rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">
            This workflow was not found in the selected workspace. <Link href="/dashboard/ai-agents/history" className="font-medium text-indigo-700">Back to history</Link>
          </p>
        ) : (
          <div className="mt-6 space-y-6">
            <section className="rounded-2xl border border-slate-200 bg-white p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Requested task</p>
                  <p className="mt-1 text-sm text-slate-800">{workflow.task}</p>
                </div>
                <StatusBadge status={workflow.status} />
              </div>
              <div
                className="mt-4 h-2 overflow-hidden rounded-full bg-slate-100"
                role="progressbar"
                aria-label="Workflow progress"
                aria-valuemin={0}
                aria-valuemax={workflow.steps_total}
                aria-valuenow={workflow.steps_done}
              >
                <div className="h-full bg-indigo-600 transition-all" style={{ width: `${workflow.steps_total ? (workflow.steps_done / workflow.steps_total) * 100 : 0}%` }} />
              </div>
              <dl className="mt-3 grid gap-2 text-xs text-slate-600 sm:grid-cols-4">
                <div><dt className="text-slate-500">Progress</dt><dd>{workflow.steps_done} of {workflow.steps_total} steps</dd></div>
                <div><dt className="text-slate-500">Agent calls</dt><dd>{workflow.agent_call_count}</dd></div>
                <div><dt className="text-slate-500">Tokens</dt><dd>{workflow.total_tokens.toLocaleString()}</dd></div>
                <div><dt className="text-slate-500">Revision rounds</dt><dd>{workflow.revision_count}</dd></div>
              </dl>
              {workflow.cancel_requested && active && <p className="mt-3 text-sm text-amber-800">Cancellation requested. Waiting for the current step to finish.</p>}
              {workflow.status === "pending" && workflow.next_attempt_at && (
                <p className="mt-3 text-sm text-amber-800">
                  Waiting to retry after a temporary Groq limit or outage. Next attempt after {new Date(workflow.next_attempt_at).toLocaleTimeString()}.
                </p>
              )}
              {workflow.error_message && (workflow.status === "failed" || workflow.status === "cancelled") && (
                <p role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-800">{workflow.error_message}</p>
              )}
              <p className="mt-3 text-xs text-slate-500">
                Selected agents: {workflow.agents.length > 0 ? workflow.agents.map((key) => key.replaceAll("_", " ")).join(", ") : "—"}
              </p>
            </section>

            <Section title="Execution timeline" aside={active ? <span className="text-xs text-slate-500">Updating every few seconds</span> : undefined}>
              <ol className="space-y-2">
                {workflow.steps.map((step) => <StepRow key={step.id} step={step} />)}
              </ol>
            </Section>

            {output && workflow.status === "succeeded" && (
              <>
                <section className="rounded-2xl border border-indigo-200 bg-indigo-50 p-5">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <h2 className="font-semibold">Review the result</h2>
                      <p className="mt-1 text-sm text-slate-700">
                        {reviewLabel(workflow.review_status)}. {output.human_review}
                      </p>
                      {workflow.review_note && <p className="mt-1 text-sm text-slate-600">Note: {workflow.review_note}</p>}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {workflow.can_accept && workflow.accept_mode === "draft" && (
                        <button type="button" onClick={() => open("accept")} className="rounded-xl bg-indigo-600 px-3 py-2 text-sm font-semibold text-white hover:bg-indigo-700">
                          Accept draft into content studio
                        </button>
                      )}
                      {workflow.can_revise && (
                        <button type="button" onClick={() => open("revise")} className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-semibold hover:bg-slate-50">
                          Request revision
                        </button>
                      )}
                      {workflow.can_reject && (
                        <button type="button" onClick={() => open("reject")} className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-semibold hover:bg-slate-50">
                          Reject
                        </button>
                      )}
                      {workflow.accepted_project_id && (
                        <Link href={`/dashboard/content/${workflow.accepted_project_id}`} className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-semibold hover:bg-slate-50">
                          Open accepted draft
                        </Link>
                      )}
                    </div>
                  </div>
                </section>
                <FinalDeliverable
                  output={output}
                  renderIdeaAction={
                    workflow.can_accept && workflow.accept_mode === "idea"
                      ? (index) =>
                          acceptedIdeas[String(index)] ? (
                            <Link href={`/dashboard/content/${acceptedIdeas[String(index)]}`} className="text-sm font-medium text-indigo-700">In content studio</Link>
                          ) : (
                            <button type="button" onClick={() => open("accept", index)} className="text-sm font-medium text-indigo-700">
                              Add to content studio
                            </button>
                          )
                      : undefined
                  }
                />
              </>
            )}
            {!output && !active && workflow.status !== "succeeded" && (
              <Section title="Final deliverable">
                <p className="text-slate-600">This workflow did not finish, so there is no final output. Completed steps above keep their results.</p>
              </Section>
            )}
          </div>
        )}

        <ConfirmDialog
          open={dialog === "cancel"}
          title="Cancel this workflow?"
          confirmLabel="Cancel workflow"
          cancelLabel="Keep running"
          tone="danger"
          busy={busy}
          onConfirm={() => void confirm()}
          onCancel={() => setDialog(null)}
        >
          The workflow stops before its next step. Results of finished steps are kept.
        </ConfirmDialog>
        <ConfirmDialog
          open={dialog === "accept"}
          title={ideaIndex === null ? "Accept this draft?" : "Add this idea to the content studio?"}
          confirmLabel={ideaIndex === null ? "Accept as draft" : "Create draft project"}
          busy={busy}
          onConfirm={() => void confirm()}
          onCancel={() => setDialog(null)}
        >
          A new content project is created with status draft. It is not approved, scheduled or published; the usual approval steps still apply.
        </ConfirmDialog>
        <ConfirmDialog
          open={dialog === "revise"}
          title="Request a revision"
          confirmLabel="Request revision"
          busy={busy}
          confirmDisabled={text.trim().length < 3}
          onConfirm={() => void confirm()}
          onCancel={() => setDialog(null)}
        >
          <label htmlFor="revision-feedback" className="block text-sm">What should change?</label>
          <textarea
            id="revision-feedback"
            className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm"
            rows={3}
            maxLength={1000}
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
          <span className="mt-2 block text-xs text-slate-500">The writer and reviewers run once more. Revision rounds are limited.</span>
        </ConfirmDialog>
        <ConfirmDialog
          open={dialog === "reject"}
          title="Reject this output?"
          confirmLabel="Reject output"
          tone="danger"
          busy={busy}
          onConfirm={() => void confirm()}
          onCancel={() => setDialog(null)}
        >
          <label htmlFor="reject-reason" className="block text-sm">Reason (optional)</label>
          <textarea
            id="reject-reason"
            className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm"
            rows={2}
            maxLength={1000}
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
        </ConfirmDialog>
      </AppShell>
    </ProtectedPage>
  );
}

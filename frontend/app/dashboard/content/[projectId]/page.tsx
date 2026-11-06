"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { AppShell, ProtectedPage } from "@/components/route-guards";
import { ApiError, apiRequest } from "@/lib/api";
import type {
  ContentApproval,
  ContentDraft,
  ContentProject,
} from "@/lib/content-types";

type PlatformValidation = {
  platform: string;
  valid: boolean;
  caption_length: number;
  hashtag_count: number;
  errors: string[];
  warnings: string[];
};

const fieldClass =
  "w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm outline-none focus:border-indigo-500";

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError
    ? error.message
    : error instanceof Error
      ? error.message
      : fallback;
}

export default function ContentProjectPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [project, setProject] = useState<ContentProject | null>(null);
  const [drafts, setDrafts] = useState<ContentDraft[]>([]);
  const [approvals, setApprovals] = useState<ContentApproval[]>([]);
  const [hashtagValues, setHashtagValues] = useState<Record<string, string>>({});
  const [validations, setValidations] = useState<Record<string, PlatformValidation>>({});
  const [newPlatform, setNewPlatform] = useState("");
  const [loadedProjectId, setLoadedProjectId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const fetchProjectData = useCallback(() => Promise.all([
    apiRequest<ContentProject>(`/content/projects/${projectId}`),
    apiRequest<ContentDraft[]>(`/content/projects/${projectId}/drafts`),
    apiRequest<ContentApproval[]>(`/content/projects/${projectId}/approvals`),
  ]), [projectId]);

  const loadProject = useCallback(async () => {
    const [projectData, draftData, approvalData] = await fetchProjectData();
    setProject(projectData);
    setDrafts(draftData);
    setApprovals(approvalData);
    setHashtagValues(
      Object.fromEntries(
        draftData.map((draft) => [draft.id, (draft.hashtags ?? []).join(", ")]),
      ),
    );
    setError(null);
    setLoadedProjectId(projectId);
  }, [fetchProjectData, projectId]);

  useEffect(() => {
    let active = true;
    fetchProjectData()
      .then(([projectData, draftData, approvalData]) => {
        if (active) {
          setProject(projectData);
          setDrafts(draftData);
          setApprovals(approvalData);
          setHashtagValues(
            Object.fromEntries(
              draftData.map((draft) => [draft.id, (draft.hashtags ?? []).join(", ")]),
            ),
          );
          setError(null);
          setLoadedProjectId(projectId);
        }
      })
      .catch((loadError: unknown) => {
        if (active) {
          setError(errorMessage(loadError, "The content project could not be loaded."));
          setLoadedProjectId(projectId);
        }
      });
    return () => {
      active = false;
    };
  }, [fetchProjectData, projectId]);
  const loading = loadedProjectId !== projectId;

  const availablePlatforms = useMemo(
    () => project?.selected_platforms.filter(
      (platform) => !drafts.some((draft) => draft.platform === platform),
    ) ?? [],
    [drafts, project],
  );
  const pendingApproval = approvals.find((approval) => approval.status === "pending");

  const runAction = async (action: () => Promise<void>, successMessage: string) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      await loadProject();
      setNotice(successMessage);
    } catch (actionError) {
      setError(errorMessage(actionError, "The requested action could not be completed."));
    } finally {
      setBusy(false);
    }
  };

  const createDraft = () =>
    runAction(async () => {
      if (!newPlatform) return;
      await apiRequest<ContentDraft>(`/content/projects/${projectId}/drafts`, {
        method: "POST",
        body: JSON.stringify({ platform: newPlatform }),
      });
      setNewPlatform("");
    }, "Draft created.");

  const saveDraft = (draft: ContentDraft) =>
    runAction(async () => {
      await apiRequest<ContentDraft>(
        `/content/projects/${projectId}/drafts/${draft.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            title: draft.title,
            hook: draft.hook,
            body: draft.body,
            cta: draft.cta,
            hashtags: (hashtagValues[draft.id] ?? "")
              .split(",")
              .map((tag) => tag.trim())
              .filter(Boolean),
          }),
        },
      );
    }, "Draft saved and versioned.");

  const validateDraft = (draft: ContentDraft) =>
    runAction(async () => {
      const result = await apiRequest<PlatformValidation>(
        `/content/projects/${projectId}/drafts/${draft.id}/validate`,
        { method: "POST" },
      );
      setValidations((current) => ({ ...current, [draft.id]: result }));
    }, "Validation complete.");

  const submitForApproval = () =>
    runAction(async () => {
      await apiRequest<ContentApproval>(`/content/projects/${projectId}/submit-for-approval`, {
        method: "POST",
        body: JSON.stringify({}),
      });
    }, "Project submitted for approval.");

  const decideApproval = (status: "approved" | "rejected" | "changes_requested") => {
    if (!pendingApproval) return;
    return runAction(async () => {
      await apiRequest<ContentApproval>(
        `/content/projects/${projectId}/approvals/${pendingApproval.id}/decision`,
        {
          method: "POST",
          body: JSON.stringify({ status }),
        },
      );
    }, `Approval marked ${status.replaceAll("_", " ")}.`);
  };

  const restoreVersion = (draft: ContentDraft, versionId: string) =>
    runAction(async () => {
      await apiRequest<ContentDraft>(
        `/content/projects/${projectId}/drafts/${draft.id}/versions/${versionId}/restore`,
        { method: "POST", body: JSON.stringify({}) },
      );
    }, "Previous version restored as a new version.");

  const updateDraft = (draftId: string, field: "title" | "hook" | "body" | "cta", value: string) => {
    setDrafts((current) =>
      current.map((draft) => draft.id === draftId ? { ...draft, [field]: value } : draft),
    );
    setValidations((current) => {
      const next = { ...current };
      delete next[draftId];
      return next;
    });
  };

  const updateHashtags = (draftId: string, value: string) => {
    setHashtagValues((current) => ({ ...current, [draftId]: value }));
    setValidations((current) => {
      const next = { ...current };
      delete next[draftId];
      return next;
    });
  };

  return (
    <ProtectedPage>
      <AppShell>
        <div className="mb-6 flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-indigo-700">
              Content studio
            </p>
            <h1 className="mt-2 text-3xl font-bold tracking-tight">
              {project?.title ?? "Content project"}
            </h1>
          </div>
          <Link href="/dashboard/content" className="text-sm font-semibold text-indigo-700">
            Back to projects
          </Link>
        </div>

        {error && <p role="alert" className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
        {notice && <p role="status" className="mb-4 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}

        {loading ? (
          <p>Loading content project…</p>
        ) : project ? (
          <div className="space-y-6">
            <section className="rounded-2xl border border-slate-200 bg-white p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="font-semibold">Project brief</h2>
                  <p className="mt-1 text-sm text-slate-600">{project.topic || "No topic provided."}</p>
                </div>
                <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
                  {project.status.replaceAll("_", " ")}
                </span>
              </div>
              {project.objective && <p className="mt-3 text-sm text-slate-600">Objective: {project.objective}</p>}
              <p className="mt-2 text-sm text-slate-500">
                Platforms: {project.selected_platforms.join(", ")} · Type: {project.content_type}
              </p>
            </section>

            <section className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-xl font-semibold">Drafts and versions</h2>
                {availablePlatforms.length > 0 && (
                  <div className="flex gap-2">
                    <select
                      aria-label="Platform for new draft"
                      className={fieldClass}
                      value={newPlatform}
                      onChange={(event) => setNewPlatform(event.target.value)}
                    >
                      <option value="">Choose platform</option>
                      {availablePlatforms.map((platform) => <option key={platform}>{platform}</option>)}
                    </select>
                    <button
                      type="button"
                      onClick={() => void createDraft()}
                      disabled={busy || !newPlatform}
                      className="shrink-0 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:bg-slate-300"
                    >
                      Add draft
                    </button>
                  </div>
                )}
              </div>

              {drafts.length === 0 && (
                <p className="rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">
                  Add a platform draft to start the review workflow.
                </p>
              )}

              {drafts.map((draft) => {
                const validation = validations[draft.id];
                return (
                  <article key={draft.id} className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <h3 className="font-semibold capitalize">{draft.platform} draft</h3>
                        <p className="text-xs text-slate-500">
                          {draft.status.replaceAll("_", " ")} · {draft.version_count} version(s)
                        </p>
                      </div>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={() => void validateDraft(draft)}
                          disabled={busy}
                          className="rounded-xl border border-slate-300 px-3 py-2 text-sm font-medium disabled:opacity-50"
                        >
                          Validate
                        </button>
                        <button
                          type="button"
                          onClick={() => void saveDraft(draft)}
                          disabled={busy}
                          className="rounded-xl bg-indigo-600 px-3 py-2 text-sm font-semibold text-white disabled:bg-slate-300"
                        >
                          Save version
                        </button>
                      </div>
                    </div>

                    <div className="grid gap-4 md:grid-cols-2">
                      <label className="space-y-1 text-sm font-medium text-slate-700">
                        Draft title
                        <input className={fieldClass} value={draft.title ?? ""} onChange={(event) => updateDraft(draft.id, "title", event.target.value)} />
                      </label>
                      <label className="space-y-1 text-sm font-medium text-slate-700">
                        Hook
                        <input className={fieldClass} value={draft.hook ?? ""} onChange={(event) => updateDraft(draft.id, "hook", event.target.value)} />
                      </label>
                      <label className="space-y-1 text-sm font-medium text-slate-700 md:col-span-2">
                        Caption body
                        <textarea className={`${fieldClass} min-h-32`} value={draft.body ?? ""} onChange={(event) => updateDraft(draft.id, "body", event.target.value)} />
                      </label>
                      <label className="space-y-1 text-sm font-medium text-slate-700">
                        Call to action
                        <input className={fieldClass} value={draft.cta ?? ""} onChange={(event) => updateDraft(draft.id, "cta", event.target.value)} />
                      </label>
                      <label className="space-y-1 text-sm font-medium text-slate-700">
                        Hashtags (comma-separated)
                        <input
                          className={fieldClass}
                          value={hashtagValues[draft.id] ?? ""}
                          onChange={(event) => updateHashtags(draft.id, event.target.value)}
                        />
                      </label>
                    </div>

                    {validation && (
                      <div className={`rounded-xl p-3 text-sm ${validation.valid ? "bg-emerald-50 text-emerald-900" : "bg-red-50 text-red-900"}`}>
                        <p>{validation.valid ? "Platform validation passed." : "Platform validation found issues."} Caption: {validation.caption_length} characters; hashtags: {validation.hashtag_count}.</p>
                        {[...validation.errors, ...validation.warnings].map((item) => <p key={item} className="mt-1">{item}</p>)}
                      </div>
                    )}

                    {draft.versions.length > 0 && (
                      <details className="rounded-xl border border-slate-200 p-3">
                        <summary className="cursor-pointer text-sm font-medium">Version history</summary>
                        <ol className="mt-3 space-y-2">
                          {[...draft.versions].reverse().map((version) => (
                            <li key={version.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
                              <span>Version {version.version_number} · {version.change_reason || "Saved revision"}</span>
                              {version.version_number !== draft.version_count && (
                                <button
                                  type="button"
                                  onClick={() => void restoreVersion(draft, version.id)}
                                  disabled={busy}
                                  className="font-medium text-indigo-700 disabled:opacity-50"
                                >
                                  Restore
                                </button>
                              )}
                            </li>
                          ))}
                        </ol>
                      </details>
                    )}
                  </article>
                );
              })}
            </section>

            <section className="rounded-2xl border border-slate-200 bg-white p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="font-semibold">Approval workflow</h2>
                  <p className="mt-1 text-sm text-slate-600">
                    Submit all valid platform drafts for workspace review. Workspace Owners and Admins can decide.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void submitForApproval()}
                  disabled={busy || drafts.length === 0 || project.status === "ready_for_review" || project.status === "in_review" || project.status === "archived"}
                  className="rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white disabled:bg-slate-300"
                >
                  Request approval
                </button>
              </div>

              {pendingApproval && (
                <div className="mt-4 flex flex-wrap items-center gap-2 rounded-xl bg-amber-50 p-4">
                  <p className="mr-auto text-sm text-amber-900">Approval is pending{pendingApproval.comments ? `: ${pendingApproval.comments}` : "."}</p>
                  <button type="button" onClick={() => void decideApproval("approved")} disabled={busy} className="rounded-lg bg-emerald-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">Approve</button>
                  <button type="button" onClick={() => void decideApproval("changes_requested")} disabled={busy} className="rounded-lg border border-amber-700 px-3 py-2 text-sm font-semibold text-amber-900 disabled:opacity-50">Request changes</button>
                  <button type="button" onClick={() => void decideApproval("rejected")} disabled={busy} className="rounded-lg border border-red-300 px-3 py-2 text-sm font-semibold text-red-800 disabled:opacity-50">Reject</button>
                </div>
              )}

              {approvals.length > 0 && (
                <ul className="mt-4 space-y-2">
                  {approvals.map((approval) => (
                    <li key={approval.id} className="flex flex-wrap justify-between gap-2 border-t border-slate-100 pt-2 text-sm">
                      <span>{approval.status.replaceAll("_", " ")}{approval.comments ? ` · ${approval.comments}` : ""}</span>
                      <time className="text-slate-500">{new Date(approval.created_at).toLocaleString()}</time>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        ) : null}
      </AppShell>
    </ProtectedPage>
  );
}

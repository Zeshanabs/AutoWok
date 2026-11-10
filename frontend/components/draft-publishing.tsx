"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { MediaPicker } from "@/components/media-picker";
import { MediaThumbnail } from "@/components/media-thumbnail";
import { PostPreview } from "@/components/post-preview";
import { StatusBadge } from "@/components/status-badge";
import { ApiError, apiRequest, newIdempotencyKey } from "@/lib/api";
import type { SocialAccount } from "@/lib/brand-types";
import type { ContentDraft, ContentProject } from "@/lib/content-types";
import {
  ACTIVE_PUBLICATION_STATUSES,
  type DraftPreview,
  type Eligibility,
  type MediaAsset,
  type Publication,
} from "@/lib/media-types";

const ACCOUNT_PLATFORM: Record<string, SocialAccount["platform"]> = {
  facebook: "facebook_page",
  instagram: "instagram",
};

function message(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

type Props = {
  draft: ContentDraft;
  project: ContentProject;
  role: string | undefined;
  disabled: boolean;
  onChanged: () => Promise<void>;
};

export function DraftPublishing({ draft, project, role, disabled, onChanged }: Props) {
  const workspaceId = project.workspace_id;
  const canPublish = role === "OWNER" || role === "ADMIN";
  const [assets, setAssets] = useState<Record<string, MediaAsset>>({});
  const [accounts, setAccounts] = useState<SocialAccount[]>([]);
  const [accountId, setAccountId] = useState("");
  const [preview, setPreview] = useState<DraftPreview | null>(null);
  const [eligibility, setEligibility] = useState<Eligibility | null>(null);
  const [jobs, setJobs] = useState<Publication[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const idempotencyKey = useRef<string | null>(null);

  const mediaIds = draft.media_asset_ids ?? [];
  const eligibleAccounts = useMemo(
    () => accounts.filter((account) => account.platform === ACCOUNT_PLATFORM[draft.platform]),
    [accounts, draft.platform],
  );

  const fetchStatic = useCallback(
    () =>
      Promise.all([
        apiRequest<MediaAsset[]>(`/media-assets?workspace_id=${workspaceId}&include_archived=true`),
        apiRequest<SocialAccount[]>(`/workspaces/${workspaceId}/social-accounts`).catch(() => [] as SocialAccount[]),
      ]),
    [workspaceId],
  );

  const fetchJobs = useCallback(
    () => apiRequest<Publication[]>(`/workspaces/${workspaceId}/publishing/jobs?draft_id=${draft.id}`),
    [workspaceId, draft.id],
  );
  const loadJobs = useCallback(async () => {
    const data = await fetchJobs();
    setJobs(data);
    return data;
  }, [fetchJobs]);

  // The chosen account, or the first connected account for this platform.
  const effectiveAccountId =
    accountId ||
    (eligibleAccounts.find((account) => account.connection_status === "connected") ?? eligibleAccounts[0])?.id ||
    "";

  const fetchPreview = useCallback(
    () =>
      Promise.all([
        apiRequest<DraftPreview>(
          `/content/drafts/${draft.id}/media-preview${effectiveAccountId ? `?social_account_id=${effectiveAccountId}` : ""}`,
        ),
        effectiveAccountId
          ? apiRequest<Eligibility>(`/content/drafts/${draft.id}/publishing/validate`, {
              method: "POST",
              body: JSON.stringify({ social_account_id: effectiveAccountId }),
            })
          : Promise.resolve(null),
      ]),
    [draft.id, effectiveAccountId],
  );
  const loadPreview = useCallback(async () => {
    const [previewData, eligibilityData] = await fetchPreview();
    setPreview(previewData);
    setEligibility(eligibilityData);
  }, [fetchPreview]);

  useEffect(() => {
    let active = true;
    fetchStatic()
      .then(([assetData, accountData]) => {
        if (!active) return;
        setAssets(Object.fromEntries(assetData.map((asset) => [asset.id, asset])));
        setAccounts(accountData);
      })
      .catch((loadError) => active && setError(message(loadError, "Media and accounts could not be loaded.")));
    fetchJobs()
      .then((data) => active && setJobs(data))
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [fetchStatic, fetchJobs]);

  const mediaKey = mediaIds.join(",");
  useEffect(() => {
    let active = true;
    fetchPreview()
      .then(([previewData, eligibilityData]) => {
        if (!active) return;
        setPreview(previewData);
        setEligibility(eligibilityData);
      })
      .catch((loadError) => active && setError(message(loadError, "The preview could not be loaded.")));
    return () => {
      active = false;
    };
  }, [fetchPreview, draft.version_count, draft.status, mediaKey]);

  const hasActiveJob = jobs.some((job) => ACTIVE_PUBLICATION_STATUSES.includes(job.status));
  useEffect(() => {
    if (!hasActiveJob) return;
    const timer = window.setInterval(() => {
      void loadJobs()
        .then((data) => {
          if (!data.some((job) => ACTIVE_PUBLICATION_STATUSES.includes(job.status))) {
            void loadPreview().catch(() => undefined);
          }
        })
        .catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [hasActiveJob, loadJobs, loadPreview]);

  const setMedia = async (ids: string[], success: string) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await apiRequest(`/content/drafts/${draft.id}/media`, { method: "PUT", body: JSON.stringify({ media_asset_ids: ids }) });
      await onChanged();
      setNotice(success);
    } catch (mediaError) {
      setError(message(mediaError, "Media could not be updated."));
    } finally {
      setBusy(false);
    }
  };

  const move = (index: number, offset: number) => {
    const next = [...mediaIds];
    const [item] = next.splice(index, 1);
    next.splice(index + offset, 0, item);
    void setMedia(next, "Media order updated.");
  };

  const openConfirm = () => {
    idempotencyKey.current = newIdempotencyKey("publish");
    setAcknowledged(false);
    setConfirmOpen(true);
  };

  const publishNow = async () => {
    setBusy(true);
    setError(null);
    try {
      await apiRequest<Publication>(`/content/drafts/${draft.id}/publish`, {
        method: "POST",
        body: JSON.stringify({ social_account_id: effectiveAccountId, confirm: true, idempotency_key: idempotencyKey.current }),
      });
      setConfirmOpen(false);
      setNotice("Publishing started. Status updates appear below.");
      await loadJobs();
    } catch (publishError) {
      setError(message(publishError, "Publishing could not be started."));
      setConfirmOpen(false);
    } finally {
      setBusy(false);
    }
  };

  const retry = async (job: Publication) => {
    let confirmNotPublished = false;
    if (job.outcome_uncertain) {
      confirmNotPublished = window.confirm(
        "Meta did not confirm this post. Check the account first. Retry only if the post is NOT there — continue?",
      );
      if (!confirmNotPublished) return;
    }
    setBusy(true);
    setError(null);
    try {
      await apiRequest(`/publishing/jobs/${job.id}/retry`, {
        method: "POST",
        body: JSON.stringify({ confirm_not_published: confirmNotPublished }),
      });
      setNotice("Retry queued.");
      await loadJobs();
    } catch (retryError) {
      setError(message(retryError, "The job could not be retried."));
    } finally {
      setBusy(false);
    }
  };

  const selectedAccount = accounts.find((account) => account.id === effectiveAccountId);

  return (
    <div className="space-y-4 rounded-xl border border-slate-200 bg-slate-50/60 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-sm font-semibold">Media</h4>
        <button
          type="button"
          onClick={() => setPickerOpen(true)}
          disabled={busy || disabled}
          className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium disabled:opacity-50"
        >
          Add from library
        </button>
      </div>
      {disabled && <p className="text-xs text-slate-500">Media cannot change while the project is in review.</p>}
      {mediaIds.length === 0 ? (
        <p className="text-sm text-slate-500">
          No media attached. {draft.platform === "instagram" ? "Instagram requires at least one image or video." : "Facebook posts can be text-only."}
        </p>
      ) : (
        <ol className="flex flex-wrap gap-3">
          {mediaIds.map((id, index) => {
            const asset = assets[id];
            return (
              <li key={id} className="w-28 overflow-hidden rounded-lg border border-slate-200 bg-white text-xs">
                {asset ? <MediaThumbnail asset={asset} className="aspect-square w-full" /> : <div className="aspect-square bg-slate-100" />}
                <p className="truncate px-1.5 pt-1">{index + 1}. {asset ? asset.title || asset.original_filename : "Unavailable"}</p>
                {asset?.archived && <p className="px-1.5 text-red-700">Archived</p>}
                <div className="flex justify-between px-1.5 pb-1.5 pt-1">
                  <button type="button" aria-label="Move earlier" disabled={busy || disabled || index === 0} onClick={() => move(index, -1)} className="disabled:opacity-30">◀</button>
                  <button type="button" disabled={busy || disabled} onClick={() => void setMedia(mediaIds.filter((item) => item !== id), "Media removed.")} className="text-red-700 disabled:opacity-30">Remove</button>
                  <button type="button" aria-label="Move later" disabled={busy || disabled || index === mediaIds.length - 1} onClick={() => move(index, 1)} className="disabled:opacity-30">▶</button>
                </div>
              </li>
            );
          })}
        </ol>
      )}
      {mediaIds.length > 0 && project.status === "draft" && (
        <p className="text-xs text-amber-700">Media changes create a new version and require approval again before publishing.</p>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-sm font-semibold">Preview</h4>
            <select
              aria-label="Social account"
              className="min-w-0 flex-1 rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm"
              value={effectiveAccountId}
              onChange={(event) => setAccountId(event.target.value)}
            >
              {eligibleAccounts.length === 0 && <option value="">No {draft.platform === "facebook" ? "Facebook Pages" : "Instagram accounts"} connected</option>}
              {eligibleAccounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.display_name}{account.connection_status !== "connected" ? ` (${account.connection_status})` : ""}
                </option>
              ))}
            </select>
          </div>
          {preview ? (
            <>
              <PostPreview preview={preview} />
              <p className="text-xs text-slate-500">{preview.disclaimer}</p>
            </>
          ) : (
            <p className="text-sm text-slate-500">Loading preview…</p>
          )}
        </div>

        <div className="space-y-3">
          <h4 className="text-sm font-semibold">Publish now</h4>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span>Approval:</span> <StatusBadge status={project.status} />
            {eligibility?.publish_format && <span className="text-slate-500">Format: {eligibility.publish_format.replaceAll("_", " ")}</span>}
          </div>
          {(eligibility?.errors ?? preview?.errors ?? []).length > 0 && (
            <ul className="space-y-1 rounded-lg bg-red-50 p-3 text-sm text-red-900">
              {(eligibility?.errors ?? preview?.errors ?? []).map((item) => <li key={item}>• {item}</li>)}
            </ul>
          )}
          {(eligibility?.warnings ?? preview?.warnings ?? []).length > 0 && (
            <ul className="space-y-1 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
              {(eligibility?.warnings ?? preview?.warnings ?? []).map((item) => <li key={item}>• {item}</li>)}
            </ul>
          )}
          {eligibility?.eligible && <p className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-900">Ready to publish to {eligibility.account_name}.</p>}
          {!canPublish && <p className="text-sm text-slate-500">Only workspace Owners and Admins can publish.</p>}
          <button
            type="button"
            onClick={openConfirm}
            disabled={busy || !canPublish || !eligibility?.eligible || hasActiveJob}
            className="rounded-xl bg-emerald-700 px-4 py-2.5 text-sm font-semibold text-white disabled:bg-slate-300"
          >
            {hasActiveJob ? "Publishing…" : "Publish now"}
          </button>
          {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
          {notice && <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}

          {jobs.length > 0 && (
            <ul className="space-y-2" aria-label="Publishing history for this draft">
              {jobs.map((job) => (
                <li key={job.id} className="rounded-lg border border-slate-200 bg-white p-3 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium">{job.account_name ?? "Account"}</span>
                    <StatusBadge status={job.status} />
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    {new Date(job.created_at).toLocaleString()} · attempt {job.attempt_count}/{job.max_attempts}
                    {job.stage && ACTIVE_PUBLICATION_STATUSES.includes(job.status) ? ` · ${job.stage.replaceAll("_", " ")}` : ""}
                    {job.source === "schedule" ? " · scheduled" : ""}
                  </p>
                  {job.error_message && <p className="mt-1 text-red-800">{job.error_message}</p>}
                  {job.status === "pending" && job.next_attempt_at && job.attempt_count > 0 && (
                    <p className="mt-1 text-xs text-slate-500">Next retry: {new Date(job.next_attempt_at).toLocaleString()}</p>
                  )}
                  <div className="mt-2 flex gap-3">
                    {job.permalink && <a href={job.permalink} target="_blank" rel="noreferrer noopener" className="font-medium text-indigo-700">View post ↗</a>}
                    {job.can_retry && canPublish && (
                      <button type="button" onClick={() => void retry(job)} disabled={busy} className="font-medium text-indigo-700 disabled:opacity-50">Retry</button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {pickerOpen && (
      <MediaPicker
        workspaceId={workspaceId}
        initialSelection={mediaIds}
        onClose={() => setPickerOpen(false)}
        onSave={(ids) => {
          setPickerOpen(false);
          void setMedia(ids, "Media attached.");
        }}
      />
      )}
      <ConfirmDialog
        open={confirmOpen}
        title="Publish immediately?"
        confirmLabel="Publish now"
        busy={busy}
        confirmDisabled={!acknowledged}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => void publishNow()}
      >
        <p>
          This publishes the approved {draft.platform} draft to <strong>{selectedAccount?.display_name}</strong> right now.
          Published posts can only be removed on {draft.platform === "facebook" ? "Facebook" : "Instagram"} itself.
        </p>
        <label className="flex items-start gap-2 text-slate-800">
          <input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} className="mt-0.5" />
          I confirm this content should be published publicly now.
        </label>
      </ConfirmDialog>
    </div>
  );
}

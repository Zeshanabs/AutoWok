"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { PostPreview } from "@/components/post-preview";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { StatusBadge } from "@/components/status-badge";
import { TimezoneSelect } from "@/components/timezone-select";
import { ApiError, apiRequest } from "@/lib/api";
import type { Brand, SocialAccount } from "@/lib/brand-types";
import type { ContentDraft, ContentProject } from "@/lib/content-types";
import type { DraftPreview, Eligibility } from "@/lib/media-types";
import type { Preferences, ScheduledPost } from "@/lib/scheduling-types";
import { addDays, todayInZone } from "@/lib/timezones";

const fieldClass = "w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm outline-none focus:border-indigo-500";
const ACCOUNT_PLATFORM: Record<string, string> = { facebook: "facebook_page", instagram: "instagram" };

function NewScheduleForm() {
  const { selectedWorkspace } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const workspaceId = selectedWorkspace?.id;
  const canSchedule = selectedWorkspace?.role === "OWNER" || selectedWorkspace?.role === "ADMIN";

  const [brands, setBrands] = useState<Brand[]>([]);
  const [projects, setProjects] = useState<ContentProject[]>([]);
  const [accounts, setAccounts] = useState<SocialAccount[]>([]);
  const [drafts, setDrafts] = useState<ContentDraft[]>([]);
  const [brandId, setBrandId] = useState("");
  const [projectId, setProjectId] = useState(params.get("project") ?? "");
  const [draftId, setDraftId] = useState(params.get("draft") ?? "");
  const [accountId, setAccountId] = useState("");
  const [timezone, setTimezone] = useState<string | null>(null);
  const [date, setDate] = useState("");
  const [time, setTime] = useState("09:00");
  const [ambiguous, setAmbiguous] = useState<"" | "earlier" | "later">("");
  const [preview, setPreview] = useState<DraftPreview | null>(null);
  const [eligibility, setEligibility] = useState<Eligibility | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [needsFold, setNeedsFold] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    apiRequest<Preferences>("/me/preferences")
      .then((prefs) => active && setTimezone(prefs.timezone))
      .catch(() => active && setTimezone("UTC"));
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!workspaceId) return;
    let active = true;
    Promise.all([
      apiRequest<Brand[]>(`/workspaces/${workspaceId}/brands`),
      apiRequest<ContentProject[]>(`/content/projects?workspace_id=${workspaceId}`),
      apiRequest<SocialAccount[]>(`/workspaces/${workspaceId}/social-accounts`).catch(() => [] as SocialAccount[]),
    ])
      .then(([brandData, projectData, accountData]) => {
        if (!active) return;
        setBrands(brandData);
        setProjects(projectData);
        setAccounts(accountData);
      })
      .catch((loadError: unknown) => active && setError(loadError instanceof ApiError ? loadError.message : "Form data could not be loaded."));
    return () => {
      active = false;
    };
  }, [workspaceId]);

  useEffect(() => {
    if (!projectId) return;
    let active = true;
    apiRequest<ContentDraft[]>(`/content/projects/${projectId}/drafts`)
      .then((data) => active && setDrafts(data))
      .catch(() => active && setDrafts([]));
    return () => {
      active = false;
    };
  }, [projectId]);

  const approvedProjects = useMemo(
    () => projects.filter((project) => project.status === "approved" && (!brandId || project.brand_id === brandId)),
    [projects, brandId],
  );
  const project = projects.find((item) => item.id === projectId);
  const draft = projectId ? drafts.find((item) => item.id === draftId) : undefined;
  const platformAccounts = accounts.filter((account) => draft && account.platform === ACCOUNT_PLATFORM[draft.platform]);
  const effectiveAccountId =
    accountId || (platformAccounts.find((account) => account.connection_status === "connected") ?? platformAccounts[0])?.id || "";
  const effectiveDate = date || (timezone ? addDays(todayInZone(timezone), 1) : "");

  useEffect(() => {
    if (!draftId || !effectiveAccountId) return;
    let active = true;
    Promise.all([
      apiRequest<DraftPreview>(`/content/drafts/${draftId}/media-preview?social_account_id=${effectiveAccountId}`),
      apiRequest<Eligibility>(`/content/drafts/${draftId}/publishing/validate`, {
        method: "POST",
        body: JSON.stringify({ social_account_id: effectiveAccountId }),
      }),
    ])
      .then(([previewData, eligibilityData]) => {
        if (!active) return;
        setPreview(previewData);
        setEligibility(eligibilityData);
      })
      .catch((loadError: unknown) => active && setError(loadError instanceof ApiError ? loadError.message : "Preview failed."));
    return () => {
      active = false;
    };
  }, [draftId, effectiveAccountId]);

  const showPreview = Boolean(draftId && effectiveAccountId && preview);
  const ready = canSchedule && Boolean(draft && effectiveAccountId && effectiveDate && time && timezone) && Boolean(eligibility?.eligible);

  const submit = async () => {
    if (!workspaceId || !draft || !timezone) return;
    setBusy(true);
    setError(null);
    try {
      const created = await apiRequest<ScheduledPost>(`/workspaces/${workspaceId}/scheduled-posts`, {
        method: "POST",
        body: JSON.stringify({
          draft_id: draft.id,
          project_id: projectId,
          brand_id: brandId || undefined,
          social_account_id: effectiveAccountId,
          scheduled_local: `${effectiveDate}T${time}`,
          timezone,
          ambiguous: ambiguous || undefined,
          confirm: true,
        }),
      });
      router.push(`/dashboard/calendar/${created.id}?created=1`);
    } catch (submitError) {
      const message = submitError instanceof ApiError ? submitError.message : "The post could not be scheduled.";
      setNeedsFold(message.includes("happens twice"));
      setError(message);
      setConfirmOpen(false);
      setBusy(false);
    }
  };

  return (
    <>
      <Link href="/dashboard/calendar" className="text-sm font-semibold text-indigo-700">← Calendar</Link>
      <h1 className="mt-3 text-3xl font-bold tracking-tight">Schedule a post</h1>
      <p className="mt-1 text-sm text-slate-600">Only approved content can be scheduled. Autowok publishes it at the chosen time, even when you are logged out.</p>
      {!canSchedule && <p className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">Only workspace Owners and Admins can schedule posts.</p>}
      {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5">
          <label className="block space-y-1 text-sm font-medium text-slate-700">
            Brand
            <select className={fieldClass} value={brandId} onChange={(e) => { setBrandId(e.target.value); setProjectId(""); setDraftId(""); }}>
              <option value="">All brands</option>
              {brands.map((brand) => <option key={brand.id} value={brand.id}>{brand.name}</option>)}
            </select>
          </label>
          <label className="block space-y-1 text-sm font-medium text-slate-700">
            Approved content post
            <select className={fieldClass} value={projectId} onChange={(e) => { setProjectId(e.target.value); setDraftId(""); setAccountId(""); setPreview(null); setEligibility(null); }}>
              <option value="">Choose content</option>
              {approvedProjects.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
            </select>
            {approvedProjects.length === 0 && <span className="block text-xs font-normal text-slate-500">No approved content yet. Submit content for approval first.</span>}
          </label>
          {project && (
            <label className="block space-y-1 text-sm font-medium text-slate-700">
              Platform
              <select className={fieldClass} value={draftId} onChange={(e) => { setDraftId(e.target.value); setAccountId(""); setPreview(null); setEligibility(null); }}>
                <option value="">Choose platform draft</option>
                {drafts.map((item) => <option key={item.id} value={item.id}>{item.platform === "facebook" ? "Facebook Page" : "Instagram"}</option>)}
              </select>
            </label>
          )}
          {draft && (
            <label className="block space-y-1 text-sm font-medium text-slate-700">
              Account
              <select className={fieldClass} value={effectiveAccountId} onChange={(e) => setAccountId(e.target.value)}>
                {platformAccounts.length === 0 && <option value="">No connected {draft.platform === "facebook" ? "Facebook Pages" : "Instagram Professional accounts"}</option>}
                {platformAccounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.display_name}{account.connection_status !== "connected" ? ` (${account.connection_status})` : ""}
                  </option>
                ))}
              </select>
            </label>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block space-y-1 text-sm font-medium text-slate-700">
              Date
              <input type="date" className={fieldClass} value={effectiveDate} onChange={(e) => setDate(e.target.value)} />
            </label>
            <label className="block space-y-1 text-sm font-medium text-slate-700">
              Time
              <input type="time" className={fieldClass} value={time} onChange={(e) => setTime(e.target.value)} />
            </label>
          </div>
          <label className="block space-y-1 text-sm font-medium text-slate-700">
            Timezone
            {timezone && <TimezoneSelect value={timezone} onChange={setTimezone} className="w-full" />}
          </label>
          {needsFold && (
            <fieldset className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900">
              <legend className="font-medium">This time occurs twice because clocks go back. Which one?</legend>
              {(["earlier", "later"] as const).map((option) => (
                <label key={option} className="mr-4 inline-flex items-center gap-1.5">
                  <input type="radio" name="fold" checked={ambiguous === option} onChange={() => setAmbiguous(option)} /> {option === "earlier" ? "First (earlier)" : "Second (later)"}
                </label>
              ))}
            </fieldset>
          )}
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span>Approval:</span> {project ? <StatusBadge status={project.status} /> : <span className="text-slate-500">—</span>}
          </div>
          {eligibility && eligibility.errors.length > 0 && (
            <ul className="space-y-1 rounded-lg bg-red-50 p-3 text-sm text-red-900">{eligibility.errors.map((item) => <li key={item}>• {item}</li>)}</ul>
          )}
          {eligibility && eligibility.warnings.length > 0 && (
            <ul className="space-y-1 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{eligibility.warnings.map((item) => <li key={item}>• {item}</li>)}</ul>
          )}
          <button type="button" disabled={!ready || busy} onClick={() => setConfirmOpen(true)} className="rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white disabled:bg-slate-300">
            Review and schedule
          </button>
        </section>

        <section className="space-y-2">
          <h2 className="text-sm font-semibold">Preview</h2>
          {showPreview && preview ? (
            <>
              <PostPreview preview={preview} />
              <p className="text-xs text-slate-500">{preview.disclaimer}</p>
            </>
          ) : (
            <p className="rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">Choose content and an account to see a preview.</p>
          )}
        </section>
      </div>

      <ConfirmDialog
        open={confirmOpen}
        title="Schedule this post?"
        confirmLabel="Schedule"
        busy={busy}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => void submit()}
      >
        <p>
          <strong>{project?.title}</strong> will be published to <strong>{platformAccounts.find((a) => a.id === effectiveAccountId)?.display_name}</strong> on{" "}
          <strong>{effectiveDate} at {time}</strong> ({timezone?.replaceAll("_", " ")}).
        </p>
        <p>If the content is edited before then, it must be approved again or the post will not publish.</p>
      </ConfirmDialog>
    </>
  );
}

export default function NewSchedulePage() {
  return (
    <ProtectedPage>
      <AppShell>
        <Suspense fallback={<p className="text-sm text-slate-500">Loading…</p>}>
          <NewScheduleForm />
        </Suspense>
      </AppShell>
    </ProtectedPage>
  );
}

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";

import { useAnalytics } from "@/components/analytics/analytics-provider";
import { ApiError, apiRequest } from "@/lib/api";
import { formatDateTime } from "@/lib/analytics-format";
import { PLATFORM_LABELS, type SyncRequestResult, type SyncStatus } from "@/lib/analytics-types";

const TABS = [
  { href: "/dashboard/analytics", label: "Overview" },
  { href: "/dashboard/analytics/accounts", label: "Accounts" },
  { href: "/dashboard/analytics/posts", label: "Posts" },
  { href: "/dashboard/analytics/content-performance", label: "Content performance" },
  { href: "/dashboard/analytics/reports", label: "Reports" },
];

const fieldClass = "rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm";

export function AnalyticsFilters() {
  const { filters, setFilters, applyPreset, brands, accounts } = useAnalytics();
  const accountOptions = accounts.filter(
    (account) => (!filters.platform || account.platform === filters.platform) && (!filters.brandId || account.brand_id === filters.brandId),
  );
  return (
    <form className="flex flex-wrap items-end gap-3" onSubmit={(event) => event.preventDefault()} aria-label="Analytics filters">
      <fieldset className="flex items-end gap-1" aria-label="Date range">
        <legend className="sr-only">Date range</legend>
        {(["7", "28", "90"] as const).map((preset) => (
          <button
            key={preset}
            type="button"
            aria-pressed={filters.preset === preset}
            onClick={() => applyPreset(preset)}
            className={`rounded-xl border px-3 py-2 text-sm ${filters.preset === preset ? "border-indigo-600 bg-indigo-50 font-semibold text-indigo-800" : "border-slate-300 bg-white"}`}
          >
            Last {preset} days
          </button>
        ))}
      </fieldset>
      <label className="text-xs text-slate-600">
        Start
        <input
          type="date"
          aria-label="Start date"
          className={`${fieldClass} mt-1 block`}
          value={filters.start}
          max={filters.end}
          onChange={(event) => setFilters({ start: event.target.value, preset: "custom" })}
        />
      </label>
      <label className="text-xs text-slate-600">
        End
        <input
          type="date"
          aria-label="End date"
          className={`${fieldClass} mt-1 block`}
          value={filters.end}
          min={filters.start}
          onChange={(event) => setFilters({ end: event.target.value, preset: "custom" })}
        />
      </label>
      <label className="text-xs text-slate-600">
        Brand
        <select aria-label="Filter by brand" className={`${fieldClass} mt-1 block`} value={filters.brandId} onChange={(event) => setFilters({ brandId: event.target.value, accountId: "" })}>
          <option value="">All brands</option>
          {brands.map((brand) => (
            <option key={brand.id} value={brand.id}>
              {brand.name}
            </option>
          ))}
        </select>
      </label>
      <label className="text-xs text-slate-600">
        Platform
        <select
          aria-label="Filter by platform"
          className={`${fieldClass} mt-1 block`}
          value={filters.platform}
          onChange={(event) => setFilters({ platform: event.target.value as "" | "facebook_page" | "instagram", accountId: "" })}
        >
          <option value="">Both platforms</option>
          <option value="facebook_page">Facebook Page</option>
          <option value="instagram">Instagram</option>
        </select>
      </label>
      <label className="text-xs text-slate-600">
        Account
        <select aria-label="Filter by account" className={`${fieldClass} mt-1 block`} value={filters.accountId} onChange={(event) => setFilters({ accountId: event.target.value })}>
          <option value="">All accounts</option>
          {accountOptions.map((account) => (
            <option key={account.id} value={account.id}>
              {account.display_name} · {PLATFORM_LABELS[account.platform]}
            </option>
          ))}
        </select>
      </label>
    </form>
  );
}

function statusTone(status: SyncStatus): string {
  if (status.active_job_id) return "text-sky-800";
  if (status.last_sync_status === "failed") return "text-red-800";
  if (!status.insights_available || status.last_sync_status === "partial") return "text-amber-800";
  return "text-emerald-800";
}

export function SyncStatusStrip() {
  const { workspaceId, canManage, sync, refreshSync, bumpData } = useAnalytics();
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = async (accountId?: string) => {
    if (!workspaceId) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await apiRequest<SyncRequestResult>(`/workspaces/${workspaceId}/analytics/sync`, {
        method: "POST",
        body: JSON.stringify(accountId ? { social_account_id: accountId } : {}),
      });
      const skipped = result.skipped.map((item) => `${item.account_name}: ${item.reason}`).join(" ");
      setMessage(`${result.jobs.length} synchronization${result.jobs.length === 1 ? "" : "s"} queued.${skipped ? ` ${skipped}` : ""}`);
      await refreshSync();
      bumpData();
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "The refresh could not be requested.");
    } finally {
      setBusy(false);
    }
  };

  if (!sync) return null;
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4" aria-label="Synchronization status">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">Data freshness</h2>
        <div className="flex items-center gap-3 text-xs text-slate-500">
          <span>Automatic sync every {sync.sync_interval_hours} h{sync.active_jobs > 0 ? ` · ${sync.active_jobs} running` : ""}</span>
          {canManage && (
            <button type="button" disabled={busy} onClick={() => void refresh()} className="rounded-lg bg-slate-900 px-3 py-1.5 font-medium text-white disabled:opacity-50">
              {busy ? "Requesting…" : "Refresh now"}
            </button>
          )}
        </div>
      </div>
      {message && <p className="mt-2 text-xs text-emerald-800">{message}</p>}
      {error && (
        <p role="alert" className="mt-2 text-xs text-red-800">
          {error}
        </p>
      )}
      {sync.accounts.length === 0 ? (
        <p className="mt-2 text-sm text-slate-600">
          No Facebook Page or Instagram account is connected.{" "}
          <Link href="/settings/social-accounts" className="font-medium text-indigo-700">
            Connect an account
          </Link>{" "}
          to start collecting analytics.
        </p>
      ) : (
        <ul className="mt-2 grid gap-2 text-xs sm:grid-cols-2">
          {sync.accounts.map((account) => (
            <li key={account.social_account_id} className="rounded-lg border border-slate-100 p-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium text-slate-800">
                  {account.account_name} <span className="text-slate-500">· {PLATFORM_LABELS[account.platform]}</span>
                </span>
                <span className={statusTone(account)}>
                  {account.active_job_id ? "Synchronizing…" : account.last_synced_at ? `Synced ${formatDateTime(account.last_synced_at)}` : "Never synchronized"}
                </span>
              </div>
              {account.last_error && <p className="mt-1 text-red-800">{account.last_error}</p>}
              {account.notes.map((note) => (
                <p key={note} className="mt-1 text-amber-800">
                  {note}
                </p>
              ))}
              {account.next_attempt_at && <p className="mt-1 text-slate-500">Next automatic attempt {formatDateTime(account.next_attempt_at)}.</p>}
              {canManage && account.can_sync && !account.active_job_id && (
                <button type="button" disabled={busy} onClick={() => void refresh(account.social_account_id)} className="mt-1 text-indigo-700">
                  Refresh this account
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function AnalyticsShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { workspaceId, loadError } = useAnalytics();
  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-indigo-700">Analytics</p>
          <h1 className="mt-2 text-3xl font-bold tracking-tight">Performance</h1>
          <p className="mt-1 text-sm text-slate-600">Facebook Page and Instagram metrics from Meta, shown per platform with their official definitions.</p>
        </div>
        <nav aria-label="Analytics sections" className="flex flex-wrap gap-1 text-sm">
          {TABS.map((tab) => {
            const active = pathname === tab.href;
            return (
              <Link
                key={tab.href}
                href={tab.href}
                aria-current={active ? "page" : undefined}
                className={`rounded-xl border px-3 py-2 ${active ? "border-slate-900 bg-slate-900 text-white" : "border-slate-300 bg-white hover:bg-slate-50"}`}
              >
                {tab.label}
              </Link>
            );
          })}
        </nav>
      </div>
      {loadError && (
        <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">
          {loadError}
        </p>
      )}
      {!workspaceId ? (
        <p className="mt-6 text-sm text-slate-600">Select a workspace to view analytics.</p>
      ) : (
        <div className="mt-6 space-y-6">
          <AnalyticsFilters />
          <SyncStatusStrip />
          {children}
        </div>
      )}
    </>
  );
}

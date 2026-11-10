"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { statusClasses, StatusBadge, statusLabel } from "@/components/status-badge";
import { TimezoneSelect } from "@/components/timezone-select";
import { ApiError, apiRequest } from "@/lib/api";
import type { Brand, SocialAccount } from "@/lib/brand-types";
import type { CalendarItem, CalendarResponse, CalendarView, Preferences } from "@/lib/scheduling-types";
import { addDays, addMonths, formatDay, todayInZone } from "@/lib/timezones";

const VIEWS: CalendarView[] = ["month", "week", "day", "list"];
const STATUSES = ["scheduled", "queued", "processing", "published", "failed", "cancelled"];
const LEGEND = ["draft", "ready_for_review", "approved", "scheduled", "processing", "published", "failed", "cancelled"];
const fieldClass = "rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm";

function itemHref(item: CalendarItem): string {
  return item.scheduled_post_id ? `/dashboard/calendar/${item.scheduled_post_id}` : `/dashboard/content/${item.project_id}`;
}

function PlatformMark({ platform }: { platform: string }) {
  return (
    <span
      aria-label={platform}
      className={`inline-flex h-4 w-4 shrink-0 items-center justify-center rounded text-[9px] font-bold text-white ${platform === "instagram" ? "bg-pink-600" : "bg-blue-600"}`}
    >
      {platform === "instagram" ? "IG" : "f"}
    </span>
  );
}

function ItemChip({ item, compact = false }: { item: CalendarItem; compact?: boolean }) {
  const needsApproval = item.kind === "scheduled" && item.approval_status !== "approved" && ["scheduled", "queued"].includes(item.status);
  return (
    <Link
      href={itemHref(item)}
      title={`${item.title ?? "Post"} · ${item.account_name ?? ""} · ${statusLabel(item.status)}`}
      className={`block rounded-lg px-2 py-1 text-xs ring-1 ring-inset hover:brightness-95 focus:outline-none focus:ring-2 focus:ring-indigo-500 ${statusClasses(item.status)}`}
    >
      <span className="flex items-center gap-1">
        <PlatformMark platform={item.platform} />
        <span className="font-semibold">{item.local_time}</span>
        <span className="truncate">{item.title ?? "Untitled"}</span>
      </span>
      {!compact && (
        <span className="mt-0.5 block truncate opacity-80">
          {item.account_name}
          {item.brand_name ? ` · ${item.brand_name}` : ""}
        </span>
      )}
      {(needsApproval || item.content_changed) && (
        <span className="mt-0.5 block font-medium text-amber-800">
          {needsApproval ? `⚠ ${statusLabel(item.approval_status ?? "draft")}` : "⚠ Content changed"}
        </span>
      )}
      {item.status === "failed" && item.last_error && !compact && (
        <span className="mt-0.5 block truncate text-red-800">{item.last_error}</span>
      )}
    </Link>
  );
}

function AgendaRow({ item }: { item: CalendarItem }) {
  return (
    <li className="rounded-xl border border-slate-200 bg-white p-3">
      <Link href={itemHref(item)} className="flex flex-wrap items-start justify-between gap-2 focus:outline-none focus:ring-2 focus:ring-indigo-500">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-sm font-semibold">
            <PlatformMark platform={item.platform} />
            <span>{item.local_time}</span>
            <span className="truncate">{item.title ?? "Untitled"}</span>
          </p>
          {item.caption_preview && <p className="mt-1 line-clamp-2 text-sm text-slate-600">{item.caption_preview}</p>}
          <p className="mt-1 text-xs text-slate-500">
            {item.account_name ?? "Account"}
            {item.brand_name ? ` · ${item.brand_name}` : ""}
            {item.kind === "published" ? " · Published immediately" : ""}
          </p>
          {item.last_error && <p className="mt-1 text-xs text-red-800">{item.last_error}</p>}
        </div>
        <div className="flex flex-col items-end gap-1">
          <StatusBadge status={item.status} />
          {item.approval_status && item.approval_status !== "approved" && <StatusBadge status={item.approval_status} />}
        </div>
      </Link>
    </li>
  );
}

export default function CalendarPage() {
  const { selectedWorkspace } = useAuth();
  const workspaceId = selectedWorkspace?.id;
  const canSchedule = selectedWorkspace?.role === "OWNER" || selectedWorkspace?.role === "ADMIN";
  const [timezone, setTimezone] = useState<string | null>(null);
  const [view, setView] = useState<CalendarView>("month");
  const [anchor, setAnchor] = useState<string | null>(null);
  const [brandId, setBrandId] = useState("");
  const [platform, setPlatform] = useState("");
  const [accountId, setAccountId] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [calendar, setCalendar] = useState<CalendarResponse | null>(null);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [accounts, setAccounts] = useState<SocialAccount[]>([]);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

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
      apiRequest<SocialAccount[]>(`/workspaces/${workspaceId}/social-accounts`).catch(() => [] as SocialAccount[]),
    ])
      .then(([brandData, accountData]) => {
        if (!active) return;
        setBrands(brandData);
        setAccounts(accountData);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [workspaceId]);

  const effectiveAnchor = anchor ?? (timezone ? todayInZone(timezone) : null);
  const queryKey = [workspaceId, timezone, view, effectiveAnchor, brandId, platform, accountId, statusFilter].join("|");

  useEffect(() => {
    if (!workspaceId || !timezone || !effectiveAnchor) return;
    let active = true;
    const params = new URLSearchParams({ view, date: effectiveAnchor, timezone });
    if (brandId) params.set("brand_id", brandId);
    if (platform) params.set("platform", platform);
    if (accountId) params.set("social_account_id", accountId);
    if (statusFilter) params.set("status", statusFilter);
    apiRequest<CalendarResponse>(`/workspaces/${workspaceId}/calendar?${params.toString()}`)
      .then((data) => {
        if (!active) return;
        setCalendar(data);
        setError(null);
        setLoadedKey(queryKey);
      })
      .catch((loadError: unknown) => {
        if (!active) return;
        setError(loadError instanceof ApiError ? loadError.message : "The calendar could not be loaded.");
        setLoadedKey(queryKey);
      });
    return () => {
      active = false;
    };
  }, [workspaceId, timezone, view, effectiveAnchor, brandId, platform, accountId, statusFilter, queryKey]);
  const loading = Boolean(workspaceId) && loadedKey !== queryKey;

  const itemsByDay = useMemo(() => {
    const map = new Map<string, CalendarItem[]>();
    for (const item of calendar?.items ?? []) {
      const list = map.get(item.local_date) ?? [];
      list.push(item);
      map.set(item.local_date, list);
    }
    return map;
  }, [calendar]);

  const changeTimezone = (value: string) => {
    setTimezone(value);
    void apiRequest("/me/preferences", { method: "PATCH", body: JSON.stringify({ timezone: value }) }).catch(() => undefined);
  };

  const step = (direction: 1 | -1) => {
    if (!effectiveAnchor) return;
    if (view === "month") setAnchor(addMonths(effectiveAnchor, direction));
    else if (view === "week") setAnchor(addDays(effectiveAnchor, 7 * direction));
    else if (view === "day") setAnchor(addDays(effectiveAnchor, direction));
    else setAnchor(addDays(effectiveAnchor, 30 * direction));
  };

  const title = (() => {
    if (!effectiveAnchor) return "";
    if (view === "month") return formatDay(effectiveAnchor, { month: "long", year: "numeric" });
    if (view === "day") return formatDay(effectiveAnchor, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
    const days = calendar?.days ?? [effectiveAnchor];
    return `${formatDay(days[0], { day: "numeric", month: "short" })} – ${formatDay(days[days.length - 1], { day: "numeric", month: "short", year: "numeric" })}`;
  })();
  const today = timezone ? todayInZone(timezone) : "";
  const currentMonth = effectiveAnchor?.slice(0, 7);
  const filteredAccounts = accounts.filter((account) => !platform || account.platform === (platform === "facebook" ? "facebook_page" : "instagram"));

  const agenda = (days: string[]) => {
    const withItems = days.filter((day) => (itemsByDay.get(day) ?? []).length > 0);
    if (withItems.length === 0) {
      return (
        <p className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-600">
          Nothing scheduled in this period.{canSchedule ? " Use “Schedule post” to add approved content." : ""}
        </p>
      );
    }
    return (
      <div className="space-y-5">
        {withItems.map((day) => (
          <section key={day}>
            <h3 className={`mb-2 text-sm font-semibold ${day === today ? "text-indigo-700" : "text-slate-700"}`}>
              {formatDay(day, { weekday: "long", day: "numeric", month: "long" })}
              {day === today ? " · Today" : ""}
            </h3>
            <ul className="space-y-2">{(itemsByDay.get(day) ?? []).map((item) => <AgendaRow key={`${item.kind}-${item.id}`} item={item} />)}</ul>
          </section>
        ))}
      </div>
    );
  };

  return (
    <ProtectedPage>
      <AppShell>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-indigo-700">Calendar</p>
            <h1 className="mt-2 text-3xl font-bold tracking-tight">Content calendar</h1>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link href="/dashboard/publishing/queue" className="rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium">Publishing queue</Link>
            {canSchedule && (
              <Link href="/dashboard/calendar/new" className="rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700">Schedule post</Link>
            )}
          </div>
        </div>

        {!workspaceId ? (
          <p className="mt-6 rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">Select a workspace to view its calendar.</p>
        ) : (
          <>
            <div className="mt-6 flex flex-wrap items-center gap-2">
              <div className="flex rounded-xl border border-slate-300 bg-white p-0.5 text-sm" role="group" aria-label="Calendar view">
                {VIEWS.map((mode) => (
                  <button key={mode} type="button" aria-pressed={view === mode} onClick={() => setView(mode)} className={`rounded-lg px-3 py-1.5 capitalize ${view === mode ? "bg-slate-900 text-white" : ""}`}>
                    {mode}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-1">
                <button type="button" aria-label="Previous" onClick={() => step(-1)} className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm">‹</button>
                <button type="button" onClick={() => setAnchor(null)} className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm">Today</button>
                <button type="button" aria-label="Next" onClick={() => step(1)} className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm">›</button>
              </div>
              <h2 className="min-w-0 flex-1 text-lg font-semibold">{title}</h2>
              {timezone && <TimezoneSelect value={timezone} onChange={changeTimezone} />}
            </div>

            <div className="mt-3 flex flex-wrap gap-2">
              <select aria-label="Filter by brand" className={fieldClass} value={brandId} onChange={(e) => setBrandId(e.target.value)}>
                <option value="">All brands</option>
                {brands.map((brand) => <option key={brand.id} value={brand.id}>{brand.name}</option>)}
              </select>
              <select aria-label="Filter by platform" className={fieldClass} value={platform} onChange={(e) => { setPlatform(e.target.value); setAccountId(""); }}>
                <option value="">All platforms</option>
                <option value="facebook">Facebook</option>
                <option value="instagram">Instagram</option>
              </select>
              <select aria-label="Filter by account" className={fieldClass} value={accountId} onChange={(e) => setAccountId(e.target.value)}>
                <option value="">All accounts</option>
                {filteredAccounts.map((account) => <option key={account.id} value={account.id}>{account.display_name}</option>)}
              </select>
              <select aria-label="Filter by status" className={fieldClass} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                <option value="">All statuses</option>
                {STATUSES.map((status) => <option key={status} value={status}>{statusLabel(status)}</option>)}
              </select>
            </div>

            <ul className="mt-3 flex flex-wrap gap-1.5" aria-label="Status legend">
              {LEGEND.map((status) => <li key={status}><StatusBadge status={status} /></li>)}
            </ul>

            {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}

            <div className="mt-5 grid gap-6 lg:grid-cols-[1fr_16rem]">
              <div className={loading ? "opacity-60 transition-opacity" : ""} aria-busy={loading}>
                {!calendar ? (
                  <p className="text-sm text-slate-500">Loading calendar…</p>
                ) : view === "month" ? (
                  <>
                    <div className="hidden overflow-hidden rounded-2xl border border-slate-200 bg-white md:block">
                      <div className="grid grid-cols-7 border-b border-slate-200 bg-slate-50 text-center text-xs font-semibold uppercase text-slate-500">
                        {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((day) => <div key={day} className="py-2">{day}</div>)}
                      </div>
                      <div className="grid grid-cols-7">
                        {calendar.days.map((day) => {
                          const items = itemsByDay.get(day) ?? [];
                          return (
                            <div key={day} className={`min-h-28 border-b border-r border-slate-100 p-1.5 ${day.slice(0, 7) !== currentMonth ? "bg-slate-50/70 text-slate-400" : ""}`}>
                              <button type="button" onClick={() => { setAnchor(day); setView("day"); }} className={`mb-1 inline-flex h-6 w-6 items-center justify-center rounded-full text-xs ${day === today ? "bg-indigo-600 font-bold text-white" : "hover:bg-slate-100"}`}>
                                {Number(day.slice(8))}
                              </button>
                              <div className="space-y-1">
                                {items.slice(0, 3).map((item) => <ItemChip key={`${item.kind}-${item.id}`} item={item} compact />)}
                                {items.length > 3 && (
                                  <button type="button" onClick={() => { setAnchor(day); setView("day"); }} className="text-xs font-medium text-indigo-700">+{items.length - 3} more</button>
                                )}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                    <div className="md:hidden">{agenda(calendar.days.filter((day) => day.slice(0, 7) === currentMonth))}</div>
                  </>
                ) : view === "week" ? (
                  <>
                    <div className="hidden gap-2 md:grid md:grid-cols-7">
                      {calendar.days.map((day) => (
                        <div key={day} className="min-h-48 rounded-xl border border-slate-200 bg-white p-2">
                          <p className={`mb-2 text-xs font-semibold ${day === today ? "text-indigo-700" : "text-slate-500"}`}>{formatDay(day, { weekday: "short", day: "numeric" })}</p>
                          <div className="space-y-1.5">{(itemsByDay.get(day) ?? []).map((item) => <ItemChip key={`${item.kind}-${item.id}`} item={item} />)}</div>
                        </div>
                      ))}
                    </div>
                    <div className="md:hidden">{agenda(calendar.days)}</div>
                  </>
                ) : (
                  agenda(calendar.days)
                )}
                <p className="mt-3 text-xs text-slate-500">Times shown in {calendar?.timezone.replaceAll("_", " ") ?? timezone}.</p>
              </div>

              <aside className="space-y-3">
                <h2 className="text-sm font-semibold">Ready to schedule</h2>
                {(calendar?.unscheduled ?? []).length === 0 ? (
                  <p className="rounded-xl border border-dashed border-slate-300 p-4 text-xs text-slate-600">
                    No approved, unscheduled drafts. Approve content in the <Link href="/dashboard/content" className="font-medium text-indigo-700">content studio</Link>.
                  </p>
                ) : (
                  <ul className="space-y-2">
                    {calendar?.unscheduled.map((item) => (
                      <li key={item.draft_id} className="rounded-xl border border-slate-200 bg-white p-3 text-sm">
                        <p className="flex items-center gap-1.5 font-medium"><PlatformMark platform={item.platform} /> <span className="truncate">{item.title ?? "Untitled"}</span></p>
                        {item.brand_name && <p className="text-xs text-slate-500">{item.brand_name}</p>}
                        {canSchedule && (
                          <Link href={`/dashboard/calendar/new?project=${item.project_id}&draft=${item.draft_id}`} className="mt-2 inline-block text-xs font-semibold text-indigo-700">Schedule →</Link>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </aside>
            </div>
          </>
        )}
      </AppShell>
    </ProtectedPage>
  );
}

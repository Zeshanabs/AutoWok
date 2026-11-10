"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { useAuth } from "@/components/auth-provider";
import { ApiError, apiRequest } from "@/lib/api";
import { defaultFilters, filterQuery, presetRange } from "@/lib/analytics-format";
import type { AnalyticsFilterState, SyncStatusList } from "@/lib/analytics-types";
import type { Brand, SocialAccount } from "@/lib/brand-types";

const STORAGE_KEY = "autowok.analytics.filters";

type AnalyticsContextValue = {
  workspaceId: string | undefined;
  canManage: boolean;
  filters: AnalyticsFilterState;
  setFilters: (update: Partial<AnalyticsFilterState>) => void;
  applyPreset: (preset: "7" | "28" | "90") => void;
  brands: Brand[];
  accounts: SocialAccount[];
  visibleAccounts: SocialAccount[];
  sync: SyncStatusList | null;
  refreshSync: () => Promise<void>;
  loadError: string | null;
  query: (extra?: Record<string, string | number | undefined | null>) => string;
  /** Bumps when a manual refresh completes so pages can reload their data. */
  dataVersion: number;
  bumpData: () => void;
};

const AnalyticsContext = createContext<AnalyticsContextValue | null>(null);

function readStored(): Partial<AnalyticsFilterState> | null {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Partial<AnalyticsFilterState>) : null;
  } catch {
    return null;
  }
}

export function AnalyticsProvider({ children }: { children: ReactNode }) {
  const { selectedWorkspace } = useAuth();
  const workspaceId = selectedWorkspace?.id;
  const canManage = selectedWorkspace?.role === "OWNER" || selectedWorkspace?.role === "ADMIN";
  const [filters, setFiltersState] = useState<AnalyticsFilterState>(() => ({ ...defaultFilters(), ...(typeof window === "undefined" ? null : readStored()) }));
  const [brands, setBrands] = useState<Brand[]>([]);
  const [accounts, setAccounts] = useState<SocialAccount[]>([]);
  const [sync, setSync] = useState<SyncStatusList | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [dataVersion, setDataVersion] = useState(0);

  const setFilters = useCallback((update: Partial<AnalyticsFilterState>) => {
    setFiltersState((current) => {
      const next = { ...current, ...update };
      if (next.start > next.end) next.start = next.end;
      try {
        window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } catch {
        /* storage is a convenience only */
      }
      return next;
    });
  }, []);

  const applyPreset = useCallback(
    (preset: "7" | "28" | "90") => setFilters({ ...presetRange(Number(preset) as 7 | 28 | 90), preset }),
    [setFilters],
  );

  const refreshSync = useCallback(async () => {
    if (!workspaceId) return;
    try {
      setSync(await apiRequest<SyncStatusList>(`/workspaces/${workspaceId}/analytics/sync/status`));
    } catch (error) {
      setLoadError(error instanceof ApiError ? error.message : "Synchronization status could not be loaded.");
    }
  }, [workspaceId]);

  useEffect(() => {
    if (!workspaceId) return;
    let active = true;
    const load = async () => {
      try {
        const [brandList, accountList] = await Promise.all([
          apiRequest<Brand[]>(`/workspaces/${workspaceId}/brands?limit=100`),
          apiRequest<SocialAccount[]>(`/workspaces/${workspaceId}/social-accounts`),
        ]);
        if (!active) return;
        setBrands(brandList);
        setAccounts(accountList.filter((account) => account.platform === "facebook_page" || account.platform === "instagram"));
        setLoadError(null);
      } catch (error) {
        if (active) setLoadError(error instanceof ApiError ? error.message : "Brands and accounts could not be loaded.");
      }
      await refreshSync();
    };
    void load();
    return () => {
      active = false;
    };
  }, [workspaceId, refreshSync]);

  // Poll while a synchronization is running so freshness indicators update.
  const activeJobs = sync?.active_jobs ?? 0;
  useEffect(() => {
    if (!workspaceId || activeJobs === 0) return;
    const timer = window.setInterval(() => {
      void refreshSync().then(() => setDataVersion((value) => value + 1));
    }, 5000);
    return () => window.clearInterval(timer);
  }, [workspaceId, activeJobs, refreshSync]);

  const visibleAccounts = useMemo(
    () =>
      accounts.filter(
        (account) => (!filters.platform || account.platform === filters.platform) && (!filters.brandId || account.brand_id === filters.brandId),
      ),
    [accounts, filters.platform, filters.brandId],
  );

  const value = useMemo<AnalyticsContextValue>(
    () => ({
      workspaceId,
      canManage,
      filters,
      setFilters,
      applyPreset,
      brands,
      accounts,
      visibleAccounts,
      sync,
      refreshSync,
      loadError,
      query: (extra) => filterQuery(filters, extra),
      dataVersion,
      bumpData: () => setDataVersion((current) => current + 1),
    }),
    [workspaceId, canManage, filters, setFilters, applyPreset, brands, accounts, visibleAccounts, sync, refreshSync, loadError, dataVersion],
  );

  return <AnalyticsContext.Provider value={value}>{children}</AnalyticsContext.Provider>;
}

export function useAnalytics(): AnalyticsContextValue {
  const context = useContext(AnalyticsContext);
  if (!context) throw new Error("useAnalytics must be used inside AnalyticsProvider.");
  return context;
}

/** Fetch helper that tracks loading/error and keeps the previous data while refetching. */
export function useAnalyticsData<T>(path: string | null, deps: unknown[]): { data: T | null; loading: boolean; error: string | null; reload: () => void } {
  const [state, setState] = useState<{ key: string; data: T | null; error: string | null }>({ key: "", data: null, error: null });
  const [tick, setTick] = useState(0);
  const key = path ? `${path}|${JSON.stringify(deps)}|${tick}` : "";

  useEffect(() => {
    if (!path) return;
    let active = true;
    apiRequest<T>(path)
      .then((result) => {
        if (active) setState({ key, data: result, error: null });
      })
      .catch((loadError: unknown) => {
        if (active) {
          setState((previous) => ({ key, data: previous.data, error: loadError instanceof ApiError ? loadError.message : "The analytics data could not be loaded." }));
        }
      });
    return () => {
      active = false;
    };
  }, [path, key]);

  const loading = Boolean(path) && state.key !== key;
  return { data: path ? state.data : null, loading, error: path ? state.error : null, reload: () => setTick((value) => value + 1) };
}

"use client";

import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { ApiError, API_BASE_URL, apiRequest } from "@/lib/api";
import type {
  Brand,
  InstagramAccountOption,
  MetaPageOption,
  SocialAccount,
} from "@/lib/brand-types";

export default function SocialAccountsPage() {
  const { selectedWorkspace } = useAuth();
  const [accounts, setAccounts] = useState<SocialAccount[]>([]);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [pages, setPages] = useState<MetaPageOption[]>([]);
  const [instagramAccounts, setInstagramAccounts] = useState<
    InstagramAccountOption[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [loadingChoices, setLoadingChoices] = useState(false);
  const [busyAccount, setBusyAccount] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const canManage =
    selectedWorkspace?.role === "OWNER" || selectedWorkspace?.role === "ADMIN";

  const loadAccounts = useCallback(async () => {
    if (!selectedWorkspace) {
      setAccounts([]);
      setBrands([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const [accountData, brandData] = await Promise.all([
        apiRequest<SocialAccount[]>(
          `/workspaces/${selectedWorkspace.id}/social-accounts`,
        ),
        apiRequest<Brand[]>(`/workspaces/${selectedWorkspace.id}/brands`),
      ]);
      setAccounts(accountData);
      setBrands(brandData);
      setError(null);
    } catch (loadError) {
      setError(
        loadError instanceof ApiError
          ? loadError.message
          : "Social accounts could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }, [selectedWorkspace]);

  const discoverAccounts = useCallback(async () => {
    if (!selectedWorkspace) return;
    setLoadingChoices(true);
    setError(null);
    try {
      const [pageData, instagramData] = await Promise.all([
        apiRequest<MetaPageOption[]>(
          `/workspaces/${selectedWorkspace.id}/social-accounts/meta/facebook-pages`,
        ),
        apiRequest<InstagramAccountOption[]>(
          `/workspaces/${selectedWorkspace.id}/social-accounts/meta/instagram-accounts`,
        ),
      ]);
      setPages(pageData);
      setInstagramAccounts(instagramData);
      setNotice("Meta accounts loaded. Select the Pages or Instagram accounts to connect.");
    } catch (loadError) {
      setError(
        loadError instanceof ApiError
          ? loadError.message
          : "Meta accounts could not be discovered.",
      );
    } finally {
      setLoadingChoices(false);
    }
  }, [selectedWorkspace]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadAccounts(), 0);
    return () => window.clearTimeout(timer);
  }, [loadAccounts]);

  useEffect(() => {
    if (!selectedWorkspace) return;
    const params = new URLSearchParams(window.location.search);
    const result = params.get("meta");
    const workspaceId = params.get("workspace_id");
    if (!result || (workspaceId && workspaceId !== selectedWorkspace.id)) return;
    const timer = window.setTimeout(() => {
      if (result === "connected") {
        setNotice("Meta authorization succeeded. Choose the accounts to connect.");
        void discoverAccounts();
      } else if (result === "denied") {
        setError("Meta authorization was cancelled. No account was connected.");
      } else if (result === "permissions") {
        setError("Meta did not grant all permissions required for account discovery.");
      } else if (result === "configuration") {
        setError("Meta token encryption is not configured on the server.");
      } else {
        setError("Meta authorization could not be completed. Try connecting again.");
      }
    }, 0);
    window.history.replaceState({}, "", window.location.pathname);
    return () => window.clearTimeout(timer);
  }, [discoverAccounts, selectedWorkspace]);

  function startMetaAuthorization() {
    if (!selectedWorkspace) return;
    const query = new URLSearchParams({ workspace_id: selectedWorkspace.id });
    // OAuth requires a full-page navigation through the backend authorization endpoint.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign(
      `${API_BASE_URL}/api/v1/oauth/meta/authorize?${query.toString()}`,
    );
  }

  async function connectAccount(
    platform: "facebook_page" | "instagram",
    platformAccountId: string,
    parentPageId?: string,
  ) {
    if (!selectedWorkspace) return;
    setBusyAccount(platformAccountId);
    setError(null);
    setNotice(null);
    try {
      const account = await apiRequest<SocialAccount>(
        `/workspaces/${selectedWorkspace.id}/social-accounts/meta/connect`,
        {
          method: "POST",
          body: JSON.stringify({
            platform,
            platform_account_id: platformAccountId,
            ...(parentPageId ? { parent_page_id: parentPageId } : {}),
          }),
        },
      );
      setAccounts((current) => [
        account,
        ...current.filter((item) => item.id !== account.id),
      ]);
      setNotice(`${account.display_name} connected to this workspace.`);
    } catch (connectError) {
      setError(
        connectError instanceof ApiError
          ? connectError.message
          : "The social account could not be connected.",
      );
    } finally {
      setBusyAccount(null);
    }
  }

  async function updateBrand(account: SocialAccount, brandId: string) {
    if (!selectedWorkspace) return;
    setBusyAccount(account.id);
    setError(null);
    try {
      const updated = await apiRequest<SocialAccount>(
        `/workspaces/${selectedWorkspace.id}/social-accounts/${account.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({ brand_id: brandId || null }),
        },
      );
      setAccounts((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setNotice("Brand association updated.");
    } catch (updateError) {
      setError(
        updateError instanceof ApiError
          ? updateError.message
          : "The brand association could not be updated.",
      );
    } finally {
      setBusyAccount(null);
    }
  }

  async function verifyAccount(account: SocialAccount) {
    if (!selectedWorkspace) return;
    setBusyAccount(account.id);
    setError(null);
    try {
      const updated = await apiRequest<SocialAccount>(
        `/workspaces/${selectedWorkspace.id}/social-accounts/${account.id}/verify`,
        { method: "POST" },
      );
      setAccounts((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setNotice(`${account.display_name} is connected.`);
    } catch (verifyError) {
      setError(
        verifyError instanceof ApiError
          ? verifyError.message
          : "The account connection could not be verified.",
      );
      await loadAccounts();
    } finally {
      setBusyAccount(null);
    }
  }

  async function disconnectAccount(account: SocialAccount) {
    if (!selectedWorkspace) return;
    if (!window.confirm(`Disconnect ${account.display_name}?`)) return;
    setBusyAccount(account.id);
    setError(null);
    try {
      const updated = await apiRequest<SocialAccount>(
        `/workspaces/${selectedWorkspace.id}/social-accounts/${account.id}/disconnect`,
        { method: "POST" },
      );
      setAccounts((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setNotice(`${account.display_name} disconnected and its stored token removed.`);
    } catch (disconnectError) {
      setError(
        disconnectError instanceof ApiError
          ? disconnectError.message
          : "The account could not be disconnected.",
      );
    } finally {
      setBusyAccount(null);
    }
  }

  async function refreshMetaAuthorization() {
    if (!selectedWorkspace) return;
    setBusyAccount("meta-refresh");
    setError(null);
    try {
      await apiRequest(
        `/oauth/meta/refresh?workspace_id=${selectedWorkspace.id}`,
        { method: "POST" },
      );
      await loadAccounts();
      setNotice("Meta authorization and connected Page credentials were refreshed.");
    } catch (refreshError) {
      setError(
        refreshError instanceof ApiError
          ? refreshError.message
          : "Meta credentials could not be refreshed. Reconnect Meta if needed.",
      );
    } finally {
      setBusyAccount(null);
    }
  }

  const facebookPages = accounts.filter(
    (account) => account.platform === "facebook_page",
  );
  const instagram = accounts.filter((account) => account.platform === "instagram");

  return (
    <ProtectedPage>
      <AppShell>
        <h1 className="text-3xl font-bold tracking-tight">Social accounts</h1>
        <p className="mt-2 max-w-3xl text-slate-600">
          Connect Facebook Pages and eligible Instagram Business or Creator
          accounts using Meta authorization. Personal Instagram accounts are
          not supported by this integration.
        </p>
        {!selectedWorkspace ? (
          <p className="mt-6 rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">
            Select or create a workspace before connecting social accounts.
          </p>
        ) : (
          <>
            {error && (
              <p role="alert" className="mt-5 rounded-lg bg-red-50 p-3 text-sm text-red-800">
                {error}
              </p>
            )}
            {notice && (
              <p role="status" className="mt-5 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">
                {notice}
              </p>
            )}
            {canManage && (
              <div className="mt-6 flex flex-wrap gap-3">
                <button
                  onClick={startMetaAuthorization}
                  className="rounded-xl bg-indigo-600 px-4 py-2.5 font-semibold text-white hover:bg-indigo-700"
                >
                  Connect Facebook / Instagram with Meta
                </button>
                <button
                  onClick={() => void discoverAccounts()}
                  disabled={loadingChoices}
                  className="rounded-xl border border-slate-300 px-4 py-2.5 font-semibold disabled:opacity-60"
                >
                  {loadingChoices ? "Loading accounts…" : "Discover available accounts"}
                </button>
                <button
                  onClick={() => void refreshMetaAuthorization()}
                  disabled={busyAccount !== null}
                  className="rounded-xl border border-slate-300 px-4 py-2.5 font-semibold disabled:opacity-60"
                >
                  Refresh Meta credentials
                </button>
              </div>
            )}
            {!canManage && (
              <p className="mt-5 text-sm text-slate-600">
                You have read-only access. A workspace Owner or Admin can connect
                and manage social accounts.
              </p>
            )}
            {loading ? (
              <p className="mt-7">Loading social accounts…</p>
            ) : (
              <>
                <section className="mt-8">
                  <h2 className="text-xl font-semibold">Connected accounts</h2>
                  {accounts.length === 0 ? (
                    <p className="mt-3 rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">
                      No social accounts have been connected to this workspace.
                    </p>
                  ) : (
                    <div className="mt-4 grid gap-3 lg:grid-cols-2">
                      {[...facebookPages, ...instagram].map((account) => (
                        <article
                          key={account.id}
                          className="rounded-2xl border border-slate-200 bg-white p-5"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <p className="text-xs font-semibold uppercase tracking-wide text-indigo-700">
                                {account.platform === "facebook_page"
                                  ? "Facebook Page"
                                  : "Instagram Professional"}
                              </p>
                              <h3 className="mt-1 font-semibold">
                                {account.display_name}
                              </h3>
                              <p className="mt-1 text-sm text-slate-600">
                                {account.username
                                  ? `@${account.username} · `
                                  : ""}
                                {account.connection_status.replaceAll("_", " ")}
                                {account.account_type
                                  ? ` · ${account.account_type}`
                                  : ""}
                              </p>
                              {account.last_verified_at && (
                                <p className="mt-1 text-xs text-slate-500">
                                  Verified{" "}
                                  {new Date(account.last_verified_at).toLocaleString()}
                                </p>
                              )}
                            </div>
                          </div>
                          <label className="mt-4 block text-sm font-medium">
                            Associated brand
                            <select
                              value={account.brand_id ?? ""}
                              onChange={(event) =>
                                void updateBrand(account, event.target.value)
                              }
                              disabled={!canManage || busyAccount === account.id}
                              className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 disabled:opacity-60"
                            >
                              <option value="">No brand</option>
                              {brands.map((brand) => (
                                <option key={brand.id} value={brand.id}>
                                  {brand.name}
                                </option>
                              ))}
                            </select>
                          </label>
                          {canManage && (
                            <div className="mt-4 flex gap-3">
                              <button
                                disabled={busyAccount !== null}
                                onClick={() => void verifyAccount(account)}
                                className="text-sm font-semibold text-indigo-700 disabled:opacity-50"
                              >
                                {busyAccount === account.id ? "Checking…" : "Verify"}
                              </button>
                              {account.connection_status !== "disconnected" && (
                                <button
                                  disabled={busyAccount !== null}
                                  onClick={() => void disconnectAccount(account)}
                                  className="text-sm font-semibold text-red-700 disabled:opacity-50"
                                >
                                  Disconnect
                                </button>
                              )}
                            </div>
                          )}
                        </article>
                      ))}
                    </div>
                  )}
                </section>
                {canManage && (
                  <div className="mt-9 grid gap-6 lg:grid-cols-2">
                    <section className="rounded-2xl border border-slate-200 bg-white p-5">
                      <h2 className="text-lg font-semibold">Available Facebook Pages</h2>
                      <p className="mt-1 text-sm text-slate-600">
                        Only Pages where your Meta user has management or content
                        creation tasks are shown.
                      </p>
                      {pages.length === 0 ? (
                        <p className="mt-4 text-sm text-slate-500">
                          Authorize Meta and discover Pages to choose one.
                        </p>
                      ) : (
                        <ul className="mt-4 space-y-3">
                          {pages.map((page) => (
                            <li
                              key={page.platform_account_id}
                              className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 p-3"
                            >
                              <div>
                                <p className="font-medium">{page.display_name}</p>
                                <p className="text-xs text-slate-500">
                                  {page.category || "Facebook Page"}
                                  {page.username ? ` · @${page.username}` : ""}
                                </p>
                              </div>
                              <button
                                disabled={busyAccount !== null}
                                onClick={() =>
                                  void connectAccount(
                                    "facebook_page",
                                    page.platform_account_id,
                                  )
                                }
                                className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-60"
                              >
                                {busyAccount === page.platform_account_id
                                  ? "Connecting…"
                                  : "Connect"}
                              </button>
                            </li>
                          ))}
                        </ul>
                      )}
                    </section>
                    <section className="rounded-2xl border border-slate-200 bg-white p-5">
                      <h2 className="text-lg font-semibold">
                        Available Instagram Professional accounts
                      </h2>
                      <p className="mt-1 text-sm text-slate-600">
                        Meta exposes Business and Creator accounts linked to
                        accessible Facebook Pages. Personal accounts are omitted.
                      </p>
                      {instagramAccounts.length === 0 ? (
                        <p className="mt-4 text-sm text-slate-500">
                          No eligible Instagram accounts were found.
                        </p>
                      ) : (
                        <ul className="mt-4 space-y-3">
                          {instagramAccounts.map((account) => (
                            <li
                              key={account.platform_account_id}
                              className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 p-3"
                            >
                              <div>
                                <p className="font-medium">
                                  {account.username
                                    ? `@${account.username}`
                                    : account.platform_account_id}
                                </p>
                                <p className="text-xs text-slate-500">
                                  {account.account_type} · Page: {account.parent_page_name}
                                </p>
                              </div>
                              <button
                                disabled={busyAccount !== null}
                                onClick={() =>
                                  void connectAccount(
                                    "instagram",
                                    account.platform_account_id,
                                    account.parent_page_id,
                                  )
                                }
                                className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-60"
                              >
                                {busyAccount === account.platform_account_id
                                  ? "Connecting…"
                                  : "Connect"}
                              </button>
                            </li>
                          ))}
                        </ul>
                      )}
                    </section>
                  </div>
                )}
              </>
            )}
          </>
        )}
      </AppShell>
    </ProtectedPage>
  );
}

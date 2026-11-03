"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { useAuth } from "@/components/auth-provider";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { ApiError, apiRequest } from "@/lib/api";
import type { BrandOverview } from "@/lib/brand-types";

const sections = [
  ["voice", "Brand voice"],
  ["audiences", "Target audiences"],
  ["pillars", "Content pillars"],
  ["goals", "Goals"],
  ["policies", "Policies"],
] as const;

export default function BrandOverviewPage() {
  const { brandId } = useParams<{ brandId: string }>();
  const { workspaces } = useAuth();
  const [overview, setOverview] = useState<BrandOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [industry, setIndustry] = useState("");
  const [businessType, setBusinessType] = useState("");
  const [website, setWebsite] = useState("");
  const [primaryColor, setPrimaryColor] = useState("");
  const [secondaryColor, setSecondaryColor] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiRequest<BrandOverview>(
        `/brands/${brandId}/overview`,
      );
      setOverview(data);
      setName(data.brand.name);
      setDescription(data.brand.description ?? "");
      setIndustry(data.brand.industry ?? "");
      setBusinessType(data.brand.business_type ?? "");
      setWebsite(data.brand.website_url ?? "");
      setPrimaryColor(data.brand.primary_color ?? "");
      setSecondaryColor(data.brand.secondary_color ?? "");
      setError(null);
    } catch (loadError) {
      setError(
        loadError instanceof ApiError
          ? loadError.message
          : "Brand details could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }, [brandId]);

  async function saveIdentity(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiRequest(`/brands/${brandId}`, {
        method: "PATCH",
        body: JSON.stringify({
          name,
          description: description || null,
          industry: industry || null,
          business_type: businessType || null,
          website_url: website || null,
          primary_color: primaryColor || null,
          secondary_color: secondaryColor || null,
        }),
      });
      await load();
    } catch (saveError) {
      setError(
        saveError instanceof ApiError
          ? saveError.message
          : "Brand identity could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function archive() {
    if (!window.confirm("Archive this brand? Its profile will be retained.")) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await apiRequest(`/brands/${brandId}`, { method: "DELETE" });
      await load();
    } catch (archiveError) {
      setError(
        archiveError instanceof ApiError
          ? archiveError.message
          : "Brand could not be archived.",
      );
    } finally {
      setBusy(false);
    }
  }

  const brandRole = workspaces.find(
    (workspace) => workspace.id === overview?.brand.workspace_id,
  )?.role;
  const canManage = brandRole === "OWNER" || brandRole === "ADMIN";
  const counts = overview
    ? [
        ["Audiences", overview.audiences.length],
        ["Pillars", overview.pillars.length],
        ["Goals", overview.goals.length],
        ["Policies", overview.policies.length],
      ]
    : [];

  return (
    <ProtectedPage>
      <AppShell>
        {error && (
          <p role="alert" className="mb-5 rounded-lg bg-red-50 p-3 text-sm text-red-800">
            {error}
          </p>
        )}
        {loading ? (
          <p>Loading brand…</p>
        ) : overview ? (
          <>
            <p className="text-sm font-medium text-indigo-700">Brand setup</p>
            <div className="mt-2 flex flex-wrap items-start justify-between gap-4">
              <div>
                <h1 className="text-3xl font-bold tracking-tight">
                  {overview.brand.name}
                </h1>
                <p className="mt-2 text-slate-600">
                  {overview.brand.description ||
                    overview.brand.industry ||
                    "Complete this profile to make brand guidance reusable."}
                </p>
              </div>
              {canManage && overview.brand.status === "ACTIVE" && (
                <button
                  disabled={busy}
                  onClick={() => void archive()}
                  className="rounded-lg border border-red-200 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-60"
                >
                  Archive brand
                </button>
              )}
            </div>
            {overview.brand.status === "ARCHIVED" && (
              <p className="mt-5 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
                This brand is archived. It is read-only and excluded from brand
                context.
              </p>
            )}
            <section className="mt-7 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {counts.map(([label, count]) => (
                <article
                  key={label}
                  className="rounded-2xl border border-slate-200 bg-white p-5"
                >
                  <p className="text-sm text-slate-500">{label}</p>
                  <p className="mt-1 text-2xl font-bold">{count}</p>
                </article>
              ))}
            </section>
            <section className="mt-7 rounded-2xl border border-slate-200 bg-white p-6">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <h2 className="text-lg font-semibold">Identity</h2>
                  <p className="mt-1 text-sm text-slate-600">
                    {overview.brand.industry || "Industry not set"}
                    {overview.brand.website_url
                      ? ` · ${overview.brand.website_url}`
                      : ""}
                  </p>
                </div>
                <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium">
                  {overview.brand.status}
                </span>
              </div>
              {canManage && overview.brand.status === "ACTIVE" && (
                <form onSubmit={saveIdentity} className="mt-5 grid gap-4 sm:grid-cols-2">
                  <label className="text-sm font-medium">
                    Brand name
                    <input
                      value={name}
                      onChange={(event) => setName(event.target.value)}
                      required
                      minLength={2}
                      maxLength={120}
                      className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2.5"
                    />
                  </label>
                  <label className="text-sm font-medium">
                    Industry
                    <input
                      value={industry}
                      onChange={(event) => setIndustry(event.target.value)}
                      maxLength={120}
                      className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2.5"
                    />
                  </label>
                  <label className="text-sm font-medium">
                    Business type
                    <input
                      value={businessType}
                      onChange={(event) => setBusinessType(event.target.value)}
                      maxLength={120}
                      className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2.5"
                    />
                  </label>
                  <label className="text-sm font-medium">
                    Website URL
                    <input
                      type="url"
                      value={website}
                      onChange={(event) => setWebsite(event.target.value)}
                      className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2.5"
                    />
                  </label>
                  <label className="text-sm font-medium sm:col-span-2">
                    Description
                    <textarea
                      value={description}
                      onChange={(event) => setDescription(event.target.value)}
                      maxLength={5000}
                      rows={3}
                      className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2.5"
                    />
                  </label>
                  <label className="text-sm font-medium">
                    Primary color
                    <input
                      type="color"
                      value={primaryColor || "#4f46e5"}
                      onChange={(event) => setPrimaryColor(event.target.value)}
                      className="mt-1 block h-11 w-full rounded-xl border border-slate-300 p-1"
                    />
                  </label>
                  <label className="text-sm font-medium">
                    Secondary color
                    <input
                      type="color"
                      value={secondaryColor || "#0f172a"}
                      onChange={(event) => setSecondaryColor(event.target.value)}
                      className="mt-1 block h-11 w-full rounded-xl border border-slate-300 p-1"
                    />
                  </label>
                  <button
                    disabled={busy}
                    className="w-fit rounded-xl bg-indigo-600 px-4 py-2.5 font-semibold text-white disabled:opacity-60 sm:col-span-2"
                  >
                    {busy ? "Saving…" : "Save identity"}
                  </button>
                </form>
              )}
            </section>
            <section className="mt-7">
              <h2 className="text-xl font-semibold">Profile setup</h2>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                {sections.map(([key, title]) => (
                  <Link
                    key={key}
                    href={`/brands/${brandId}/${key}`}
                    className="rounded-2xl border border-slate-200 bg-white p-5 transition hover:border-indigo-300 hover:shadow-sm"
                  >
                    <h3 className="font-semibold">{title}</h3>
                    <p className="mt-1 text-sm text-slate-600">
                      {key === "voice"
                        ? overview.voice
                          ? "Voice guidance is saved."
                          : "Set a consistent tone and language."
                        : "Review and manage the saved profile entries."}
                    </p>
                    <span className="mt-3 inline-block text-sm font-semibold text-indigo-700">
                      Configure →
                    </span>
                  </Link>
                ))}
              </div>
            </section>
          </>
        ) : null}
      </AppShell>
    </ProtectedPage>
  );
}

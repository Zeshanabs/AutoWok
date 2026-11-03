"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";

import { useAuth } from "@/components/auth-provider";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { ApiError, apiRequest } from "@/lib/api";
import type { Brand } from "@/lib/brand-types";

export default function BrandsPage() {
  const { selectedWorkspace } = useAuth();
  const [brands, setBrands] = useState<Brand[]>([]);
  const [name, setName] = useState("");
  const [industry, setIndustry] = useState("");
  const [website, setWebsite] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const loadBrands = useCallback(async () => {
    if (!selectedWorkspace) {
      setBrands([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      setBrands(
        await apiRequest<Brand[]>(
          `/workspaces/${selectedWorkspace.id}/brands`,
        ),
      );
      setError(null);
    } catch (loadError) {
      setError(
        loadError instanceof ApiError
          ? loadError.message
          : "Brands could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }, [selectedWorkspace]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadBrands(), 0);
    return () => window.clearTimeout(timer);
  }, [loadBrands]);

  async function createBrand(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedWorkspace) return;
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const brand = await apiRequest<Brand>(
        `/workspaces/${selectedWorkspace.id}/brands`,
        {
          method: "POST",
          body: JSON.stringify({
            name,
            industry: industry || null,
            website_url: website || null,
          }),
        },
      );
      setName("");
      setIndustry("");
      setWebsite("");
      setSuccess("Brand created. Continue setup from the overview.");
      setBrands((current) => [brand, ...current]);
    } catch (createError) {
      setError(
        createError instanceof ApiError
          ? createError.message
          : "Brand could not be created.",
      );
    } finally {
      setSaving(false);
    }
  }

  const canManage =
    selectedWorkspace?.role === "OWNER" || selectedWorkspace?.role === "ADMIN";

  return (
    <ProtectedPage>
      <AppShell>
        <h1 className="text-3xl font-bold tracking-tight">Brands</h1>
        <p className="mt-2 text-slate-600">
          Set up workspace-specific identity, voice, audiences, and content
          policies.
        </p>
        {!selectedWorkspace ? (
          <p className="mt-6 rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">
            Select or create a workspace before managing brands.
          </p>
        ) : (
          <>
            {error && (
              <p role="alert" className="mt-5 rounded-lg bg-red-50 p-3 text-sm text-red-800">
                {error}
              </p>
            )}
            {success && (
              <p role="status" className="mt-5 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">
                {success}
              </p>
            )}
            <section className="mt-7 space-y-3">
              {loading ? (
                <p>Loading brands…</p>
              ) : brands.length === 0 ? (
                <p className="rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">
                  No brands in {selectedWorkspace.name} yet.
                </p>
              ) : (
                brands.map((brand) => (
                  <article
                    key={brand.id}
                    className="flex flex-col gap-4 rounded-2xl border border-slate-200 bg-white p-5 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div>
                      <h2 className="font-semibold">{brand.name}</h2>
                      <p className="mt-1 text-sm text-slate-500">
                        {brand.industry || "Industry not set"} · {brand.status.toLowerCase()}
                      </p>
                    </div>
                    <Link
                      href={`/brands/${brand.id}`}
                      className="rounded-lg bg-slate-900 px-3 py-2 text-center text-sm font-medium text-white hover:bg-slate-800"
                    >
                      Open brand setup
                    </Link>
                  </article>
                ))
              )}
            </section>
            {canManage ? (
              <form
                onSubmit={createBrand}
                className="mt-9 max-w-2xl rounded-2xl border border-slate-200 bg-white p-6"
              >
                <h2 className="text-lg font-semibold">Start a brand setup</h2>
                <p className="mt-1 text-sm text-slate-600">
                  Begin with the basics; complete voice and profile details on
                  the brand page.
                </p>
                <label className="mt-4 block text-sm font-medium">
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
                <label className="mt-4 block text-sm font-medium">
                  Industry
                  <input
                    value={industry}
                    onChange={(event) => setIndustry(event.target.value)}
                    maxLength={120}
                    className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2.5"
                  />
                </label>
                <label className="mt-4 block text-sm font-medium">
                  Website URL
                  <input
                    type="url"
                    value={website}
                    onChange={(event) => setWebsite(event.target.value)}
                    placeholder="https://example.com"
                    className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2.5"
                  />
                </label>
                <button
                  disabled={saving}
                  className="mt-5 rounded-xl bg-indigo-600 px-4 py-2.5 font-semibold text-white disabled:opacity-60"
                >
                  {saving ? "Creating…" : "Create brand"}
                </button>
              </form>
            ) : (
              <p className="mt-6 text-sm text-slate-600">
                You have read-only access to this workspace’s brands.
              </p>
            )}
          </>
        )}
      </AppShell>
    </ProtectedPage>
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { useAuth } from "@/components/auth-provider";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { ApiError, apiRequest } from "@/lib/api";
import type { Brand } from "@/lib/brand-types";

export default function BrandsPage() {
  const { selectedWorkspace } = useAuth();
  const [brands, setBrands] = useState<Brand[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
                      <p className="mt-1 text-sm text-slate-500">
                        {brand.website_url || "Website not set"} · Updated{" "}
                        {new Date(brand.updated_at).toLocaleDateString()}
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
              <Link
                href="/brands/new"
                className="mt-8 inline-flex rounded-xl bg-indigo-600 px-4 py-2.5 font-semibold text-white hover:bg-indigo-700"
              >
                Create a brand
              </Link>
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

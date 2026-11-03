"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { useAuth } from "@/components/auth-provider";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { ApiError, apiRequest } from "@/lib/api";
import type { BrandOverview } from "@/lib/brand-types";

const inputClass =
  "mt-1 w-full rounded-xl border border-slate-300 px-3 py-2.5";

export default function BrandSettingsPage() {
  const { brandId } = useParams<{ brandId: string }>();
  const { workspaces } = useAuth();
  const [overview, setOverview] = useState<BrandOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [industry, setIndustry] = useState("");
  const [businessType, setBusinessType] = useState("");
  const [website, setWebsite] = useState("");
  const [logoUrl, setLogoUrl] = useState("");
  const [primaryColor, setPrimaryColor] = useState("#4f46e5");
  const [secondaryColor, setSecondaryColor] = useState("#0f172a");

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
      setLogoUrl(data.brand.logo_url ?? "");
      setPrimaryColor(data.brand.primary_color ?? "#4f46e5");
      setSecondaryColor(data.brand.secondary_color ?? "#0f172a");
      setError(null);
    } catch (loadError) {
      setError(
        loadError instanceof ApiError
          ? loadError.message
          : "Brand settings could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }, [brandId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function saveSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      await apiRequest(`/brands/${brandId}`, {
        method: "PATCH",
        body: JSON.stringify({
          name,
          description: description || null,
          industry: industry || null,
          business_type: businessType || null,
          website_url: website || null,
          logo_url: logoUrl || null,
          primary_color: primaryColor,
          secondary_color: secondaryColor,
        }),
      });
      await load();
      setSuccess("Brand settings saved.");
    } catch (saveError) {
      setError(
        saveError instanceof ApiError
          ? saveError.message
          : "Brand settings could not be saved.",
      );
    } finally {
      setSaving(false);
    }
  }

  const role = workspaces.find(
    (workspace) => workspace.id === overview?.brand.workspace_id,
  )?.role;
  const canManage = role === "OWNER" || role === "ADMIN";
  const editable = canManage && overview?.brand.status === "ACTIVE";

  return (
    <ProtectedPage>
      <AppShell>
        <Link
          href={`/brands/${brandId}`}
          className="text-sm font-semibold text-indigo-700"
        >
          ← Brand overview
        </Link>
        <h1 className="mt-4 text-3xl font-bold tracking-tight">Brand settings</h1>
        <p className="mt-2 text-slate-600">
          Update identity details used throughout this brand profile.
        </p>
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
        {loading ? (
          <p className="mt-6">Loading brand settings…</p>
        ) : overview ? (
          <form
            onSubmit={saveSettings}
            className="mt-7 grid max-w-3xl gap-4 rounded-2xl border border-slate-200 bg-white p-6 sm:grid-cols-2"
          >
            {!editable && (
              <p className="text-sm text-slate-600 sm:col-span-2">
                {overview.brand.status === "ARCHIVED"
                  ? "Archived brands are read-only."
                  : "Your workspace role has read-only access to these settings."}
              </p>
            )}
            <label className="text-sm font-medium">
              Brand name
              <input
                className={inputClass}
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
                minLength={2}
                maxLength={120}
                readOnly={!editable}
              />
            </label>
            <label className="text-sm font-medium">
              Industry
              <input
                className={inputClass}
                value={industry}
                onChange={(event) => setIndustry(event.target.value)}
                maxLength={120}
                readOnly={!editable}
              />
            </label>
            <label className="text-sm font-medium">
              Business type
              <input
                className={inputClass}
                value={businessType}
                onChange={(event) => setBusinessType(event.target.value)}
                maxLength={120}
                readOnly={!editable}
              />
            </label>
            <label className="text-sm font-medium">
              Website URL
              <input
                className={inputClass}
                type="url"
                value={website}
                onChange={(event) => setWebsite(event.target.value)}
                readOnly={!editable}
              />
            </label>
            <label className="text-sm font-medium sm:col-span-2">
              Logo URL
              <input
                className={inputClass}
                type="url"
                value={logoUrl}
                onChange={(event) => setLogoUrl(event.target.value)}
                readOnly={!editable}
              />
            </label>
            <label className="text-sm font-medium sm:col-span-2">
              Description
              <textarea
                className={inputClass}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                maxLength={5000}
                rows={4}
                readOnly={!editable}
              />
            </label>
            <label className="text-sm font-medium">
              Primary color
              <input
                className="mt-1 block h-11 w-full rounded-xl border border-slate-300 p-1"
                type="color"
                value={primaryColor}
                onChange={(event) => setPrimaryColor(event.target.value)}
                disabled={!editable}
              />
            </label>
            <label className="text-sm font-medium">
              Secondary color
              <input
                className="mt-1 block h-11 w-full rounded-xl border border-slate-300 p-1"
                type="color"
                value={secondaryColor}
                onChange={(event) => setSecondaryColor(event.target.value)}
                disabled={!editable}
              />
            </label>
            {editable && (
              <button
                disabled={saving}
                className="w-fit rounded-xl bg-indigo-600 px-4 py-2.5 font-semibold text-white disabled:opacity-60 sm:col-span-2"
              >
                {saving ? "Saving…" : "Save settings"}
              </button>
            )}
          </form>
        ) : null}
      </AppShell>
    </ProtectedPage>
  );
}

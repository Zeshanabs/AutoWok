"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/auth-provider";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { ApiError, apiRequest } from "@/lib/api";
import type { Brand } from "@/lib/brand-types";

const inputClass =
  "mt-1 w-full rounded-xl border border-slate-300 px-3 py-2.5";

export default function NewBrandPage() {
  const { selectedWorkspace } = useAuth();
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [industry, setIndustry] = useState("");
  const [businessType, setBusinessType] = useState("");
  const [description, setDescription] = useState("");
  const [website, setWebsite] = useState("");
  const [logoUrl, setLogoUrl] = useState("");
  const [primaryColor, setPrimaryColor] = useState("#4f46e5");
  const [secondaryColor, setSecondaryColor] = useState("#0f172a");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canManage =
    selectedWorkspace?.role === "OWNER" || selectedWorkspace?.role === "ADMIN";

  async function createBrand(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedWorkspace) return;
    setSaving(true);
    setError(null);
    try {
      const brand = await apiRequest<Brand>(
        `/workspaces/${selectedWorkspace.id}/brands`,
        {
          method: "POST",
          body: JSON.stringify({
            name,
            slug: slug || null,
            industry: industry || null,
            business_type: businessType || null,
            description: description || null,
            website_url: website || null,
            logo_url: logoUrl || null,
            primary_color: primaryColor,
            secondary_color: secondaryColor,
          }),
        },
      );
      router.push(`/brands/${brand.id}`);
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

  return (
    <ProtectedPage>
      <AppShell>
        <Link href="/brands" className="text-sm font-semibold text-indigo-700">
          ← All brands
        </Link>
        <h1 className="mt-4 text-3xl font-bold tracking-tight">
          Create a brand
        </h1>
        <p className="mt-2 text-slate-600">
          Set up a workspace brand in two steps. You can refine the profile
          after creation.
        </p>
        {!selectedWorkspace ? (
          <p className="mt-6 rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">
            Select or create a workspace before setting up a brand.
          </p>
        ) : !canManage ? (
          <p className="mt-6 rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">
            You need a workspace owner or admin role to create a brand.
          </p>
        ) : (
          <form
            onSubmit={createBrand}
            className="mt-7 max-w-2xl rounded-2xl border border-slate-200 bg-white p-6"
          >
            <ol aria-label="Brand setup progress" className="mb-6 flex gap-3 text-sm">
              <li
                aria-current={step === 1 ? "step" : undefined}
                className={step === 1 ? "font-semibold text-indigo-700" : "text-slate-500"}
              >
                1. Basics
              </li>
              <li aria-hidden="true" className="text-slate-400">→</li>
              <li
                aria-current={step === 2 ? "step" : undefined}
                className={step === 2 ? "font-semibold text-indigo-700" : "text-slate-500"}
              >
                2. Brand identity
              </li>
            </ol>
            {error && (
              <p role="alert" className="mb-5 rounded-lg bg-red-50 p-3 text-sm text-red-800">
                {error}
              </p>
            )}
            {step === 1 ? (
              <section aria-label="Brand basics" className="space-y-4">
                <h2 className="text-lg font-semibold">Brand basics</h2>
                <label className="block text-sm font-medium">
                  Brand name
                  <input
                    className={inputClass}
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    required
                    minLength={2}
                    maxLength={120}
                  />
                </label>
                <label className="block text-sm font-medium">
                  URL slug (optional)
                  <input
                    className={inputClass}
                    value={slug}
                    onChange={(event) =>
                      setSlug(
                        event.target.value
                          .toLowerCase()
                          .replace(/[^a-z0-9]+/g, "-")
                          .replace(/^-|-$/g, ""),
                      )
                    }
                    minLength={2}
                    maxLength={140}
                    pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
                    placeholder="my-brand"
                  />
                </label>
                <label className="block text-sm font-medium">
                  Industry
                  <input
                    className={inputClass}
                    value={industry}
                    onChange={(event) => setIndustry(event.target.value)}
                    maxLength={120}
                  />
                </label>
                <label className="block text-sm font-medium">
                  Business type
                  <input
                    className={inputClass}
                    value={businessType}
                    onChange={(event) => setBusinessType(event.target.value)}
                    maxLength={120}
                  />
                </label>
                <button
                  type="button"
                  onClick={() => setStep(2)}
                  disabled={name.trim().length < 2}
                  className="rounded-xl bg-indigo-600 px-4 py-2.5 font-semibold text-white disabled:opacity-50"
                >
                  Continue
                </button>
              </section>
            ) : (
              <section aria-label="Brand identity" className="space-y-4">
                <h2 className="text-lg font-semibold">Brand identity</h2>
                <label className="block text-sm font-medium">
                  Description
                  <textarea
                    className={inputClass}
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    maxLength={5000}
                    rows={4}
                  />
                </label>
                <label className="block text-sm font-medium">
                  Website URL
                  <input
                    className={inputClass}
                    type="url"
                    value={website}
                    onChange={(event) => setWebsite(event.target.value)}
                    placeholder="https://example.com"
                  />
                </label>
                <label className="block text-sm font-medium">
                  Logo URL
                  <input
                    className={inputClass}
                    type="url"
                    value={logoUrl}
                    onChange={(event) => setLogoUrl(event.target.value)}
                    placeholder="https://example.com/logo.png"
                  />
                </label>
                <div className="grid gap-4 sm:grid-cols-2">
                  <label className="block text-sm font-medium">
                    Primary color
                    <input
                      className="mt-1 block h-11 w-full rounded-xl border border-slate-300 p-1"
                      type="color"
                      value={primaryColor}
                      onChange={(event) => setPrimaryColor(event.target.value)}
                    />
                  </label>
                  <label className="block text-sm font-medium">
                    Secondary color
                    <input
                      className="mt-1 block h-11 w-full rounded-xl border border-slate-300 p-1"
                      type="color"
                      value={secondaryColor}
                      onChange={(event) => setSecondaryColor(event.target.value)}
                    />
                  </label>
                </div>
                <div className="flex flex-wrap gap-3">
                  <button
                    type="button"
                    onClick={() => setStep(1)}
                    className="rounded-xl border border-slate-300 px-4 py-2.5 font-semibold"
                  >
                    Back
                  </button>
                  <button
                    disabled={saving}
                    className="rounded-xl bg-indigo-600 px-4 py-2.5 font-semibold text-white disabled:opacity-60"
                  >
                    {saving ? "Creating…" : "Create brand"}
                  </button>
                </div>
              </section>
            )}
          </form>
        )}
      </AppShell>
    </ProtectedPage>
  );
}

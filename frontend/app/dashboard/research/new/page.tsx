"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/auth-provider";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { ApiError, apiRequest } from "@/lib/api";
import type { Brand } from "@/lib/brand-types";

const CATEGORY_OPTIONS = [
  "General topic research",
  "Industry research",
  "Competitor research",
  "Audience research",
  "Trending topics",
  "Content opportunity research",
  "Product and service research",
  "Brand-related research",
  "News and current events",
  "Keyword and hashtag research",
  "Custom category",
];

export default function NewResearchPage() {
  const router = useRouter();
  const { selectedWorkspace } = useAuth();
  const [brands, setBrands] = useState<Brand[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    title: "",
    research_question: "",
    brand_id: "",
    category: CATEGORY_OPTIONS[0],
    target_audience: "",
    geographic_scope: "",
    language: "en",
    recency_preference: "30 days",
    research_depth: "standard",
    optional_keywords: "",
  });

  const loadBrands = useCallback(async () => {
    if (!selectedWorkspace) {
      setBrands([]);
      return;
    }
    try {
      const workspaceBrands = await apiRequest<Brand[]>(
        `/workspaces/${selectedWorkspace.id}/brands`,
      );
      setBrands(workspaceBrands);
      if (workspaceBrands[0] && !form.brand_id) {
        setForm((current) => ({ ...current, brand_id: workspaceBrands[0].id }));
      }
    } catch (loadError) {
      setError(
        loadError instanceof ApiError
          ? loadError.message
          : "The workspace brands could not be loaded.",
      );
    }
  }, [selectedWorkspace, form.brand_id]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadBrands(), 0);
    return () => window.clearTimeout(timer);
  }, [loadBrands]);

  const canSubmit = useMemo(() => {
    return (
      selectedWorkspace &&
      form.title.trim().length >= 2 &&
      form.research_question.trim().length >= 2
    );
  }, [form.research_question, form.title, selectedWorkspace]);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedWorkspace || !canSubmit) {
      setError("Choose a workspace and provide a title and research question.");
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const payload = {
        workspace_id: selectedWorkspace.id,
        brand_id: form.brand_id || null,
        title: form.title,
        research_question: form.research_question,
        category: form.category,
        target_audience: form.target_audience || null,
        geographic_scope: form.geographic_scope || null,
        language: form.language,
        recency_preference: form.recency_preference || null,
        research_depth: form.research_depth,
        optional_keywords: form.optional_keywords
          .split(",")
          .map((keyword) => keyword.trim())
          .filter(Boolean),
      };

      const project = await apiRequest<{ id: string }>("/research", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      router.push(`/dashboard/research/${project.id}`);
    } catch (submitError) {
      setError(
        submitError instanceof ApiError
          ? submitError.message
          : "The research project could not be created.",
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <ProtectedPage>
      <AppShell>
        <div className="mb-6 flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-indigo-700">
              New project
            </p>
            <h1 className="mt-2 text-3xl font-bold tracking-tight">Research brief</h1>
          </div>
          <Link href="/dashboard/research" className="text-sm font-semibold text-indigo-700">
            Back to research
          </Link>
        </div>

        {!selectedWorkspace ? (
          <p className="rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">
            Select a workspace before starting research.
          </p>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-5 rounded-2xl border border-slate-200 bg-white p-6">
            {error && (
              <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">
                {error}
              </p>
            )}

            <div className="grid gap-5 md:grid-cols-2">
              <label className="space-y-2 text-sm font-medium text-slate-700">
                Research title
                <input
                  value={form.title}
                  onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))}
                  className="w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-500"
                  placeholder="AI-powered growth strategy for our brand"
                  required
                />
              </label>

              <label className="space-y-2 text-sm font-medium text-slate-700">
                Brand
                <select
                  value={form.brand_id}
                  onChange={(event) => setForm((current) => ({ ...current, brand_id: event.target.value }))}
                  className="w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-500"
                >
                  <option value="">No brand selected</option>
                  {brands.map((brand) => (
                    <option key={brand.id} value={brand.id}>
                      {brand.name}
                    </option>
                  ))}
                </select>
              </label>

              <label className="space-y-2 text-sm font-medium text-slate-700 md:col-span-2">
                Research question
                <textarea
                  value={form.research_question}
                  onChange={(event) => setForm((current) => ({ ...current, research_question: event.target.value }))}
                  className="min-h-28 w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-500"
                  placeholder="What trends, audience signals, and opportunities matter for our category right now?"
                  required
                />
              </label>

              <label className="space-y-2 text-sm font-medium text-slate-700">
                Category
                <select
                  value={form.category}
                  onChange={(event) => setForm((current) => ({ ...current, category: event.target.value }))}
                  className="w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-500"
                >
                  {CATEGORY_OPTIONS.map((category) => (
                    <option key={category} value={category}>
                      {category}
                    </option>
                  ))}
                </select>
              </label>

              <label className="space-y-2 text-sm font-medium text-slate-700">
                Target audience
                <input
                  value={form.target_audience}
                  onChange={(event) => setForm((current) => ({ ...current, target_audience: event.target.value }))}
                  className="w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-500"
                  placeholder="Small business owners in the U.S."
                />
              </label>

              <label className="space-y-2 text-sm font-medium text-slate-700">
                Geographic scope
                <input
                  value={form.geographic_scope}
                  onChange={(event) => setForm((current) => ({ ...current, geographic_scope: event.target.value }))}
                  className="w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-500"
                  placeholder="United States"
                />
              </label>

              <label className="space-y-2 text-sm font-medium text-slate-700">
                Language
                <input
                  value={form.language}
                  onChange={(event) => setForm((current) => ({ ...current, language: event.target.value }))}
                  className="w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-500"
                />
              </label>

              <label className="space-y-2 text-sm font-medium text-slate-700">
                Recency preference
                <input
                  value={form.recency_preference}
                  onChange={(event) => setForm((current) => ({ ...current, recency_preference: event.target.value }))}
                  className="w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-500"
                  placeholder="Last 30 days"
                />
              </label>

              <label className="space-y-2 text-sm font-medium text-slate-700">
                Research depth
                <select
                  value={form.research_depth}
                  onChange={(event) => setForm((current) => ({ ...current, research_depth: event.target.value }))}
                  className="w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-500"
                >
                  <option value="quick">Quick</option>
                  <option value="standard">Standard</option>
                  <option value="deep">Deep</option>
                  <option value="comprehensive">Comprehensive</option>
                </select>
              </label>

              <label className="space-y-2 text-sm font-medium text-slate-700 md:col-span-2">
                Optional keywords
                <input
                  value={form.optional_keywords}
                  onChange={(event) => setForm((current) => ({ ...current, optional_keywords: event.target.value }))}
                  className="w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-500"
                  placeholder="AI, ecommerce, marketing automation"
                />
              </label>
            </div>

            <div className="flex justify-end">
              <button
                type="submit"
                disabled={!canSubmit || saving}
                className="rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300"
              >
                {saving ? "Creating…" : "Create research project"}
              </button>
            </div>
          </form>
        )}
      </AppShell>
    </ProtectedPage>
  );
}

"use client";

import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/auth-provider";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { ApiError, apiRequest } from "@/lib/api";

const PLATFORM_OPTIONS = ["facebook", "instagram"];
const CONTENT_TYPES = [
  "text_post",
  "image_post",
  "carousel",
  "reel",
  "story",
  "promotional",
  "educational",
  "announcement",
  "testimonial",
  "product_promotion",
  "engagement",
];

export default function NewContentProjectPage() {
  const router = useRouter();
  const { selectedWorkspace } = useAuth();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    title: "",
    topic: "",
    objective: "",
    content_type: CONTENT_TYPES[0],
    selected_platforms: ["instagram"],
    content_pillar: "",
    target_audience: "",
    preferred_tone: "confident",
    language: "en",
    keywords: "",
    required_phrases: "",
    prohibited_phrases: "",
    cta_requirements: "",
    hashtag_preferences: "",
    emoji_preferences: "",
    desired_length: "medium",
  });

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedWorkspace) {
      setError("Select a workspace before creating a content project.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload = {
        workspace_id: selectedWorkspace.id,
        title: form.title,
        topic: form.topic || null,
        objective: form.objective || null,
        selected_platforms: form.selected_platforms,
        content_type: form.content_type,
        content_pillar: form.content_pillar || null,
        target_audience: form.target_audience || null,
        preferred_tone: form.preferred_tone || null,
        language: form.language,
        keywords: form.keywords
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean),
        required_phrases: form.required_phrases
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean),
        prohibited_phrases: form.prohibited_phrases
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean),
        cta_requirements: form.cta_requirements || null,
        hashtag_preferences: form.hashtag_preferences || null,
        emoji_preferences: form.emoji_preferences || null,
        desired_length: form.desired_length || null,
      };
      const project = await apiRequest<{ id: string }>("/content/projects", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      router.push(`/dashboard/content/${project.id}`);
    } catch (submitError) {
      setError(
        submitError instanceof ApiError
          ? submitError.message
          : "The content project could not be created.",
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
              Content studio
            </p>
            <h1 className="mt-2 text-3xl font-bold tracking-tight">New content project</h1>
          </div>
          <Link href="/dashboard/content" className="text-sm font-semibold text-indigo-700">
            Back to projects
          </Link>
        </div>

        {!selectedWorkspace ? (
          <p className="rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">
            Select a workspace to start a content project.
          </p>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-5 rounded-2xl border border-slate-200 bg-white p-6">
            {error && (
              <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">
                {error}
              </p>
            )}

            <div className="grid gap-5 md:grid-cols-2">
              <label className="space-y-2 text-sm font-medium text-slate-700 md:col-span-2">
                Project title
                <input
                  value={form.title}
                  onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))}
                  className="w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-500"
                  required
                />
              </label>

              <label className="space-y-2 text-sm font-medium text-slate-700 md:col-span-2">
                Topic
                <textarea
                  value={form.topic}
                  onChange={(event) => setForm((current) => ({ ...current, topic: event.target.value }))}
                  className="min-h-24 w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-500"
                />
              </label>

              <label className="space-y-2 text-sm font-medium text-slate-700 md:col-span-2">
                Objective
                <textarea
                  value={form.objective}
                  onChange={(event) => setForm((current) => ({ ...current, objective: event.target.value }))}
                  className="min-h-20 w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-500"
                />
              </label>

              <label className="space-y-2 text-sm font-medium text-slate-700">
                Content type
                <select
                  value={form.content_type}
                  onChange={(event) => setForm((current) => ({ ...current, content_type: event.target.value }))}
                  className="w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-500"
                >
                  {CONTENT_TYPES.map((type) => (
                    <option key={type} value={type}>{type}</option>
                  ))}
                </select>
              </label>

              <label className="space-y-2 text-sm font-medium text-slate-700">
                Content pillar
                <input
                  value={form.content_pillar}
                  onChange={(event) => setForm((current) => ({ ...current, content_pillar: event.target.value }))}
                  className="w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-500"
                />
              </label>

              <label className="space-y-2 text-sm font-medium text-slate-700">
                Target audience
                <input
                  value={form.target_audience}
                  onChange={(event) => setForm((current) => ({ ...current, target_audience: event.target.value }))}
                  className="w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-500"
                />
              </label>

              <label className="space-y-2 text-sm font-medium text-slate-700">
                Preferred tone
                <input
                  value={form.preferred_tone}
                  onChange={(event) => setForm((current) => ({ ...current, preferred_tone: event.target.value }))}
                  className="w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-500"
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

              <label className="space-y-2 text-sm font-medium text-slate-700 md:col-span-2">
                Selected platforms
                <div className="flex flex-wrap gap-3">
                  {PLATFORM_OPTIONS.map((platform) => (
                    <label key={platform} className="flex items-center gap-2 rounded-xl border border-slate-300 px-3 py-2 text-sm">
                      <input
                        type="checkbox"
                        checked={form.selected_platforms.includes(platform)}
                        onChange={(event) => {
                          setForm((current) => {
                            const selected = new Set(current.selected_platforms);
                            if (event.target.checked) selected.add(platform);
                            else selected.delete(platform);
                            return { ...current, selected_platforms: Array.from(selected) };
                          });
                        }}
                      />
                      {platform}
                    </label>
                  ))}
                </div>
              </label>

              <label className="space-y-2 text-sm font-medium text-slate-700 md:col-span-2">
                Keywords (comma-separated)
                <input
                  value={form.keywords}
                  onChange={(event) => setForm((current) => ({ ...current, keywords: event.target.value }))}
                  className="w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-500"
                />
              </label>

              <label className="space-y-2 text-sm font-medium text-slate-700 md:col-span-2">
                Required phrases (comma-separated)
                <input
                  value={form.required_phrases}
                  onChange={(event) => setForm((current) => ({ ...current, required_phrases: event.target.value }))}
                  className="w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-500"
                />
              </label>

              <label className="space-y-2 text-sm font-medium text-slate-700 md:col-span-2">
                Prohibited phrases (comma-separated)
                <input
                  value={form.prohibited_phrases}
                  onChange={(event) => setForm((current) => ({ ...current, prohibited_phrases: event.target.value }))}
                  className="w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-500"
                />
              </label>

              <label className="space-y-2 text-sm font-medium text-slate-700 md:col-span-2">
                CTA requirements
                <input
                  value={form.cta_requirements}
                  onChange={(event) => setForm((current) => ({ ...current, cta_requirements: event.target.value }))}
                  className="w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-500"
                />
              </label>

              <label className="space-y-2 text-sm font-medium text-slate-700">
                Hashtag preferences
                <input
                  value={form.hashtag_preferences}
                  onChange={(event) => setForm((current) => ({ ...current, hashtag_preferences: event.target.value }))}
                  className="w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-500"
                />
              </label>

              <label className="space-y-2 text-sm font-medium text-slate-700">
                Emoji preferences
                <input
                  value={form.emoji_preferences}
                  onChange={(event) => setForm((current) => ({ ...current, emoji_preferences: event.target.value }))}
                  className="w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-500"
                />
              </label>

              <label className="space-y-2 text-sm font-medium text-slate-700">
                Desired length
                <input
                  value={form.desired_length}
                  onChange={(event) => setForm((current) => ({ ...current, desired_length: event.target.value }))}
                  className="w-full rounded-xl border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-500"
                />
              </label>
            </div>

            <button
              type="submit"
              disabled={saving || !selectedWorkspace || !form.title.trim()}
              className="rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              {saving ? "Creating…" : "Create content project"}
            </button>
          </form>
        )}
      </AppShell>
    </ProtectedPage>
  );
}

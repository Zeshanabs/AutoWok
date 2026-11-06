"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { ApiError, apiRequest } from "@/lib/api";
import type { ResearchProject } from "@/lib/research-types";

export default function ResearchDashboardPage() {
  const { selectedWorkspace } = useAuth();
  const [projects, setProjects] = useState<ResearchProject[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadProjects = useCallback(async () => {
    if (!selectedWorkspace) {
      setProjects([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const research = await apiRequest<ResearchProject[]>(
        `/research?workspace_id=${encodeURIComponent(selectedWorkspace.id)}`,
      );
      setProjects(research);
      setError(null);
    } catch (loadError) {
      setError(
        loadError instanceof ApiError
          ? loadError.message
          : "Research projects could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }, [selectedWorkspace]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadProjects(), 0);
    return () => window.clearTimeout(timer);
  }, [loadProjects]);

  return (
    <ProtectedPage>
      <AppShell>
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-indigo-700">
              Research workspace
            </p>
            <h1 className="mt-2 text-3xl font-bold tracking-tight">Research projects</h1>
          </div>
          <Link
            href="/dashboard/research/new"
            className="rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700"
          >
            New research
          </Link>
        </div>

        {!selectedWorkspace ? (
          <p className="mt-6 rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">
            Select a workspace to view research projects.
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
                <p>Loading research projects…</p>
              ) : projects.length === 0 ? (
                <p className="rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">
                  No research projects yet for this workspace.
                </p>
              ) : (
                projects.map((project) => (
                  <article
                    key={project.id}
                    className="flex flex-col gap-4 rounded-2xl border border-slate-200 bg-white p-5 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div>
                      <h2 className="font-semibold">{project.title}</h2>
                      <p className="mt-1 text-sm text-slate-600">{project.category}</p>
                      <p className="mt-1 text-sm text-slate-500">
                        Status: {project.status} · Created {new Date(project.created_at).toLocaleDateString()}
                      </p>
                    </div>
                    <Link
                      href={`/dashboard/research/${project.id}`}
                      className="rounded-lg bg-slate-900 px-3 py-2 text-center text-sm font-medium text-white hover:bg-slate-800"
                    >
                      Open report
                    </Link>
                  </article>
                ))
              )}
            </section>
          </>
        )}
      </AppShell>
    </ProtectedPage>
  );
}

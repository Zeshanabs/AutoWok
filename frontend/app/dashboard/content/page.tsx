"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { ApiError, apiRequest } from "@/lib/api";
import type { ContentProject } from "@/lib/content-types";

export default function ContentStudioDashboardPage() {
  const { selectedWorkspace } = useAuth();
  const [projects, setProjects] = useState<ContentProject[]>([]);
  const [loadedWorkspaceId, setLoadedWorkspaceId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const workspaceId = selectedWorkspace?.id;

  useEffect(() => {
    if (!workspaceId) return;
    let active = true;
    apiRequest<ContentProject[]>(`/content/projects?workspace_id=${encodeURIComponent(workspaceId)}`)
      .then((data) => {
        if (active) {
          setProjects(data);
          setError(null);
          setLoadedWorkspaceId(workspaceId);
        }
      })
      .catch((loadError) => {
        if (active) {
          setError(
            loadError instanceof ApiError
              ? loadError.message
              : "Content projects could not be loaded.",
          );
          setLoadedWorkspaceId(workspaceId);
        }
      })
    return () => {
      active = false;
    };
  }, [workspaceId]);
  const loading = Boolean(workspaceId) && loadedWorkspaceId !== workspaceId;

  return (
    <ProtectedPage>
      <AppShell>
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-indigo-700">
              Content studio
            </p>
            <h1 className="mt-2 text-3xl font-bold tracking-tight">Content projects</h1>
          </div>
          <Link
            href="/dashboard/content/new"
            className="rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700"
          >
            New content project
          </Link>
        </div>

        {!selectedWorkspace ? (
          <p className="mt-6 rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">
            Select a workspace to view content projects.
          </p>
        ) : (
          <div className="mt-6 space-y-3">
            {error && (
              <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">
                {error}
              </p>
            )}

            {loading ? (
              <p>Loading content projects…</p>
            ) : projects.length === 0 ? (
              <p className="rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">
                No content projects yet for this workspace.
              </p>
            ) : (
              projects.map((project) => (
                <article
                  key={project.id}
                  className="rounded-2xl border border-slate-200 bg-white p-5"
                >
                  <Link
                    href={`/dashboard/content/${project.id}`}
                    className="block rounded-2xl focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  >
                    <div className="flex items-center justify-between gap-4">
                      <div>
                        <h2 className="font-semibold">{project.title}</h2>
                        <p className="mt-1 text-sm text-slate-600">{project.content_type}</p>
                      </div>
                      <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700">
                        {project.status.replaceAll("_", " ")}
                      </span>
                    </div>
                    <p className="mt-3 text-sm text-slate-500">
                      Platforms: {project.selected_platforms.join(", ")}
                    </p>
                  </Link>
                </article>
              ))
            )}
          </div>
        )}
      </AppShell>
    </ProtectedPage>
  );
}

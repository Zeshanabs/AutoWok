"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";

import { useAuth } from "@/components/auth-provider";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { apiRequest, ApiError } from "@/lib/api";

export default function WorkspacesPage() {
  const { workspaces, selectedWorkspace, selectWorkspace, refreshUser } =
    useAuth();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  async function select(workspaceId: string) {
    setError(null);
    try {
      await selectWorkspace(workspaceId);
    } catch (selectError) {
      setError(
        selectError instanceof ApiError
          ? selectError.message
          : "Workspace could not be selected.",
      );
    }
  }

  async function createWorkspace(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSuccess(null);
    setBusy(true);
    try {
      const workspace = await apiRequest<{ id: string; name: string }>(
        "/workspaces",
        { method: "POST", body: JSON.stringify({ name }) },
      );
      await refreshUser();
      await selectWorkspace(workspace.id);
      setName("");
      setSuccess("Workspace created.");
    } catch (createError) {
      setError(
        createError instanceof ApiError
          ? createError.message
          : "Workspace could not be created.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <ProtectedPage>
      <AppShell>
        <h1 className="text-3xl font-bold tracking-tight">Workspaces</h1>
        <p className="mt-2 text-slate-600">
          Choose a workspace or create one for your team.
        </p>
        <section className="mt-7 space-y-3">
          {error && (
            <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">
              {error}
            </p>
          )}
          {workspaces.length === 0 ? (
            <p className="rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">
              No workspaces yet.
            </p>
          ) : (
            workspaces.map((workspace) => (
              <article
                key={workspace.id}
                className="flex flex-col gap-4 rounded-2xl border border-slate-200 bg-white p-5 sm:flex-row sm:items-center sm:justify-between"
              >
                <div>
                  <h2 className="font-semibold">{workspace.name}</h2>
                  <p className="mt-1 text-sm text-slate-500">
                    Role: {workspace.role}
                    {selectedWorkspace?.id === workspace.id
                      ? " · Selected"
                      : ""}
                  </p>
                </div>
                <div className="flex gap-3 text-sm">
                  <button
                    onClick={() => void select(workspace.id)}
                    className="rounded-lg border border-slate-300 px-3 py-2 font-medium hover:bg-slate-50"
                  >
                    Select
                  </button>
                  <Link
                    href={`/workspaces/${workspace.id}`}
                    className="rounded-lg bg-slate-900 px-3 py-2 font-medium text-white hover:bg-slate-800"
                  >
                    Details
                  </Link>
                </div>
              </article>
            ))
          )}
        </section>

        <form
          onSubmit={createWorkspace}
          className="mt-9 max-w-xl rounded-2xl border border-slate-200 bg-white p-6"
        >
          <h2 className="text-lg font-semibold">Create a workspace</h2>
          <label className="mt-4 block text-sm font-medium">
            Workspace name
            <input
              className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2.5"
              value={name}
              onChange={(event) => setName(event.target.value)}
              minLength={2}
              maxLength={100}
              required
            />
          </label>
          {error && (
            <p role="alert" className="mt-3 text-sm text-red-700">
              {error}
            </p>
          )}
          {success && (
            <p role="status" className="mt-3 text-sm text-emerald-700">
              {success}
            </p>
          )}
          <button
            disabled={busy}
            className="mt-4 rounded-xl bg-indigo-600 px-4 py-2.5 font-semibold text-white disabled:opacity-60"
          >
            {busy ? "Creating…" : "Create workspace"}
          </button>
        </form>
      </AppShell>
    </ProtectedPage>
  );
}

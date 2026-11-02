"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useParams } from "next/navigation";

import { useAuth } from "@/components/auth-provider";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { apiRequest, ApiError } from "@/lib/api";
import type { WorkspaceMember } from "@/lib/auth-types";

type WorkspaceInfo = {
  id: string;
  name: string;
  slug: string;
  owner_id: string;
};

function manageableRole(value: string): "ADMIN" | "MEMBER" | null {
  return value === "ADMIN" || value === "MEMBER" ? value : null;
}

export default function WorkspaceDetailsPage() {
  const params = useParams<{ workspaceId: string }>();
  const workspaceId = params.workspaceId;
  const { workspaces, selectWorkspace } = useAuth();
  const role = workspaces.find((workspace) => workspace.id === workspaceId)?.role;
  const canManage = role === "OWNER" || role === "ADMIN";
  const [workspace, setWorkspace] = useState<WorkspaceInfo | null>(null);
  const [editedName, setEditedName] = useState("");
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [email, setEmail] = useState("");
  const [newRole, setNewRole] = useState<"ADMIN" | "MEMBER">("MEMBER");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const loadWorkspace = useCallback(async (showLoading = false) => {
    if (showLoading) {
      setLoading(true);
    }
    try {
      const [details, memberList] = await Promise.all([
        apiRequest<WorkspaceInfo>(`/workspaces/${workspaceId}`),
        apiRequest<WorkspaceMember[]>(`/workspaces/${workspaceId}/members`),
      ]);
      setWorkspace(details);
      setEditedName(details.name);
      setMembers(memberList);
      setError(null);
    } catch (loadError) {
      setError(
        loadError instanceof ApiError
          ? loadError.message
          : "Workspace details could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadWorkspace(), 0);
    return () => window.clearTimeout(timer);
  }, [loadWorkspace]);

  async function addMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSuccess(null);
    try {
      await apiRequest(`/workspaces/${workspaceId}/members`, {
        method: "POST",
        body: JSON.stringify({ email, role: newRole }),
      });
      setEmail("");
      setSuccess("Member added.");
      await loadWorkspace(true);
    } catch (changeError) {
      setError(
        changeError instanceof ApiError
          ? changeError.message
          : "Member could not be added.",
      );
    }
  }

  async function updateWorkspace(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSuccess(null);
    try {
      await apiRequest(`/workspaces/${workspaceId}`, {
        method: "PATCH",
        body: JSON.stringify({ name: editedName }),
      });
      setSuccess("Workspace updated.");
      await loadWorkspace(true);
    } catch (updateError) {
      setError(
        updateError instanceof ApiError
          ? updateError.message
          : "Workspace could not be updated.",
      );
    }
  }

  async function changeRole(userId: string, memberRole: "ADMIN" | "MEMBER") {
    setError(null);
    setSuccess(null);
    try {
      await apiRequest(
        `/workspaces/${workspaceId}/members/${userId}/role`,
        { method: "PATCH", body: JSON.stringify({ role: memberRole }) },
      );
      setSuccess("Member role updated.");
      await loadWorkspace(true);
    } catch (changeError) {
      setError(
        changeError instanceof ApiError
          ? changeError.message
          : "Member role could not be updated.",
      );
    }
  }

  async function removeMember(userId: string) {
    setError(null);
    setSuccess(null);
    try {
      await apiRequest(`/workspaces/${workspaceId}/members/${userId}`, {
        method: "DELETE",
      });
      setSuccess("Member removed.");
      await loadWorkspace(true);
    } catch (changeError) {
      setError(
        changeError instanceof ApiError
          ? changeError.message
          : "Member could not be removed.",
      );
    }
  }

  return (
    <ProtectedPage>
      <AppShell>
        {loading ? (
          <p>Loading workspace…</p>
        ) : error && !workspace ? (
          <p role="alert" className="rounded-xl bg-red-50 p-4 text-red-800">
            {error}
          </p>
        ) : workspace ? (
          <>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="text-sm text-indigo-700">{workspace.slug}</p>
                <h1 className="mt-1 text-3xl font-bold tracking-tight">
                  {workspace.name}
                </h1>
                <p className="mt-2 text-sm text-slate-600">
                  Your role: {role ?? "MEMBER"}
                </p>
              </div>
              <button
                onClick={() =>
                  void selectWorkspace(workspaceId).catch((selectError: unknown) =>
                    setError(
                      selectError instanceof Error
                        ? selectError.message
                        : "Workspace could not be selected.",
                    ),
                  )
                }
                className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-semibold"
              >
                Select workspace
              </button>
            </div>
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
            <section className="mt-8 rounded-2xl border border-slate-200 bg-white p-6">
              <h2 className="text-lg font-semibold">Members</h2>
              <ul className="mt-4 divide-y divide-slate-100">
                {members.map((member) => (
                  <li
                    key={member.user_id}
                    className="flex flex-wrap items-center justify-between gap-4 py-4"
                  >
                    <div>
                      <p className="font-medium">{member.full_name}</p>
                      <p className="text-sm text-slate-500">{member.email}</p>
                    </div>
                    <div className="flex items-center gap-3">
                      {member.role === "OWNER" ? (
                        <span className="text-sm font-medium">OWNER</span>
                      ) : canManage ? (
                        <>
                          <select
                            aria-label={`Role for ${member.full_name}`}
                            value={member.role}
                            onChange={(event) => {
                              const role = manageableRole(event.target.value);
                              if (role) {
                                void changeRole(member.user_id, role);
                              }
                            }}
                            className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
                          >
                            <option value="MEMBER">MEMBER</option>
                            <option value="ADMIN">ADMIN</option>
                          </select>
                          <button
                            onClick={() => void removeMember(member.user_id)}
                            className="text-sm font-medium text-red-700"
                          >
                            Remove
                          </button>
                        </>
                      ) : (
                        <span className="text-sm text-slate-600">
                          {member.role}
                        </span>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </section>
            {canManage && (
              <form
                onSubmit={updateWorkspace}
                className="mt-6 max-w-xl rounded-2xl border border-slate-200 bg-white p-6"
              >
                <h2 className="font-semibold">Workspace settings</h2>
                <label className="mt-4 block text-sm font-medium">
                  Workspace name
                  <input
                    value={editedName}
                    onChange={(event) => setEditedName(event.target.value)}
                    minLength={2}
                    maxLength={100}
                    required
                    className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2"
                  />
                </label>
                <button className="mt-4 rounded-xl bg-slate-900 px-4 py-2 font-semibold text-white">
                  Save changes
                </button>
              </form>
            )}
            {canManage && (
              <form
                onSubmit={addMember}
                className="mt-6 max-w-2xl rounded-2xl border border-slate-200 bg-white p-6"
              >
                <h2 className="font-semibold">Add a registered user</h2>
                <p className="mt-1 text-sm text-slate-500">
                  Invitations by email are not available yet.
                </p>
                <div className="mt-4 flex flex-col gap-3 sm:flex-row">
                  <input
                    type="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    placeholder="member@example.com"
                    required
                    className="min-w-0 flex-1 rounded-xl border border-slate-300 px-3 py-2"
                  />
                  <select
                    value={newRole}
                    onChange={(event) => {
                      const role = manageableRole(event.target.value);
                      if (role) {
                        setNewRole(role);
                      }
                    }}
                    className="rounded-xl border border-slate-300 px-3 py-2"
                  >
                    <option value="MEMBER">MEMBER</option>
                    <option value="ADMIN">ADMIN</option>
                  </select>
                  <button className="rounded-xl bg-indigo-600 px-4 py-2 font-semibold text-white">
                    Add member
                  </button>
                </div>
              </form>
            )}
          </>
        ) : null}
      </AppShell>
    </ProtectedPage>
  );
}

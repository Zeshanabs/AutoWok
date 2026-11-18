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

type Invitation = {
  id: string;
  email: string;
  role: string;
  status: string;
  email_sent: boolean;
  expires_at: string;
};

type CreatedInvitation = Invitation & { invite_url: string; email_error: string | null };

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
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [shareLink, setShareLink] = useState<{ email: string; url: string; reason: string | null } | null>(null);
  const [copied, setCopied] = useState(false);

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
      // Pending invitations are visible to admins only; members simply see none.
      setInvitations(
        await apiRequest<Invitation[]>(`/workspaces/${workspaceId}/invitations`).catch(() => []),
      );
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

  async function inviteByEmail() {
    const invitedEmail = email.trim();
    try {
      const created = await apiRequest<CreatedInvitation>(`/workspaces/${workspaceId}/invitations`, {
        method: "POST",
        body: JSON.stringify({ email: invitedEmail, role: newRole }),
      });
      setEmail("");
      if (created.email_sent) {
        setSuccess(`Invitation emailed to ${created.email}. They join when they open the link and sign in with that address.`);
      } else {
        setShareLink({ email: created.email, url: created.invite_url, reason: created.email_error });
      }
      await loadWorkspace();
    } catch (inviteError) {
      setError(inviteError instanceof ApiError ? inviteError.message : "The invitation could not be created.");
    }
  }

  async function revokeInvitation(invitation: Invitation) {
    setError(null);
    setSuccess(null);
    try {
      await apiRequest(`/workspaces/${workspaceId}/invitations/${invitation.id}`, { method: "DELETE" });
      setSuccess(`Invitation for ${invitation.email} cancelled.`);
      await loadWorkspace();
    } catch (revokeError) {
      setError(revokeError instanceof ApiError ? revokeError.message : "The invitation could not be cancelled.");
    }
  }

  async function addMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSuccess(null);
    setShareLink(null);
    setCopied(false);
    try {
      await apiRequest(`/workspaces/${workspaceId}/members`, {
        method: "POST",
        body: JSON.stringify({ email, role: newRole }),
      });
      setEmail("");
      setSuccess("Member added.");
      await loadWorkspace(true);
    } catch (changeError) {
      if (changeError instanceof ApiError && changeError.status === 404) {
        // No account uses this address yet: send an invitation instead.
        await inviteByEmail();
        return;
      }
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
          <p role="status">Loading workspace…</p>
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
                            <option value="MEMBER">Member</option>
                            <option value="ADMIN">Admin</option>
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
                <h2 className="font-semibold">Add or invite a member</h2>
                <p className="mt-1 text-sm text-slate-500">
                  Someone who already has an Autowok account is added straight away. Anyone else gets an invitation email with a link to join.
                </p>
                <div className="mt-4 flex flex-col gap-3 sm:flex-row">
                  <input
                    type="email"
                    aria-label="Member email"
                    autoComplete="off"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    placeholder="member@example.com"
                    required
                    className="min-w-0 flex-1 rounded-xl border border-slate-300 px-3 py-2"
                  />
                  <select
                    aria-label="Role for the new member"
                    value={newRole}
                    onChange={(event) => {
                      const role = manageableRole(event.target.value);
                      if (role) {
                        setNewRole(role);
                      }
                    }}
                    className="rounded-xl border border-slate-300 px-3 py-2"
                  >
                    <option value="MEMBER">Member</option>
                    <option value="ADMIN">Admin</option>
                  </select>
                  <button className="rounded-xl bg-indigo-600 px-4 py-2 font-semibold text-white">
                    Add or invite
                  </button>
                </div>
              </form>
            )}
            {shareLink && (
              <div role="status" className="mt-5 max-w-2xl rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-900">
                <p className="font-semibold">Invitation created for {shareLink.email}, but the email was not sent.</p>
                {shareLink.reason && <p className="mt-1">{shareLink.reason}</p>}
                <p className="mt-3">Send them this link yourself. It is shown only once and works only for that email address:</p>
                <div className="mt-2 flex flex-col gap-2 sm:flex-row">
                  <input readOnly aria-label="Invitation link" value={shareLink.url} onFocus={(event) => event.target.select()} className="min-w-0 flex-1 rounded-xl border border-amber-300 bg-white px-3 py-2 text-slate-900" />
                  <button
                    type="button"
                    onClick={() => void navigator.clipboard.writeText(shareLink.url).then(() => setCopied(true)).catch(() => setCopied(false))}
                    className="rounded-xl bg-slate-900 px-4 py-2 font-semibold text-white hover:bg-slate-800"
                  >
                    {copied ? "Copied" : "Copy link"}
                  </button>
                </div>
              </div>
            )}
            {canManage && invitations.length > 0 && (
              <section className="mt-6 max-w-2xl rounded-2xl border border-slate-200 bg-white p-6">
                <h2 className="font-semibold">Pending invitations</h2>
                <ul className="mt-3 divide-y divide-slate-100">
                  {invitations.map((invitation) => (
                    <li key={invitation.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                      <div className="min-w-0">
                        <p className="truncate font-medium">{invitation.email}</p>
                        <p className="text-sm text-slate-500">
                          {invitation.role === "ADMIN" ? "Admin" : "Member"}, {invitation.status === "expired" ? "expired" : `expires ${new Date(invitation.expires_at).toLocaleDateString()}`}
                          {invitation.email_sent ? ", email sent" : ", email not sent"}
                        </p>
                      </div>
                      <button type="button" onClick={() => void revokeInvitation(invitation)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-50">
                        Cancel invitation
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        ) : null}
      </AppShell>
    </ProtectedPage>
  );
}

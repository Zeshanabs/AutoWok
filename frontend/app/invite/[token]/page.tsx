"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { AuthLayout } from "@/components/auth-layout";
import { useAuth } from "@/components/auth-provider";
import { ApiError, apiRequest } from "@/lib/api";
import { forgetInvite, rememberInvite } from "@/lib/pending-invite";

type Preview = { workspace_name: string; email: string; role: string; expires_at: string };

const primaryButton = "inline-flex w-full items-center justify-center rounded-xl bg-indigo-600 px-4 py-3 font-semibold text-white hover:bg-indigo-700 disabled:opacity-60";
const secondaryButton = "inline-flex w-full items-center justify-center rounded-xl border border-slate-300 bg-white px-4 py-3 font-semibold text-slate-800 hover:border-slate-400";

export default function InvitationPage() {
  const { token } = useParams<{ token: string }>();
  const { status, user, refreshUser, selectWorkspace, logout } = useAuth();
  const router = useRouter();
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    apiRequest<Preview>(`/invitations/${encodeURIComponent(token)}`)
      .then((data) => {
        if (!active) return;
        setPreview(data);
        rememberInvite(token);
      })
      .catch((loadError: unknown) => {
        if (!active) return;
        forgetInvite();
        setError(loadError instanceof ApiError ? loadError.message : "This invitation could not be loaded.");
      });
    return () => {
      active = false;
    };
  }, [token]);

  async function accept() {
    setBusy(true);
    setError(null);
    try {
      const joined = await apiRequest<{ workspace_id: string }>(`/invitations/${encodeURIComponent(token)}/accept`, { method: "POST" });
      forgetInvite();
      await refreshUser();
      await selectWorkspace(joined.workspace_id).catch(() => undefined);
      router.replace(`/workspaces/${joined.workspace_id}`);
    } catch (acceptError) {
      setError(acceptError instanceof ApiError ? acceptError.message : "The invitation could not be accepted.");
      setBusy(false);
    }
  }

  if (!preview) {
    return (
      <AuthLayout title={error ? "Invitation unavailable" : "Opening invitation"} description={error ? "This link cannot be used." : "One moment…"}>
        {error ? (
          <>
            <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>
            <Link href="/dashboard" className={`${secondaryButton} mt-5`}>Go to Autowok</Link>
          </>
        ) : (
          <p role="status" className="text-sm text-slate-600">Loading the invitation…</p>
        )}
      </AuthLayout>
    );
  }

  const roleText = preview.role === "ADMIN" ? "an admin" : "a member";
  const signedInAs = status === "authenticated" ? user?.email : null;
  const matches = signedInAs?.toLowerCase() === preview.email.toLowerCase();

  return (
    <AuthLayout
      title={`Join ${preview.workspace_name}`}
      description={`You were invited to this Autowok workspace as ${roleText}. The invitation is for ${preview.email}.`}
    >
      {error && <p role="alert" className="mb-5 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      {status === "loading" ? (
        <p role="status" className="text-sm text-slate-600">Checking your session…</p>
      ) : matches ? (
        <button type="button" disabled={busy} onClick={() => void accept()} className={primaryButton}>
          {busy ? "Joining…" : "Join workspace"}
        </button>
      ) : signedInAs ? (
        <>
          <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
            You are signed in as {signedInAs}. Log out, then sign in or create an account with {preview.email}.
          </p>
          <button type="button" onClick={() => void logout().catch(() => undefined)} className={`${secondaryButton} mt-5`}>
            Log out
          </button>
        </>
      ) : (
        <div className="space-y-3">
          <Link href="/register" className={primaryButton}>Create an account</Link>
          <Link href="/login" className={secondaryButton}>I already have an account</Link>
          <p className="text-sm text-slate-600">Use {preview.email}. You will come back here to join the workspace.</p>
        </div>
      )}
    </AuthLayout>
  );
}

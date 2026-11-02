"use client";

import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { apiRequest, ApiError } from "@/lib/api";
import type { SessionInfo } from "@/lib/auth-types";

export default function SecuritySettingsPage() {
  const { logout } = useAuth();
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const loadSessions = useCallback(async (showLoading = false) => {
    if (showLoading) {
      setLoading(true);
    }
    try {
      setSessions(await apiRequest<SessionInfo[]>("/auth/sessions"));
      setError(null);
    } catch (loadError) {
      setError(
        loadError instanceof ApiError
          ? loadError.message
          : "Sessions could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadSessions(), 0);
    return () => window.clearTimeout(timer);
  }, [loadSessions]);

  async function revokeSession(id: string) {
    setError(null);
    setSuccess(null);
    try {
      await apiRequest(`/auth/sessions/${id}`, { method: "DELETE" });
      setSuccess("Session revoked.");
      await loadSessions(true);
    } catch (revokeError) {
      setError(
        revokeError instanceof ApiError
          ? revokeError.message
          : "Session could not be revoked.",
      );
    }
  }

  return (
    <ProtectedPage>
      <AppShell>
        <h1 className="text-3xl font-bold tracking-tight">Security settings</h1>
        <p className="mt-2 text-slate-600">
          Review and revoke active sign-in sessions.
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
          <p className="mt-6">Loading sessions…</p>
        ) : (
          <section className="mt-6 divide-y divide-slate-100 rounded-2xl border border-slate-200 bg-white px-6">
            {sessions.length === 0 ? (
              <p className="py-6 text-sm text-slate-600">No active sessions.</p>
            ) : (
              sessions.map((session) => (
                <article
                  key={session.id}
                  className="flex flex-wrap items-center justify-between gap-4 py-5"
                >
                  <div>
                    <p className="font-medium">
                      {session.is_current ? "This device" : "Other session"}
                    </p>
                    <p className="mt-1 text-sm text-slate-500">
                      {session.device_label}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      Last active {new Date(session.last_used_at).toLocaleString()}
                    </p>
                  </div>
                  <button
                    onClick={() => void revokeSession(session.id)}
                    className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium hover:bg-slate-50"
                  >
                    Revoke
                  </button>
                </article>
              ))
            )}
          </section>
        )}
        <button
          onClick={() => {
            if (window.confirm("Sign out all active sessions?")) {
              void logout(true).catch((logoutError) =>
                setError(
                  logoutError instanceof Error
                    ? logoutError.message
                    : "Could not log out all sessions.",
                ),
              );
            }
          }}
          className="mt-6 rounded-xl bg-red-700 px-4 py-2.5 font-semibold text-white hover:bg-red-800"
        >
          Log out all sessions
        </button>
      </AppShell>
    </ProtectedPage>
  );
}

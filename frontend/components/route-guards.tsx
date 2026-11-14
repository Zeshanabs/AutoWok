"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/auth-provider";

export function ProtectedPage({ children }: { children: ReactNode }) {
  const { status, error, refreshUser } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "unauthenticated") {
      router.replace("/login");
    }
  }, [status, router]);

  if (status === "loading" || status === "unauthenticated") {
    return <p className="p-8 text-sm text-slate-500">Checking your session…</p>;
  }
  if (status === "unavailable") {
    return (
      <main className="mx-auto max-w-xl p-8">
        <p role="alert" className="rounded-xl bg-red-50 p-4 text-red-800">
          {error ?? "The authentication service is unavailable."}
        </p>
        <button
          className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-white"
          onClick={() => void refreshUser()}
        >
          Retry
        </button>
      </main>
    );
  }
  return <>{children}</>;
}

export function GuestPage({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "authenticated") {
      router.replace("/dashboard");
    }
  }, [status, router]);

  if (status === "loading" || status === "authenticated") {
    return <p className="p-8 text-sm text-slate-500">Checking your session…</p>;
  }
  return <>{children}</>;
}

export function AppShell({ children }: { children: ReactNode }) {
  const { user, selectedWorkspace, logout } = useAuth();
  const [logoutError, setLogoutError] = useState<string | null>(null);
  return (
    <main className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <nav className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-4 sm:px-6">
          <Link href="/dashboard" className="font-bold tracking-tight">
            Autowok
          </Link>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
            {selectedWorkspace && (
              <span className="hidden text-slate-500 sm:inline">
                {selectedWorkspace.name} · {selectedWorkspace.role}
              </span>
            )}
            <Link href="/workspaces" className="hover:text-indigo-700">
              Workspaces
            </Link>
            <Link href="/brands" className="hover:text-indigo-700">
              Brands
            </Link>
            <Link href="/dashboard/research" className="hover:text-indigo-700">
              Research
            </Link>
            <Link href="/dashboard/content" className="hover:text-indigo-700">
              Content studio
            </Link>
            <Link href="/dashboard/calendar" className="hover:text-indigo-700">
              Calendar
            </Link>
            <Link href="/dashboard/media" className="hover:text-indigo-700">
              Media
            </Link>
            <Link href="/dashboard/publishing" className="hover:text-indigo-700">
              Publishing
            </Link>
            <Link href="/dashboard/analytics" className="hover:text-indigo-700">
              Analytics
            </Link>
            <Link href="/dashboard/automations" className="hover:text-indigo-700">
              Automations
            </Link>
            <Link href="/dashboard/ai-agents" className="hover:text-indigo-700">
              AI agents
            </Link>
            <Link href="/dashboard/notifications" className="hover:text-indigo-700">
              Notifications
            </Link>
            <Link href="/settings/ai" className="hover:text-indigo-700">
              AI settings
            </Link>
            <Link href="/settings/social-accounts" className="hover:text-indigo-700">
              Social accounts
            </Link>
            <Link href="/settings/security" className="hover:text-indigo-700">
              Security
            </Link>
            <span className="hidden text-slate-500 md:inline">
              {user?.full_name}
            </span>
            <button
              onClick={() => {
                setLogoutError(null);
                void logout().catch((error: unknown) =>
                  setLogoutError(
                    error instanceof Error
                      ? error.message
                      : "Could not log out.",
                  ),
                );
              }}
              className="rounded-lg border border-slate-300 px-3 py-1.5 hover:bg-slate-50"
            >
              Log out
            </button>
          </div>
        </nav>
        {logoutError && (
          <p role="alert" className="mx-auto max-w-6xl px-6 pb-3 text-sm text-red-700">
            {logoutError}
          </p>
        )}
      </header>
      <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-10">{children}</div>
    </main>
  );
}

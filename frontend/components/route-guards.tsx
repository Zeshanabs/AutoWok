"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

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
    return (
      <main>
        <p role="status" className="p-8 text-sm text-slate-600">Checking your session…</p>
      </main>
    );
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
    return (
      <main>
        <p role="status" className="p-8 text-sm text-slate-600">Checking your session…</p>
      </main>
    );
  }
  return <>{children}</>;
}

const NAV_LINKS: { href: string; label: string }[] = [
  { href: "/workspaces", label: "Workspaces" },
  { href: "/brands", label: "Brands" },
  { href: "/dashboard/research", label: "Research" },
  { href: "/dashboard/content", label: "Content studio" },
  { href: "/dashboard/calendar", label: "Calendar" },
  { href: "/dashboard/media", label: "Media" },
  { href: "/dashboard/publishing", label: "Publishing" },
  { href: "/dashboard/analytics", label: "Analytics" },
  { href: "/dashboard/automations", label: "Automations" },
  { href: "/dashboard/ai-agents", label: "AI agents" },
  { href: "/dashboard/notifications", label: "Notifications" },
  { href: "/settings/ai", label: "AI settings" },
  { href: "/settings/social-accounts", label: "Social accounts" },
  { href: "/settings/security", label: "Security" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const { user, selectedWorkspace, logout } = useAuth();
  const pathname = usePathname() ?? "";
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const section = pathname === "/dashboard" ? "Dashboard" : NAV_LINKS.find((link) => pathname === link.href || pathname.startsWith(`${link.href}/`))?.label;
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <title>{section ? `${section} · Autowok` : "Autowok"}</title>
      <a
        href="#content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-white focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:shadow"
      >
        Skip to content
      </a>
      <header className="border-b border-slate-200 bg-white">
        <nav aria-label="Primary" className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-4 sm:px-6">
          <Link href="/dashboard" className="font-bold tracking-tight" aria-current={pathname === "/dashboard" ? "page" : undefined}>
            Autowok
          </Link>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
            {selectedWorkspace && (
              <span className="hidden text-slate-600 sm:inline">
                {selectedWorkspace.name} · {selectedWorkspace.role}
              </span>
            )}
            {NAV_LINKS.map((link) => {
              const current = pathname === link.href || pathname.startsWith(`${link.href}/`);
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  aria-current={current ? "page" : undefined}
                  className={current ? "font-semibold text-indigo-700" : "hover:text-indigo-700"}
                >
                  {link.label}
                </Link>
              );
            })}
            <span className="hidden text-slate-600 md:inline">
              {user?.full_name}
            </span>
            <button
              type="button"
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
      <main id="content" tabIndex={-1} className="mx-auto max-w-6xl px-4 py-8 outline-none sm:px-6 sm:py-10">
        {children}
      </main>
    </div>
  );
}

"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { useAuth } from "@/components/auth-provider";
import { pathAfterSignIn } from "@/lib/pending-invite";

function SessionCheck() {
  return (
    <main className="flex min-h-screen items-center justify-center">
      <p role="status" className="text-sm text-slate-600">Checking your session…</p>
    </main>
  );
}

export function ProtectedPage({ children }: { children: ReactNode }) {
  const { status, error, refreshUser } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "unauthenticated") {
      router.replace("/login");
    }
  }, [status, router]);

  if (status === "loading" || status === "unauthenticated") {
    return <SessionCheck />;
  }
  if (status === "unavailable") {
    return (
      <main className="mx-auto max-w-xl p-8">
        <p role="alert" className="rounded-xl bg-red-50 p-4 text-red-800">
          {error ?? "The authentication service is unavailable."}
        </p>
        <button
          className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800"
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
      router.replace(pathAfterSignIn());
    }
  }, [status, router]);

  if (status === "loading" || status === "authenticated") {
    return <SessionCheck />;
  }
  return <>{children}</>;
}

/** The Autowok mark: a wok seen from the side, with the burner's ember under it. */
export function BrandMark({ className = "h-7 w-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={className} fill="none">
      <rect width="32" height="32" rx="8" className="fill-indigo-600" />
      <path d="M6 13.5h20c0 6-4.2 9.5-10 9.5S6 19.5 6 13.5Z" fill="#fff" />
      <path d="M25.5 13.5 29 11.2" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" />
      <circle cx="16" cy="26.3" r="1.7" className="fill-ember" />
    </svg>
  );
}

type NavLink = { href: string; label: string; icon: string };
type NavGroup = { title: string; links: NavLink[] };

// Icon paths are drawn on a 20 x 20 grid with a 1.6 stroke.
const NAV_GROUPS: NavGroup[] = [
  {
    title: "Plan",
    links: [
      { href: "/dashboard/research", label: "Research", icon: "M9 3a6 6 0 1 0 0 12A6 6 0 0 0 9 3Zm4.5 10.5L17 17" },
      { href: "/dashboard/content", label: "Content studio", icon: "M4 16l1-4 8.5-8.5a1.8 1.8 0 0 1 2.5 2.5L7.5 14.5 4 16Zm8-10.5 2.5 2.5" },
      { href: "/dashboard/calendar", label: "Calendar", icon: "M4 5.5h12v10.5H4V5.5Zm0 3.5h12M7 3.5v3M13 3.5v3" },
      { href: "/dashboard/media", label: "Media", icon: "M3.5 4.5h13v11h-13v-11Zm0 8 3.5-3.5 3 3 2.5-2.5 4 4M13 7.5h.010" },
    ],
  },
  {
    title: "Publish",
    links: [
      { href: "/dashboard/publishing", label: "Publishing", icon: "M3.5 10 16.5 4l-4 12.5-2.5-5-6.5-1.5Zm6.5 1.5 3-3.5" },
      { href: "/dashboard/automations", label: "Automations", icon: "M11 2.5 4.5 11H10l-1 6.5L15.5 9H10l1-6.5Z" },
      { href: "/dashboard/ai-agents", label: "AI agents", icon: "M10 3v2.5M5 7.5h10v8H5v-8Zm3 3.5h.010M12 11h.010M8 13.5h4M3 10.5v2M17 10.5v2" },
    ],
  },
  {
    title: "Measure",
    links: [
      { href: "/dashboard/analytics", label: "Analytics", icon: "M4 16V9.5M8.5 16V4M13 16v-5M17 16V7" },
      { href: "/dashboard/notifications", label: "Notifications", icon: "M5.5 13.5V9a4.5 4.5 0 0 1 9 0v4.5l1.5 1.5H4l1.5-1.5ZM8.5 17h3" },
    ],
  },
  {
    title: "Workspace",
    links: [
      { href: "/workspaces", label: "Workspaces", icon: "M3.5 16.5v-10l6.5-3 6.5 3v10h-13Zm4.5 0v-4h4v4M8 8.5h.010M12 8.5h.010" },
      { href: "/brands", label: "Brands", icon: "M3.5 3.5h6l7 7-6 6-7-7v-6Zm3.5 3.5h.010" },
    ],
  },
  {
    title: "Settings",
    links: [
      { href: "/settings/ai", label: "AI settings", icon: "M10 2.5l1.8 4.7 4.7 1.8-4.7 1.8L10 15.5l-1.8-4.7L3.5 9l4.7-1.8L10 2.5ZM15.5 14v3M14 15.5h3" },
      { href: "/settings/social-accounts", label: "Social accounts", icon: "M7 5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5ZM3 16c0-2.5 1.8-4 4-4s4 1.5 4 4M13.5 6.5a2 2 0 1 0 0 4 2 2 0 0 0 0-4ZM13 12c2.2 0 4 1.3 4 3.5" },
      { href: "/settings/security", label: "Security", icon: "M10 2.5l6 2.2v4.8c0 3.7-2.5 6.3-6 8-3.5-1.7-6-4.3-6-8V4.7l6-2.2Zm-2.5 7.5 2 2 3.5-4" },
    ],
  },
];

const NAV_LINKS = NAV_GROUPS.flatMap((group) => group.links);

function isCurrent(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

function NavIcon({ path }: { path: string }) {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true" className="h-[18px] w-[18px] shrink-0" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d={path} />
    </svg>
  );
}

function roleLabel(role: string): string {
  return role.charAt(0).toUpperCase() + role.slice(1).toLowerCase();
}

function initials(name: string | undefined): string {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase() || "?";
}

export function AppShell({ children }: { children: ReactNode }) {
  const { user, selectedWorkspace, logout } = useAuth();
  const pathname = usePathname() ?? "";
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const onDashboard = pathname === "/dashboard";
  const section = onDashboard ? "Dashboard" : NAV_LINKS.find((link) => isCurrent(pathname, link.href))?.label;
  const linkClass = (current: boolean) =>
    `flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-sm ${
      current ? "bg-white/10 font-semibold text-white" : "text-slate-300 hover:bg-white/5 hover:text-white"
    }`;

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 lg:grid lg:grid-cols-[15.5rem_minmax(0,1fr)]">
      <title>{section ? `${section} · Autowok` : "Autowok"}</title>
      <a
        href="#content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-white focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:shadow"
      >
        Skip to content
      </a>
      <header className="app-sidebar bg-slate-900 text-slate-300 lg:sticky lg:top-0 lg:flex lg:h-screen lg:flex-col lg:overflow-y-auto">
        <div className="flex items-center justify-between gap-3 px-4 py-3.5 lg:px-5 lg:pb-2 lg:pt-5">
          <Link
            href="/dashboard"
            aria-current={onDashboard ? "page" : undefined}
            className="flex items-center gap-2.5 font-display text-lg font-bold tracking-tight text-white"
            onClick={() => setMenuOpen(false)}
          >
            <BrandMark />
            Autowok
          </Link>
          <button
            type="button"
            aria-expanded={menuOpen}
            aria-controls="primary-navigation"
            onClick={() => setMenuOpen((open) => !open)}
            className="rounded-lg border border-white/15 px-3 py-1.5 text-sm font-medium text-white hover:bg-white/10 lg:hidden"
          >
            {menuOpen ? "Close menu" : "Menu"}
          </button>
        </div>

        <div id="primary-navigation" className={`${menuOpen ? "block" : "hidden"} px-3 pb-4 lg:flex lg:min-h-0 lg:flex-1 lg:flex-col`}>
          {selectedWorkspace && (
            <p className="mx-2 mb-1 mt-2 rounded-lg border border-white/10 px-3 py-2 text-sm text-slate-300">
              <span className="block truncate font-medium text-white">{selectedWorkspace.name}</span>
              <span className="text-xs text-slate-400">{roleLabel(selectedWorkspace.role)}</span>
            </p>
          )}
          <nav aria-label="Primary" className="mt-3 space-y-4">
            {NAV_GROUPS.map((group) => (
              <div key={group.title}>
                <p className="px-2.5 pb-1 text-xs font-medium text-slate-400">{group.title}</p>
                <ul className="space-y-0.5">
                  {group.links.map((link) => {
                    const current = isCurrent(pathname, link.href);
                    return (
                      <li key={link.href}>
                        <Link
                          href={link.href}
                          aria-current={current ? "page" : undefined}
                          className={linkClass(current)}
                          onClick={() => setMenuOpen(false)}
                        >
                          <NavIcon path={link.icon} />
                          {link.label}
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </nav>

          <div className="mt-5 border-t border-white/10 pt-3 lg:mt-auto">
            <div className="flex items-center gap-3 px-2">
              <span aria-hidden="true" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white/10 text-xs font-semibold text-white">
                {initials(user?.full_name)}
              </span>
              <span className="min-w-0 flex-1 truncate text-sm text-white">{user?.full_name}</span>
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
                className="shrink-0 rounded-lg border border-white/15 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-white/10"
              >
                Log out
              </button>
            </div>
            {logoutError && (
              <p role="alert" className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800">
                {logoutError}
              </p>
            )}
          </div>
        </div>
      </header>
      <main id="content" tabIndex={-1} className="min-w-0 outline-none">
        <div className="mx-auto max-w-6xl px-4 py-8 sm:px-8 sm:py-10">{children}</div>
      </main>
    </div>
  );
}

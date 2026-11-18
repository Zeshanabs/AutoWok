"use client";

import Link from "next/link";

import { useAuth } from "@/components/auth-provider";
import { AppShell, ProtectedPage } from "@/components/route-guards";

// The order a post travels through the app.
const STAGES: { title: string; summary: string; links: { href: string; label: string; detail: string }[] }[] = [
  {
    title: "Plan",
    summary: "Decide what to say and prepare it.",
    links: [
      { href: "/dashboard/research", label: "Research workspace", detail: "Gather sources on a topic" },
      { href: "/dashboard/content", label: "Content studio", detail: "Write and review drafts" },
      { href: "/dashboard/media", label: "Media library", detail: "Upload images and video" },
      { href: "/dashboard/calendar", label: "Calendar", detail: "Schedule approved posts" },
    ],
  },
  {
    title: "Publish",
    summary: "Send posts out and keep work moving.",
    links: [
      { href: "/dashboard/publishing", label: "Publishing", detail: "Publish now and check the queue" },
      { href: "/dashboard/automations", label: "Automations", detail: "Rules for tasks and reminders" },
      { href: "/dashboard/ai-agents", label: "AI agents", detail: "Drafts and recommendations to review" },
    ],
  },
  {
    title: "Measure",
    summary: "See what worked.",
    links: [
      { href: "/dashboard/analytics", label: "Analytics", detail: "Reach, engagement and growth" },
      { href: "/dashboard/notifications", label: "Notifications", detail: "Tasks and alerts for you" },
    ],
  },
];

const SETUP: { href: string; label: string }[] = [
  { href: "/workspaces", label: "Manage workspaces" },
  { href: "/brands", label: "Manage brands" },
  { href: "/settings/social-accounts", label: "Social accounts" },
  { href: "/settings/ai", label: "AI provider settings" },
  { href: "/settings/security", label: "Security settings" },
];

export default function DashboardPage() {
  const { user, selectedWorkspace } = useAuth();
  return (
    <ProtectedPage>
      <AppShell>
        <section className="flex flex-wrap items-end justify-between gap-6">
          <div>
            <h1 className="text-3xl font-bold">
              Welcome, {user?.full_name}
            </h1>
            <p className="mt-2 text-slate-600">
              Pick up where you left off, or start a new post.
            </p>
          </div>
          <Link
            href="/dashboard/content/new"
            className="rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700"
          >
            New content
          </Link>
        </section>

        <div className="mt-8 grid gap-5 lg:grid-cols-3">
          {STAGES.map((stage) => (
            <section key={stage.title} className="rounded-2xl border border-slate-200 bg-white p-5">
              <h2 className="text-lg font-semibold">{stage.title}</h2>
              <p className="mt-1 text-sm text-slate-500">{stage.summary}</p>
              <ul className="mt-4 divide-y divide-slate-100 border-t border-slate-100">
                {stage.links.map((link) => (
                  <li key={link.href}>
                    <Link href={link.href} className="group block py-3">
                      <span className="block text-sm font-semibold text-slate-900 group-hover:text-indigo-700">{link.label}</span>
                      <span className="block text-sm text-slate-500">{link.detail}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>

        <div className="mt-5 grid gap-5 md:grid-cols-2">
          <article className="rounded-2xl border border-slate-200 bg-white p-6">
            <h2 className="font-semibold">Active workspace</h2>
            {selectedWorkspace ? (
              <>
                <p className="mt-4 text-lg font-semibold">
                  {selectedWorkspace.name}
                </p>
                <p className="mt-1 text-sm text-slate-500">
                  Your role: {selectedWorkspace.role}
                </p>
                <Link
                  href={`/workspaces/${selectedWorkspace.id}`}
                  className="mt-5 inline-block text-sm font-semibold text-indigo-700 hover:text-indigo-900"
                >
                  View workspace
                </Link>
              </>
            ) : (
              <p className="mt-4 text-sm text-slate-600">
                You don’t belong to a workspace yet.
              </p>
            )}
          </article>
          <article className="rounded-2xl border border-slate-200 bg-white p-6">
            <h2 className="font-semibold">Account</h2>
            <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-slate-500">Name</dt>
                <dd className="mt-1 font-medium">{user?.full_name}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Account status</dt>
                <dd className="mt-1 font-medium">
                  {user?.is_active ? "Active" : "Inactive"}
                  {user?.is_verified ? ", verified" : ", not verified"}
                </dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-slate-500">Email</dt>
                <dd className="mt-1 break-all font-medium">{user?.email}</dd>
              </div>
            </dl>
          </article>
        </div>

        <nav aria-label="Setup" className="mt-6 flex flex-wrap gap-2 text-sm">
          {SETUP.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 font-medium text-slate-700 hover:border-slate-400 hover:text-slate-900"
            >
              {link.label}
            </Link>
          ))}
        </nav>
      </AppShell>
    </ProtectedPage>
  );
}

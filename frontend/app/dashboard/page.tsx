"use client";

import Link from "next/link";

import { useAuth } from "@/components/auth-provider";
import { AppShell, ProtectedPage } from "@/components/route-guards";

export default function DashboardPage() {
  const { user, selectedWorkspace } = useAuth();
  return (
    <ProtectedPage>
      <AppShell>
        <section>
          <p className="text-sm font-medium text-indigo-700">Account overview</p>
          <h1 className="mt-2 text-3xl font-bold tracking-tight">
            Welcome, {user?.full_name}
          </h1>
          <p className="mt-2 text-slate-600">
            Your account and workspace access at a glance.
          </p>
        </section>
        <div className="mt-8 grid gap-5 md:grid-cols-2">
          <article className="rounded-2xl border border-slate-200 bg-white p-6">
            <h2 className="font-semibold">Account</h2>
            <dl className="mt-4 space-y-3 text-sm">
              <div>
                <dt className="text-slate-500">Name</dt>
                <dd className="mt-1 font-medium">{user?.full_name}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Email</dt>
                <dd className="mt-1 font-medium">{user?.email}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Account status</dt>
                <dd className="mt-1 font-medium">
                  {user?.is_active ? "Active" : "Inactive"}
                  {user?.is_verified ? " · Verified" : " · Not verified"}
                </dd>
              </div>
            </dl>
          </article>
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
                  className="mt-5 inline-block text-sm font-semibold text-indigo-700"
                >
                  View workspace →
                </Link>
              </>
            ) : (
              <p className="mt-4 text-sm text-slate-600">
                You don’t belong to a workspace yet.
              </p>
            )}
          </article>
        </div>
        <div className="mt-6 flex flex-wrap gap-4 text-sm">
          <Link href="/workspaces" className="font-semibold text-indigo-700">
            Manage workspaces
          </Link>
          <Link href="/brands" className="font-semibold text-indigo-700">
            Manage brands
          </Link>
          <Link href="/dashboard/research" className="font-semibold text-indigo-700">
            Research workspace
          </Link>
          <Link href="/dashboard/content" className="font-semibold text-indigo-700">
            Content studio
          </Link>
          <Link href="/dashboard/calendar" className="font-semibold text-indigo-700">
            Calendar
          </Link>
          <Link href="/dashboard/media" className="font-semibold text-indigo-700">
            Media library
          </Link>
          <Link href="/dashboard/publishing" className="font-semibold text-indigo-700">
            Publishing
          </Link>
          <Link href="/dashboard/analytics" className="font-semibold text-indigo-700">
            Analytics
          </Link>
          <Link href="/dashboard/automations" className="font-semibold text-indigo-700">
            Automations
          </Link>
          <Link href="/dashboard/notifications" className="font-semibold text-indigo-700">
            Notifications
          </Link>
          <Link href="/settings/ai" className="font-semibold text-indigo-700">
            AI provider settings
          </Link>
          <Link
            href="/settings/security"
            className="font-semibold text-indigo-700"
          >
            Security settings
          </Link>
        </div>
      </AppShell>
    </ProtectedPage>
  );
}

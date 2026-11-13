"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/auth-provider";
import { AutomationForm } from "@/components/automations/automation-form";
import { AppShell, ProtectedPage } from "@/components/route-guards";

export default function NewAutomationPage() {
  const router = useRouter();
  const { selectedWorkspace } = useAuth();
  const canManage = selectedWorkspace?.role === "OWNER" || selectedWorkspace?.role === "ADMIN";
  return (
    <ProtectedPage>
      <AppShell>
        <Link href="/dashboard/automations" className="text-sm font-semibold text-indigo-700">← Automations</Link>
        <h1 className="mt-3 text-3xl font-bold tracking-tight">New automation</h1>
        <p className="mt-1 text-sm text-slate-600">
          Choose a trigger, add conditions and actions, test the configuration, then save it as a draft. Enabling is a separate, confirmed step.
        </p>
        <div className="mt-6">
          {!selectedWorkspace ? (
            <p className="text-sm text-slate-600">Select a workspace.</p>
          ) : !canManage ? (
            <p className="rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">Only workspace Owners and Admins can create automations.</p>
          ) : (
            <AutomationForm workspaceId={selectedWorkspace.id} onSaved={(automation) => router.push(`/dashboard/automations/${automation.id}`)} />
          )}
        </div>
      </AppShell>
    </ProtectedPage>
  );
}

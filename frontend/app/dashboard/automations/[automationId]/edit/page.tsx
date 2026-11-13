"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { AutomationForm } from "@/components/automations/automation-form";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { ApiError, apiRequest } from "@/lib/api";
import type { AutomationDetail } from "@/lib/automation-types";

export default function EditAutomationPage() {
  const { automationId } = useParams<{ automationId: string }>();
  const router = useRouter();
  const { selectedWorkspace } = useAuth();
  const workspaceId = selectedWorkspace?.id;
  const canManage = selectedWorkspace?.role === "OWNER" || selectedWorkspace?.role === "ADMIN";
  const [automation, setAutomation] = useState<AutomationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!workspaceId) return;
    let active = true;
    apiRequest<AutomationDetail>(`/workspaces/${workspaceId}/automations/${automationId}`)
      .then((data) => {
        if (active) setAutomation(data);
      })
      .catch((loadError: unknown) => {
        if (active) setError(loadError instanceof ApiError ? loadError.message : "The automation could not be loaded.");
      });
    return () => {
      active = false;
    };
  }, [workspaceId, automationId]);

  return (
    <ProtectedPage>
      <AppShell>
        <Link href={`/dashboard/automations/${automationId}`} className="text-sm font-semibold text-indigo-700">← Back to automation</Link>
        <h1 className="mt-3 text-3xl font-bold tracking-tight">Edit automation</h1>
        {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
        <div className="mt-6">
          {!workspaceId ? (
            <p className="text-sm text-slate-600">Select a workspace.</p>
          ) : !canManage ? (
            <p className="rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">Only workspace Owners and Admins can edit automations.</p>
          ) : !automation ? (
            !error && <p className="text-sm text-slate-500">Loading…</p>
          ) : automation.status === "archived" ? (
            <p className="rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">Archived automations cannot be edited. Duplicate it to start a new draft.</p>
          ) : (
            <>
              {automation.status === "enabled" && (
                <p className="mb-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
                  This automation is enabled. Saved changes apply to the next event; you become the owner whose permissions it runs with.
                </p>
              )}
              <AutomationForm workspaceId={workspaceId} initial={automation} onSaved={() => router.push(`/dashboard/automations/${automationId}`)} />
            </>
          )}
        </div>
      </AppShell>
    </ProtectedPage>
  );
}

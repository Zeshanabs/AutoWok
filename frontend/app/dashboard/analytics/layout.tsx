"use client";

import type { ReactNode } from "react";

import { AnalyticsProvider } from "@/components/analytics/analytics-provider";
import { AnalyticsShell } from "@/components/analytics/analytics-shell";
import { AppShell, ProtectedPage } from "@/components/route-guards";

export default function AnalyticsLayout({ children }: { children: ReactNode }) {
  return (
    <ProtectedPage>
      <AppShell>
        <AnalyticsProvider>
          <AnalyticsShell>{children}</AnalyticsShell>
        </AnalyticsProvider>
      </AppShell>
    </ProtectedPage>
  );
}

"use client";

import Link from "next/link";
import type { ReactNode } from "react";

const TABS = [
  { href: "/dashboard/ai-agents", label: "Overview" },
  { href: "/dashboard/ai-agents/workflows", label: "New workflow" },
  { href: "/dashboard/ai-agents/history", label: "History" },
  { href: "/dashboard/ai-agents/settings", label: "Agents & settings" },
];

export function AgentsHeader({
  active,
  title,
  description,
  actions,
}: {
  active: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-indigo-700">AI agents</p>
          <h1 className="mt-2 text-3xl font-bold tracking-tight">{title}</h1>
          <p className="mt-1 max-w-3xl text-sm text-slate-600">{description}</p>
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
      <nav aria-label="AI agents" className="mt-5 flex flex-wrap gap-1 border-b border-slate-200 text-sm">
        {TABS.map((tab) => (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={tab.href === active ? "page" : undefined}
            className={`-mb-px border-b-2 px-3 py-2 font-medium ${
              tab.href === active ? "border-indigo-600 text-indigo-700" : "border-transparent text-slate-600 hover:text-slate-900"
            }`}
          >
            {tab.label}
          </Link>
        ))}
      </nav>
    </div>
  );
}

export function HumanControlNote() {
  return (
    <p className="rounded-xl border border-slate-200 bg-white p-3 text-sm text-slate-600">
      Agents produce drafts and recommendations for you to review. They cannot approve, schedule or publish content.
    </p>
  );
}

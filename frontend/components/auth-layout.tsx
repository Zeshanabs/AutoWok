import Link from "next/link";
import type { ReactNode } from "react";

import { BrandMark } from "@/components/route-guards";

const POINTS = [
  "Research, drafts, approvals and scheduling in one workspace",
  "Publishes to Facebook Pages and Instagram",
  "AI drafts in your brand voice; people approve every post",
];

/** Sign-in and registration share this frame: what Autowok is on one side, the form on the other. */
export function AuthLayout({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <main className="grid min-h-screen bg-white lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <aside className="hidden flex-col justify-between bg-slate-900 p-10 text-white lg:flex xl:p-14">
        <Link href="/" className="flex items-center gap-2.5 font-display text-xl font-bold tracking-tight">
          <BrandMark className="h-8 w-8" />
          Autowok
        </Link>
        <div>
          <p className="max-w-sm font-display text-3xl font-semibold leading-tight tracking-tight">
            Every post, from first idea to final numbers.
          </p>
          <ul className="mt-8 space-y-3 text-sm text-slate-300">
            {POINTS.map((point) => (
              <li key={point} className="flex gap-3">
                <span aria-hidden="true" className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-ember" />
                {point}
              </li>
            ))}
          </ul>
        </div>
        <p className="text-xs text-slate-400">Facebook and Instagram are trademarks of Meta.</p>
      </aside>
      <div className="flex items-center justify-center px-5 py-12 sm:px-8">
        <section className="w-full max-w-sm">
          <Link href="/" className="mb-10 flex items-center gap-2.5 font-display text-lg font-bold tracking-tight lg:hidden">
            <BrandMark />
            Autowok
          </Link>
          <h1 className="text-3xl font-bold">{title}</h1>
          <p className="mb-8 mt-2 text-sm text-slate-600">{description}</p>
          {children}
        </section>
      </div>
    </main>
  );
}

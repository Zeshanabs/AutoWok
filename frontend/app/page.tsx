"use client";

import { useEffect, useState } from "react";

type HealthResponse = {
  status: string;
  service: string;
  environment?: string;
};

type DependencyState = {
  database: boolean;
  redis: boolean;
};

type ReadyResponse = {
  status: string;
  service: string;
  dependencies: DependencyState;
};

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function Home() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [readiness, setReadiness] = useState<ReadyResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const [healthResponse, readyResponse] = await Promise.all([
          fetch(`${API_BASE_URL}/api/v1/health`),
          fetch(`${API_BASE_URL}/api/v1/ready`),
        ]);

        if (!healthResponse.ok || !readyResponse.ok) {
          throw new Error("Backend status endpoint is unavailable.");
        }

        const [healthData, readyData] = await Promise.all([
          healthResponse.json() as Promise<HealthResponse>,
          readyResponse.json() as Promise<ReadyResponse>,
        ]);

        setHealth(healthData);
        setReadiness(readyData);
      } catch (loadError) {
        setError(
          loadError instanceof Error
            ? loadError.message
            : "Unable to connect to the backend service.",
        );
      } finally {
        setLoading(false);
      }
    };

    fetchStatus();
  }, []);

  const dependencyCards = readiness
    ? [
        ["Database", readiness.dependencies.database],
        ["Redis", readiness.dependencies.redis],
      ]
    : [];

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,#f5f3ff_0%,#eef2ff_30%,#f8fafc_100%)] text-slate-900">
      <div className="mx-auto flex max-w-7xl flex-col px-6 py-16 lg:px-8">
        <header className="flex items-center justify-between border-b border-slate-200/80 bg-white/60 px-5 py-4 backdrop-blur-sm">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600 font-bold text-white shadow-sm">
              A
            </div>
            <div>
              <p className="text-lg font-semibold tracking-tight">Autowok</p>
              <p className="text-xs text-slate-500">Phase 0 foundation</p>
            </div>
          </div>
          <nav className="hidden items-center gap-8 text-sm font-medium text-slate-600 md:flex">
            <a href="#platform" className="transition hover:text-slate-900">Platform</a>
            <a href="#workflow" className="transition hover:text-slate-900">Workflow</a>
            <a href="#status" className="transition hover:text-slate-900">Status</a>
          </nav>
        </header>

        <section className="grid items-center gap-10 py-20 lg:grid-cols-[1.1fr_0.9fr] lg:py-28">
          <div className="space-y-8">
            <span className="inline-flex items-center rounded-full border border-indigo-200 bg-indigo-50 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-indigo-700">
              Social media operations foundation
            </span>
            <div className="space-y-5">
              <h1 className="max-w-xl text-4xl font-black tracking-tight text-slate-950 sm:text-5xl lg:text-6xl">
                Build a smarter, more reliable social content engine.
              </h1>
              <p className="max-w-xl text-lg leading-8 text-slate-600">
                Autowok is being developed as a brand-aware research, drafting, approval, and publishing platform for modern teams.
              </p>
            </div>
            <div className="flex flex-col gap-4 sm:flex-row">
              <a
                href="#status"
                className="inline-flex items-center justify-center rounded-full bg-slate-900 px-6 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800"
              >
                View project status
              </a>
              <a
                href="#workflow"
                className="inline-flex items-center justify-center rounded-full border border-slate-300 bg-white px-6 py-3 text-sm font-semibold text-slate-700 transition hover:border-slate-400 hover:bg-slate-50"
              >
                See the roadmap
              </a>
            </div>
          </div>

          <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-xl shadow-indigo-100/40">
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-5">
              <div className="mb-5 flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-slate-500">System status</p>
                  <p className="text-2xl font-bold text-slate-900">{health?.service ?? "Autowok"}</p>
                </div>
                <div
                  className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
                    readiness?.status === "ready"
                      ? "bg-emerald-100 text-emerald-700"
                      : readiness?.status === "degraded"
                        ? "bg-amber-100 text-amber-700"
                        : "bg-slate-200 text-slate-700"
                  }`}
                >
                  {loading ? "Loading" : readiness?.status ?? "Offline"}
                </div>
              </div>

              {error ? (
                <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                  {error}
                </div>
              ) : (
                <div className="space-y-4">
                  {[
                    ["Frontend", "Next.js + TypeScript + Tailwind"],
                    ["Backend", health ? `${health.status} API` : "Loading..."],
                    ["Environment", health?.environment ?? "development"],
                  ].map(([label, value]) => (
                    <div key={label} className="flex items-center justify-between rounded-xl border border-slate-200 bg-white px-3 py-2.5">
                      <span className="text-sm font-medium text-slate-500">{label}</span>
                      <span className="text-sm font-semibold text-slate-900">{value}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </section>

        <section id="platform" className="grid gap-6 py-12 md:grid-cols-3">
          {[
            ["Brand-aware workflows", "Create the foundation for identity, research, approvals, and content coordination."],
            ["Reliable infrastructure", "Adopt PostgreSQL, Redis, and Docker to support future automation and background processing."],
            ["Operational clarity", "Separate the API, data layer, local storage, and deployment concerns for growth."],
          ].map(([title, text]) => (
            <article key={title} className="rounded-2xl border border-slate-200 bg-white/80 p-6 shadow-sm">
              <h2 className="mb-3 text-lg font-semibold text-slate-900">{title}</h2>
              <p className="text-sm leading-7 text-slate-600">{text}</p>
            </article>
          ))}
        </section>

        <section id="workflow" className="py-12">
          <div className="mb-7 max-w-2xl">
            <p className="mb-3 text-sm font-semibold uppercase tracking-[0.2em] text-indigo-600">Roadmap</p>
            <h2 className="text-3xl font-bold tracking-tight text-slate-900">Phase 0 excludes product features but defines the path ahead.</h2>
          </div>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {[
              "Authentication & roles",
              "Brand profiles & settings",
              "Content approval & publishing",
              "Scheduling & analytics",
            ].map((step) => (
              <div key={step} className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-5 text-sm font-medium text-slate-700">
                {step}
              </div>
            ))}
          </div>
        </section>

        <section id="status" className="py-12">
          <div className="rounded-3xl border border-slate-200 bg-slate-950 p-8 text-white shadow-xl shadow-slate-900/10">
            <p className="mb-3 text-sm font-semibold uppercase tracking-[0.2em] text-indigo-300">Current status</p>
            <h2 className="text-3xl font-bold">
              {loading ? "Checking foundation health..." : readiness?.status === "ready" ? "Foundation active" : "Foundation degraded"}
            </h2>
            <p className="mt-4 max-w-2xl text-slate-300">
              {readiness
                ? `${readiness.service} is reporting a ${readiness.status} state across its service dependencies.`
                : "The frontend is awaiting a live backend response to confirm platform health."}
            </p>

            <div className="mt-6 grid gap-3 md:grid-cols-2">
              {dependencyCards.length > 0 ? (
                dependencyCards.map(([name, ok]) => (
                  <div key={name} className="flex items-center justify-between rounded-2xl border border-slate-800 bg-slate-900/80 px-4 py-3">
                    <span className="text-sm text-slate-300">{name}</span>
                    <span
                      className={`rounded-full px-2 py-1 text-xs font-semibold ${
                        ok ? "bg-emerald-500/20 text-emerald-300" : "bg-red-500/20 text-red-300"
                      }`}
                    >
                      {ok ? "Connected" : "Unavailable"}
                    </span>
                  </div>
                ))
              ) : (
                <div className="rounded-2xl border border-slate-800 bg-slate-900/80 px-4 py-3 text-sm text-slate-400">
                  Waiting for backend status...
                </div>
              )}
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}

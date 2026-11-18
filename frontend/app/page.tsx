"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { BrandMark } from "@/components/route-guards";

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

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// One post's journey through Autowok. This is a real sequence, so it is numbered.
const JOURNEY: { step: string; detail: string; state: string; tone: string }[] = [
  { step: "Research", detail: "Sources gathered on home brewing habits", state: "Done", tone: "bg-emerald-50 text-emerald-800" },
  { step: "Draft", detail: "Caption written in your brand voice", state: "Done", tone: "bg-emerald-50 text-emerald-800" },
  { step: "Approve", detail: "Ravi reviewed and approved the draft", state: "Approved", tone: "bg-emerald-50 text-emerald-800" },
  { step: "Schedule", detail: "Thursday 9:00, Facebook and Instagram", state: "Scheduled", tone: "bg-indigo-50 text-indigo-800" },
  { step: "Publish", detail: "Sent to Meta at the scheduled time", state: "Waiting", tone: "bg-slate-100 text-slate-600" },
  { step: "Measure", detail: "Reach and engagement collected after posting", state: "Waiting", tone: "bg-slate-100 text-slate-600" },
];

const FEATURES: [string, string][] = [
  ["Research before you write", "Collect sources on a topic and keep them next to the content they support."],
  ["Drafts in your brand voice", "Set the tone, audience and banned phrases once. AI drafts follow them, and you edit the result."],
  ["Nothing goes out unapproved", "Every post passes a reviewer. AI agents can suggest, but only people approve, schedule and publish."],
  ["One calendar for both networks", "Schedule Facebook Page and Instagram posts in your time zone and see the whole week at once."],
  ["Rules for the repetitive parts", "Automations create tasks, reminders and follow-ups when something is published, fails or goes quiet."],
  ["Numbers with their source", "Reach, engagement and follower growth come from Meta, each shown with the time it was collected."],
];

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

  const statusItems: [string, boolean][] = readiness
    ? [
        ["API", health?.status === "ok" || readiness.status === "ready"],
        ["Database", readiness.dependencies.database],
        ["Redis", readiness.dependencies.redis],
      ]
    : [];

  return (
    <main className="min-h-screen bg-slate-50 text-slate-900">
      <header className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-5 py-5 sm:px-8">
        <Link href="/" className="flex items-center gap-2.5 font-display text-xl font-bold tracking-tight">
          <BrandMark className="h-8 w-8" />
          Autowok
        </Link>
        <nav aria-label="Account" className="flex items-center gap-2 text-sm font-semibold sm:gap-3">
          <Link href="/login" className="rounded-lg px-3 py-2 text-slate-700 hover:bg-slate-100 hover:text-slate-900">
            Sign in
          </Link>
          <Link href="/register" className="rounded-lg bg-indigo-600 px-4 py-2 text-white hover:bg-indigo-700">
            Create account
          </Link>
        </nav>
      </header>

      <section className="mx-auto grid max-w-6xl items-center gap-12 px-5 pb-16 pt-10 sm:px-8 lg:grid-cols-[1.05fr_0.95fr] lg:pb-24 lg:pt-16">
        <div>
          <h1 className="max-w-xl text-4xl font-extrabold text-slate-950 sm:text-5xl lg:text-[3.5rem]">
            Every post, from first idea to final numbers.
          </h1>
          <p className="mt-6 max-w-lg text-lg leading-8 text-slate-600">
            Autowok is one workspace for your Facebook and Instagram content. Research a topic, draft in your brand
            voice, get approval, schedule, publish and see how it performed.
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <Link
              href="/register"
              className="inline-flex items-center justify-center rounded-xl bg-indigo-600 px-6 py-3 text-sm font-semibold text-white hover:bg-indigo-700"
            >
              Create your account
            </Link>
            <Link
              href="/login"
              className="inline-flex items-center justify-center rounded-xl border border-slate-300 bg-white px-6 py-3 text-sm font-semibold text-slate-800 hover:border-slate-400 hover:bg-slate-50"
            >
              Sign in
            </Link>
          </div>
          <p className="mt-4 text-sm text-slate-500">Your account comes with a private workspace. Invite your team when you are ready.</p>
        </div>

        <div className="rounded-3xl bg-slate-900 p-6 text-white sm:p-7">
          <p className="text-sm text-slate-400">Example post</p>
          <p className="mt-1 font-display text-xl font-semibold">Three brewing mistakes</p>
          <ol className="mt-6">
            {JOURNEY.map((item, index) => (
              <li key={item.step} className="relative flex gap-4 pb-5 last:pb-0">
                {index < JOURNEY.length - 1 && (
                  <span aria-hidden="true" className="absolute left-[13px] top-7 h-[calc(100%-1.75rem)] w-px bg-white/15" />
                )}
                <span
                  className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
                    item.state === "Waiting" ? "border border-white/25 text-slate-400" : "bg-indigo-500 text-white"
                  }`}
                >
                  {index + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-semibold">{item.step}</p>
                    <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${item.tone}`}>{item.state}</span>
                  </div>
                  <p className="mt-0.5 text-sm text-slate-400">{item.detail}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="border-y border-slate-200 bg-white">
        <div className="mx-auto max-w-6xl px-5 py-16 sm:px-8">
          <h2 className="max-w-2xl text-3xl font-bold text-slate-950">What you can do in Autowok</h2>
          <dl className="mt-10 grid gap-x-10 gap-y-9 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map(([title, text]) => (
              <div key={title} className="border-t-2 border-slate-900 pt-4">
                <dt className="font-display text-lg font-semibold text-slate-950">{title}</dt>
                <dd className="mt-2 text-sm leading-6 text-slate-600">{text}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <footer className="mx-auto flex max-w-6xl flex-col gap-3 px-5 py-8 text-sm text-slate-600 sm:flex-row sm:items-center sm:justify-between sm:px-8">
        <p>
          Autowok{health?.environment ? `, ${health.environment} environment` : ""}
        </p>
        <div role="status" className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <span className="font-medium text-slate-900">Service status</span>
          {loading ? (
            <span>Checking…</span>
          ) : error ? (
            <span className="text-red-700">{error}</span>
          ) : (
            statusItems.map(([name, ok]) => (
              <span key={name} className="inline-flex items-center gap-1.5">
                <span aria-hidden="true" className={`h-2 w-2 rounded-full ${ok ? "bg-emerald-500" : "bg-red-500"}`} />
                {name}: {ok ? "working" : "unavailable"}
              </span>
            ))
          )}
        </div>
      </footer>
    </main>
  );
}

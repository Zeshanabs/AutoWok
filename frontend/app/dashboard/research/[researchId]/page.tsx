"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { useAuth } from "@/components/auth-provider";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { ApiError, apiRequest } from "@/lib/api";
import type { ResearchFinding, ResearchProject, ResearchReport, ResearchSource } from "@/lib/research-types";

export default function ResearchDetailPage() {
  const params = useParams<{ researchId: string }>();
  const researchId = params?.researchId;
  const { selectedWorkspace } = useAuth();
  const [project, setProject] = useState<ResearchProject | null>(null);
  const [report, setReport] = useState<ResearchReport | null>(null);
  const [sources, setSources] = useState<ResearchSource[]>([]);
  const [findings, setFindings] = useState<ResearchFinding[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadProject = useCallback(async () => {
    if (!researchId) {
      return;
    }
    try {
      const [detail, reportData, sourceData, findingData] = await Promise.all([
        apiRequest<ResearchProject>(`/research/${researchId}`),
        apiRequest<ResearchReport | null>(`/research/${researchId}/report`).catch(() => null),
        apiRequest<ResearchSource[]>(`/research/${researchId}/sources`).catch(() => []),
        apiRequest<ResearchFinding[]>(`/research/${researchId}/findings`).catch(() => []),
      ]);
      setProject(detail);
      setReport(reportData);
      setSources(sourceData);
      setFindings(findingData);
      setError(null);
    } catch (loadError) {
      setError(
        loadError instanceof ApiError
          ? loadError.message
          : "The research project could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }, [researchId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadProject(), 0);
    return () => window.clearTimeout(timer);
  }, [loadProject]);

  return (
    <ProtectedPage>
      <AppShell>
        <div className="mb-6 flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-indigo-700">
              Research report
            </p>
            <h1 className="mt-2 text-3xl font-bold tracking-tight">
              {project?.title ?? "Research project"}
            </h1>
          </div>
          <Link href="/dashboard/research" className="text-sm font-semibold text-indigo-700">
            Back to research
          </Link>
        </div>

        {error && (
          <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">
            {error}
          </p>
        )}

        {loading ? (
          <p>Loading research report…</p>
        ) : !project ? (
          <p className="rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">
            Project not found.
          </p>
        ) : (
          <div className="space-y-8">
            <section className="rounded-2xl border border-slate-200 bg-white p-6">
              <div className="grid gap-4 md:grid-cols-3 text-sm">
                <div>
                  <p className="text-slate-500">Status</p>
                  <p className="mt-1 font-semibold">{project.status}</p>
                </div>
                <div>
                  <p className="text-slate-500">Stage</p>
                  <p className="mt-1 font-semibold">{project.current_stage}</p>
                </div>
                <div>
                  <p className="text-slate-500">Category</p>
                  <p className="mt-1 font-semibold">{project.category}</p>
                </div>
              </div>
            </section>

            {report ? (
              <>
                <section className="rounded-2xl border border-slate-200 bg-white p-6">
                  <h2 className="text-xl font-semibold">Executive summary</h2>
                  <p className="mt-4 whitespace-pre-line text-slate-700">
                    {report.executive_summary || "No executive summary is available yet."}
                  </p>
                </section>

                <section className="rounded-2xl border border-slate-200 bg-white p-6">
                  <h2 className="text-xl font-semibold">Key findings</h2>
                  <ul className="mt-4 list-disc space-y-2 pl-5 text-slate-700">
                    {(report.key_findings.length ? report.key_findings : ["No findings yet."]).map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </section>

                <section className="grid gap-6 md:grid-cols-2">
                  <div className="rounded-2xl border border-slate-200 bg-white p-6">
                    <h2 className="text-xl font-semibold">Trends</h2>
                    <ul className="mt-4 list-disc space-y-2 pl-5 text-slate-700">
                      {(report.trends.length ? report.trends : ["No trend data yet."]).map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                  <div className="rounded-2xl border border-slate-200 bg-white p-6">
                    <h2 className="text-xl font-semibold">Opportunities</h2>
                    <ul className="mt-4 list-disc space-y-2 pl-5 text-slate-700">
                      {(report.opportunities.length ? report.opportunities : ["No opportunities recorded."]).map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                </section>
              </>
            ) : (
              <p className="rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">
                No report is available yet. Run the research to generate findings.
              </p>
            )}

            <section className="rounded-2xl border border-slate-200 bg-white p-6">
              <h2 className="text-xl font-semibold">Sources and citations</h2>
              <div className="mt-4 space-y-4">
                {sources.length === 0 ? (
                  <p className="text-sm text-slate-600">No sources retrieved yet.</p>
                ) : (
                  sources.map((source) => (
                    <div key={source.id} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                      <a href={source.url} target="_blank" rel="noreferrer" className="font-semibold text-indigo-700 underline">
                        {source.title}
                      </a>
                      <p className="mt-2 text-sm text-slate-600">{source.domain}</p>
                      <p className="mt-2 text-sm text-slate-700">{source.snippet || "No snippet available."}</p>
                    </div>
                  ))
                )}
              </div>
            </section>

            <section className="rounded-2xl border border-slate-200 bg-white p-6">
              <h2 className="text-xl font-semibold">Findings</h2>
              <div className="mt-4 space-y-4">
                {findings.length === 0 ? (
                  <p className="text-sm text-slate-600">No findings created yet.</p>
                ) : (
                  findings.map((finding) => (
                    <div key={finding.id} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                      <p className="font-semibold">{finding.claim}</p>
                      <p className="mt-2 text-sm text-slate-600">{finding.explanation || "No explanation provided."}</p>
                      <p className="mt-2 text-xs font-medium uppercase tracking-[0.12em] text-slate-500">
                        {finding.finding_type} · {finding.confidence_label}
                      </p>
                    </div>
                  ))
                )}
              </div>
            </section>

            {selectedWorkspace && (
              <div className="flex gap-3">
                <button
                  onClick={() => {
                    void apiRequest(`/research/${project.id}/run`, { method: "POST" }).then(() => void loadProject());
                  }}
                  className="rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700"
                >
                  Run research
                </button>
                <button
                  onClick={() => {
                    void apiRequest(`/research/${project.id}/cancel`, { method: "POST" }).then(() => void loadProject());
                  }}
                  className="rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold hover:bg-slate-50"
                >
                  Cancel
                </button>
              </div>
            )}
          </div>
        )}
      </AppShell>
    </ProtectedPage>
  );
}

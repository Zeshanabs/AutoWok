"use client";

import type { ReactNode } from "react";

import {
  CLASSIFICATION_LABELS,
  type BrandReview,
  type DraftVersion,
  type Evidence,
  type FactCheck,
  type FinalOutput,
  type QualityAssessment,
} from "@/lib/agent-types";

const SEVERITY: Record<string, string> = {
  high: "bg-red-50 text-red-800 ring-red-200",
  medium: "bg-amber-50 text-amber-800 ring-amber-200",
  low: "bg-slate-100 text-slate-700 ring-slate-200",
};

const CLASSIFICATION: Record<string, string> = {
  SUPPORTED: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  PARTIALLY_SUPPORTED: "bg-amber-50 text-amber-800 ring-amber-200",
  UNSUPPORTED: "bg-red-50 text-red-800 ring-red-200",
  CONTRADICTED: "bg-red-100 text-red-900 ring-red-300",
  OPINION: "bg-slate-100 text-slate-700 ring-slate-200",
  UNVERIFIABLE: "bg-sky-50 text-sky-800 ring-sky-200",
};

function Pill({ className, children }: { className: string; children: ReactNode }) {
  return <span className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${className}`}>{children}</span>;
}

export function Section({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">{title}</h2>
        {aside}
      </div>
      <div className="mt-3 text-sm">{children}</div>
    </section>
  );
}

export function BulletList({ items, empty }: { items?: string[] | null; empty?: string }) {
  if (!items || items.length === 0) return empty ? <p className="text-slate-500">{empty}</p> : null;
  return (
    <ul className="list-disc space-y-1 pl-5 text-slate-700">
      {items.map((item, index) => <li key={`${index}-${item.slice(0, 24)}`}>{item}</li>)}
    </ul>
  );
}

export function WarningList({ warnings }: { warnings?: string[] | null }) {
  if (!warnings || warnings.length === 0) return null;
  return (
    <div role="note" className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900">
      <p className="font-medium">Warnings</p>
      <ul className="mt-1 list-disc space-y-1 pl-5">
        {warnings.map((warning, index) => <li key={`${index}-${warning.slice(0, 24)}`}>{warning}</li>)}
      </ul>
    </div>
  );
}

export function EvidenceList({ evidence }: { evidence?: Evidence[] | null }) {
  if (!evidence || evidence.length === 0) return <p className="text-slate-500">No source references. Treat factual statements as unverified.</p>;
  return (
    <ul className="space-y-1">
      {evidence.map((item, index) =>
        item.type === "metric" ? (
          <li key={`metric-${index}`} className="text-slate-700">
            <span className="font-medium">{item.metric}</span>: {item.value}
            {item.scope ? <span className="text-slate-500"> · {item.scope}</span> : null}
            <span className="text-slate-500"> (measured)</span>
          </li>
        ) : (
          <li key={item.source_id ?? `source-${index}`} className="text-slate-700">
            {/* Source URLs come from the web: only http(s) links are made clickable. */}
            {item.url && /^https?:\/\//i.test(item.url) ? (
              <a href={item.url} target="_blank" rel="noopener noreferrer nofollow" className="font-medium text-indigo-700 hover:underline">
                {item.title || item.url}
              </a>
            ) : (
              <span className="font-medium">{item.title || "Source"}</span>
            )}
            {item.domain ? <span className="text-slate-500"> · {item.domain}</span> : null}
          </li>
        ),
      )}
    </ul>
  );
}

export function DraftVersions({ versions }: { versions?: DraftVersion[] | null }) {
  if (!versions || versions.length === 0) return <p className="text-slate-500">No draft was produced.</p>;
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {versions.map((version) => (
        <article key={version.platform} className="rounded-xl border border-slate-200 p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{version.platform}</p>
          <p className="mt-2 font-semibold">{version.hook}</p>
          <p className="mt-2 whitespace-pre-wrap text-slate-700">{version.body}</p>
          {version.cta && <p className="mt-2 font-medium text-slate-900">{version.cta}</p>}
          {version.hashtags.length > 0 && <p className="mt-2 text-indigo-700">{version.hashtags.join(" ")}</p>}
        </article>
      ))}
    </div>
  );
}

export function BrandReviewView({ review }: { review?: BrandReview | null }) {
  if (!review || !review.assessment) return <p className="text-slate-500">No brand review.</p>;
  const issues = review.issues ?? [];
  return (
    <div className="space-y-3">
      <p>
        <Pill className={review.assessment === "consistent" ? CLASSIFICATION.SUPPORTED : review.assessment === "major_issues" ? SEVERITY.high : SEVERITY.medium}>
          {review.assessment.replaceAll("_", " ")}
        </Pill>{" "}
        <span className="text-slate-700">{review.summary}</span>
      </p>
      {issues.length > 0 && (
        <ul className="space-y-2">
          {issues.map((issue, index) => (
            <li key={`${issue.category}-${index}`} className="rounded-lg border border-slate-200 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <Pill className={SEVERITY[issue.severity] ?? SEVERITY.low}>{issue.severity}</Pill>
                <span className="font-medium">{issue.category.replaceAll("_", " ")}</span>
                {issue.platform && <span className="text-slate-500">{issue.platform}</span>}
                {issue.detected_by === "rule" && <span className="text-xs text-slate-500">found by rule check</span>}
              </div>
              {issue.excerpt && <p className="mt-1 text-slate-500">“{issue.excerpt}”</p>}
              <p className="mt-1 text-slate-700">{issue.explanation}</p>
              {issue.suggestion && <p className="mt-1 text-slate-700"><span className="font-medium">Suggestion:</span> {issue.suggestion}</p>}
            </li>
          ))}
        </ul>
      )}
      {review.approval_note && <p className="text-xs text-slate-500">{review.approval_note}</p>}
    </div>
  );
}

export function FactCheckView({ report }: { report?: FactCheck | null }) {
  if (!report || !report.claims) return <p className="text-slate-500">No fact-check report.</p>;
  const coverage = report.citation_coverage;
  return (
    <div className="space-y-3">
      <p className="text-slate-700">{report.summary}</p>
      {coverage && (
        <p className="text-slate-600">
          {coverage.claims_with_evidence} of {coverage.factual_claims} factual claim{coverage.factual_claims === 1 ? "" : "s"} have a source · {coverage.sources_available} source{coverage.sources_available === 1 ? "" : "s"} available
        </p>
      )}
      {report.claims.length === 0 ? (
        <p className="text-slate-500">The draft makes no factual claims.</p>
      ) : (
        <ul className="space-y-2">
          {report.claims.map((claim, index) => (
            <li key={`${index}-${claim.claim.slice(0, 24)}`} className="rounded-lg border border-slate-200 p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <p className="font-medium">{claim.claim}</p>
                <Pill className={CLASSIFICATION[claim.classification] ?? SEVERITY.low}>{CLASSIFICATION_LABELS[claim.classification] ?? claim.classification}</Pill>
              </div>
              {claim.reasoning && <p className="mt-1 text-slate-700">{claim.reasoning}</p>}
              <p className="mt-1 text-xs text-slate-500">
                {claim.source_refs.length > 0 ? `Evidence: ${claim.source_refs.join(", ")}` : "No evidence reference"}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function QualityView({ quality }: { quality?: QualityAssessment | null }) {
  if (!quality || !quality.scores) return <p className="text-slate-500">No quality assessment.</p>;
  return (
    <div className="space-y-3">
      <p>
        <span className="text-2xl font-bold">{quality.overall_score ?? "—"}</span>
        <span className="text-slate-500"> / 10 overall</span>
      </p>
      <dl className="grid gap-2 sm:grid-cols-2">
        {Object.entries(quality.scores).map(([name, item]) => (
          <div key={name} className="rounded-lg border border-slate-200 p-3">
            <dt className="flex items-center justify-between gap-2 font-medium">
              <span>{name.replaceAll("_", " ").replace(/^\w/, (c) => c.toUpperCase())}</span>
              <span>{item.score}/10</span>
            </dt>
            <dd className="mt-1 text-slate-600">{item.explanation}</dd>
          </div>
        ))}
      </dl>
      {quality.disclaimer && <p className="text-xs text-slate-500">{quality.disclaimer}</p>}
    </div>
  );
}

function ContentDeliverable({ output }: { output: FinalOutput }) {
  return (
    <>
      <Section title={output.content_draft?.title ? `Draft: ${output.content_draft.title}` : "Content draft"}>
        <DraftVersions versions={output.content_draft?.versions} />
      </Section>
      {output.open_issues && output.open_issues.length > 0 && (
        <Section title="Open issues">
          <p className="mb-2 text-slate-600">
            {output.revision_limit_reached
              ? "The automatic revision limit was reached with these issues still open. Request a revision or fix them in the content studio."
              : "Reviewers raised these points."}
          </p>
          <BulletList items={output.open_issues} />
        </Section>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Brand review"><BrandReviewView review={output.brand_review} /></Section>
        <Section title="Quality assessment"><QualityView quality={output.quality_assessment} /></Section>
      </div>
      {output.type === "social_content" && <Section title="Fact-check report"><FactCheckView report={output.fact_check} /></Section>}
      <div className="grid gap-4 lg:grid-cols-3">
        <Section title="Alternative hooks"><BulletList items={output.alternative_hooks} empty="None suggested." /></Section>
        <Section title="CTA recommendations"><BulletList items={output.cta_recommendations} empty="None suggested." /></Section>
        <Section title="Improvement suggestions"><BulletList items={output.improvement_suggestions} empty="None suggested." /></Section>
      </div>
    </>
  );
}

function ResearchDeliverable({ output, renderIdeaAction }: { output: FinalOutput; renderIdeaAction?: (index: number) => ReactNode }) {
  const research = output.research_findings;
  const strategy = output.strategic_recommendations;
  return (
    <>
      <Section title="Research findings">
        <p className="text-slate-700">{research?.summary}</p>
        <ul className="mt-3 space-y-2">
          {(research?.findings ?? []).map((finding, index) => (
            <li key={`${index}-${finding.claim.slice(0, 24)}`} className="rounded-lg border border-slate-200 p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <p className="font-medium">{finding.claim}</p>
                <Pill className={finding.verified ? CLASSIFICATION.SUPPORTED : CLASSIFICATION.UNVERIFIABLE}>
                  {finding.verified ? `Sourced (${finding.source_refs.join(", ")})` : "Assumption — no source"}
                </Pill>
              </div>
              {finding.explanation && <p className="mt-1 text-slate-700">{finding.explanation}</p>}
            </li>
          ))}
        </ul>
        {research?.assumptions && research.assumptions.length > 0 && (
          <div className="mt-3"><p className="font-medium">Assumptions</p><BulletList items={research.assumptions} /></div>
        )}
        {research?.limitations && research.limitations.length > 0 && (
          <div className="mt-3"><p className="font-medium">Limitations</p><BulletList items={research.limitations} /></div>
        )}
      </Section>
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Audience insights"><BulletList items={output.audience_insights} empty="None." /></Section>
        <Section title="Content opportunities"><BulletList items={output.content_opportunities} empty="None." /></Section>
      </div>
      <Section title="Strategic recommendations">
        <p className="text-slate-700">{strategy?.strategy_summary}</p>
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          <div><p className="font-medium">Recommended themes</p><BulletList items={strategy?.recommended_themes} empty="None." /></div>
          <div><p className="font-medium">Campaign objectives</p><BulletList items={strategy?.campaign_objectives} empty="None." /></div>
        </div>
        {strategy?.content_mix && strategy.content_mix.length > 0 && (
          <div className="mt-3">
            <p className="font-medium">Recommended content mix</p>
            <ul className="mt-1 space-y-1 text-slate-700">
              {strategy.content_mix.map((item) => <li key={item.format}>{item.share_percent}% {item.format} — {item.rationale}</li>)}
            </ul>
          </div>
        )}
        {strategy?.supporting_evidence && strategy.supporting_evidence.length > 0 && (
          <div className="mt-3">
            <p className="font-medium">Supporting evidence</p>
            <ul className="mt-1 space-y-1 text-slate-700">
              {strategy.supporting_evidence.map((item, index) => (
                <li key={`${index}-${item.statement.slice(0, 24)}`}>
                  <Pill className={item.basis === "assumption" ? CLASSIFICATION.UNVERIFIABLE : CLASSIFICATION.SUPPORTED}>{item.basis.replaceAll("_", " ")}</Pill> {item.statement}
                </li>
              ))}
            </ul>
          </div>
        )}
      </Section>
      <Section
        title="Suggested content ideas"
        aside={output.suggested_publishing_frequency ? (
          <span className="text-xs text-slate-500">Suggested frequency: {output.suggested_publishing_frequency.posts_per_week} posts per week (nothing is scheduled)</span>
        ) : undefined}
      >
        <ul className="space-y-2">
          {(output.content_ideas ?? []).map((idea, index) => (
            <li key={`${index}-${idea.title}`} className="rounded-lg border border-slate-200 p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="font-medium">{idea.title}</p>
                  <p className="text-xs text-slate-500">{idea.platform} · {idea.format.replaceAll("_", " ")}{idea.content_pillar ? ` · ${idea.content_pillar}` : ""}</p>
                </div>
                {renderIdeaAction?.(index)}
              </div>
              <p className="mt-1 text-slate-700">{idea.description}</p>
              {idea.suggested_hook && <p className="mt-1 text-slate-600">Hook: {idea.suggested_hook}</p>}
            </li>
          ))}
        </ul>
      </Section>
    </>
  );
}

function PerformanceDeliverable({ output }: { output: FinalOutput }) {
  const measured = output.measured_data;
  return (
    <>
      <Section
        title="Performance summary"
        aside={measured?.period ? <span className="text-xs text-slate-500">{measured.period.start} to {measured.period.end} · {measured.post_count ?? 0} measured posts</span> : undefined}
      >
        <p className="text-slate-700">{output.performance_summary}</p>
        {output.label && <p className="mt-2 text-xs text-slate-500">{output.label}</p>}
        {output.unverified_numbers && output.unverified_numbers.length > 0 && (
          <p className="mt-2 rounded-lg bg-amber-50 p-2 text-amber-900">
            Unverified numbers in the text (not in the measured data): {output.unverified_numbers.join(", ")}
          </p>
        )}
      </Section>
      <Section title="Content patterns">
        {(output.content_patterns ?? []).length === 0 ? <p className="text-slate-500">No patterns were identified.</p> : (
          <ul className="space-y-2">
            {(output.content_patterns ?? []).map((pattern, index) => (
              <li key={`${index}-${pattern.observation.slice(0, 24)}`} className="rounded-lg border border-slate-200 p-3">
                <p className="text-slate-700">{pattern.observation}</p>
                <p className="mt-1 text-xs text-slate-500">
                  {pattern.metric_refs.length > 0
                    ? `Measured: ${pattern.metric_refs.map((ref) => `${ref.metric} ${ref.value}${ref.scope ? ` (${ref.scope})` : ""}`).join("; ")}`
                    : "No measured value supports this observation."}
                </p>
              </li>
            ))}
          </ul>
        )}
      </Section>
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Improvement opportunities"><BulletList items={output.improvement_opportunities} empty="None." /></Section>
        <Section title="Data limitations"><BulletList items={output.data_limitations} empty="None reported." /></Section>
      </div>
      <Section title="Recommendations (AI interpretation)">
        {(output.recommendations ?? []).length === 0 ? <p className="text-slate-500">None.</p> : (
          <ul className="space-y-2 text-slate-700">
            {(output.recommendations ?? []).map((item, index) => (
              <li key={`${index}-${item.recommendation.slice(0, 24)}`}><span className="font-medium">{item.recommendation}</span>{item.rationale ? ` — ${item.rationale}` : ""}</li>
            ))}
          </ul>
        )}
        {output.strategic_recommendations?.strategy_summary && (
          <p className="mt-3 text-slate-700"><span className="font-medium">Strategy:</span> {output.strategic_recommendations.strategy_summary}</p>
        )}
      </Section>
      <Section title="Suggested experiments">
        {(output.suggested_experiments ?? []).length === 0 ? <p className="text-slate-500">None.</p> : (
          <ul className="space-y-2 text-slate-700">
            {(output.suggested_experiments ?? []).map((item, index) => (
              <li key={`${index}-${item.hypothesis.slice(0, 24)}`} className="rounded-lg border border-slate-200 p-3">
                <p className="font-medium">{item.hypothesis}</p>
                <p className="mt-1">Change: {item.change}</p>
                <p className="mt-1 text-slate-500">Measure: {item.measure}</p>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </>
  );
}

export function FinalDeliverable({ output, renderIdeaAction }: { output: FinalOutput; renderIdeaAction?: (index: number) => ReactNode }) {
  const evidence = output.type === "performance_analysis" ? output.metric_references : output.evidence;
  return (
    <div className="space-y-4">
      <WarningList warnings={output.warnings} />
      {output.type === "content_research" && <ResearchDeliverable output={output} renderIdeaAction={renderIdeaAction} />}
      {(output.type === "social_content" || output.type === "content_repurposing") && <ContentDeliverable output={output} />}
      {output.type === "performance_analysis" && <PerformanceDeliverable output={output} />}
      <Section title={output.type === "performance_analysis" ? "Supporting metric references" : "Evidence and citations"}>
        <EvidenceList evidence={evidence} />
      </Section>
    </div>
  );
}

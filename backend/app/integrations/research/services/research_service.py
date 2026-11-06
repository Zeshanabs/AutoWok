from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session as DBSession

from app.core.config import get_settings
from app.integrations.research.base import SearchProviderConfig, SearchResult
from app.integrations.research.providers.search_provider import ConfiguredSearchProvider
from app.integrations.research.retrieval.fetcher import validate_url
from app.models import ResearchFinding, ResearchProject, ResearchQuery, ResearchReport, ResearchSource, ResearchUsageLog


class ResearchEngineService:
    def __init__(self, db: DBSession, *, settings: Any | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def build_query_plan(self, project: ResearchProject) -> list[str]:
        questions = [project.research_question.strip()]
        keywords = []
        for query in self.db.query(ResearchQuery).filter(ResearchQuery.research_id == project.id).all():
            if query.query and query.query.strip():
                keywords.append(query.query.strip())
        for keyword in project.title.split()[:6]:
            questions.append(f"{keyword} {project.research_question.strip()}")
        for keyword in keywords:
            questions.append(keyword)
        unique: list[str] = []
        seen: set[str] = set()
        for item in questions:
            cleaned = " ".join(item.split())
            if cleaned and cleaned.lower() not in seen:
                seen.add(cleaned.lower())
                unique.append(cleaned)
        return unique[:10]

    def get_provider_config(self) -> SearchProviderConfig:
        provider_name = (self.settings.research_search_provider or "configured").strip() or "configured"
        return SearchProviderConfig(
            name=provider_name,
            api_key=(self.settings.research_search_api_key or "").strip(),
            base_url=(self.settings.research_search_base_url or "").strip() or "https://example.com",
            max_results=int(self.settings.research_max_results or 10),
            timeout_seconds=int(self.settings.research_timeout_seconds or 30),
        )

    def ensure_search_provider(self) -> SearchProviderConfig:
        config = self.get_provider_config()
        if not config.api_key:
            raise RuntimeError(
                "Research search provider is not configured. Set RESEARCH_SEARCH_PROVIDER and RESEARCH_SEARCH_API_KEY before running a research project."
            )
        if not config.name or config.name == "configured":
            raise RuntimeError(
                "Research search provider is not configured. Set RESEARCH_SEARCH_PROVIDER and RESEARCH_SEARCH_API_KEY before running a research project."
            )
        return config

    def search(self, project: ResearchProject) -> list[SearchResult]:
        config = self.ensure_search_provider()
        provider = ConfiguredSearchProvider(config)
        results: list[SearchResult] = []
        for query in self.build_query_plan(project):
            for result in provider.search(query, max_results=config.max_results, timeout_seconds=config.timeout_seconds):
                if not result.url:
                    continue
                if not validate_url(result.url):
                    continue
                if result.url not in {entry.url for entry in results}:
                    results.append(result)
                if len(results) >= config.max_results:
                    return results
        return results

    def create_default_report(self, project: ResearchProject, *, generated_by_model: str | None = None) -> ResearchReport:
        report = ResearchReport(
            research_id=project.id,
            executive_summary=(
                f"Research completed for {project.title}. "
                f"This report summarizes the topic, key opportunities, and evidence available at the time of review."
            ),
            key_findings=[project.research_question],
            trends=["Monitoring current signals and evidence is recommended before creating content."],
            opportunities=["Use the findings to build content angles and audience-focused messaging."],
            risks=["Evidence must be reviewed for recency and source quality before using claims in publish-ready content."],
            audience_insights=["Audience-specific evidence should be validated against comparable sources."],
            competitor_insights=["Competitor review is recommended when the research question relates to category performance."],
            content_angles=["Turn validated findings into educational, trend-led, or problem-solution angles."],
            limitations=["This report is based on the search provider configuration available in the current environment."],
            generated_by_model=generated_by_model,
        )
        self.db.add(report)
        self.db.flush()
        return report

    def create_usage_log(self, project: ResearchProject, *, provider_name: str, status: str, search_requests: int, model_name: str | None = None) -> ResearchUsageLog:
        log = ResearchUsageLog(
            workspace_id=project.workspace_id,
            research_id=project.id,
            search_provider=provider_name,
            ai_provider="groq",
            model_name=model_name,
            search_requests=search_requests,
            status=status,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(log)
        self.db.flush()
        return log

    def create_queries(self, project: ResearchProject) -> list[ResearchQuery]:
        queries = [
            project.research_question,
            f"{project.research_question} {project.category}",
            f"{project.research_question} {project.target_audience or 'target audience'}",
        ]
        if project.category:
            queries.append(f"{project.category} {project.research_question}")
        if project.geographic_scope:
            queries.append(f"{project.geographic_scope} {project.research_question}")
        seen: set[str] = set()
        result: list[ResearchQuery] = []
        for query in queries:
            cleaned = " ".join(query.split())
            if not cleaned or cleaned.lower() in seen:
                continue
            seen.add(cleaned.lower())
            record = ResearchQuery(research_id=project.id, query=cleaned, query_type="topic", status="PENDING")
            self.db.add(record)
            result.append(record)
        self.db.flush()
        return result

    def persist_source_result(self, project: ResearchProject, result: SearchResult) -> ResearchSource:
        source = ResearchSource(
            research_id=project.id,
            title=result.title,
            url=result.url,
            domain=result.domain,
            snippet=result.snippet,
            publication_date=result.publication_date,
            retrieved_at=datetime.now(timezone.utc),
            source_type="web",
            retrieval_status="retrieved",
            quality_metadata={
                "provider": result.provider,
                "source_quality": "needs_review",
                "domain": result.domain,
            },
        )
        self.db.add(source)
        self.db.flush()
        return source

    def persist_finding(self, project: ResearchProject, *, finding_type: str, claim: str, explanation: str | None, supporting_source_ids: list[str], confidence_label: str = "MEDIUM") -> ResearchFinding:
        row = ResearchFinding(
            research_id=project.id,
            finding_type=finding_type,
            claim=claim,
            explanation=explanation,
            confidence_label=confidence_label,
            supporting_source_ids=supporting_source_ids,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def export_markdown(self, project: ResearchProject, report: ResearchReport | None = None) -> str:
        title = project.title
        summary = report.executive_summary if report and report.executive_summary else "No executive summary available."
        sent = [
            f"# {title}",
            "",
            f"- Research question: {project.research_question}",
            f"- Category: {project.category}",
            f"- Status: {project.status}",
            "",
            "## Executive summary",
            summary,
            "",
            "## Key findings",
        ]
        if report and report.key_findings:
            for entry in report.key_findings:
                sent.append(f"- {entry}")
        else:
            sent.append("- No findings were generated.")
        return "\n".join(sent)

"""The eight specialized agents.

Each agent has two halves:

``prepare``   reads what it needs through its allowlisted tools and builds one prompt.
``finalize``  receives the model's answer *after* schema validation and checks it against
              the records the agent was given: citations must point at real source records,
              metric values must exist in the measured data, prohibited phrases are found by
              rule rather than trusted to the model.

Agents return data. They never approve, schedule or publish anything.
"""

from __future__ import annotations

import re
from statistics import mean
from typing import Any

from app.integrations.research.services.citation_service import CitationValidationService
from app.services.agents import schemas as S
from app.services.agents.llm import UNTRUSTED_RULES, AgentOutputError, AgentRunError, json_instructions, untrusted
from app.services.agents.registry import (
    AgentSpec,
    ExecutionLimits,
    Finalized,
    ModelConfig,
    Prepared,
    register_agent,
)
from app.services.agents.tools import AgentContext, ToolBox
from app.services.content_studio import ContentStudioService

CONTENT_FORMATS = {
    "text_post", "image_post", "carousel", "reel", "story", "promotional", "educational",
    "announcement", "testimonial", "product_promotion", "engagement",
}
QUALITY_DISCLAIMER = (
    "Scores are editorial assessments by an AI reviewer. They are not predictions of reach, "
    "engagement or any other performance result."
)
ANALYTICS_LABEL = (
    "Metric references are measured values from Autowok analytics. Everything else is AI interpretation: "
    "it describes patterns and does not establish why a post performed as it did."
)
HUMAN_APPROVAL_NOTE = (
    "This review is advisory. Only an authorized workspace reviewer can approve content."
)


def _header(key: str, version: str, role: str) -> str:
    return f"AGENT: {key} v{version}\nYou are the {role} in a marketing team. You work only on the task below.\n\n{UNTRUSTED_RULES}\n"


# Shared helpers -------------------------------------------------------------------


def _brand(tools: ToolBox, brand_id: str | None) -> dict[str, Any] | None:
    return tools.call("get_brand_profile", brand_id=brand_id) if brand_id else None


def _brand_brief(brand: dict[str, Any] | None) -> dict[str, Any]:
    """The parts of the brand context agents need, without ids or URLs."""
    if not brand:
        return {"note": "No brand was selected. Use a neutral, professional voice."}
    voice = brand.get("voice") or {}
    return {
        "name": brand["brand"].get("name"),
        "industry": brand["brand"].get("industry"),
        "description": brand["brand"].get("description"),
        "voice": {key: voice.get(key) for key in (
            "tone", "personality", "writing_style", "communication_style", "preferred_phrases",
            "prohibited_phrases", "emoji_policy", "hashtag_policy", "call_to_action_style",
        )} if voice else None,
        "audiences": [
            {key: item.get(key) for key in ("name", "description", "pain_points", "goals", "preferred_platforms")}
            for item in (brand.get("audiences") or [])[:4]
        ],
        "content_pillars": [
            {key: item.get(key) for key in ("name", "description", "objective")}
            for item in (brand.get("content_pillars") or [])[:8]
        ],
        "goals": [
            {key: item.get(key) for key in ("type", "title", "description", "target_metric")}
            for item in (brand.get("goals") or [])[:6]
        ],
        "policies": [
            {key: item.get(key) for key in ("type", "name", "value", "severity")}
            for item in (brand.get("policies") or [])[:12]
        ],
    }


def _prohibited_phrases(brand: dict[str, Any] | None) -> list[str]:
    if not brand:
        return []
    phrases = list((brand.get("voice") or {}).get("prohibited_phrases") or [])
    for policy in brand.get("policies") or []:
        if str(policy.get("type") or "").lower() in {"prohibited_phrase", "prohibited_phrases", "banned_phrase", "prohibited_term"}:
            phrases.append(str(policy.get("value") or ""))
    cleaned = [" ".join(str(item).split()) for item in phrases]
    return list(dict.fromkeys(item for item in cleaned if len(item) >= 2))


def _sources(tools: ToolBox, research_ids: list[str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load research and give each source a short reference (S1, S2...) for the prompt."""
    if not research_ids:
        return {"projects": [], "sources": []}, []
    research = tools.call("get_research", research_ids=list(dict.fromkeys(research_ids)))
    refs = [
        S.SourceRef(
            ref=f"S{index}",
            source_id=item["source_id"],
            research_id=item["research_id"],
            title=item["title"],
            url=item["url"],
            domain=item.get("domain"),
        ).model_dump()
        for index, item in enumerate(research["sources"], start=1)
    ]
    return research, refs


def _source_prompt(research: dict[str, Any], refs: list[dict[str, Any]]) -> str:
    if not refs:
        return "No research sources are available. Do not cite any source; leave source_refs empty."
    snippets = {item["source_id"]: item.get("snippet") for item in research["sources"]}
    rows = [
        {"ref": ref["ref"], "title": ref["title"], "domain": ref["domain"], "text": snippets.get(ref["source_id"])}
        for ref in refs
    ]
    return (
        "Research sources. Cite them only by their ref (for example \"S1\"). Never cite anything else.\n"
        + untrusted("research_sources", rows, max_chars=7000)
    )


def _report_prompt(research: dict[str, Any]) -> str:
    reports = [
        {"title": project["title"], "question": project["research_question"], "report": project["report"]}
        for project in research["projects"]
        if project.get("report")
    ]
    return untrusted("research_reports", reports, max_chars=4000) if reports else ""


def _resolve_refs(refs: list[str], known: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Map model-supplied refs to real source ids. Returns (valid source ids, rejected refs)."""
    by_ref = {item["ref"].upper(): item for item in known}
    by_id = {item["source_id"]: item for item in known}
    candidate_ids: list[str] = []
    rejected: list[str] = []
    for raw in refs:
        token = str(raw).strip()
        match = by_ref.get(token.upper().strip("[]()"))
        if match is not None:
            candidate_ids.append(match["source_id"])
        elif token in by_id:
            candidate_ids.append(token)
        else:
            rejected.append(token)
    # Phase 4 citation validation is the final say on which ids are real.
    invalid = set(CitationValidationService.validate_references(None, candidate_ids, set(by_id)))  # type: ignore[arg-type]
    valid = list(dict.fromkeys(item for item in candidate_ids if item not in invalid))
    return valid, rejected + sorted(invalid)


def _evidence(source_ids: list[str], known: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {item["source_id"]: item for item in known}
    return [
        {"type": "research_source", **{key: by_id[sid][key] for key in ("source_id", "research_id", "title", "url", "domain")}}
        for sid in dict.fromkeys(source_ids)
        if sid in by_id
    ]


def _draft_versions(draft: dict[str, Any]) -> list[dict[str, Any]]:
    versions = draft.get("versions")
    return [item for item in versions if isinstance(item, dict)] if isinstance(versions, list) else []


def _draft_text(version: dict[str, Any]) -> str:
    return "\n".join(str(version.get(key) or "") for key in ("hook", "body", "cta"))


def _draft_prompt(draft: dict[str, Any]) -> str:
    compact = {
        "title": draft.get("title"),
        "versions": [
            {key: version.get(key) for key in ("platform", "hook", "body", "cta", "hashtags")}
            for version in _draft_versions(draft)
        ],
    }
    return untrusted("content_draft", compact, max_chars=8000)


def _require_draft(draft: dict[str, Any]) -> None:
    if not _draft_versions(draft):
        raise AgentRunError("There is no content draft to review.", kind="invalid_input")


# 1. Research Agent ----------------------------------------------------------------


def research_prepare(ctx: AgentContext, tools: ToolBox, inputs: S.ResearchInput) -> Prepared:
    warnings: list[str] = []
    research_ids = list(inputs.research_ids)
    if inputs.run_new_research or not research_ids:
        outcome = tools.call("run_research", question=inputs.task, brand_id=inputs.brand_id)
        if outcome.get("research_id"):
            research_ids.append(outcome["research_id"])
        if outcome.get("message"):
            warnings.append(f"External research: {outcome['message']}")
    research, refs = _sources(tools, research_ids)
    if not refs:
        warnings.append(
            "No external sources were available, so nothing in this research is verified. "
            "Every finding is an assumption until a search provider returns sources."
        )
    brand = _brand(tools, inputs.brand_id)
    prompt = "\n".join(
        [
            _header("research", "1.0.0", "Research Analyst"),
            f"Task: {inputs.task}",
            "Research the industry, competitors, audience needs, trends and content opportunities relevant to the task.",
            "Rules:",
            "- A finding is a fact only if at least one source supports it; then list the source refs in source_refs.",
            "- Anything you cannot tie to a source belongs in \"assumptions\", or is a finding with empty source_refs.",
            "- Do not describe a trend as current unless a source says so.",
            untrusted("brand_profile", _brand_brief(brand), max_chars=2500),
            _source_prompt(research, refs),
            _report_prompt(research),
            json_instructions(
                """
{"summary": "string",
 "findings": [{"claim": "string", "explanation": "string",
               "category": "industry|competitor|audience|trend|opportunity|other", "source_refs": ["S1"]}],
 "audience_needs": ["string"], "trends": ["string"], "content_opportunities": ["string"],
 "assumptions": ["string"], "limitations": ["string"]}"""
            ),
        ]
    )
    return Prepared(prompt=prompt, context={"refs": refs, "research_ids": research_ids}, warnings=warnings)


def research_finalize(ctx: AgentContext, prepared: Prepared, output: S.ResearchOutput) -> Finalized:
    refs = prepared.context["refs"]
    warnings: list[str] = []
    cited: list[str] = []
    rejected_total = 0
    for finding in output.findings:
        valid, rejected = _resolve_refs(finding.source_refs, refs)
        rejected_total += len(rejected)
        finding.source_ids = valid
        finding.source_refs = [ref["ref"] for ref in refs if ref["source_id"] in valid]
        finding.verified = bool(valid)
        cited.extend(valid)
    if rejected_total:
        warnings.append(f"Removed {rejected_total} citation(s) that do not match any retrieved source.")
    unverified = sum(1 for finding in output.findings if not finding.verified)
    if unverified:
        warnings.append(f"{unverified} finding(s) have no supporting source and are marked as unverified assumptions.")
    result = output.model_dump()
    result["research_ids"] = prepared.context["research_ids"]
    result["sources_available"] = len(refs)
    result["verified_findings"] = len(output.findings) - unverified
    return Finalized(result=result, evidence=_evidence(cited, refs), warnings=warnings)


# 2. Marketing Strategist Agent ----------------------------------------------------


def strategy_prepare(ctx: AgentContext, tools: ToolBox, inputs: S.StrategyInput) -> Prepared:
    warnings: list[str] = []
    brand = _brand(tools, inputs.brand_id)
    if brand is None:
        warnings.append("No brand was selected; the strategy is not tailored to a brand profile.")
    research, refs = _sources(tools, inputs.research_ids)
    analytics = inputs.analytics_insights
    if analytics is None and inputs.analytics_days:
        analytics = tools.call("get_analytics", days=inputs.analytics_days, brand_id=inputs.brand_id)
    parts = [
        _header("marketing_strategist", "1.0.0", "Marketing Strategist"),
        f"Task: {inputs.task}",
        "Create a marketing content strategy from the brand profile, the research and the analytics provided.",
        "Rules:",
        "- Every supporting_evidence item states its basis: research (with source_refs), analytics, brand_profile or assumption.",
        "- Use basis \"research\" only when you cite a source ref. Otherwise use \"assumption\" and list it under assumptions too.",
        "- Do not promise results. share_percent values of content_mix should add up to about 100.",
        untrusted("brand_profile", _brand_brief(brand), max_chars=3500),
    ]
    if inputs.research_findings:
        parts.append(untrusted("research_agent_findings", inputs.research_findings, max_chars=5000))
    parts.append(_source_prompt(research, refs))
    parts.append(_report_prompt(research))
    if analytics:
        parts.append(untrusted("analytics", analytics, max_chars=4500))
    else:
        parts.append("No analytics are available. Say so under limitations.")
    parts.append(
        json_instructions(
            """
{"strategy_summary": "string", "audience_insights": ["string"], "recommended_themes": ["string"],
 "content_pillars": ["string"], "campaign_objectives": ["string"],
 "content_mix": [{"format": "string", "share_percent": 40, "rationale": "string"}],
 "supporting_evidence": [{"statement": "string", "basis": "research|analytics|brand_profile|assumption", "source_refs": ["S1"]}],
 "assumptions": ["string"], "limitations": ["string"]}"""
        )
    )
    return Prepared(
        prompt="\n".join(part for part in parts if part),
        context={"refs": refs, "has_analytics": bool(analytics), "has_brand": brand is not None},
        warnings=warnings,
    )


def strategy_finalize(ctx: AgentContext, prepared: Prepared, output: S.StrategyOutput) -> Finalized:
    refs = prepared.context["refs"]
    warnings: list[str] = []
    cited: list[str] = []
    downgraded = 0
    for item in output.supporting_evidence:
        valid, _rejected = _resolve_refs(item.source_refs, refs)
        item.source_ids = valid
        item.source_refs = [ref["ref"] for ref in refs if ref["source_id"] in valid]
        cited.extend(valid)
        unsupported = (
            (item.basis == "research" and not valid)
            or (item.basis == "analytics" and not prepared.context["has_analytics"])
            or (item.basis == "brand_profile" and not prepared.context["has_brand"])
        )
        if unsupported:
            item.basis = "assumption"
            downgraded += 1
    if downgraded:
        warnings.append(f"{downgraded} evidence statement(s) had no usable support and were relabelled as assumptions.")
    return Finalized(result=output.model_dump(), evidence=_evidence(cited, refs), warnings=warnings)


# 3. Content Planner Agent ---------------------------------------------------------


def plan_prepare(ctx: AgentContext, tools: ToolBox, inputs: S.PlanInput) -> Prepared:
    brand = _brand(tools, inputs.brand_id)
    research, refs = _sources(tools, inputs.research_ids)
    parts = [
        _header("content_planner", "1.0.0", "Content Planner"),
        f"Task: {inputs.task}",
        f"Create {inputs.idea_count} content idea(s) for these platforms only: {', '.join(inputs.platforms)}.",
        "Rules:",
        "- Each idea targets exactly one of the listed platforms.",
        f"- format is one of: {', '.join(sorted(CONTENT_FORMATS))}.",
        "- suggested_publishing_frequency is advice for the team. You do not schedule anything.",
        "- Cite source refs only for ideas that rest on a research source.",
        untrusted("brand_profile", _brand_brief(brand), max_chars=3000),
    ]
    if inputs.strategy:
        parts.append(untrusted("marketing_strategy", inputs.strategy, max_chars=5000))
    if inputs.research_findings:
        parts.append(untrusted("research_agent_findings", inputs.research_findings, max_chars=4000))
    if inputs.source_content:
        parts.append("Plan how to repurpose this approved content for each platform.")
        parts.append(untrusted("approved_source_content", inputs.source_content, max_chars=6000))
    parts.append(_source_prompt(research, refs))
    parts.append(
        json_instructions(
            """
{"ideas": [{"title": "string", "description": "string", "content_angle": "string", "platform": "facebook|instagram",
            "format": "text_post", "content_pillar": "string or null", "objective": "string",
            "suggested_hook": "string", "source_refs": ["S1"]}],
 "suggested_publishing_frequency": {"posts_per_week": 3, "rationale": "string"},
 "platform_adaptations": [{"platform": "facebook|instagram", "guidance": "string"}],
 "notes": ["string"]}"""
        )
    )
    return Prepared(prompt="\n".join(part for part in parts if part), context={"refs": refs, "platforms": list(inputs.platforms)})


def plan_finalize(ctx: AgentContext, prepared: Prepared, output: S.PlanOutput) -> Finalized:
    refs = prepared.context["refs"]
    platforms = prepared.context["platforms"]
    warnings: list[str] = []
    kept = [idea for idea in output.ideas if idea.platform in platforms]
    if not kept:
        raise AgentOutputError("The plan contains no idea for the requested platform(s).")
    if len(kept) != len(output.ideas):
        warnings.append(f"Dropped {len(output.ideas) - len(kept)} idea(s) for platforms that were not requested.")
    output.ideas = kept
    output.platform_adaptations = [item for item in output.platform_adaptations if item.platform in platforms]
    cited: list[str] = []
    rejected_total = 0
    for idea in output.ideas:
        if idea.format not in CONTENT_FORMATS:
            idea.format = "text_post"
        valid, rejected = _resolve_refs(idea.source_refs, refs)
        rejected_total += len(rejected)
        idea.source_ids = valid
        idea.source_refs = [ref["ref"] for ref in refs if ref["source_id"] in valid]
        cited.extend(valid)
    if rejected_total:
        warnings.append(f"Removed {rejected_total} citation(s) that do not match any retrieved source.")
    result = output.model_dump()
    result["scheduling_note"] = "Publishing frequency is a suggestion. Nothing was scheduled."
    return Finalized(result=result, evidence=_evidence(cited, refs), warnings=warnings)


# 4. Content Writer Agent ----------------------------------------------------------


def writer_prepare(ctx: AgentContext, tools: ToolBox, inputs: S.WriterInput) -> Prepared:
    brand = _brand(tools, inputs.brand_id)
    research, refs = _sources(tools, inputs.research_ids)
    parts = [
        _header("content_writer", "1.0.0", "Content Writer"),
        f"Task: {inputs.task}",
        f"Write one social media post version for each of these platforms: {', '.join(inputs.platforms)}.",
        "Rules:",
        "- Follow the brand voice. Never use a prohibited phrase from the brand profile.",
        "- Facebook: conversational, can be longer, at most 10 hashtags. Instagram: strong first line, at most 2,200 characters and 30 hashtags.",
        "- Every hashtag starts with #. Each version needs a hook, a body and a call to action.",
        "- Only state facts that the research sources or the approved source content support. Do not invent statistics, quotes or customer results.",
        "- List every factual statement you made in factual_claims (leave it empty if the post states no facts).",
        untrusted("brand_profile", _brand_brief(brand), max_chars=3000),
    ]
    if inputs.plan:
        parts.append(untrusted("content_plan", inputs.plan, max_chars=4500))
    if inputs.source_content:
        parts.append("Repurpose the approved source content below. Keep its meaning; adapt length and style per platform.")
        parts.append(untrusted("approved_source_content", inputs.source_content, max_chars=6000))
    parts.append(_source_prompt(research, refs))
    if inputs.previous_draft:
        parts.append(f"This is revision round {inputs.revision_round}. Improve the previous draft; keep what already works.")
        parts.append(_draft_prompt(inputs.previous_draft))
        if inputs.revision_requests:
            parts.append(untrusted("revision_requests", inputs.revision_requests, max_chars=3500))
    parts.append(
        json_instructions(
            """
{"title": "string",
 "versions": [{"platform": "facebook|instagram", "hook": "string", "body": "string", "cta": "string", "hashtags": ["#tag"]}],
 "alternative_hooks": ["string"], "cta_recommendations": ["string"],
 "factual_claims": ["string"], "notes": ["string"]}"""
        )
    )
    return Prepared(
        prompt="\n".join(part for part in parts if part),
        context={"platforms": list(inputs.platforms), "prohibited": _prohibited_phrases(brand), "round": inputs.revision_round},
    )


def writer_finalize(ctx: AgentContext, prepared: Prepared, output: S.WriterOutput) -> Finalized:
    platforms = prepared.context["platforms"]
    by_platform: dict[str, S.DraftVersion] = {}
    for version in output.versions:
        if version.platform in platforms and version.platform not in by_platform:
            by_platform[version.platform] = version
    missing = [platform for platform in platforms if platform not in by_platform]
    if missing:
        raise AgentOutputError(f"The draft is missing a version for: {', '.join(missing)}.")
    output.versions = [by_platform[platform] for platform in platforms]
    studio = ContentStudioService(ctx.db)
    warnings: list[str] = []
    validation: list[dict[str, Any]] = []
    for version in output.versions:
        report = studio.platform_validation(version.platform, version.model_dump())
        if report["errors"]:
            raise AgentOutputError(f"The {version.platform} version breaks platform rules: {'; '.join(report['errors'])}")
        warnings.extend(f"{version.platform}: {item}" for item in report["warnings"])
        validation.append(report)
        text = _draft_text(version.model_dump()).lower()
        used = [phrase for phrase in prepared.context["prohibited"] if phrase.lower() in text]
        if used:
            warnings.append(f"{version.platform}: uses prohibited phrase(s): {', '.join(used)}.")
    result = output.model_dump()
    result["platform_validation"] = validation
    result["revision_round"] = prepared.context["round"]
    result["status_note"] = "Draft only. It is not saved to the content studio until a person accepts it."
    return Finalized(result=result, warnings=warnings)


# 5. Brand Guardian Agent ----------------------------------------------------------


def brand_prepare(ctx: AgentContext, tools: ToolBox, inputs: S.BrandReviewInput) -> Prepared:
    _require_draft(inputs.draft)
    brand = _brand(tools, inputs.brand_id)
    warnings = [] if brand else ["No brand was selected; the review used general professional standards only."]
    rule_issues: list[dict[str, Any]] = []
    for version in _draft_versions(inputs.draft):
        text = _draft_text(version) + "\n" + " ".join(str(tag) for tag in version.get("hashtags") or [])
        for phrase in _prohibited_phrases(brand):
            if phrase.lower() in text.lower():
                rule_issues.append(
                    S.BrandIssue(
                        category="prohibited_phrase",
                        severity="high",
                        platform=version.get("platform") if version.get("platform") in S.PLATFORMS else None,
                        excerpt=phrase,
                        explanation=f"The draft uses \"{phrase}\", which the brand profile prohibits.",
                        suggestion="Remove or replace this phrase.",
                        detected_by="rule",
                    ).model_dump()
                )
    prompt = "\n".join(
        [
            _header("brand_guardian", "1.0.0", "Brand Guardian"),
            "Review the content draft against the brand profile: tone, terminology, prohibited phrases, "
            "unsupported claims and brand policies.",
            "Rules:",
            "- Report only real problems, each with the exact excerpt, a severity and a concrete suggestion.",
            "- Use severity high only for prohibited phrases, policy violations or claims the brand could not stand behind.",
            "- You give advice. You do not approve content.",
            untrusted("brand_profile", _brand_brief(brand), max_chars=4000),
            _draft_prompt(inputs.draft),
            json_instructions(
                """
{"assessment": "consistent|minor_issues|major_issues", "summary": "string",
 "issues": [{"category": "tone|terminology|prohibited_phrase|unsupported_claim|guideline", "severity": "low|medium|high",
             "platform": "facebook|instagram|null", "excerpt": "string", "explanation": "string", "suggestion": "string"}],
 "suggested_improvements": ["string"]}"""
            ),
        ]
    )
    return Prepared(prompt=prompt, context={"rule_issues": rule_issues}, warnings=warnings)


def brand_finalize(ctx: AgentContext, prepared: Prepared, output: S.BrandReviewOutput) -> Finalized:
    rule_issues = prepared.context["rule_issues"]
    known = {(item["platform"], item["excerpt"].lower()) for item in rule_issues}
    model_issues = []
    for issue in output.issues:
        issue.detected_by = "model"
        if issue.category == "prohibited_phrase" and (issue.platform, issue.excerpt.lower()) in known:
            continue
        model_issues.append(issue.model_dump())
    issues = rule_issues + model_issues
    severities = {item["severity"] for item in issues}
    if "high" in severities:
        assessment = "major_issues"
    elif issues:
        assessment = "major_issues" if output.assessment == "major_issues" else "minor_issues"
    else:
        assessment = "consistent"
    result = output.model_dump()
    result.update(
        {
            "assessment": assessment,
            "issues": issues,
            "issue_counts": {level: sum(1 for item in issues if item["severity"] == level) for level in ("high", "medium", "low")},
            "human_approval_required": True,
            "approval_note": HUMAN_APPROVAL_NOTE,
        }
    )
    warnings = [f"{len(rule_issues)} prohibited phrase(s) were found by rule check."] if rule_issues else []
    return Finalized(result=result, warnings=warnings)


# 6. Fact-Checker Agent ------------------------------------------------------------

EVIDENCE_REQUIRED = {"SUPPORTED", "PARTIALLY_SUPPORTED", "CONTRADICTED"}


def fact_prepare(ctx: AgentContext, tools: ToolBox, inputs: S.FactCheckInput) -> Prepared:
    _require_draft(inputs.draft)
    research, refs = _sources(tools, inputs.research_ids)
    claims = [str(item) for item in (inputs.draft.get("factual_claims") or []) if str(item).strip()][:20]
    warnings = [] if refs else [
        "No research sources were available, so no claim could be confirmed. Factual claims are UNVERIFIABLE or UNSUPPORTED."
    ]
    prompt = "\n".join(
        [
            _header("fact_checker", "1.0.0", "Fact-Checker"),
            "Identify the factual claims in the content draft and compare each one with the research sources.",
            "Classifications:",
            "- SUPPORTED: a source states it. PARTIALLY_SUPPORTED: a source supports part of it.",
            "- CONTRADICTED: a source says otherwise. UNSUPPORTED: a checkable claim that no source backs.",
            "- OPINION: a judgement or brand promise, not a checkable fact. UNVERIFIABLE: cannot be checked with these sources.",
            "Rules:",
            "- SUPPORTED, PARTIALLY_SUPPORTED and CONTRADICTED must list the source refs that show it.",
            "- Never cite a source that does not say what you claim. If unsure, use UNVERIFIABLE.",
            untrusted("claims_listed_by_writer", claims, max_chars=3000) if claims else "The writer listed no claims; find them in the draft yourself.",
            _draft_prompt(inputs.draft),
            _source_prompt(research, refs),
            json_instructions(
                """
{"claims": [{"claim": "string",
             "classification": "SUPPORTED|PARTIALLY_SUPPORTED|UNSUPPORTED|CONTRADICTED|OPINION|UNVERIFIABLE",
             "reasoning": "string", "source_refs": ["S1"]}],
 "summary": "string"}"""
            ),
        ]
    )
    return Prepared(prompt=prompt, context={"refs": refs}, warnings=warnings)


def fact_finalize(ctx: AgentContext, prepared: Prepared, output: S.FactCheckOutput) -> Finalized:
    refs = prepared.context["refs"]
    warnings: list[str] = []
    cited: list[str] = []
    downgraded = 0
    rejected_total = 0
    for claim in output.claims:
        valid, rejected = _resolve_refs(claim.source_refs, refs)
        rejected_total += len(rejected)
        claim.source_ids = valid
        claim.source_refs = [ref["ref"] for ref in refs if ref["source_id"] in valid]
        cited.extend(valid)
        if claim.classification in EVIDENCE_REQUIRED and not valid:
            claim.reasoning = (
                f"Originally classified {claim.classification}, but no valid source reference was given. {claim.reasoning}"
            ).strip()[: S.MEDIUM]
            claim.classification = "UNVERIFIABLE"
            downgraded += 1
    if rejected_total:
        warnings.append(f"Removed {rejected_total} citation(s) that do not match any retrieved source.")
    if downgraded:
        warnings.append(f"{downgraded} claim(s) were downgraded to UNVERIFIABLE because their evidence could not be confirmed.")
    counts = {name: sum(1 for claim in output.claims if claim.classification == name) for name in S.FACT_CLASSIFICATIONS}
    factual = len(output.claims) - counts["OPINION"]
    result = output.model_dump()
    result["counts"] = counts
    result["citation_coverage"] = {
        "factual_claims": factual,
        "claims_with_evidence": sum(1 for claim in output.claims if claim.source_ids),
        "sources_available": len(refs),
    }
    result["needs_attention"] = counts["UNSUPPORTED"] + counts["CONTRADICTED"]
    return Finalized(result=result, evidence=_evidence(cited, refs), warnings=warnings)


# 7. Content Quality Agent ---------------------------------------------------------


def quality_prepare(ctx: AgentContext, tools: ToolBox, inputs: S.QualityInput) -> Prepared:
    _require_draft(inputs.draft)
    prompt = "\n".join(
        [
            _header("content_quality", "1.0.0", "Content Quality Editor"),
            "Evaluate the editorial quality of the content draft. Score each criterion from 1 (poor) to 10 (excellent) "
            "and explain the score in one or two sentences.",
            "Criteria: clarity, readability, structure, hook_strength, cta_quality, platform_suitability "
            "(does each version fit the conventions of its platform?).",
            "Rules:",
            "- These are editorial judgements. Do not predict engagement, reach or sales.",
            "- List repeated words or ideas under repetition_issues and concrete edits under improvements.",
            f"Brief the draft was written for: {inputs.task or 'not provided'}",
            _draft_prompt(inputs.draft),
            json_instructions(
                """
{"scores": {"clarity": {"score": 7, "explanation": "string"}, "readability": {"score": 7, "explanation": "string"},
            "structure": {"score": 7, "explanation": "string"}, "hook_strength": {"score": 7, "explanation": "string"},
            "cta_quality": {"score": 7, "explanation": "string"}, "platform_suitability": {"score": 7, "explanation": "string"}},
 "repetition_issues": ["string"], "improvements": ["string"], "summary": "string"}"""
            ),
        ]
    )
    return Prepared(prompt=prompt)


def quality_finalize(ctx: AgentContext, prepared: Prepared, output: S.QualityOutput) -> Finalized:
    result = output.model_dump()
    values = [item["score"] for item in result["scores"].values()]
    result["overall_score"] = round(mean(values), 1)
    result["lowest_criteria"] = sorted(result["scores"], key=lambda key: result["scores"][key]["score"])[:2]
    result["disclaimer"] = QUALITY_DISCLAIMER
    return Finalized(result=result)


# 8. Analytics Strategist Agent ----------------------------------------------------

NUMBER_PATTERN = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")


def _numbers_in(value: Any, found: set[float] | None = None) -> set[float]:
    """Every numeric value present in the measured data (used to reject invented metrics)."""
    found = set() if found is None else found
    if isinstance(value, bool) or value is None:
        return found
    if isinstance(value, (int, float)):
        found.add(round(float(value), 2))
    elif isinstance(value, dict):
        for item in value.values():
            _numbers_in(item, found)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _numbers_in(item, found)
    return found


def _is_measured(value: float, allowed: set[float]) -> bool:
    return any(abs(round(float(value), 2) - item) <= 0.01 for item in allowed)


def _unverified_numbers(text: str, allowed: set[float]) -> list[str]:
    unknown: list[str] = []
    for token in NUMBER_PATTERN.findall(text):
        try:
            number = float(token.replace(",", ""))
        except ValueError:
            continue
        if abs(number) < 10 and number == int(number):
            continue  # small counts ("3 posts", "2 formats") are not metric claims
        if not _is_measured(number, allowed) and token not in unknown:
            unknown.append(token)
    return unknown


def analytics_prepare(ctx: AgentContext, tools: ToolBox, inputs: S.AnalyticsInput) -> Prepared:
    data = tools.call("get_analytics", days=inputs.days, brand_id=inputs.brand_id)
    context = {"data": data, "allowed": sorted(_numbers_in(data) | {float(inputs.days)})}
    if not data.get("post_count"):
        reason = (
            "No Facebook or Instagram account is connected for analytics."
            if not data.get("connected_accounts")
            else f"No measured posts were found in the last {inputs.days} days."
        )
        return Prepared(
            prompt=None,
            context=context,
            warnings=[f"{reason} No analysis was generated."],
            static_result=S.AnalyticsOutput(
                performance_summary=f"{reason} There is nothing to interpret yet.",
                data_limitations=[
                    reason,
                    "Publish content and let analytics synchronize before running a performance analysis.",
                ],
            ).model_dump(),
        )
    prompt = "\n".join(
        [
            _header("analytics_strategist", "1.0.0", "Analytics Strategist"),
            f"Task: {inputs.task}",
            "Interpret the measured social media analytics below.",
            "Rules:",
            "- Use ONLY numbers that appear in the analytics data. Never estimate, extrapolate or round to a new value.",
            "- Every pattern lists the measured values it rests on in metric_refs, copied exactly from the data.",
            "- null means the metric was unavailable. Never treat it as zero.",
            "- Facebook and Instagram define reach and engagement differently. Do not add or directly compare them as equals.",
            "- Describe what happened. Do not claim to know why, and do not predict results. Experiments are hypotheses to test.",
            "- If the sample is small or data is missing, say so in data_limitations.",
            untrusted("analytics", data, max_chars=9000),
            json_instructions(
                """
{"performance_summary": "string",
 "patterns": [{"observation": "string", "metric_refs": [{"metric": "engagements", "value": 120, "scope": "top Instagram post"}]}],
 "opportunities": ["string"],
 "recommendations": [{"recommendation": "string", "rationale": "string"}],
 "experiments": [{"hypothesis": "string", "change": "string", "measure": "string"}],
 "data_limitations": ["string"]}"""
            ),
        ]
    )
    return Prepared(prompt=prompt, context=context)


def analytics_finalize(ctx: AgentContext, prepared: Prepared, output: S.AnalyticsOutput) -> Finalized:
    data = prepared.context["data"]
    allowed = set(prepared.context["allowed"])
    warnings: list[str] = []
    evidence: list[dict[str, Any]] = []
    removed = 0
    for pattern in output.patterns:
        kept = []
        for ref in pattern.metric_refs:
            if _is_measured(ref.value, allowed):
                kept.append(ref)
                evidence.append({"type": "metric", "metric": ref.metric, "value": ref.value, "scope": ref.scope})
            else:
                removed += 1
        pattern.metric_refs = kept
    if removed:
        warnings.append(f"Removed {removed} metric reference(s) whose values are not in the measured analytics data.")
    narrative = " ".join(
        [output.performance_summary]
        + [pattern.observation for pattern in output.patterns]
        + [item.rationale for item in output.recommendations]
    )
    unknown = _unverified_numbers(narrative, allowed)
    if unknown:
        warnings.append(
            "The text mentions number(s) that are not in the measured data and should be treated as unverified: "
            + ", ".join(unknown[:8])
        )
    result = output.model_dump()
    result["unverified_numbers"] = unknown[:8]
    result["measured_data"] = {
        "period": data.get("period"),
        "post_count": data.get("post_count"),
        "connected_accounts": data.get("connected_accounts"),
        "period_change": data.get("period_change"),
        "ranking_method": data.get("ranking_method"),
        "metric_notes": data.get("metric_notes"),
    }
    result["label"] = ANALYTICS_LABEL
    return Finalized(result=result, evidence=evidence, warnings=warnings)


# Registration ---------------------------------------------------------------------

RESEARCH = register_agent(
    AgentSpec(
        key="research",
        name="Research Agent",
        description="Researches industries, competitors, audiences and trends and returns findings with source references.",
        responsibility="External and stored research with citations. Uses the Phase 4 research engine and its search provider.",
        version="1.0.0",
        input_model=S.ResearchInput,
        output_model=S.ResearchOutput,
        tools=("get_brand_profile", "get_research", "run_research"),
        prepare=research_prepare,
        finalize=research_finalize,
        model=ModelConfig(temperature=0.2, max_tokens=1800),
    )
)
MARKETING_STRATEGIST = register_agent(
    AgentSpec(
        key="marketing_strategist",
        name="Marketing Strategist Agent",
        description="Turns brand goals, audiences, research and analytics into a content strategy.",
        responsibility="Strategy summary, audience insights, themes, pillars, objectives and content mix, with evidence and assumptions kept apart.",
        version="1.0.0",
        input_model=S.StrategyInput,
        output_model=S.StrategyOutput,
        tools=("get_brand_profile", "get_research", "get_analytics"),
        prepare=strategy_prepare,
        finalize=strategy_finalize,
        model=ModelConfig(temperature=0.4, max_tokens=1800),
    )
)
CONTENT_PLANNER = register_agent(
    AgentSpec(
        key="content_planner",
        name="Content Planner Agent",
        description="Converts a strategy or source content into concrete content ideas per platform.",
        responsibility="Content ideas, formats, platform adaptations and a suggested publishing frequency. Never schedules.",
        version="1.0.0",
        input_model=S.PlanInput,
        output_model=S.PlanOutput,
        tools=("get_brand_profile", "get_research"),
        prepare=plan_prepare,
        finalize=plan_finalize,
        model=ModelConfig(temperature=0.6, max_tokens=1800),
    )
)
CONTENT_WRITER = register_agent(
    AgentSpec(
        key="content_writer",
        name="Content Writer Agent",
        description="Writes Facebook and Instagram captions, hooks and calls to action in the brand voice.",
        responsibility="Platform-specific draft versions that pass the content studio's platform validation. Drafts only.",
        version="1.0.0",
        input_model=S.WriterInput,
        output_model=S.WriterOutput,
        tools=("get_brand_profile", "get_research"),
        prepare=writer_prepare,
        finalize=writer_finalize,
        model=ModelConfig(temperature=0.7, max_tokens=2000),
    )
)
BRAND_GUARDIAN = register_agent(
    AgentSpec(
        key="brand_guardian",
        name="Brand Guardian Agent",
        description="Reviews a draft against brand voice, terminology, prohibited phrases and policies.",
        responsibility="Advisory brand consistency review with issues, severity and suggestions. Cannot approve content.",
        version="1.0.0",
        input_model=S.BrandReviewInput,
        output_model=S.BrandReviewOutput,
        tools=("get_brand_profile",),
        prepare=brand_prepare,
        finalize=brand_finalize,
        model=ModelConfig(temperature=0.2, max_tokens=1500),
    )
)
FACT_CHECKER = register_agent(
    AgentSpec(
        key="fact_checker",
        name="Fact-Checker Agent",
        description="Finds factual claims in a draft and compares them with stored research sources.",
        responsibility="Claim classification with evidence references and citation coverage. Never fabricates sources.",
        version="1.0.0",
        input_model=S.FactCheckInput,
        output_model=S.FactCheckOutput,
        tools=("get_research",),
        prepare=fact_prepare,
        finalize=fact_finalize,
        model=ModelConfig(temperature=0.1, max_tokens=1800),
    )
)
CONTENT_QUALITY = register_agent(
    AgentSpec(
        key="content_quality",
        name="Content Quality Agent",
        description="Scores clarity, readability, structure, hook, call to action and platform fit.",
        responsibility="Editorial scores with explanations and improvement suggestions. Not a performance prediction.",
        version="1.0.0",
        input_model=S.QualityInput,
        output_model=S.QualityOutput,
        tools=(),
        prepare=quality_prepare,
        finalize=quality_finalize,
        model=ModelConfig(temperature=0.2, max_tokens=1200),
    )
)
ANALYTICS_STRATEGIST = register_agent(
    AgentSpec(
        key="analytics_strategist",
        name="Analytics Strategist Agent",
        description="Interprets measured Facebook and Instagram analytics and suggests experiments.",
        responsibility="Performance summary, patterns with metric references, opportunities and experiments. Never invents metrics.",
        version="1.0.0",
        input_model=S.AnalyticsInput,
        output_model=S.AnalyticsOutput,
        tools=("get_analytics",),
        prepare=analytics_prepare,
        finalize=analytics_finalize,
        model=ModelConfig(temperature=0.2, max_tokens=1600),
        limits=ExecutionLimits(max_attempts=2),
    )
)

"""Analytics reports: a structured report document plus CSV and PDF renderers.

Reports contain only data already stored for the caller's workspace (the
filters are resolved against workspace accounts before this module is
called). Every report states the reporting period, the brand and accounts,
the metrics with their platform definitions, collection timestamps and an
explanation for every missing value.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.services.analytics import metrics as M
from app.services.analytics import queries as Q
from app.services.analytics.pdf import PdfDocument

REPORT_POST_LIMIT = 200


def _fmt(value: Any, unit: str | None = None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        text = f"{value:,.2f}" if unit == "percent" or value != int(value) else f"{int(value):,}"
    elif isinstance(value, int):
        text = f"{value:,}"
    elif isinstance(value, datetime):
        text = value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    else:
        text = str(value)
    if unit == "percent" and value is not None:
        text += "%"
    return text


def build_report(db: DBSession, filters: Q.AnalyticsFilters) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc)
    account_keys = ("followers", "reach", "views", "engagements", "likes", "comments", "shares", "saves", "video_views")
    metrics = Q.account_metric_summary(db, filters, account_keys)
    posts = Q.list_posts(db, filters, sort="engagements", order="desc", limit=REPORT_POST_LIMIT)["items"]
    insights = Q.account_insights(db, filters)
    counts = Q.published_post_counts(db, filters)
    growth = Q.follower_growth(db, filters)

    missing: list[str] = []
    for metric in metrics:
        for entry in metric["platforms"]:
            if entry["availability"] != "available" and entry.get("reason"):
                missing.append(f"{entry['platform_label']} - {metric['label']}: {entry['reason']}")
    for post in posts:
        for key, reason in post["metric_availability"].items():
            if key in Q.POST_SUMMARY_KEYS and post["metrics"].get(key) is None and reason.startswith("missing_permission"):
                missing.append(f"Post metrics on {post['platform_label']}: {Q._reason_text(reason)}")
                break
    seen: set[str] = set()
    missing = [item for item in missing if not (item in seen or seen.add(item))]

    definitions = []
    platforms = {account.platform for account in filters.accounts}
    for platform in sorted(platforms, key=M.PLATFORMS.index):
        for metric in M.account_metrics(platform) + M.post_metrics(platform):
            definitions.append(metric.to_dict())
    definitions.extend({"key": key, "platform": "both", "level": "derived", **value} for key, value in M.DERIVED_METRICS.items())

    return {
        "title": "Autowok analytics report",
        "generated_at": generated_at,
        "period": {"start": filters.start, "end": filters.end, "days": filters.days},
        "previous_period": dict(zip(("start", "end"), filters.previous)),
        "brand": {"id": filters.brand_id, "name": Q.brand_name(db, filters.brand_id)},
        "platform_filter": filters.platform,
        "accounts": [
            {
                "id": account.id,
                "display_name": account.display_name,
                "username": account.username,
                "platform": account.platform,
                "platform_label": M.PLATFORM_LABELS[account.platform],
                "connection_status": account.connection_status,
            }
            for account in filters.accounts
        ],
        "key_metrics": metrics,
        "follower_growth": growth,
        "published_posts": counts,
        "account_insights": insights,
        "posts": posts,
        "definitions": definitions,
        "missing_data": missing,
        "collection": {
            "newest_collected_at": max([p["collected_at"] for p in posts if p["collected_at"]] + [e["collected_at"] for m in metrics for e in m["platforms"] if e.get("collected_at")], default=None),
            "note": "Each value shows when it was retrieved from Meta. Meta data can lag by up to 48 hours.",
        },
    }


def render_csv(report: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["Autowok analytics report"])
    writer.writerow(["Generated at (UTC)", _fmt(report["generated_at"])])
    writer.writerow(["Period start", report["period"]["start"].isoformat(), "Period end", report["period"]["end"].isoformat(), "Days", report["period"]["days"]])
    writer.writerow(["Brand", report["brand"]["name"] or "All brands", "Platform filter", report["platform_filter"] or "All platforms"])
    writer.writerow([])
    writer.writerow(["Accounts"])
    writer.writerow(["Account", "Username", "Platform", "Connection status"])
    for account in report["accounts"]:
        writer.writerow([account["display_name"], account["username"] or "", account["platform_label"], account["connection_status"]])
    writer.writerow([])
    writer.writerow(["Key metrics (account level, per platform)"])
    writer.writerow(["Metric", "Platform", "Source metric", "Current value", "Previous value", "Change %", "Unit", "Availability", "Reason", "Collected at (UTC)", "Definition"])
    for metric in report["key_metrics"]:
        for entry in metric["platforms"]:
            writer.writerow(
                [
                    metric["label"],
                    entry["platform_label"],
                    entry.get("source_metric") or "",
                    _fmt(entry["value"]),
                    _fmt(entry["previous_value"]),
                    _fmt(entry["change_percent"], "percent"),
                    entry.get("unit") or "",
                    entry["availability"],
                    entry.get("reason") or "",
                    _fmt(entry.get("collected_at")),
                    entry.get("definition") or "",
                ]
            )
    writer.writerow([])
    writer.writerow(["Follower growth (calculated from snapshots)"])
    writer.writerow(["Account", "Platform", "Latest followers", "Change in period", "Snapshots", "Note"])
    for entry in report["follower_growth"]:
        writer.writerow([entry["account_name"], M.PLATFORM_LABELS[entry["platform"]], _fmt(entry["latest"]), _fmt(entry["change"]), entry["snapshots"], entry["note"] or ""])
    writer.writerow([])
    writer.writerow(["Published posts", report["published_posts"]["total"], "From Autowok", report["published_posts"]["from_autowok"], "Previous period", report["published_posts"]["previous_total"]])
    writer.writerow([])
    writer.writerow(["Post performance"])
    writer.writerow(
        ["Published at (UTC)", "Platform", "Account", "Format", "Source", "Caption", "Permalink", "Reach / unique viewers", "Views", "Engagements", "Engagement rate %", "Likes", "Comments", "Shares", "Saves", "Clicks", "Video views", "Unavailable metrics", "Collected at (UTC)"]
    )
    for post in report["posts"]:
        unavailable = ", ".join(f"{key}: {reason}" for key, reason in sorted(post["metric_availability"].items()) if key in Q.POST_SUMMARY_KEYS and post["metrics"].get(key) is None)
        metrics = post["metrics"]
        writer.writerow(
            [
                _fmt(post["published_at"]),
                post["platform_label"],
                post["account_name"] or "",
                post["content_format_label"] or "",
                post["source"],
                post["caption_preview"] or "",
                post["permalink"] or "",
                _fmt(metrics.get("reach")),
                _fmt(metrics.get("views")),
                _fmt(metrics.get("engagements")),
                _fmt(post["engagement_rate"], "percent"),
                _fmt(metrics.get("likes")),
                _fmt(metrics.get("comments")),
                _fmt(metrics.get("shares")),
                _fmt(metrics.get("saves")),
                _fmt(metrics.get("clicks")),
                _fmt(metrics.get("video_views")),
                unavailable,
                _fmt(post["collected_at"]),
            ]
        )
    writer.writerow([])
    writer.writerow(["Missing data explanations"])
    for item in report["missing_data"] or ["All requested metrics were available."]:
        writer.writerow([item])
    writer.writerow([])
    writer.writerow(["Metric definitions"])
    writer.writerow(["Key", "Platform", "Level", "Label", "Source", "Unit", "Definition"])
    for definition in report["definitions"]:
        writer.writerow(
            [
                definition["key"],
                definition.get("platform_label") or definition.get("platform"),
                definition.get("level"),
                definition.get("label"),
                definition.get("source_name") or definition.get("formula") or "",
                definition.get("unit") or "",
                definition.get("definition") or "",
            ]
        )
    writer.writerow([])
    writer.writerow(["Data collection", report["collection"]["note"], "Newest collection", _fmt(report["collection"]["newest_collected_at"])])
    return buffer.getvalue()


def render_pdf(report: dict[str, Any]) -> bytes:
    doc = PdfDocument(title=report["title"])
    doc.heading(report["title"], level=0)
    doc.paragraph(f"Generated {_fmt(report['generated_at'])}.")
    doc.paragraph(
        f"Reporting period: {report['period']['start'].isoformat()} to {report['period']['end'].isoformat()} "
        f"({report['period']['days']} days). Previous period: {report['previous_period']['start'].isoformat()} to {report['previous_period']['end'].isoformat()}."
    )
    doc.paragraph(f"Brand: {report['brand']['name'] or 'All brands'}. Platform filter: {report['platform_filter'] or 'All platforms'}.")
    doc.heading("Accounts")
    if report["accounts"]:
        doc.table(["Account", "Platform", "Status"], [[a["display_name"], a["platform_label"], a["connection_status"]] for a in report["accounts"]], [40, 18, 14])
    else:
        doc.paragraph("No accounts match the selected filters.")

    doc.heading("Key metrics (account level)")
    rows = []
    for metric in report["key_metrics"]:
        for entry in metric["platforms"]:
            rows.append([metric["label"], entry["platform_label"], _fmt(entry["value"]), _fmt(entry["previous_value"]), _fmt(entry["change_percent"], "percent"), entry["availability"]])
    doc.table(["Metric", "Platform", "Current", "Previous", "Change", "Availability"], rows, [30, 14, 12, 12, 10, 12])
    doc.paragraph("Values are per platform. Facebook and Instagram define reach, views and engagement differently; see the definitions section.")

    doc.heading("Audience growth (calculated)")
    doc.table(
        ["Account", "Platform", "Followers", "Change"],
        [[g["account_name"], M.PLATFORM_LABELS[g["platform"]], _fmt(g["latest"]), _fmt(g["change"])] for g in report["follower_growth"]],
        [40, 16, 14, 14],
    )
    counts = report["published_posts"]
    doc.paragraph(f"Published posts in period: {counts['total']} ({counts['from_autowok']} published through Autowok). Previous period: {counts['previous_total']}.")

    doc.heading("Post performance (top 25 by engagements)")
    post_rows = []
    for post in report["posts"][:25]:
        metrics = post["metrics"]
        post_rows.append(
            [
                _fmt(post["published_at"])[:10],
                post["platform_label"][:9],
                (post["content_format_label"] or "")[:11],
                _fmt(metrics.get("reach")),
                _fmt(metrics.get("views")),
                _fmt(metrics.get("engagements")),
                _fmt(post["engagement_rate"], "percent"),
                (post["caption_preview"] or post["external_post_id"])[:28],
            ]
        )
    doc.table(["Published", "Platform", "Format", "Reach", "Views", "Engage.", "Rate", "Caption"], post_rows, [10, 9, 11, 8, 8, 8, 8, 28])
    doc.paragraph("Engagement rate = engagements / reach x 100 using each platform's own definitions; n/a when reach is unavailable or zero.")

    doc.heading("Missing data")
    if report["missing_data"]:
        for item in report["missing_data"]:
            doc.bullet(item)
    else:
        doc.paragraph("All requested metrics were available.")

    doc.heading("Data collection")
    doc.paragraph(report["collection"]["note"])
    doc.paragraph(f"Newest collection: {_fmt(report['collection']['newest_collected_at'])}.")

    doc.heading("Metric definitions")
    for definition in report["definitions"]:
        platform = definition.get("platform_label") or definition.get("platform")
        source = definition.get("source_name") or definition.get("formula") or ""
        doc.bullet(f"{definition.get('label')} [{platform}, {source}]: {definition.get('definition')}")
    return doc.render()

from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import urlsplit


class SourceQualityService:
    @staticmethod
    def evaluate(url: str, *, snippet: str | None = None, publication_date: datetime | None = None) -> dict[str, object]:
        parsed = urlsplit(url)
        domain = parsed.netloc.lower() if parsed.netloc else "unknown"
        age_days = None
        if publication_date is not None:
            age_days = max(0, (datetime.utcnow() - publication_date.replace(tzinfo=None)).days)
        return {
            "domain": domain,
            "official_source": domain.endswith(".gov") or domain.endswith(".edu") or domain.endswith(".org"),
            "has_text": bool(snippet) and len(snippet.strip()) > 20,
            "recency_score": (0 if age_days is None else max(0, 30 - age_days)) / 30,
            "is_primary_source": "report" in url.lower() or "blog" not in url.lower(),
            "publication_date": publication_date,
        }

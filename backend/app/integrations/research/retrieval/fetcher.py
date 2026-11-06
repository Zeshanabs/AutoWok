from __future__ import annotations

from urllib.parse import urlsplit

import httpx


def validate_url(url: str) -> bool:
    if not url:
        return False
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.netloc:
        return False
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return False
    if parsed.hostname and parsed.hostname.startswith("."):
        return False
    return True


def fetch_page(url: str, *, timeout_seconds: float = 30.0) -> str:
    if not validate_url(url):
        raise ValueError("Unsafe or invalid source URL.")
    with httpx.Client(follow_redirects=True, timeout=timeout_seconds) as client:
        response = client.get(url)
        if response.status_code >= 400:
            raise RuntimeError(f"Source fetch failed with status {response.status_code}.")
        content_type = response.headers.get("content-type", "")
        if "text/" not in content_type and "application/xhtml" not in content_type and "application/xml" not in content_type:
            raise RuntimeError("Source content type is not readable text.")
        return response.text

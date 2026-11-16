"""HTTP-level protections shared by every route: body size limits, security
headers and a low-cardinality route label for logs and metrics."""

from __future__ import annotations

import json
from typing import Any

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

UPLOAD_PATH_SUFFIX = "/media-assets/upload"
# Multipart framing and the other form fields around the file itself.
_UPLOAD_OVERHEAD_BYTES = 1024 * 1024


class _BodyTooLarge(Exception):
    pass


class BodyLimitMiddleware:
    """Rejects request bodies above a limit *while they are being received*.

    Without this, a multipart upload is parsed and spooled to disk in full
    before the route (and its authentication) runs. The declared
    ``Content-Length`` is checked first; bodies sent without one (chunked) are
    counted as they arrive. Media uploads get the configured media limit, every
    other endpoint a small JSON limit. Uploads without a session cookie are
    refused before any of the body is read.
    """

    def __init__(self, app: ASGIApp, settings: Any) -> None:
        self.app = app
        self.settings = settings

    def _limit(self, path: str) -> int:
        if path.endswith(UPLOAD_PATH_SUFFIX):
            return max(self.settings.media_max_image_bytes, self.settings.media_max_video_bytes) + _UPLOAD_OVERHEAD_BYTES
        return self.settings.max_request_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in {"GET", "HEAD", "OPTIONS"}:
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        limit = self._limit(path)
        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}

        if path.endswith(UPLOAD_PATH_SUFFIX) and f"{self.settings.session_cookie_name}=" not in headers.get("cookie", ""):
            await _reply(send, 401, "Authentication required.")
            return
        declared = headers.get("content-length")
        if declared is not None:
            try:
                if int(declared) > limit:
                    await _reply(send, 413, _message(limit))
                    return
            except ValueError:
                await _reply(send, 400, "Invalid Content-Length header.")
                return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if not response_started:
                await _reply(send, 413, _message(limit))


def _message(limit: int) -> str:
    if limit >= 1024 * 1024:
        return f"The request is too large. The limit is {limit // (1024 * 1024)} MB."
    return f"The request is too large. The limit is {limit // 1024} KB."


async def _reply(send: Send, status_code: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def route_template(request: Request) -> str:
    """The matched route pattern (``/api/v1/brands/{brand_id}``), never the raw
    path, so identifiers do not end up in metric labels or access logs.

    Built from the request path by putting each path parameter's name back in
    place of its value. This does not depend on how the framework stores router
    prefixes, which has changed between FastAPI releases.
    """
    if request.scope.get("route") is None:
        return "unmatched"
    segments = request.scope.get("path", "").split("/")
    for name, value in (request.scope.get("path_params") or {}).items():
        text = str(value)
        for index, segment in enumerate(segments):
            if segment == text:
                segments[index] = "{" + name + "}"
                break
    return "/".join(segments)


_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


def security_headers(settings: Any, path: str) -> dict[str, str]:
    """Headers for API responses. The API returns JSON and media files only, so
    the policy forbids everything: nothing it returns may run script, be framed
    or load sub-resources. The interactive docs (development only) need their
    CDN assets and are exempt from the CSP."""
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Cross-Origin-Opener-Policy": "same-origin",
        # Media is loaded by the frontend origin and by Meta's fetchers.
        "Cross-Origin-Resource-Policy": "cross-origin",
    }
    if not path.startswith(_DOCS_PATHS):
        headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    if settings.secure_cookies:
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if path.startswith(settings.api_v1_prefix) and "/media" not in path:
        # API JSON is per-user; shared caches must never store it.
        headers["Cache-Control"] = "no-store"
    return headers

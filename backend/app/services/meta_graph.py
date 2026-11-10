from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import get_settings


META_SCOPES = ("pages_show_list", "pages_read_engagement", "instagram_basic")
# Publishing permissions are requested during login but are optional at
# callback time; publishing eligibility checks them per account.
FACEBOOK_PUBLISH_SCOPES = ("pages_manage_posts", "pages_read_engagement", "pages_show_list")
FACEBOOK_VIDEO_SCOPES = ("publish_video",)
INSTAGRAM_PUBLISH_SCOPES = ("instagram_basic", "instagram_content_publish", "pages_read_engagement")
META_REQUESTED_SCOPES = tuple(
    dict.fromkeys(META_SCOPES + FACEBOOK_PUBLISH_SCOPES + FACEBOOK_VIDEO_SCOPES + INSTAGRAM_PUBLISH_SCOPES)
)
PAGE_FIELDS = (
    "id,name,username,category,picture{url},"
    "access_token,tasks,"
    "instagram_business_account{id,username,account_type,profile_picture_url}"
)


class MetaGraphError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        code: int | None = None,
        *,
        subcode: int | None = None,
        meta_message: str | None = None,
        is_transient: bool = False,
        request_sent: bool = True,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.subcode = subcode
        # Meta error messages do not contain access tokens; they are still
        # truncated before storage.
        self.meta_message = (meta_message or "")[:500] or None
        self.is_transient = is_transient
        # False when the request provably never reached Meta (connection
        # refused/DNS failure), so a retry cannot create a duplicate post.
        self.request_sent = request_sent
        super().__init__("The Meta Graph API request could not be completed.")


class MetaGraphClient:
    def __init__(
        self,
        *,
        timeout_seconds: float = 15,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        settings = get_settings()
        self._settings = settings
        self._base_url = f"https://graph.facebook.com/{settings.meta_graph_api_version}"
        self._client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=transport is None,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> MetaGraphClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def authorization_url(self, *, state: str) -> str:
        settings = self._settings
        query = urlencode(
            {
                "client_id": settings.meta_app_id,
                "redirect_uri": settings.meta_redirect_uri,
                "response_type": "code",
                "scope": ",".join(META_REQUESTED_SCOPES),
                "state": state,
            }
        )
        return f"https://www.facebook.com/{settings.meta_graph_api_version}/dialog/oauth?{query}"

    def exchange_code(self, code: str) -> tuple[str, int | None]:
        settings = self._settings
        response = self._request(
            "GET",
            "/oauth/access_token",
            params={
                "client_id": settings.meta_app_id,
                "client_secret": settings.meta_app_secret,
                "redirect_uri": settings.meta_redirect_uri,
                "code": code,
            },
        )
        short_lived = response.get("access_token")
        if not isinstance(short_lived, str) or not short_lived:
            raise MetaGraphError(502)
        long_lived = self._request(
            "GET",
            "/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": settings.meta_app_id,
                "client_secret": settings.meta_app_secret,
                "fb_exchange_token": short_lived,
            },
        )
        access_token = long_lived.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise MetaGraphError(502)
        expires_in = long_lived.get("expires_in")
        return access_token, expires_in if isinstance(expires_in, int) else None

    def refresh_user_token(self, current_token: str) -> tuple[str, int | None]:
        settings = self._settings
        response = self._request(
            "GET",
            "/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": settings.meta_app_id,
                "client_secret": settings.meta_app_secret,
                "fb_exchange_token": current_token,
            },
        )
        access_token = response.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise MetaGraphError(502)
        expires_in = response.get("expires_in")
        return access_token, expires_in if isinstance(expires_in, int) else None

    def get(self, path: str, access_token: str, **params: Any) -> dict[str, Any]:
        return self._request(
            "GET",
            path,
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
        )

    def post(self, path: str, access_token: str, **data: Any) -> dict[str, Any]:
        return self._request(
            "POST",
            path,
            data={key: str(value) for key, value in data.items() if value is not None},
            headers={"Authorization": f"Bearer {access_token}"},
        )

    def list_pages(self, access_token: str) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(20):
            params: dict[str, str] = {"fields": PAGE_FIELDS, "limit": "100"}
            if cursor:
                params["after"] = cursor
            response = self.get("/me/accounts", access_token, **params)
            data = response.get("data")
            if not isinstance(data, list):
                raise MetaGraphError(502)
            pages.extend(page for page in data if isinstance(page, dict))
            paging = response.get("paging")
            cursors = paging.get("cursors") if isinstance(paging, dict) else None
            next_cursor = cursors.get("after") if isinstance(cursors, dict) else None
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
        return pages

    def get_user(self, access_token: str) -> dict[str, Any]:
        return self.get("/me", access_token, fields="id,name")

    def get_permissions(self, access_token: str) -> list[str]:
        response = self.get("/me/permissions", access_token)
        values = response.get("data")
        if not isinstance(values, list):
            return []
        return [
            item["permission"]
            for item in values
            if isinstance(item, dict)
            and item.get("status") == "granted"
            and isinstance(item.get("permission"), str)
        ]

    def get_social_account(
        self,
        *,
        account_id: str,
        platform: str,
        access_token: str,
    ) -> dict[str, Any]:
        fields = (
            "id,username,account_type,profile_picture_url"
            if platform == "instagram"
            else "id,name,username,category,picture{url}"
        )
        return self.get(f"/{account_id}", access_token, fields=fields)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self._client.request(
                method,
                f"{self._base_url}{path}",
                params=params,
                data=data,
                headers=headers,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise MetaGraphError(503, is_transient=True, request_sent=False) from exc
        except httpx.TimeoutException as exc:
            raise MetaGraphError(504, is_transient=True) from exc
        except httpx.HTTPError as exc:
            raise MetaGraphError(502, is_transient=True) from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise MetaGraphError(502) from exc
        if not response.is_success:
            error = body.get("error") if isinstance(body, dict) else None
            error = error if isinstance(error, dict) else {}
            code = error.get("code")
            subcode = error.get("error_subcode")
            message = error.get("error_user_msg") or error.get("message")
            raise MetaGraphError(
                response.status_code,
                code if isinstance(code, int) else None,
                subcode=subcode if isinstance(subcode, int) else None,
                meta_message=message if isinstance(message, str) else None,
                is_transient=bool(error.get("is_transient")),
            )
        if not isinstance(body, dict):
            raise MetaGraphError(502)
        return body

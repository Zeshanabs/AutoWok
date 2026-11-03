from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import get_settings


META_SCOPES = ("pages_show_list", "pages_read_engagement", "instagram_basic")
PAGE_FIELDS = (
    "id,name,username,category,picture{url},"
    "access_token,tasks,"
    "instagram_business_account{id,username,account_type,profile_picture_url}"
)


class MetaGraphError(RuntimeError):
    def __init__(self, status_code: int, code: int | None = None) -> None:
        self.status_code = status_code
        self.code = code
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
                "scope": ",".join(META_SCOPES),
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
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self._client.request(
                method,
                f"{self._base_url}{path}",
                params=params,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise MetaGraphError(504) from exc
        except httpx.HTTPError as exc:
            raise MetaGraphError(502) from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise MetaGraphError(502) from exc
        if not response.is_success:
            error = body.get("error") if isinstance(body, dict) else None
            code = error.get("code") if isinstance(error, dict) else None
            raise MetaGraphError(
                response.status_code,
                code if isinstance(code, int) else None,
            )
        if not isinstance(body, dict):
            raise MetaGraphError(502)
        return body

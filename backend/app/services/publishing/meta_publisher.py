"""Facebook Page and Instagram Professional publishing via the Graph API.

Every state change that matters for safe recovery (stage, container IDs,
child IDs) is persisted through ``checkpoint`` *before* the next Meta call, so
a crash or timeout can be resumed without publishing twice.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from app.models import ContentPublication, MediaAsset, SocialAccount
from app.services.meta_graph import MetaGraphClient, MetaGraphError
from app.services.publishing import errors as E

STAGE_PREPARING = "preparing"
STAGE_UPLOADING = "uploading_media"
STAGE_CONTAINER = "creating_container"
STAGE_PROCESSING = "awaiting_processing"
STAGE_PUBLISHING = "publishing"
STAGE_DONE = "done"


class PublishFailure(Exception):
    def __init__(self, failure: E.FailureClassification) -> None:
        super().__init__(failure.message)
        self.failure = failure


@dataclass
class PublishResult:
    external_post_id: str | None
    permalink: str | None
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class PublishContext:
    job: ContentPublication
    account: SocialAccount
    access_token: str
    media: list[MediaAsset]
    caption: str
    publish_format: str
    media_url: Callable[[MediaAsset], str]
    checkpoint: Callable[[], None]
    sleep: Callable[[float], None] = time.sleep
    poll_interval_seconds: float = 30
    max_polls: int = 10


def _id(response: dict[str, Any], key: str = "id") -> str:
    value = response.get(key)
    if not isinstance(value, (str, int)) or not str(value):
        raise PublishFailure(E.classification(E.PLATFORM_TEMPORARY, "Meta returned an unexpected response.", "bad_response"))
    return str(value)


def _set_stage(ctx: PublishContext, stage: str) -> None:
    ctx.job.stage = stage
    ctx.checkpoint()


class MetaPublisher:
    def __init__(self, graph_factory: Callable[[], MetaGraphClient] = MetaGraphClient) -> None:
        self._graph_factory = graph_factory

    def publish(self, ctx: PublishContext) -> PublishResult:
        with self._graph_factory() as graph:
            if ctx.account.platform == "facebook_page":
                return self._facebook(graph, ctx)
            return self._instagram(graph, ctx)

    # Facebook Pages -----------------------------------------------------

    def _facebook(self, graph: MetaGraphClient, ctx: PublishContext) -> PublishResult:
        page_id = ctx.account.platform_account_id
        token = ctx.access_token
        fmt = ctx.publish_format
        if fmt == "text":
            _set_stage(ctx, STAGE_PUBLISHING)
            response = graph.post(f"/{page_id}/feed", token, message=ctx.caption)
            post_id = _id(response)
        elif fmt == "photo":
            _set_stage(ctx, STAGE_PUBLISHING)
            response = graph.post(
                f"/{page_id}/photos", token, url=ctx.media_url(ctx.media[0]), message=ctx.caption or None
            )
            post_id = str(response.get("post_id") or _id(response))
        elif fmt == "multi_photo":
            _set_stage(ctx, STAGE_UPLOADING)
            children = list(ctx.job.external_child_ids or [])
            for asset in ctx.media[len(children):]:
                # Unpublished photos are not visible; re-uploading after a
                # crash cannot create a duplicate public post.
                response = graph.post(f"/{page_id}/photos", token, url=ctx.media_url(asset), published="false")
                children.append(_id(response))
                ctx.job.external_child_ids = list(children)
                ctx.checkpoint()
            _set_stage(ctx, STAGE_PUBLISHING)
            fields = {f"attached_media[{index}]": json.dumps({"media_fbid": child}) for index, child in enumerate(children)}
            response = graph.post(f"/{page_id}/feed", token, message=ctx.caption or None, **fields)
            post_id = _id(response)
        elif fmt == "video":
            _set_stage(ctx, STAGE_PUBLISHING)
            response = graph.post(
                f"/{page_id}/videos", token, file_url=ctx.media_url(ctx.media[0]), description=ctx.caption or None
            )
            post_id = _id(response)
        else:
            raise PublishFailure(E.classification(E.VALIDATION, "Unsupported Facebook post format."))
        ctx.job.external_post_id = post_id
        _set_stage(ctx, STAGE_DONE)
        permalink = None
        try:
            details = graph.get(f"/{post_id}", token, fields="permalink_url")
            permalink = details.get("permalink_url") if isinstance(details.get("permalink_url"), str) else None
        except MetaGraphError:
            permalink = None
        return PublishResult(post_id, permalink or f"https://www.facebook.com/{post_id}", {"id": post_id, "format": fmt})

    # Instagram Professional ---------------------------------------------

    def _container_status(self, graph: MetaGraphClient, ctx: PublishContext, container_id: str) -> str:
        response = graph.get(f"/{container_id}", ctx.access_token, fields="status_code")
        status = response.get("status_code")
        return status if isinstance(status, str) else "UNKNOWN"

    def _wait_for_container(self, graph: MetaGraphClient, ctx: PublishContext, container_id: str) -> str:
        for poll in range(ctx.max_polls):
            status = self._container_status(graph, ctx, container_id)
            if status in {"FINISHED", "PUBLISHED"}:
                return status
            if status == "ERROR":
                raise PublishFailure(
                    E.classification(E.INVALID_MEDIA, "Instagram could not process the media. Check the format and try different media.", "container_error")
                )
            if status == "EXPIRED":
                ctx.job.external_container_id = None
                ctx.job.external_child_ids = []
                ctx.checkpoint()
                raise PublishFailure(
                    E.classification(E.PLATFORM_TEMPORARY, "The Instagram media container expired before publishing; it will be recreated.", "container_expired")
                )
            if poll < ctx.max_polls - 1:
                ctx.sleep(ctx.poll_interval_seconds)
        raise PublishFailure(
            E.classification(E.PLATFORM_TEMPORARY, "Instagram is still processing the media. The job will check again later.", "processing_timeout")
        )

    def _create_item(self, graph: MetaGraphClient, ctx: PublishContext, asset: MediaAsset, *, carousel_item: bool) -> str:
        ig_id = ctx.account.platform_account_id
        params: dict[str, Any] = {}
        if asset.mime_type.startswith("video/"):
            params["media_type"] = "VIDEO" if carousel_item else "REELS"
            params["video_url"] = ctx.media_url(asset)
        else:
            params["image_url"] = ctx.media_url(asset)
        if carousel_item:
            params["is_carousel_item"] = "true"
        else:
            params["caption"] = ctx.caption or None
        return _id(graph.post(f"/{ig_id}/media", ctx.access_token, **params))

    def _check_quota(self, graph: MetaGraphClient, ctx: PublishContext) -> None:
        try:
            response = graph.get(
                f"/{ctx.account.platform_account_id}/content_publishing_limit",
                ctx.access_token,
                fields="quota_usage,config",
            )
        except MetaGraphError as error:
            if error.code in {190, 102}:
                raise
            return
        data = response.get("data")
        entry = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else {}
        usage = entry.get("quota_usage")
        config = entry.get("config") if isinstance(entry.get("config"), dict) else {}
        total = config.get("quota_total")
        if isinstance(usage, int) and isinstance(total, int) and usage >= total:
            raise PublishFailure(
                E.classification(E.RATE_LIMITED, "This Instagram account reached its 24-hour API publishing limit.", "ig_quota")
            )

    def _instagram(self, graph: MetaGraphClient, ctx: PublishContext) -> PublishResult:
        ig_id = ctx.account.platform_account_id
        job = ctx.job

        # Resume: a container from a previous attempt is checked first so an
        # interrupted media_publish call is never repeated after it succeeded.
        if job.external_container_id:
            status = self._container_status(graph, ctx, job.external_container_id)
            if status == "PUBLISHED":
                _set_stage(ctx, STAGE_DONE)
                return PublishResult(
                    job.external_post_id,
                    job.permalink,
                    {"container_id": job.external_container_id, "recovered": True},
                )
            if status in {"ERROR", "EXPIRED"}:
                job.external_container_id = None
                job.external_child_ids = []
                ctx.checkpoint()

        if not job.external_container_id:
            _set_stage(ctx, STAGE_CONTAINER)
            if ctx.publish_format == "carousel":
                children = list(job.external_child_ids or [])
                for asset in ctx.media[len(children):]:
                    children.append(self._create_item(graph, ctx, asset, carousel_item=True))
                    job.external_child_ids = list(children)
                    ctx.checkpoint()
                _set_stage(ctx, STAGE_PROCESSING)
                for child in children:
                    self._wait_for_container(graph, ctx, child)
                _set_stage(ctx, STAGE_CONTAINER)
                container = _id(
                    graph.post(
                        f"/{ig_id}/media",
                        ctx.access_token,
                        media_type="CAROUSEL",
                        children=",".join(children),
                        caption=ctx.caption or None,
                    )
                )
            elif ctx.publish_format in {"image", "reel"}:
                container = self._create_item(graph, ctx, ctx.media[0], carousel_item=False)
            else:
                raise PublishFailure(E.classification(E.VALIDATION, "Unsupported Instagram post format."))
            job.external_container_id = container
            ctx.checkpoint()

        _set_stage(ctx, STAGE_PROCESSING)
        status = self._wait_for_container(graph, ctx, job.external_container_id)
        if status == "PUBLISHED":
            _set_stage(ctx, STAGE_DONE)
            return PublishResult(job.external_post_id, job.permalink, {"container_id": job.external_container_id, "recovered": True})

        self._check_quota(graph, ctx)
        _set_stage(ctx, STAGE_PUBLISHING)
        media_id = _id(graph.post(f"/{ig_id}/media_publish", ctx.access_token, creation_id=job.external_container_id))
        job.external_post_id = media_id
        _set_stage(ctx, STAGE_DONE)
        permalink = None
        try:
            details = graph.get(f"/{media_id}", ctx.access_token, fields="permalink")
            permalink = details.get("permalink") if isinstance(details.get("permalink"), str) else None
        except MetaGraphError:
            permalink = None
        return PublishResult(media_id, permalink, {"id": media_id, "container_id": job.external_container_id, "format": ctx.publish_format})

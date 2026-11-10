"""Classification of Meta API failures during analytics collection.

The publishing classifier (``app.services.publishing.errors``) already maps
Meta error codes to retry categories. Analytics adds two outcomes that must
*not* be treated as failures of the whole synchronization:

* ``unsupported_metric`` - Meta rejected a metric name (code 100 / 3001). The
  metric is recorded as unavailable and collection continues.
* ``insufficient_data`` - Instagram returns error code 10 "Not enough viewers
  for the media to show insights" for media with fewer than 5 viewers. This is
  not a permission problem; the media's insights are simply unavailable.
* ``object_unavailable`` - the post or media no longer exists or cannot be read
  (code 100 with subcode 33, or an HTTP 404). Only that object is skipped.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.meta_graph import MetaGraphError
from app.services.publishing import errors as publishing_errors

UNSUPPORTED_METRIC = "unsupported_metric"
INSUFFICIENT_DATA = "insufficient_data"
OBJECT_UNAVAILABLE = "object_unavailable"

NETWORK = publishing_errors.NETWORK
PLATFORM_TEMPORARY = publishing_errors.PLATFORM_TEMPORARY
RATE_LIMITED = publishing_errors.RATE_LIMITED
TOKEN_EXPIRED = publishing_errors.TOKEN_EXPIRED
PERMISSION = publishing_errors.PERMISSION
PERMANENT = publishing_errors.PERMANENT
CONFIGURATION = publishing_errors.CONFIGURATION

# Categories that stop the current synchronization run for the account.
ABORTING_CATEGORIES = {NETWORK, PLATFORM_TEMPORARY, RATE_LIMITED, TOKEN_EXPIRED, PERMISSION}
RETRYABLE_CATEGORIES = {NETWORK, PLATFORM_TEMPORARY, RATE_LIMITED}
USER_ACTION_CATEGORIES = {TOKEN_EXPIRED, PERMISSION, CONFIGURATION}

MESSAGES = {
    NETWORK: "Meta could not be reached. Synchronization will be retried automatically.",
    PLATFORM_TEMPORARY: "Meta reported a temporary problem. Synchronization will be retried automatically.",
    RATE_LIMITED: "Meta rate-limited analytics requests for this account. Synchronization will resume later.",
    TOKEN_EXPIRED: "The account authorization expired or was revoked. Reconnect the account to resume analytics.",
    PERMISSION: (
        "Meta denied access to insights. Reconnect the account and grant the insights permissions "
        "(read_insights for Pages, instagram_manage_insights for Instagram)."
    ),
    UNSUPPORTED_METRIC: "Meta does not support this metric for this account, object or API version.",
    INSUFFICIENT_DATA: "Meta does not return insights for media with fewer than 5 viewers.",
    OBJECT_UNAVAILABLE: "The post could not be read from Meta (it may have been deleted).",
    PERMANENT: "Meta rejected the analytics request.",
    CONFIGURATION: "The stored account credential could not be decrypted. Reconnect the account.",
}


@dataclass(frozen=True)
class CollectionFailure:
    category: str
    code: str | None
    message: str
    retry_after_seconds: int | None = None

    @property
    def retryable(self) -> bool:
        return self.category in RETRYABLE_CATEGORIES

    @property
    def aborts_sync(self) -> bool:
        return self.category in ABORTING_CATEGORIES

    @property
    def requires_user_action(self) -> bool:
        return self.category in USER_ACTION_CATEGORIES


def failure(category: str, code: str | None = None, message: str | None = None) -> CollectionFailure:
    return CollectionFailure(category=category, code=code, message=message or MESSAGES.get(category, MESSAGES[PERMANENT]))


def classify_collection_error(error: MetaGraphError) -> CollectionFailure:
    code = error.code
    subcode = error.subcode
    text = (error.meta_message or "").lower()
    code_text = f"{code}" + (f".{subcode}" if subcode else "") if code is not None else f"http_{error.status_code}"

    if code == 10 and "enough viewers" in text:
        return failure(INSUFFICIENT_DATA, code_text)
    if code == 3001 or (code == 100 and ("metric" in text or subcode == 1504028)):
        return failure(UNSUPPORTED_METRIC, code_text)
    if code == 100 and (subcode == 33 or "does not exist" in text or "unsupported get request" in text):
        return failure(OBJECT_UNAVAILABLE, code_text)
    if code is None and error.status_code == 404:
        return failure(OBJECT_UNAVAILABLE, code_text)

    base = publishing_errors.classify_meta_error(error, final_publish_call=False, platform="analytics")
    category = base.category
    if category == publishing_errors.INVALID_CONTENT:
        # Code 100 without a metric hint: the request itself was invalid for this object.
        category = UNSUPPORTED_METRIC
    elif category not in MESSAGES:
        category = PERMANENT
    return CollectionFailure(
        category=category,
        code=code_text,
        message=MESSAGES.get(category, MESSAGES[PERMANENT]),
        retry_after_seconds=error.retry_after_seconds if category == RATE_LIMITED else None,
    )

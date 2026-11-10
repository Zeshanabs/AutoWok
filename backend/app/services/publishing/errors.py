"""Classification of publishing failures into safe retry decisions."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.meta_graph import MetaGraphError

NETWORK = "network"
PLATFORM_TEMPORARY = "platform_temporary"
RATE_LIMITED = "rate_limited"
TOKEN_EXPIRED = "token_expired"
PERMISSION = "permission"
INVALID_MEDIA = "invalid_media"
INVALID_CONTENT = "invalid_content"
PERMANENT = "permanent"
VALIDATION = "validation"
UNCERTAIN = "uncertain"
CONFIGURATION = "configuration"

RETRYABLE_CATEGORIES = {NETWORK, PLATFORM_TEMPORARY, RATE_LIMITED}
USER_ACTION_CATEGORIES = {TOKEN_EXPIRED, PERMISSION, INVALID_MEDIA, INVALID_CONTENT, VALIDATION, UNCERTAIN, CONFIGURATION}

_RATE_LIMIT_CODES = {4, 17, 32, 613} | set(range(80001, 80015))
_INSTAGRAM_MEDIA_SUBCODES = {
    2207003, 2207004, 2207005, 2207006, 2207008, 2207009, 2207010, 2207026,
    2207023, 2207050, 2207052, 2207053, 2207057,
}
_INSTAGRAM_RATE_SUBCODES = {2207042}

USER_MESSAGES = {
    NETWORK: "Meta could not be reached. The job will be retried automatically.",
    PLATFORM_TEMPORARY: "Meta reported a temporary problem. The job will be retried automatically.",
    RATE_LIMITED: "Meta rate-limited publishing for this account. The job will be retried later.",
    TOKEN_EXPIRED: "The account authorization expired or was revoked. Reconnect the account, then retry.",
    PERMISSION: "Meta denied permission to publish. Reconnect the account and grant the publishing permissions, then retry.",
    INVALID_MEDIA: "Meta rejected the media. Replace or fix the attached media, then retry.",
    INVALID_CONTENT: "Meta rejected the post content. Edit the content, get it re-approved, then retry.",
    PERMANENT: "Meta permanently rejected this post.",
    UNCERTAIN: (
        "The final publish request was sent but no confirmation was received. Check the account "
        "for the post before retrying, to avoid a duplicate."
    ),
}


@dataclass(frozen=True)
class FailureClassification:
    category: str
    retryable: bool
    requires_user_action: bool
    uncertain: bool
    code: str | None
    message: str


def classify_meta_error(error: MetaGraphError, *, final_publish_call: bool, platform: str) -> FailureClassification:
    """Classify an error raised by a Meta request.

    ``final_publish_call`` marks the request that makes a post live
    (Facebook ``/feed``/``/photos``/``/videos`` or Instagram ``media_publish``).
    A network failure there may have succeeded on Meta's side. Instagram can
    be recovered safely by checking the container status; Facebook cannot,
    so it is marked uncertain and never retried automatically.
    """
    code = error.code
    subcode = error.subcode
    code_text = f"{code}" + (f".{subcode}" if subcode else "") if code is not None else f"http_{error.status_code}"
    detail = error.meta_message

    def result(category: str, *, uncertain: bool = False) -> FailureClassification:
        retryable = category in RETRYABLE_CATEGORIES
        message = USER_MESSAGES.get(category, USER_MESSAGES[PERMANENT])
        if detail and category in {INVALID_MEDIA, INVALID_CONTENT, PERMANENT, PERMISSION}:
            message = f"{message} Meta said: {detail}"
        return FailureClassification(
            category=category,
            retryable=retryable,
            requires_user_action=category in USER_ACTION_CATEGORIES,
            uncertain=uncertain,
            code=code_text,
            message=message,
        )

    if code is None:
        if error.status_code == 429:
            return result(RATE_LIMITED)
        if error.status_code >= 500 or error.status_code in {502, 503, 504}:
            if final_publish_call and error.request_sent and platform != "instagram":
                return result(UNCERTAIN, uncertain=True)
            return result(NETWORK if error.status_code in {502, 503, 504} else PLATFORM_TEMPORARY)
        if error.status_code in {401}:
            return result(TOKEN_EXPIRED)
        if error.status_code == 403:
            return result(PERMISSION)
        return result(PERMANENT)

    if code == 190 or code == 102:
        return result(TOKEN_EXPIRED)
    if code in _RATE_LIMIT_CODES or subcode in _INSTAGRAM_RATE_SUBCODES or error.status_code == 429:
        return result(RATE_LIMITED)
    if code == 10 or 200 <= code <= 299 or code == 3:
        return result(PERMISSION)
    if subcode in _INSTAGRAM_MEDIA_SUBCODES or code in {324, 352} or 36000 <= code <= 36010:
        return result(INVALID_MEDIA)
    if code in {1, 2} or error.is_transient:
        if final_publish_call and platform != "instagram":
            return result(UNCERTAIN, uncertain=True)
        return result(PLATFORM_TEMPORARY)
    if code == 100:
        return result(INVALID_CONTENT)
    return result(PERMANENT)


def classification(category: str, message: str | None = None, code: str | None = None) -> FailureClassification:
    return FailureClassification(
        category=category,
        retryable=category in RETRYABLE_CATEGORIES,
        requires_user_action=category in USER_ACTION_CATEGORIES,
        uncertain=category == UNCERTAIN,
        code=code,
        message=message or USER_MESSAGES.get(category, USER_MESSAGES[PERMANENT]),
    )

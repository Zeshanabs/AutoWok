"""Catalogue of analytics metrics supported by Autowok.

Every entry maps a *normalized* metric key used throughout Autowok to the
exact Meta Graph API metric or object field it is read from, with the
official definition, unit and availability requirements. Only metrics that
are documented in Meta's current Page Insights, Page Post, Instagram
Account Insights, Instagram Media Insights and object-field references are
listed. Deprecated metrics (Instagram ``impressions``; Facebook
``page_impressions*``, ``post_impressions*``, ``page_fans*`` and the
``*_unique`` impression variants removed in 2025) are intentionally absent.

Facebook and Instagram definitions are kept separate. A normalized key that
exists on both platforms (for example ``reach``) is only *comparable* when
``comparable`` is True; the per-platform ``definition`` text always explains
what Meta actually measures.

Sources (Meta for Developers, checked November 2026, Graph API v26.0):

* Page Insights metrics reference and deprecated metrics list
* Page and Page Post object references
* Instagram Platform: IG User, IG User insights, IG Media, IG Media insights
"""

from __future__ import annotations

from dataclasses import dataclass, field

FACEBOOK = "facebook_page"
INSTAGRAM = "instagram"
PLATFORMS = (FACEBOOK, INSTAGRAM)

PLATFORM_LABELS = {FACEBOOK: "Facebook Page", INSTAGRAM: "Instagram"}

# Source kinds
INSIGHT = "insight"  # /{id}/insights metric
FIELD = "field"  # object field, e.g. followers_count
DERIVED = "derived"  # calculated by Autowok from stored source values

ACCOUNT = "account"
POST = "post"


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    platform: str
    level: str  # account | post
    label: str
    source_kind: str  # insight | field | derived
    source_name: str  # exact Meta metric / field name, or the formula for derived metrics
    definition: str
    unit: str = "count"
    period: str | None = None  # Meta period used for insights
    # Instagram media product types / Facebook formats the metric applies to.
    applies_to: tuple[str, ...] = ()
    requirements: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    # True when the normalized key measures the same thing on both platforms
    # closely enough to place side by side (differences are still explained).
    comparable: bool = False
    # Whether per-account daily values can be summed over a date range.
    aggregation: str = "sum"  # sum | last | none

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "platform": self.platform,
            "platform_label": PLATFORM_LABELS[self.platform],
            "level": self.level,
            "label": self.label,
            "source_kind": self.source_kind,
            "source_name": self.source_name,
            "definition": self.definition,
            "unit": self.unit,
            "period": self.period,
            "applies_to": list(self.applies_to),
            "requirements": list(self.requirements),
            "limitations": list(self.limitations),
            "comparable": self.comparable,
            "aggregation": self.aggregation,
        }


FB_INSIGHT_REQ = ("read_insights", "pages_read_engagement", "Page access token with the ANALYZE task")
FB_FIELD_REQ = ("pages_read_engagement", "pages_show_list")
IG_INSIGHT_REQ = ("instagram_manage_insights", "instagram_basic", "pages_read_engagement")
IG_FIELD_REQ = ("instagram_basic", "pages_read_engagement")

FB_PAGE_LIMITS = (
    "Page Insights are only available for Pages with 100 or more likes.",
    "Most metrics update about once every 24 hours.",
    "Meta keeps at most two years of data; each request may span at most 90 days.",
)
IG_ACCOUNT_LIMITS = (
    "Data can be delayed by up to 48 hours.",
    "Missing data is returned as an empty result, not as zero.",
)
IG_MEDIA_LIMITS = (
    "Insights are not returned for media with fewer than 5 viewers (error code 10).",
    "Media inside a carousel album has no insights of its own.",
    "Data can be delayed by up to 48 hours and is stored by Meta for up to 2 years.",
)

ACCOUNT_METRICS: tuple[MetricDefinition, ...] = (
    # ---------------------------------------------------------------- Facebook
    MetricDefinition(
        key="followers", platform=FACEBOOK, level=ACCOUNT, label="Followers",
        source_kind=FIELD, source_name="followers_count", aggregation="last", comparable=True,
        definition="The number of people following the Page, as reported by the Page object when the snapshot was collected.",
        requirements=FB_FIELD_REQ,
    ),
    MetricDefinition(
        key="views", platform=FACEBOOK, level=ACCOUNT, label="Media views",
        source_kind=INSIGHT, source_name="page_media_view", period="day", comparable=True,
        definition="Number of times media from the Page was viewed (Meta's replacement for the deprecated page_impressions metric).",
        requirements=FB_INSIGHT_REQ, limitations=FB_PAGE_LIMITS,
    ),
    MetricDefinition(
        key="reach", platform=FACEBOOK, level=ACCOUNT, label="Unique viewers",
        source_kind=INSIGHT, source_name="page_total_media_view_unique", period="day", comparable=True,
        definition="Number of unique accounts that viewed the Page's media (Meta's replacement for the deprecated page_impressions_unique metric, which was Facebook's reach figure).",
        requirements=FB_INSIGHT_REQ, limitations=FB_PAGE_LIMITS,
    ),
    MetricDefinition(
        key="engagements", platform=FACEBOOK, level=ACCOUNT, label="Post engagements",
        source_kind=INSIGHT, source_name="page_post_engagements", period="day",
        definition="Number of times people engaged with the Page's posts through reactions, comments, shares and clicks.",
        requirements=FB_INSIGHT_REQ, limitations=FB_PAGE_LIMITS,
    ),
    MetricDefinition(
        key="follows", platform=FACEBOOK, level=ACCOUNT, label="New follows",
        source_kind=INSIGHT, source_name="page_daily_follows_unique", period="day",
        definition="Number of unique accounts that started following the Page on that day.",
        requirements=FB_INSIGHT_REQ, limitations=FB_PAGE_LIMITS,
    ),
    MetricDefinition(
        key="unfollows", platform=FACEBOOK, level=ACCOUNT, label="Unfollows",
        source_kind=INSIGHT, source_name="page_daily_unfollows_unique", period="day",
        definition="Number of unique accounts that stopped following the Page on that day.",
        requirements=FB_INSIGHT_REQ, limitations=FB_PAGE_LIMITS,
    ),
    MetricDefinition(
        key="page_views", platform=FACEBOOK, level=ACCOUNT, label="Page views",
        source_kind=INSIGHT, source_name="page_views_total", period="day",
        definition="Number of times the Page's profile was viewed by logged-in and logged-out people.",
        requirements=FB_INSIGHT_REQ, limitations=FB_PAGE_LIMITS,
    ),
    MetricDefinition(
        key="video_views", platform=FACEBOOK, level=ACCOUNT, label="Video views",
        source_kind=INSIGHT, source_name="page_video_views", period="day",
        definition="Number of times the Page's videos were viewed for 3 seconds or more (Meta's definition for page_video_views).",
        requirements=FB_INSIGHT_REQ,
        limitations=FB_PAGE_LIMITS + ("Accurate only for videos the Page itself created; reshared videos return 0.",),
    ),
    MetricDefinition(
        key="reactions", platform=FACEBOOK, level=ACCOUNT, label="Reactions",
        source_kind=INSIGHT, source_name="page_actions_post_reactions_total", period="day",
        definition="Total reactions on the Page's posts, summed over the reaction types returned by Meta (like, love, wow, haha, sorry, anger). The per-type breakdown is kept.",
        requirements=FB_INSIGHT_REQ, limitations=FB_PAGE_LIMITS,
    ),
    # --------------------------------------------------------------- Instagram
    MetricDefinition(
        key="followers", platform=INSTAGRAM, level=ACCOUNT, label="Followers",
        source_kind=FIELD, source_name="followers_count", aggregation="last", comparable=True,
        definition="Total number of accounts following the Instagram professional account when the snapshot was collected.",
        requirements=IG_FIELD_REQ,
    ),
    MetricDefinition(
        key="reach", platform=INSTAGRAM, level=ACCOUNT, label="Reach",
        source_kind=INSIGHT, source_name="reach", period="day", comparable=True,
        definition="Number of unique accounts that saw any of the account's content at least once (estimated by Meta).",
        requirements=IG_INSIGHT_REQ, limitations=IG_ACCOUNT_LIMITS,
    ),
    MetricDefinition(
        key="views", platform=INSTAGRAM, level=ACCOUNT, label="Views",
        source_kind=INSIGHT, source_name="views", period="day", comparable=True,
        definition="Number of times the account's reels, posts and stories were played or displayed (Meta's replacement for the deprecated impressions metric; marked 'in development' by Meta).",
        requirements=IG_INSIGHT_REQ, limitations=IG_ACCOUNT_LIMITS,
    ),
    MetricDefinition(
        key="accounts_engaged", platform=INSTAGRAM, level=ACCOUNT, label="Accounts engaged",
        source_kind=INSIGHT, source_name="accounts_engaged", period="day",
        definition="Number of accounts that interacted with the account's content, including ads (estimated by Meta).",
        requirements=IG_INSIGHT_REQ, limitations=IG_ACCOUNT_LIMITS,
    ),
    MetricDefinition(
        key="engagements", platform=INSTAGRAM, level=ACCOUNT, label="Total interactions",
        source_kind=INSIGHT, source_name="total_interactions", period="day",
        definition="Total number of post, story, reel, video and live video interactions, including boosted content (likes, comments, saves, shares and replies as counted by Meta).",
        requirements=IG_INSIGHT_REQ, limitations=IG_ACCOUNT_LIMITS,
    ),
    MetricDefinition(
        key="likes", platform=INSTAGRAM, level=ACCOUNT, label="Likes",
        source_kind=INSIGHT, source_name="likes", period="day",
        definition="Number of likes on the account's posts, reels and videos.",
        requirements=IG_INSIGHT_REQ, limitations=IG_ACCOUNT_LIMITS,
    ),
    MetricDefinition(
        key="comments", platform=INSTAGRAM, level=ACCOUNT, label="Comments",
        source_kind=INSIGHT, source_name="comments", period="day",
        definition="Number of comments on the account's posts, reels, videos and live videos (marked 'in development' by Meta).",
        requirements=IG_INSIGHT_REQ, limitations=IG_ACCOUNT_LIMITS,
    ),
    MetricDefinition(
        key="shares", platform=INSTAGRAM, level=ACCOUNT, label="Shares",
        source_kind=INSIGHT, source_name="shares", period="day",
        definition="Number of shares of the account's posts, stories, reels, videos and live videos.",
        requirements=IG_INSIGHT_REQ, limitations=IG_ACCOUNT_LIMITS,
    ),
    MetricDefinition(
        key="saves", platform=INSTAGRAM, level=ACCOUNT, label="Saves",
        source_kind=INSIGHT, source_name="saves", period="day",
        definition="Number of saves of the account's posts, reels and videos.",
        requirements=IG_INSIGHT_REQ, limitations=IG_ACCOUNT_LIMITS,
    ),
    MetricDefinition(
        key="replies", platform=INSTAGRAM, level=ACCOUNT, label="Story replies",
        source_kind=INSIGHT, source_name="replies", period="day",
        definition="Number of replies to the account's stories, including text and quick-reaction replies.",
        requirements=IG_INSIGHT_REQ, limitations=IG_ACCOUNT_LIMITS,
    ),
    MetricDefinition(
        key="profile_link_taps", platform=INSTAGRAM, level=ACCOUNT, label="Profile link taps",
        source_kind=INSIGHT, source_name="profile_links_taps", period="day",
        definition="Number of taps on the business address, call, email and text buttons on the profile.",
        requirements=IG_INSIGHT_REQ, limitations=IG_ACCOUNT_LIMITS,
    ),
)

POST_METRICS: tuple[MetricDefinition, ...] = (
    # ---------------------------------------------------------------- Facebook
    MetricDefinition(
        key="views", platform=FACEBOOK, level=POST, label="Views",
        source_kind=INSIGHT, source_name="post_media_view", period="lifetime", comparable=True,
        definition="Number of times the post's media was viewed (Meta's replacement for the deprecated post_impressions metric).",
        requirements=FB_INSIGHT_REQ, limitations=FB_PAGE_LIMITS,
    ),
    MetricDefinition(
        key="reach", platform=FACEBOOK, level=POST, label="Unique viewers",
        source_kind=INSIGHT, source_name="post_total_media_view_unique", period="lifetime", comparable=True,
        definition="Number of unique accounts that viewed the post's media (Meta's replacement for the deprecated post_impressions_unique metric, which was Facebook's post reach).",
        requirements=FB_INSIGHT_REQ, limitations=FB_PAGE_LIMITS,
    ),
    MetricDefinition(
        key="clicks", platform=FACEBOOK, level=POST, label="Post clicks",
        source_kind=INSIGHT, source_name="post_clicks", period="lifetime",
        definition="Number of clicks anywhere in the post (lifetime).",
        requirements=FB_INSIGHT_REQ, limitations=FB_PAGE_LIMITS,
    ),
    MetricDefinition(
        key="reactions", platform=FACEBOOK, level=POST, label="Reactions",
        source_kind=INSIGHT, source_name="post_reactions_by_type_total", period="lifetime",
        definition="Total reactions on the post summed over the reaction types returned by Meta; the per-type breakdown is kept.",
        requirements=FB_INSIGHT_REQ, limitations=FB_PAGE_LIMITS,
    ),
    MetricDefinition(
        key="likes", platform=FACEBOOK, level=POST, label="Likes",
        source_kind=INSIGHT, source_name="post_reactions_by_type_total[like]", period="lifetime", comparable=True,
        definition="The 'like' entry of post_reactions_by_type_total. Other reaction types (love, wow, haha, sorry, anger) are counted under Reactions, not Likes.",
        requirements=FB_INSIGHT_REQ, limitations=FB_PAGE_LIMITS,
    ),
    MetricDefinition(
        key="comments", platform=FACEBOOK, level=POST, label="Comments",
        source_kind=FIELD, source_name="comments.summary(total_count)", comparable=True,
        definition="Total number of comments on the post, as reported by the comments edge summary.",
        requirements=FB_FIELD_REQ,
    ),
    MetricDefinition(
        key="shares", platform=FACEBOOK, level=POST, label="Shares",
        source_kind=FIELD, source_name="shares.count", comparable=True,
        definition="Number of times the post was shared, from the post's shares field. Meta omits the field when the count is zero; an omitted field on a successful read is recorded as 0 and flagged in the raw metrics.",
        requirements=FB_FIELD_REQ,
    ),
    MetricDefinition(
        key="video_views", platform=FACEBOOK, level=POST, label="Video views",
        source_kind=INSIGHT, source_name="post_video_views", period="lifetime", applies_to=("video",),
        definition="Number of times the post's video was viewed for 3 seconds or more (video posts only).",
        requirements=FB_INSIGHT_REQ, limitations=FB_PAGE_LIMITS,
    ),
    MetricDefinition(
        key="engagements", platform=FACEBOOK, level=POST, label="Engagements (calculated)",
        source_kind=DERIVED, source_name="reactions + comments + shares + clicks",
        definition="Autowok calculation: reactions + comments + shares + post clicks, mirroring Meta's page_post_engagements definition. Clicks are omitted from the sum when post insights are unavailable, and the result is marked partial.",
    ),
    # --------------------------------------------------------------- Instagram
    MetricDefinition(
        key="reach", platform=INSTAGRAM, level=POST, label="Reach",
        source_kind=INSIGHT, source_name="reach", applies_to=("image", "carousel", "reel", "video"), comparable=True,
        definition="Number of unique accounts that saw the media at least once (estimated by Meta).",
        requirements=IG_INSIGHT_REQ, limitations=IG_MEDIA_LIMITS,
    ),
    MetricDefinition(
        key="views", platform=INSTAGRAM, level=POST, label="Views",
        source_kind=INSIGHT, source_name="views", applies_to=("image", "carousel", "reel", "video"), comparable=True,
        definition="Number of times the media was played or displayed on Instagram (Meta's replacement for impressions and plays; marked 'in development' by Meta).",
        requirements=IG_INSIGHT_REQ, limitations=IG_MEDIA_LIMITS,
    ),
    MetricDefinition(
        key="likes", platform=INSTAGRAM, level=POST, label="Likes",
        source_kind=FIELD, source_name="like_count", comparable=True,
        definition="Number of likes on the media (organic; excludes likes on promoted versions and on carousel children). Omitted by Meta when the owner hides like counts.",
        requirements=IG_FIELD_REQ,
    ),
    MetricDefinition(
        key="comments", platform=INSTAGRAM, level=POST, label="Comments",
        source_kind=FIELD, source_name="comments_count", comparable=True,
        definition="Number of comments on the media, including replies (excludes comments on carousel children).",
        requirements=IG_FIELD_REQ,
    ),
    MetricDefinition(
        key="saves", platform=INSTAGRAM, level=POST, label="Saves",
        source_kind=INSIGHT, source_name="saved", applies_to=("image", "carousel", "reel", "video"),
        definition="Number of times the media was saved.",
        requirements=IG_INSIGHT_REQ, limitations=IG_MEDIA_LIMITS,
    ),
    MetricDefinition(
        key="shares", platform=INSTAGRAM, level=POST, label="Shares",
        source_kind=INSIGHT, source_name="shares", applies_to=("image", "carousel", "reel", "video"), comparable=True,
        definition="Number of times the media was shared.",
        requirements=IG_INSIGHT_REQ, limitations=IG_MEDIA_LIMITS,
    ),
    MetricDefinition(
        key="engagements", platform=INSTAGRAM, level=POST, label="Total interactions",
        source_kind=INSIGHT, source_name="total_interactions", applies_to=("image", "carousel", "reel", "video"),
        definition="Meta's total_interactions: likes, saves, comments and shares on the media, minus unlikes, unsaves and deleted comments (marked 'in development' by Meta).",
        requirements=IG_INSIGHT_REQ, limitations=IG_MEDIA_LIMITS,
    ),
    MetricDefinition(
        key="follows", platform=INSTAGRAM, level=POST, label="Follows from post",
        source_kind=INSIGHT, source_name="follows", applies_to=("image", "carousel"),
        definition="Number of accounts that started following the account after seeing this feed post.",
        requirements=IG_INSIGHT_REQ, limitations=IG_MEDIA_LIMITS,
    ),
    MetricDefinition(
        key="profile_visits", platform=INSTAGRAM, level=POST, label="Profile visits",
        source_kind=INSIGHT, source_name="profile_visits", applies_to=("image", "carousel"),
        definition="Number of profile visits that came from this feed post.",
        requirements=IG_INSIGHT_REQ, limitations=IG_MEDIA_LIMITS,
    ),
    MetricDefinition(
        key="reel_avg_watch_time", platform=INSTAGRAM, level=POST, label="Average watch time",
        source_kind=INSIGHT, source_name="ig_reels_avg_watch_time", applies_to=("reel",), unit="milliseconds",
        definition="Average time the reel was played per play, in milliseconds.",
        requirements=IG_INSIGHT_REQ, limitations=IG_MEDIA_LIMITS,
    ),
    MetricDefinition(
        key="reel_total_watch_time", platform=INSTAGRAM, level=POST, label="Total watch time",
        source_kind=INSIGHT, source_name="ig_reels_video_view_total_time", applies_to=("reel",), unit="milliseconds",
        definition="Total time the reel was played, including replays, in milliseconds (marked 'in development' by Meta).",
        requirements=IG_INSIGHT_REQ, limitations=IG_MEDIA_LIMITS,
    ),
)

# Normalized keys that are stored as dedicated columns on PostAnalytics.
POST_COLUMNS = ("reach", "views", "engagements", "likes", "reactions", "comments", "shares", "saves", "clicks", "video_views")

# Keys that are not supported on a platform at all (shown as unavailable).
NOT_SUPPORTED: dict[str, dict[str, str]] = {
    FACEBOOK: {
        "saves": "Facebook does not report saves for Page posts.",
        "accounts_engaged": "Facebook Page Insights do not report accounts engaged.",
    },
    INSTAGRAM: {
        "clicks": "Instagram does not report post clicks for feed posts or reels.",
        "reactions": "Instagram has likes only; it does not report reaction types.",
        "video_views": "Instagram reports plays as Views; there is no separate video views metric.",
        "page_views": "Instagram does not report profile views through the account insights API in the supported version.",
    },
}

DERIVED_METRICS: dict[str, dict[str, str]] = {
    "engagement_rate_by_reach": {
        "label": "Engagement rate by reach (calculated)",
        "formula": "(engagements / reach) x 100",
        "unit": "percent",
        "definition": (
            "Autowok calculation. Facebook: (reactions + comments + shares + clicks) / unique viewers x 100. "
            "Instagram: total_interactions / reach x 100. Not calculated when reach is missing or zero. "
            "The two platforms count different interactions, so their rates are reported separately."
        ),
    },
    "follower_change": {
        "label": "Audience growth (calculated)",
        "formula": "followers at end of period - followers at start of period",
        "unit": "count",
        "definition": (
            "Autowok calculation from stored follower snapshots: the difference between the last and the first "
            "follower count available in the period. Not calculated with fewer than two snapshots."
        ),
    },
    "percentage_change": {
        "label": "Change versus previous period (calculated)",
        "formula": "(current - previous) / previous x 100",
        "unit": "percent",
        "definition": "Autowok calculation. Not calculated when the previous value is missing or zero.",
    },
}


def account_metrics(platform: str) -> list[MetricDefinition]:
    return [metric for metric in ACCOUNT_METRICS if metric.platform == platform]


def post_metrics(platform: str, content_format: str | None = None) -> list[MetricDefinition]:
    result = []
    for metric in POST_METRICS:
        if metric.platform != platform:
            continue
        if content_format and metric.applies_to and content_format not in metric.applies_to:
            continue
        result.append(metric)
    return result


def definition(platform: str, level: str, key: str) -> MetricDefinition | None:
    source = ACCOUNT_METRICS if level == ACCOUNT else POST_METRICS
    for metric in source:
        if metric.platform == platform and metric.key == key:
            return metric
    return None


def account_metric_keys() -> list[str]:
    keys: list[str] = []
    for metric in ACCOUNT_METRICS:
        if metric.key not in keys:
            keys.append(metric.key)
    return keys


def post_metric_keys() -> list[str]:
    keys: list[str] = []
    for metric in POST_METRICS:
        if metric.key not in keys:
            keys.append(metric.key)
    return keys


def is_comparable(level: str, key: str) -> bool:
    """A key is comparable across platforms only when both platform definitions say so."""
    source = ACCOUNT_METRICS if level == ACCOUNT else POST_METRICS
    entries = [metric for metric in source if metric.key == key]
    return len(entries) == 2 and all(metric.comparable for metric in entries)


def catalogue() -> dict[str, object]:
    return {
        "account_metrics": [metric.to_dict() for metric in ACCOUNT_METRICS],
        "post_metrics": [metric.to_dict() for metric in POST_METRICS],
        "derived_metrics": [{"key": key, **value} for key, value in DERIVED_METRICS.items()],
        "not_supported": NOT_SUPPORTED,
        "platforms": [{"key": key, "label": label} for key, label in PLATFORM_LABELS.items()],
    }

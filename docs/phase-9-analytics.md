# Phase 9: Social media analytics, performance tracking and reporting

Phase 9 lets workspace members understand how their connected **Facebook Pages** and
**Instagram Professional accounts** perform: account-level insights, post-level
performance, platform comparison, content-performance rankings, trend charts, and CSV/PDF
reports. Metrics are collected in the background through the official Meta Graph API and
stored as dated snapshots, so opening the dashboard never calls Meta.

No other social platform is supported, and no content is generated, published or
scheduled by this phase.

## Verification status

| Area | Status |
| --- | --- |
| Metric catalogue (names, definitions, availability) | Checked against Meta's current developer documentation (November 2026, Graph API v26.0; v27.0 is the latest release) |
| Facebook Page and post collection | **Mocked Graph API only - live retrieval NOT VERIFIED** |
| Instagram account and media collection | **Mocked Graph API only - live retrieval NOT VERIFIED** |
| Storage, duplicate prevention, calculations, sync jobs, retries | Automated tests (SQLite) |
| Analytics API, filters, isolation, CSV and PDF exports | Automated tests |
| Dashboard pages and charts | Vitest component tests, TypeScript and ESLint |
| PostgreSQL migration | Offline SQL compiled; SQLite upgrade/downgrade verified; **not run against PostgreSQL in this environment** |
| Docker Compose | Compose file validated; **containers not started in this environment** |

No Meta app with the insights permissions, App Review approval or an eligible test
account was available while building this phase, so no live insight has been retrieved.

## User interface

| Route | Purpose |
| --- | --- |
| `/dashboard/analytics` | Overview: per-platform key metrics with previous-period change, published post count, audience growth, reach/views/engagement/follower charts, platform comparison, top posts |
| `/dashboard/analytics/accounts` | One card per account: every supported metric with current and previous value, change, collection time and definition; follower chart; sync status |
| `/dashboard/analytics/posts` | Post performance table with thumbnail, platform, account, publish date, link to the Autowok content, metrics, engagement rate and last sync; filters for content type, source and engagement range; sorting; pagination; post details with history; side-by-side comparison of 2-6 posts |
| `/dashboard/analytics/content-performance` | Highest and lowest performing posts, content-format comparison, weekly trend, posting consistency, period change, optional Groq interpretation |
| `/dashboard/analytics/reports` | Report preview and CSV/PDF download using the active filters |

A single filter row (date presets or custom range, brand, platform, account) scopes
every section. Filters are kept in `sessionStorage` as a convenience. The "Data
freshness" strip shows each account's last synchronization, permission gaps and
errors; Owners and Admins can request a refresh.

Charts are inline SVG with a crosshair tooltip, keyboard navigation (arrow keys), a
legend for two or more series, selective end labels, and a table view twin. Colour follows
the platform (blue = Facebook Page, orange = Instagram) and never the row position. The
palette was validated for colour-vision deficiency and contrast with the data-viz validator.

## Architecture

```
Worker (python -m app.worker)                             API (FastAPI)              Browser
  schedule_analytics_syncs ─▶ analytics_sync_jobs ◀────── POST /analytics/sync        │
  run_analytics_syncs ─▶ claim job ─▶ MetaInsightsCollector ─▶ Meta Graph API          │
                           │  normalize (metrics catalogue)                          │
                           ▼                                                          │
                 analytics_snapshots / post_analytics / post_analytics_history ◀── queries ◀── /dashboard/analytics
                                                                                  reports (CSV/PDF)
```

`backend/app/services/analytics/` is split by responsibility:

1. `metrics.py` - catalogue of supported metrics (normalized key -> official Meta name, definition, unit, requirements, limitations, comparability).
2. `errors.py` - classification of Meta failures for collection (adds `unsupported_metric`, `insufficient_data`, `object_unavailable` to the publishing categories).
3. `collector.py` - Graph API calls, 90-day chunking, pagination, per-metric fallback, type-checked parsing.
4. `storage.py` - idempotent upserts for snapshots, posts and post history.
5. `calculations.py` - documented derived metrics.
6. `sync.py` + `worker_tasks.py` - job lifecycle, scheduling, retries.
7. `queries.py` - aggregations for the API (overview, time series, accounts, posts, comparisons, content performance).
8. `reports.py` + `pdf.py` - report document, CSV and PDF renderers (no new dependency).
9. `summaries.py` - optional Groq interpretation.

The existing `MetaGraphClient` and encrypted token storage are reused. Tokens are
decrypted only inside the worker, sent only in the `Authorization` header, and never
appear in responses, logs, job details or exports.

## Data model (migration `20261110_0009`)

| Table | Purpose | Duplicate protection |
| --- | --- | --- |
| `analytics_snapshots` | One account metric value per day: workspace, brand, account, platform, `metric_key`, `source_metric`, `period`, `snapshot_date`, `metric_value`, `metric_unit`, `value_breakdown` (e.g. reactions by type), `source`, `api_version`, `collected_at` | unique `(social_account_id, metric_key, period, snapshot_date)` - re-collection updates the row |
| `post_analytics` | Latest metrics for one post on one account: links to `content_publications`/project/draft when Autowok published it, `external_post_id`, permalink, `published_at`, `content_format`, caption preview, thumbnail, normalized columns (`reach`, `views`, `engagements`, `likes`, `reactions`, `comments`, `shares`, `saves`, `clicks`, `video_views`; `NULL` = unavailable, never 0), `raw_metrics` (source names and values), `metric_availability` (reason per key), `api_version`, `collected_at` | unique `(social_account_id, external_post_id)` |
| `post_analytics_history` | One metric set per post per collection day for trends | unique `(post_analytics_id, snapshot_date)` |
| `analytics_sync_jobs` | Sync run per account: status (`pending/running/succeeded/partial/failed/cancelled`), trigger (`manual/scheduled`), range, attempts, `next_attempt_at`, lease, error category/code/message, `records_processed`, `details` (counters, unavailable metrics, per-post errors) | unique `active_guard` - one active job per account |

Everything is workspace-scoped and cascades with the account. Facebook and Instagram
values are never merged in storage: each row carries its platform and its exact source
metric name.

## Metrics

Only metrics present in Meta's current references are collected. Deprecated metrics are
not used: Instagram `impressions` (removed for all versions on 21 April 2025) and the
Facebook `page_impressions*`, `post_impressions*`, `page_fans*` families and `*_unique`
impression variants (removed 15 June and 15 November 2025). Meta's replacements are the
"media view" metrics on Facebook and `views` on Instagram.

### Account level (daily snapshots)

| Platform | Autowok key | Official metric | Meaning | Availability requirements | Collection limitations |
| --- | --- | --- | --- | --- | --- |
| Facebook Page | `followers` | Page field `followers_count` (`fan_count` fallback) | Followers at collection time | `pages_read_engagement`, `pages_show_list` | One snapshot per sync day |
| Facebook Page | `views` | `page_media_view` (day) | Media views (replacement for `page_impressions`) | `read_insights` + `pages_read_engagement`, Page token with ANALYZE task | Pages need 100+ likes; updates about daily; 2 years of history; 90 days per request |
| Facebook Page | `reach` | `page_total_media_view_unique` (day) | Unique viewers (replacement for `page_impressions_unique`) | same | same |
| Facebook Page | `engagements` | `page_post_engagements` (day) | Reactions, comments, shares and clicks on posts | same | same |
| Facebook Page | `follows` / `unfollows` | `page_daily_follows_unique` / `page_daily_unfollows_unique` (day) | New follows / unfollows per day | same | same |
| Facebook Page | `page_views` | `page_views_total` (day) | Page profile views | same | same |
| Facebook Page | `video_views` | `page_video_views` (day) | Video views of 3 s or more | same | Accurate only for the Page's own videos |
| Facebook Page | `reactions` | `page_actions_post_reactions_total` (day) | Reactions by type, summed; breakdown kept | same | same |
| Instagram | `followers` | IG User field `followers_count` | Followers at collection time | `instagram_basic`, `pages_read_engagement` | One snapshot per sync day |
| Instagram | `reach` | `reach` (day, `time_series`) | Unique accounts reached (estimated) | `instagram_manage_insights`, `instagram_basic`, `pages_read_engagement` | Up to 48 h delay; empty result when missing; requested in windows of at most 30 days |
| Instagram | `views` | `views` (day, `total_value`) | Plays/displays of reels, posts and stories (replacement for `impressions`; Meta marks it "in development") | same | One request per day |
| Instagram | `accounts_engaged` | `accounts_engaged` | Accounts that interacted (estimated) | same | same |
| Instagram | `engagements` | `total_interactions` | Likes + saves + comments + shares + replies as counted by Meta | same | same |
| Instagram | `likes`, `comments`, `shares`, `saves`, `replies` | same names | Interaction counts | same | `comments` marked "in development" by Meta |
| Instagram | `profile_link_taps` | `profile_links_taps` | Taps on address/call/email/text buttons | same | same |

### Post level

| Platform | Autowok key | Official metric / field | Meaning | Requirements | Limitations |
| --- | --- | --- | --- | --- | --- |
| Facebook post | `views` | `post_media_view` (lifetime) | Media views (replacement for `post_impressions`) | `read_insights`, `pages_read_engagement` | Pages need 100+ likes |
| Facebook post | `reach` | `post_total_media_view_unique` (lifetime) | Unique viewers (replacement for `post_impressions_unique`) | same | same |
| Facebook post | `clicks` | `post_clicks` (lifetime) | Clicks anywhere in the post | same | same |
| Facebook post | `reactions` / `likes` | `post_reactions_by_type_total` (lifetime) | Total reactions (sum) / the `like` entry; breakdown kept. Falls back to `reactions.summary(total_count)` and `likes.summary(total_count)` when insights are unavailable | same (fallback: `pages_read_engagement`) | - |
| Facebook post | `comments` | `comments.summary(total_count)` | Total comments | `pages_read_engagement` | - |
| Facebook post | `shares` | `shares.count` | Shares. Meta omits the field at zero; an omitted field on a successful read is stored as 0 and flagged in `raw_metrics.shares_note` | same | - |
| Facebook post | `video_views` | `post_video_views` (lifetime) | Video views of 3 s or more | `read_insights` | Video posts only |
| Facebook post | `engagements` | **Calculated**: reactions + comments + shares + clicks | Mirrors `page_post_engagements`; marked `calculated_without_clicks` when insights are unavailable | - | - |
| Facebook post | `saves` | - | Not reported by Facebook | - | shown as unavailable |
| Instagram media | `reach`, `views`, `saves` (`saved`), `shares`, `engagements` (`total_interactions`) | media insights | Per-media insights | `instagram_manage_insights` | Error code 10 below 5 viewers -> `insufficient_data`; carousel children have no insights; 48 h delay; 2 years retention |
| Instagram media | `likes`, `comments` | fields `like_count`, `comments_count` | Organic counts | `instagram_basic` | `like_count` omitted when the owner hides likes |
| Instagram media | `follows`, `profile_visits` | media insights (feed posts) | Follows / profile visits from the post | `instagram_manage_insights` | Feed posts only |
| Instagram media | `reel_avg_watch_time`, `reel_total_watch_time` | `ig_reels_avg_watch_time`, `ig_reels_video_view_total_time` (ms) | Reel watch time | same | Reels only |
| Instagram media | `clicks`, `reactions`, `video_views` | - | Not reported by Instagram | - | shown as unavailable |

Stories are not collected (their insights expire after 24 hours and Autowok does not
publish stories).

### Which posts are tracked

Every sync lists the account's recent posts (`/{page-id}/published_posts`,
`/{ig-user-id}/media`) within `ANALYTICS_POST_LOOKBACK_DAYS`, up to
`ANALYTICS_MAX_POSTS_PER_SYNC`, and additionally fetches any post Autowok published
(`content_publications.external_post_id`) that was not in the listing. Autowok posts are
linked to their project/draft by external id, including the video id that Facebook returns
for video posts (matched through the post's attachment target). Posts published outside
Autowok are shown with the source "external".

## Calculations (`calculations.py`)

| Calculation | Formula | Rules |
| --- | --- | --- |
| Engagement rate by reach | engagements / reach x 100 | Facebook: (reactions + comments + shares + clicks) / unique viewers. Instagram: total_interactions / reach. `None` when reach is missing or zero. Never averaged across platforms |
| Percentage change | (current - previous) / previous x 100 | `None` when the previous value is missing or zero |
| Audience growth | last follower snapshot - first snapshot in the period | `None` with fewer than two snapshots |
| Rankings | sort by engagement rate (falls back to engagements when most posts lack reach) | Deterministic: ties broken by publish time then id; posts without the metric are excluded; the method used is returned with the data |
| Format comparison | per platform and format: posts, average engagements, average reach, average engagement rate | Groups with fewer than 3 posts are marked indicative; a "best format" is only named with enough data and is described as a past measurement, not a prediction |
| Consistency | posts per week, active days, longest gap | - |

Calculated values are always labelled ("calc", "calculated") and raw platform metrics are
stored separately in `raw_metrics`. Cross-platform totals exist only for keys the
catalogue marks comparable (followers, reach, views, likes, comments, shares); engagement
is always shown per platform with both definitions.

## Synchronization

* `schedule_analytics_syncs` creates a job for each connected Facebook/Instagram account
  whose last job is older than `ANALYTICS_SYNC_INTERVAL_HOURS` (default 12 h; Meta
  updates most Page Insights about once a day).
* `run_analytics_syncs` claims due jobs with a conditional `UPDATE` (status, lease) so
  several workers can run. A job collects:
  1. the account fields (followers);
  2. daily insights for the job range - the first run looks back
     `ANALYTICS_INITIAL_LOOKBACK_DAYS` (30), later runs `ANALYTICS_INCREMENTAL_LOOKBACK_DAYS`
     (3) because Meta data can lag 48 hours; Facebook requests are chunked to 90 days,
     Instagram `reach` to 30-day windows and the `total_value` metrics to one request per day;
  3. recent posts and their insights (pagination with bounded cursors).
* Upserts are idempotent, so retries and overlapping ranges never duplicate rows.
* Manual refresh: `POST /workspaces/{id}/analytics/sync` (Owner/Admin), limited to
  `ANALYTICS_MANUAL_REFRESH_LIMIT_PER_HOUR` per user and workspace (Redis) and to one job
  per account every `ANALYTICS_MANUAL_REFRESH_COOLDOWN_MINUTES`. The worker is woken through
  the existing Redis list and otherwise picks the job up on its next poll.

### Errors, rate limits and retries

| Meta response | Category | Effect |
| --- | --- | --- |
| Codes 4, 17, 32, 613, 80001-80014, HTTP 429 | `rate_limited` | Job returns to `pending`; next attempt after Meta's `estimated_time_to_regain_access` (from the `X-Business-Use-Case-Usage` header) or the publishing backoff with a 5-minute minimum |
| Timeouts, 5xx, codes 1/2, transient errors | `network` / `platform_temporary` | Retried with bounded exponential backoff up to `ANALYTICS_SYNC_MAX_ATTEMPTS` |
| Code 190/102, HTTP 401 | `token_expired` | Job fails; the account is marked `expired`; the user must reconnect |
| Codes 10 (other), 200-299, 3, HTTP 403 | `permission` | Job fails with a reconnect message; `last_error_code = insights_permission_denied` |
| Code 100 "valid insights metric", 3001 | `unsupported_metric` | Metrics are retried one by one; the failing metric is recorded as unavailable and the job continues |
| Code 10 "Not enough viewers" | `insufficient_data` | The media's insights are unavailable; field counts are kept |
| Code 100 subcode 33 / HTTP 404 on a post | `object_unavailable` | The post is skipped and listed in the job details |
| Missing `read_insights` / `instagram_manage_insights` scope | - | Insights are not requested at all; the job completes as `partial` with the reason per metric |

Meta applies Business Use Case rate limits (Pages: 4800 x engaged users per 24 h with a
Page token; Instagram: 4800 x impressions per app-user pair). The collector keeps request
counts in the job details and never retries a limited request immediately.

## API (`/api/v1/workspaces/{workspace_id}/analytics`)

All routes require workspace membership; `POST /sync` requires Owner or Admin. Brand,
account and post ids are checked against the workspace (404 otherwise). Common query
parameters: `start`, `end` (dates, at most 366 days, default last 28 days), `brand_id`,
`platform` (`facebook_page|instagram`), `social_account_id`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/metrics` | Metric catalogue with definitions, requirements, limitations and comparability |
| `GET` | `/overview` | Key metrics per platform with previous period and change, follower growth, published post counts, top posts, freshness |
| `GET` | `/timeseries?metric=&group_by=platform|account` | Daily series (gaps are `null`) |
| `GET` | `/accounts` · `/accounts/{account_id}` | Account insights: all supported metrics, follower series, sync status |
| `GET` | `/posts?content_format=&source=&min_engagements=&max_engagements=&sort=&order=&offset=&limit=` | Post performance list |
| `GET` | `/posts/{post_id}` | Post details with history and definitions |
| `POST` | `/posts/compare` `{post_ids: [2..6]}` | Side-by-side comparison with comparability flags |
| `GET` | `/platforms/compare` | Facebook vs Instagram comparison (comparable metrics flagged; definitions attached) |
| `GET` | `/content-performance` | Rankings, formats, weekly trend, consistency, period change |
| `POST` | `/content-performance/summary` | Optional Groq interpretation (rate limited; returns `available: false` when Groq is unavailable) |
| `POST` | `/sync` `{social_account_id?}` | Request a manual refresh (202) |
| `GET` | `/sync/status` · `/sync/history?social_account_id=&limit=` | Synchronization status and history |
| `GET` | `/reports` | Report document (JSON) |
| `GET` | `/reports/export?format=csv|pdf` | File download with the same filters |

Responses use ISO 8601 UTC timestamps. Missing values are `null`, never `0`, and carry a
reason in `metric_availability` / `reason`.

## Reports

Reports contain the reporting period and previous period, brand and accounts, key metrics
per platform (current, previous, change, availability, reason, collection time,
definition), follower growth, published post counts, up to 200 posts sorted by
engagements with their metrics and unavailable-metric notes, metric definitions, data
collection timestamps and missing-data explanations. CSV is UTF-8 with BOM; PDF is
generated by a small built-in writer (`pdf.py`, Helvetica/Courier, A4) with no extra
dependency. Exports are produced only from the caller's workspace data.

## Meta permissions and App Review

The login dialog now also requests `read_insights` (Page Insights; the connecting user
needs the ANALYZE Page task) and `instagram_manage_insights`. Both are optional at
callback time: accounts connected without them keep working for publishing, and analytics
collects followers and post counts while marking insights "unavailable" until the account
is reconnected. Using these permissions for Pages or accounts outside the app's roles
requires Advanced Access through Meta App Review and Business Verification. Page Insights
return an empty result without `read_insights`, and only Pages with 100+ likes have data.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `ANALYTICS_ENABLED` | `true` | Disable scheduling and manual refresh |
| `ANALYTICS_SYNC_INTERVAL_HOURS` | `12` | Automatic sync interval per account (1-168) |
| `ANALYTICS_INITIAL_LOOKBACK_DAYS` | `30` | Daily history collected on the first sync (max 90) |
| `ANALYTICS_INCREMENTAL_LOOKBACK_DAYS` | `3` | Days re-collected on later syncs (Meta lags up to 48 h) |
| `ANALYTICS_POST_LOOKBACK_DAYS` | `90` | How far back posts are listed |
| `ANALYTICS_MAX_POSTS_PER_SYNC` | `100` | Post budget per sync |
| `ANALYTICS_SYNC_MAX_ATTEMPTS` | `3` | Retries for transient failures |
| `ANALYTICS_SYNC_LEASE_SECONDS` | `900` | Lease before a crashed job is reclaimed |
| `ANALYTICS_MANUAL_REFRESH_COOLDOWN_MINUTES` | `15` | Minimum gap between manual refreshes of one account |
| `ANALYTICS_MANUAL_REFRESH_LIMIT_PER_HOUR` | `6` | Manual refresh requests per user and workspace |

## Local development

```
cd backend && alembic upgrade head
uvicorn app.main:app --reload          # API
python -m app.worker                   # worker: scheduler + publishing + analytics sync
cd ../frontend && npm run dev          # http://localhost:3000/dashboard/analytics
```

With Docker Compose the `worker` service already runs the analytics tasks. Connect a
Facebook Page or Instagram Professional account with the insights permissions, then use
**Refresh now** on the analytics page or wait for the scheduled sync.

## Tests

* `backend/tests/test_phase9_analytics.py`: metric catalogue, calculations, error
  classification, Facebook and Instagram collection (mocked), pagination, unsupported and
  missing metrics, missing permissions, insufficient data, rate limits with Meta's hint,
  expired tokens, permission failures, network timeouts and retry exhaustion, duplicate
  prevention, scheduler and worker loop, overview filters and platform separation, time
  series, accounts, posts, comparisons, content performance, Groq fallback, reports, CSV
  and PDF exports, roles, cooldowns and workspace isolation.
* `frontend/app/dashboard/analytics/phase9-analytics.test.tsx` and
  `frontend/lib/analytics-format.test.ts`: metric cards, unavailable states, filters,
  refresh action, post table, exports, chart legend/gaps/table view, formatting.

## Known limitations

* Live Meta insight retrieval is **not verified**; every Meta interaction is mocked.
* Daily values follow Meta's reporting day for each account (Pacific time for Page
  Insights); post dates are compared in UTC. Day boundaries can therefore differ from the
  user's timezone by a few hours.
* Instagram `total_value` metrics need one request per day in the range; the initial
  30-day backfill is therefore about 30 requests per account. Stories are not collected.
* Facebook video posts are matched to Autowok publications through the attachment target
  id; if Meta omits attachments the video publication cannot be linked.
* Only the first 100 posts per sync (configurable) are refreshed; older posts keep their
  last known values with their collection timestamp.
* The PDF export is text and tables only (no charts).
* Groq summaries depend on the workspace or server Groq configuration and are rate limited;
  they are labelled as AI interpretations and never add numbers that are not in the data.

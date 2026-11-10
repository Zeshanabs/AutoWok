# Phase 8: Content calendar, scheduling, and automated publishing queue

Phase 8 lets Owners and Admins schedule **approved** content for a Facebook Page or an eligible
Instagram Professional account at a chosen date, time and timezone. The background worker publishes
it at that moment, whether or not anyone is logged in. The worker reuses the Phase 7 publishing
service unchanged: the same Meta calls, attempt records, retry rules and duplicate protection.

## User interface

| Route | Purpose |
| --- | --- |
| `/dashboard/calendar` | Month, week, day and list views. Navigation, timezone picker (saved as a preference), filters for brand, platform, account and status, status legend, and a "Ready to schedule" list of approved, unscheduled drafts. On small screens, month and week views become an agenda list. |
| `/dashboard/calendar/new` | Scheduling form with brand, approved content, platform draft, account, date, time, timezone, approximate preview, approval status, validation messages and a final confirmation. Ambiguous DST times ask "earlier or later". |
| `/dashboard/calendar/[scheduleId]` | Details, reschedule, cancel (with confirmation), retry, reconnect hint, published link, scheduling history and publishing attempts |
| `/dashboard/publishing/queue` | Queue status: counts, jobs publishing now, jobs waiting to retry, jobs needing attention, and upcoming posts |
| `/dashboard/publishing` | Publishing history, with a new manual/scheduled filter |

Status colours: Draft, Awaiting approval, Approved, Scheduled, Queued, Publishing (processing), Published,
Failed, Cancelled. A scheduled post whose content lost its approval shows a warning on the calendar.

## Data model

* **`scheduled_posts`** holds the workspace, project, draft, account, brand and platform, plus:
  * `scheduled_at`: the UTC instant.
  * `scheduled_local` and `timezone`: the wall-clock time the user chose.
  * `status`: `scheduled | queued | processing | published | failed | cancelled`.
  * `revision`: incremented on every edit.
  * `content_version_number`: the approved draft version that was scheduled.
  * `active_guard`: unique while active or published, so a draft can't be scheduled twice to the same account.
  * `publication_id`: the Phase 7 job created at due time.
  * Also `last_error`, `created_by`/`updated_by`, and the timestamps `queued_at`, `cancelled_at`, `published_at`.
* **`scheduling_history`** records each action (`created`, `rescheduled`, `updated`, `cancelled`, `queued`,
  `published`, `failed`, `retry_scheduled`, `retried`, `validation_failed`, `missed`) with previous and new
  times, the user (or System), and details.
* **`users.timezone`** is the preferred IANA timezone. When it is empty, `DEFAULT_TIMEZONE` applies (default `UTC`).

Attempts, Meta responses, errors and external post IDs are **not** duplicated. They stay on
`content_publications` and `publishing_attempts`.

## Timezones

* Instants are stored in UTC. API responses for scheduling and calendar data use ISO 8601 UTC with a trailing `Z`.
* Clients send a wall-clock `scheduled_local` (`YYYY-MM-DDTHH:MM`) plus an IANA `timezone`. The server converts it.
* **Nonexistent times** (DST spring-forward gaps, for example `2026-03-08 02:30` in America/New_York) are rejected (422).
* **Ambiguous times** (DST fall-back) are rejected unless `ambiguous` is `"earlier"` or `"later"`.
* Calendar ranges are computed in the viewer's timezone. Weeks start on Monday, month view covers whole
  weeks, list view covers 30 days, and DST days are 23 or 25 hours long. An item's `local_date` and
  `local_time` depend on the viewer's timezone.
* `GET/PATCH /api/v1/me/preferences` stores the user's timezone. `GET /api/v1/timezones` lists valid zones.

## API (`/api/v1`)

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/workspaces/{id}/calendar?view=month\|week\|day\|list&date=YYYY-MM-DD&timezone=&brand_id=&platform=&social_account_id=&status=` | Items (scheduled posts and immediate publications), the range, the days, and unscheduled approved drafts |
| `POST` | `/workspaces/{id}/scheduled-posts` | `{draft_id, social_account_id, scheduled_local, timezone, confirm: true, project_id?, brand_id?, ambiguous?}` |
| `GET` | `/workspaces/{id}/scheduled-posts?upcoming=&status=&start=&end=&brand_id=&platform=&social_account_id=` | List |
| `GET` | `/scheduled-posts/{id}` · `/scheduled-posts/{id}/history` | Details with history and job attempts |
| `PATCH` | `/scheduled-posts/{id}` | Change the time, timezone and/or account. Re-validates and re-binds to the current approved version |
| `POST` | `/scheduled-posts/{id}/reschedule` | Change the time only |
| `POST` | `/scheduled-posts/{id}/cancel` | Cancel |
| `POST` | `/scheduled-posts/{id}/retry` | Retry a failed publishing job (`confirm_not_published` for uncertain outcomes) |
| `GET` | `/workspaces/{id}/publishing/queue` | Queue status |
| `GET` | `/workspaces/{id}/publishing/jobs?source=schedule` | Scheduled publishing history (existing Phase 7 endpoint) |

Members can view the calendar and queue. Only Owners and Admins can create, edit, cancel or retry schedules.
Every ID from the browser is checked against the database for workspace ownership; cross-workspace IDs return 404.

### Validation when scheduling

The user must be authenticated with the Owner or Admin role. The post, brand, account and media must belong
to the workspace, and the brand must match the content. The Phase 7 eligibility checks also apply:

* approved content
* a connected and eligible account with publishing permissions
* valid platform content and media in a supported format

The time must be at least `SCHEDULE_MIN_LEAD_SECONDS` in the future and within `SCHEDULE_MAX_HORIZON_DAYS`.
The draft must not already be scheduled, publishing or published to that account. Immediate publishing is
blocked while a schedule exists for the same draft and account, and the reverse is also true.

### Approval and versioning

Editing content after approval resets it to draft (Phase 5 rules), which blocks publishing. Each schedule
records the approved version. If the content changes and is approved again, the schedule still fails at due
time with "content changed after this job was created" until a user saves the schedule again (edit or
reschedule), which binds it to the newly approved version. An old approval is never applied to new content.

## Scheduler and worker

The worker (`python -m app.worker`, or the `worker` service in Docker Compose) runs this loop:

1. It waits up to `WORKER_POLL_INTERVAL_SECONDS` for a Redis wake-up.
2. It runs the **scheduler** task (`schedule_due_posts`). For each post with `status='scheduled'` and
   `scheduled_at <= now`, it does the following in **one database transaction**:
   * Claims the post with `UPDATE … WHERE id=… AND status='scheduled' AND revision=…`. Only one worker can win.
   * Revalidates ownership, account connection, approval, the content version, media and platform rules.
   * Creates the Phase 7 job with idempotency key `schedule:<id>:<revision>`, links it, and commits.
   * After the commit, sends a Redis wake-up.
3. It processes due jobs from the database: new jobs, jobs whose retry time has come, and jobs whose
   lease expired after a crash.

A completion hook mirrors the job result onto the schedule (published, failed, retrying, or cancelled) and writes history.

### Reliability guarantees

* **No duplicates:**
  * The schedule claim is conditional on status and revision.
  * Each revision gets exactly one job (unique idempotency key).
  * The job claim is atomic, and the Phase 7 `active_guard` blocks a second job for the same draft and account.
* **Crash safety:**
  * Claim and job creation commit together, so a crash leaves the post `scheduled`, and it is picked up again.
  * Abandoned jobs are recovered after their lease expires. An interrupted final Facebook call is treated
    as uncertain and is never republished automatically. Instagram resumes safely using the saved container ID.
* **Redis restarts:** Redis only wakes the worker. The database is polled every interval, and Redis errors fall
  back to polling (with a sleep, so the loop does not spin).
* **Long outages:** a post more than `SCHEDULE_MAX_LATENESS_SECONDS` (default 6 hours) late is marked failed
  ("Missed the publishing window") instead of being published unexpectedly late.
* **Multiple instances:** any number of API and worker processes can run against the same database.

### Rescheduling and cancellation races

* `scheduled`: reschedule or cancel is a conditional update.
* `queued` (job created but not started): the job is cancelled with `UPDATE … WHERE status='pending'`
  first. If a worker has already claimed it, the update matches nothing and the user gets
  409 "being published right now". Cancellation and publication cannot both succeed.
* `processing`: it cannot be changed.
* `published`: it cannot be rescheduled.
* `failed`: it can be rescheduled or cancelled, unless the outcome is uncertain. In that case the user must
  first resolve it with "retry, I confirmed it was not published".
* Every reschedule increments `revision`. A stale queue entry for an older revision can never be claimed
  and never matches the new idempotency key.

## Retries

Scheduled jobs follow the Phase 7 rules (see `docs/phase-7-media-publishing.md`):

* Network and temporary errors retry automatically with bounded exponential backoff and jitter.
* Rate limits retry with a base delay of at least 5 minutes.
* Expired tokens, permissions, invalid media and invalid content need user action: the user fixes the
  cause, then presses Retry.
* Permanent rejections are not retryable; reschedule the post instead.

The original scheduled time is kept for display. The schedule shows "Queued" with the last error while it waits for a retry.

## Running locally

```
docker compose up --build            # postgres, redis, backend, worker, frontend
# or, directly:
cd backend && alembic upgrade head
uvicorn app.main:app --reload        # API
python -m app.worker                 # worker: scheduler + publishing (run in a second terminal)
```

Publishing media requires `PUBLIC_MEDIA_BASE_URL` and `MEDIA_URL_SIGNING_SECRET` (see Phase 7).

## Tests

`backend/tests/test_phase8_scheduling.py` covers:

* DST and timezone conversion, and month, week, day and list ranges
* preferences, schedule validation and rejections, update, reschedule, cancel, and history
* calendar filters and timezone-dependent days
* due processing exactly once, ignoring future posts, concurrent schedulers, and stale revisions
* cancellation and worker races, approval invalidation, version mismatch, and missed windows
* recovery from a worker crash and a Redis outage, and the worker loop
* rate limits, expired tokens, permanent and uncertain failures, retries, and queue status
* immediate publishing alongside schedules (regression)

Frontend: `app/dashboard/calendar/phase8-calendar.test.tsx`.

## Known limitations

* Live Meta publishing remains **not verified**. Every Meta interaction is mocked.
* Automated tests run on SQLite. The conditional-update locking is designed for PostgreSQL row locks, but
  has not been run against PostgreSQL in this environment (Docker was unavailable).
* There is no drag-and-drop rescheduling. Use the reschedule form.
* Recurring posts and campaigns are out of scope.
* Posts are processed at the next worker poll after the due time, which adds up to
  `WORKER_POLL_INTERVAL_SECONDS` (default 15 s) of delay, plus Meta processing time.
* The week start (Monday) is fixed.

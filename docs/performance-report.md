# Performance report (Phase 12)

Measured results before and after the Phase 12 changes, the conditions they were measured under, and initial performance budgets. Nothing here is estimated: every number is from a run recorded on 2026-11-16. Read the conditions before comparing with any other environment.

## Test conditions

| | |
|---|---|
| Machine | One developer workstation: Windows 11 Pro, 7.6 GB RAM visible to Docker; the API ran natively (Python 3.12.8, one uvicorn process), PostgreSQL 16 and Redis 7 in Docker Desktop containers reached through Docker's port forwarding |
| Not a production host | Client, API and database shared the machine. Docker's network path adds roughly 2–5 ms to every database round trip here, which a co-located database would not. |
| Background load | Other containers were running on the same Docker VM, including an unrelated development container in a restart loop that at times used a full CPU core. This affected later runs: see [Noise](#noise-and-what-the-numbers-can-support). |
| Dataset | Seeded by `backend/perf/seed.py` (fixed random seed): 31 workspaces, about 190,000 rows. The measured workspace has 5 brands, 2,000 content projects (4,000 drafts, 12,000 versions), 1,500 media assets, 1,200 scheduled posts spread over ±45 days, 1,000 publishing jobs, 1,800 daily analytics snapshots, 1,500 analysed posts, 2,000 notifications. Thirty other workspaces add data the queries must not touch. |
| Load | `backend/perf/bench.py`: 8 concurrent clients, up to 200 requests per endpoint, 25-second budget per endpoint (slow endpoints get fewer samples; the sample count is shown) |
| Not measured | CPU and memory per request, behaviour above 8 concurrent clients, multi-container scaling, the worker under load, real Meta or Groq latency |

Reproduce:

```sh
cd backend
DATABASE_URL=postgresql+psycopg://.../autowok_perf alembic upgrade head
DATABASE_URL=... PERF_ALLOW_SEED=1 python -m perf.seed          # refuses a database that is not named perf/test or already has users
DATABASE_URL=... uvicorn app.main:app --port 8010
python -m perf.bench --base-url http://127.0.0.1:8010 --workspace <id> --email ... --password ... --out result.json
DATABASE_URL=... python -m perf.query_count --workspace <id> --email ... --password ...   # SQL statements per request
```

## API latency, before and after

Run A is the code before Phase 12. Run B is the Phase 12 code measured about an hour later under similar conditions. Milliseconds; 8 concurrent clients; error rate 0 unless noted.

| Endpoint | A avg | A p50 | A p95 | A p99 | B avg | B p50 | B p95 | B p99 | Change in avg |
|---|---|---|---|---|---|---|---|---|---|
| `GET /health` | 9 | 9 | 13 | 14 | 17 | 16 | 29 | 38 | see note 1 |
| `POST /auth/login` (5 sequential) | 68 | 65 | 77 | – | 93 | 66 | 201 | – | within noise |
| `GET /auth/me` | 115 | 114 | 163 | 170 | 60 | 52 | 96 | 143 | −48% |
| Brands list | 183 | 177 | 272 | 293 | 73 | 62 | 114 | 234 | −60% |
| Content projects list | 1,900 | 2,184 | 2,894 | 2,999 | 213 | 202 | 321 | 380 | −89% |
| Media assets list | 512 | 515 | 786 | 864 | 324 | 325 | 511 | 621 | −37% |
| Calendar, month view | 25,655 (n=8) | 25,682 | 25,988 | – | 2,040 (n=88) | 2,085 | 2,403 | 2,513 | −92% |
| Calendar, week view | 3,763 (n=56) | 3,712 | 4,006 | 4,012 | 432 | 416 | 582 | 636 | −89% |
| Publishing queue | 2,445 (n=80) | 2,440 | 2,809 | 2,849 | 172 | 164 | 223 | 322 | −93% |
| Publishing jobs list | 2,642 (n=80) | 2,589 | 3,096 | 3,120 | 227 | 210 | 362 | 494 | −91% |
| Scheduled posts list | 9,542 (n=24) | 9,389 | 10,643 | 10,649 | 533 | 533 | 655 | 900 | −94% |
| Analytics overview | 980 (n=184) | 991 | 1,269 | 1,483 | 647 | 671 | 806 | 880 | −34% |
| Analytics time series | 217 | 216 | 286 | 333 | 112 | 104 | 178 | 271 | −48% |
| Analytics posts | 276 | 276 | 378 | 512 | 143 | 133 | 192 | 339 | −48% |
| Analytics content performance | 793 | 792 | 1,107 | 1,214 | 524 | 536 | 681 | 840 | −34% |
| Analytics report | 1,670 (n=120) | 1,662 | 1,920 | 1,943 | 1,276 | 1,273 | 1,780 | 1,788 | note 2 |
| Automations list | 167 | 165 | 223 | 286 | 69 | 62 | 90 | 97 | −59% |
| Notifications | 201 | 205 | 240 | 245 | 100 | 91 | 149 | 213 | −50% |
| Agent workflows list | 184 | 184 | 225 | 236 | 78 | 72 | 100 | 124 | −58% |
| Agent workflow stats | 194 | 192 | 221 | 333 | 79 | 75 | 106 | 118 | −59% |

Note 1: `/health` does no I/O. It gained request-context, metrics and header work in Phase 12, but the difference could not be separated from machine noise: an in-process comparison of old and new code gave medians of 11, 50 and 23 ms for the old code and 18, 37 and 29 ms for the new code in three alternating rounds.

Note 2: in run B, 171 of 200 report requests were rejected by the new export rate limit (30 per hour), which is the limit working. The timing is from the 29 that succeeded.

Response sizes: the content projects list went from 1.58 MB (all 2,000 projects) to 158 KB (the newest 200, paginated). Others are unchanged.

### SQL statements per request

Measured in-process with `perf/query_count.py`, one request each.

| Endpoint | Before | After |
|---|---|---|
| `GET /auth/me` | 7 | 3 |
| Brands list | 8 | 4 |
| Content projects list | 7 | 4 |
| Calendar, month view | 2,080 | 13 |
| Calendar, week view | 307 | 13 |
| Publishing queue | 89 | 12 |
| Publishing jobs list | 208 | 6 |
| Scheduled posts list | 808 | 8 |
| Analytics overview | 24 | 20 |
| Analytics report | 35 | 31 |
| Automations, notifications, agent workflows lists | 8–9 | 4–5 |

### What changed

| Change | Effect |
|---|---|
| Session "last used" is written at most every 5 minutes instead of on every request, and the user is loaded with the session | 4 fewer statements and one fewer commit on every authenticated request |
| Calendar, scheduled posts, publishing jobs and queue load related rows in batches instead of 5–7 lookups per row | 2,080 → 13 statements for the month view |
| Publishing queue counts by status in SQL and loads only the rows it shows | No longer loads every job and scheduled post in the workspace |
| Content projects list is paginated (default 200, maximum 500, `X-Total-Count` header) | 10× smaller response |
| Calendar's "ready to schedule" list excludes scheduled and published drafts in SQL | No full id sets loaded; also returns the 50 newest matches rather than 50 minus exclusions |
| Draft list loads versions in one query | Removes one query per draft |
| Media upload and download no longer hold whole files in several copies or block the event loop | See [security-assessment.md](security/security-assessment.md) H1 |

## Database

### Index changes (migration `20261116_0012`)

Added, each for a specific query:

| Index | Serves |
|---|---|
| `content_projects (workspace_id, created_at)` | The paginated project list |
| `content_approvals (created_at) WHERE status = 'pending'` | The approval-reminder scan the worker runs every minute |
| Partial indexes on `notifications(execution_id)`, `notifications(automation_id)`, `content_tasks(execution_id)`, `content_tasks(automation_id)`, `content_tasks(publication_id)`, `automation_execution_steps(action_id)`, `automation_events(origin_automation_id)`, `post_analytics(draft_id)`, `agent_workflows(accepted_project_id)` | Foreign keys PostgreSQL must scan when the parent row is deleted (automation edits and deletes, draft deletion). Partial (`IS NOT NULL`) because most rows are NULL. |

Removed: five indexes that exactly duplicated a unique constraint or another index (`ix_media_assets_brand`, `ix_content_publications_account`, `ix_content_drafts_platform`, `ix_content_versions_draft_number`, `ix_research_reports_research_id`).

Measured with `EXPLAIN (ANALYZE, BUFFERS)` on the seeded database:

| Query | Before | After |
|---|---|---|
| Project list (workspace, newest 200) | Bitmap scan then top-N sort, 3.26 ms | Index scan in order, 0.49 ms |
| Pending-approval reminder scan | Sequential scan of 11,000 approvals (10,925 rows discarded), 3.25 ms | Partial index scan, 0.84 ms |

Both are small in absolute terms at this size; the point is that they no longer grow with the whole table. The foreign-key indexes were added from the schema (a delete of a parent row scans the child table without them), not from a timing.

About 30 single-column indexes are left-prefixes of a composite index and could be dropped to speed up writes. They were left in place: removing them needs write-heavy measurements that were not taken.

The migration creates and drops indexes `CONCURRENTLY` on PostgreSQL, so it does not block writes. It was applied, checked for drift, downgraded and re-applied on PostgreSQL 16.

### Other findings

* Foreign keys all declare `ON DELETE`; uniqueness constraints back every idempotency key and duplicate guard.
* The worker's due-job queries now order never-attempted jobs first on PostgreSQL (they previously sorted last, behind retries).
* Connection pool, connect timeout and a 30-second statement timeout are now configured ([configuration.md](configuration.md#database-and-redis)).
* Several routes still hold a database connection while waiting for Groq or Meta (content generation, analytics summary, provider tests, OAuth callback). With the default pool of 15 connections per process, 15 slow external calls at once would make other requests wait. The new per-user rate limits bound this; restructuring those routes is a follow-up.
* Analytics endpoints aggregate rows in Python (about 20 statements and several thousand rows for the overview). They are the slowest remaining read paths; moving the aggregation into SQL is the next optimisation.
* No retention exists for sessions, OAuth state, audit logs or automation events.

## Frontend

Production build (`next build`, Next.js 16.4.3, Turbopack), static output measured on disk:

| | Before | After |
|---|---|---|
| JavaScript, all routes (uncompressed) | 1,484,625 bytes in 57 files | 1,505,264 bytes in 57 files |
| Largest JavaScript file | 229,850 bytes | 235,074 bytes |
| CSS | 45,100 bytes | 45,187 bytes |
| Fonts | 146,464 bytes in 11 files | 75,948 bytes in 5 files |
| Routes prerendered | 45 | 45 |

Login page from the production container through the proxy: 10 script files, 187 KB transferred compressed, 7.8 KB of HTML, no third-party origins.

JavaScript grew by 20.6 KB (1.4%) for error reporting, dialog focus handling and the polling helper. The unused monospace font was removed. The only runtime dependencies are `next`, `react` and `react-dom`; charts and the calendar are hand-written, so there is no large library to split.

Request behaviour changed (not timed in a browser):

* Analytics pages no longer refetch every chart every 5 seconds while a sync runs; only the sync status is polled, and the pages reload once when it finishes.
* All seven polling loops stop while the tab is hidden and skip a tick while the previous request is still running.
* Media grids show the stored poster image for videos instead of opening each video file.
* The two draft cards on the content editor share one media-library request and one accounts request instead of making their own.

Not done, and listed in [accessibility-report.md](accessibility-report.md#not-addressed): a shared layout for the dashboard (the header remounts on navigation), request caching for brand and account lists, and pagination in the media, publishing and notification screens. No browser-based measurement (Lighthouse, Web Vitals) was taken; no hydration warnings were seen in the build or test output, but pages were not inspected in a browser console.

## Noise and what the numbers can support

A final benchmark run on the finished code, after the dependency upgrades, was 2–3 times slower than run B on every endpoint, including ones with no code change in between. The cause was the machine, not the code:

* SQL statement counts were identical to run B.
* Time spent inside the database driver itself doubled for the same statements.
* An unrelated container on the same Docker VM was using about 97% of a CPU core.
* Running identical code alternately with the old and the new dependency versions gave totals of 3.4, 2.9 and 6.6 seconds (old) and 2.7, 4.4 and 3.5 seconds (new) for the same 151 statements: no consistent difference.

So: the before/after comparison above (runs A and B) is solid for the list endpoints, whose improvements are 9× to 18× and far outside this noise, and for the statement counts, which do not depend on the machine. The smaller improvements (30–60%) agree with the reduction in statements per request, but a difference of that size is within what this machine can produce on its own. The dependency upgrade showed no measurable regression; small effects cannot be ruled out. Re-run the benchmark on staging for numbers you intend to hold the system to.

## Initial performance budgets

Set from run B with headroom, for this dataset size at 8 concurrent clients. They are starting points to validate on staging, not service levels.

| Path | p95 budget |
|---|---|
| Health | 50 ms |
| Authentication check (`/auth/me`) | 200 ms |
| Small lists (brands, automations, notifications, agent workflows) | 300 ms |
| Content projects, media, publishing jobs lists | 750 ms |
| Publishing queue | 500 ms |
| Calendar, week view | 1,000 ms |
| Calendar, month view (about 800 items) | 3,500 ms |
| Analytics pages | 1,500 ms |
| Analytics report | 2,500 ms |
| SQL statements for any list endpoint | 35, and not proportional to the number of rows |

The statement-count budget is the one to enforce in tests: it does not depend on the machine.

## Not covered

Automation execution, agent workflow execution and the publishing worker were not load-tested. Their correctness under concurrency, retries and crashes is covered by tests ([architecture.md](architecture.md#background-work-and-recovery)); their throughput is bounded by external services (Meta, Groq) that were mocked, so a local timing would not be meaningful.

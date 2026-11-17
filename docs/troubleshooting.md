# Troubleshooting guide

Symptoms, how to confirm the cause, and what to do. Commands assume the production Compose stack:

```sh
C="docker compose --env-file .env.production -f docker-compose.prod.yml"
```

For an outage in progress, start with [incident-response.md](incident-response.md).

## First look

```sh
$C ps                                         # which services are up and healthy
$C logs --since 15m backend | grep '"level": "ERROR"'
$C logs --since 15m worker  | grep '"level": "ERROR"'
curl -s https://<host>/api/v1/ready           # {"dependencies": {"database": ..., "redis": ...}}
```

A user can give you the `request_id` shown with an error (it is also the `X-Request-ID` response header). Search the logs for it to see that request's log lines.

## Start-up

| Symptom | Cause | Fix |
|---|---|---|
| API or worker exits immediately with `ConfigurationError: Invalid configuration. Unsafe production configuration: ...` | A required production setting is missing or unsafe. The message names each one. | Set the named variables in `.env.production` ([configuration.md](configuration.md#fail-safe-start-up-in-production)), then `$C up -d`. |
| `ConfigurationError: ... AGENT_LEASE_SECONDS must be greater than AGENT_STEP_TIMEOUT_SECONDS` | Agent lease shorter than a step may take. | Raise the lease or lower the step timeout. |
| Compose reports `set POSTGRES_PASSWORD` (or another name) | A required Compose variable is empty. | Fill it in `.env.production`. |
| Proxy restarts; log says `wrong argument count ... 'email'` | `ACME_EMAIL` is empty. | Set it. |
| Proxy runs but HTTPS fails | DNS does not point at the server, or port 80/443 is closed, so the certificate cannot be issued. | Fix DNS or the firewall; `$C logs proxy` shows the ACME error. |
| `relation "..." does not exist` in API logs | Migrations were not applied. | `$C run --rm migrate`. |
| Development container fails with `ModuleNotFoundError` (for example `PIL`, `prometheus_client`) | The development image is older than `requirements.txt`. | `docker compose up --build`. |

## Signing in and requests

| Symptom | Cause | Fix |
|---|---|---|
| Every POST returns 403 "Request origin could not be verified" | The browser's origin is not in `CORS_ORIGINS`, or a non-browser client did not send `Origin` and `X-CSRF-Protection: 1`. | Set `PUBLIC_ORIGIN` / `CORS_ORIGINS` to the exact origin users load (scheme, host, port). |
| Login works but the next request is 401 | The session cookie is `Secure` and the site is being used over plain HTTP, or the web app and API are on different sites. | Use HTTPS and one origin. |
| 400 "Invalid host header" | `ALLOWED_HOSTS` does not include the host name in use. | Add it. |
| 429 "Too many ... requests" | A rate limit was reached. The message names the feature and `Retry-After` gives the wait. | Wait, or raise the matching `RATE_LIMIT_*` setting ([configuration.md](configuration.md#rate-limits)). |
| Everyone is rate limited at once on login | The API sees the proxy's address as the client. | Check `FORWARDED_ALLOW_IPS` and that the proxy sends `X-Forwarded-For` ([deployment.md](deployment.md#behind-another-proxy-or-load-balancer)). |
| 503 "... is temporarily unavailable" on login or other limited actions | Redis is unreachable; rate limits fail closed. | `$C ps redis`, `$C logs redis`; check `REDIS_PASSWORD` matches on both sides. |
| 413 "The request is too large" | Body above `MAX_REQUEST_BODY_BYTES`, or an upload above the media limit or the proxy limit. | Reduce the file, or raise `MEDIA_MAX_*_BYTES` and the proxy's `max_size`. |
| 500 with a `request_id` | Unexpected error. | Search the logs for the id; the entry has `error_category` and a traceback. |

## Publishing and scheduling

| Symptom | Check | Fix |
|---|---|---|
| Posts stay "Queued" / nothing publishes | `$C ps worker`; `/api/v1/health/details` → `worker.available`; metric `autowok_workers_alive` | Start or restart the worker: `$C up -d worker`. Jobs are in the database and resume. |
| Worker is up but slow to publish | Worker log lines "Task budget used up"; `autowok_queue_depth` | A long AI workflow or sync is running. Add a second worker (`--scale worker=2`) or lower `WORKER_TASK_BUDGET_SECONDS`. |
| Job failed: "Reconnect the account" / token expired | Publishing page → job details | Reconnect the account in Settings → Social accounts. |
| Job failed with "outcome uncertain" | Meta did not confirm the last request, or the worker stopped during it. | Look at the Page or profile. If the post is there, leave it. If not, use Retry and confirm it is not there. It is never retried automatically, to avoid a duplicate. |
| Job failed: "interrupted repeatedly" (`attempts_exhausted`) | The worker stopped several times while running this job. | Check worker logs for a crash around the job, then Retry. |
| Scheduled post marked "Missed the publishing window" | The worker was unavailable for longer than `SCHEDULE_MAX_LATENESS_SECONDS` (6 hours) after the scheduled time. | Reschedule the post. |
| Scheduled post failed: "could not be queued because of an unexpected error" | Worker logs at that time, category `publishing`. | Fix the cause shown in the log, then reschedule. |
| Instagram or Facebook cannot fetch media | `PUBLIC_MEDIA_BASE_URL` must be the public HTTPS origin and `/api/v1/public-media/...` must be reachable from the internet. | Correct the origin; check the proxy. |
| A scheduled post shows "Queued" although its job finished | Corrected automatically within a minute by the worker's reconciliation. | If it persists, check that a worker is running. |

## Analytics

| Symptom | Fix |
|---|---|
| "Last synchronized" does not advance | Check `autowok_analytics_last_success_timestamp_seconds` and the sync history on the analytics page. A failed job shows its reason (token expired, permission missing, rate limited). |
| Metrics shown as unavailable | The account was connected without the insights permission, or Meta does not provide that metric for the account type. Reconnect and grant `read_insights` / `instagram_manage_insights`. |
| Manual refresh refused | Cooldown (15 minutes per account) or hourly limit reached. |

## AI

| Symptom | Fix |
|---|---|
| "Groq is not configured" | Save a key in Settings → AI, or set `GROQ_API_KEY` and `GROQ_DEFAULT_MODEL`. |
| Workflow waits, then continues later | Groq returned a rate limit; the step is rescheduled using Groq's retry time. Free-tier limits are per model and set by Groq. |
| Workflow stays "Pending" | No worker is running. |
| Content intelligence tools return generic suggestions | Those tools are rule-based; they do not call Groq. Use content generation in the content studio or an AI workflow for model output. |
| 429 on generation | Per-user hourly limit (`RATE_LIMIT_AI_GENERATE_PER_HOUR`). |

## Database and performance

| Symptom | Check | Fix |
|---|---|---|
| `/api/v1/ready` 503 with `database: false` | `$C ps postgres`, `$C logs postgres` | Restore the database service; the API and worker reconnect by themselves. |
| Requests fail after 30 seconds waiting | Log shows a pool timeout. Many requests are waiting on Groq or Meta while holding a connection, or the pool is too small. | Raise `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` within PostgreSQL's `max_connections`. |
| `canceling statement due to statement timeout` | A query exceeded `DB_STATEMENT_TIMEOUT_MS` (30 s). | Find the query in the log; check for a missing index or an unusually large workspace. |
| A list page is slow | `python -m perf.query_count` against a copy shows statements per request. | A count that grows with the number of rows is an N+1 query ([performance-report.md](performance-report.md)). |
| Migration waits or fails with an INVALID index | A concurrent index build was interrupted. | `DROP INDEX CONCURRENTLY <name>;` then run the migration again (it is idempotent). |

## Monitoring

| Symptom | Fix |
|---|---|
| `/metrics` returns 401 | Send `Authorization: Bearer <METRICS_TOKEN>`. |
| `/metrics` returns 404 | From outside: expected, the proxy blocks it. From inside: `METRICS_ENABLED=false`, or production without a token. |
| No worker counters in `/metrics` | The worker has not run since Redis data was last cleared, or Redis is unreachable from the worker. |
| Logs are not JSON | `LOG_FORMAT=text` is set, or `APP_ENV` is not `production`. |

## Local development

| Symptom | Fix |
|---|---|
| Frontend type check fails in `.next/types/validator.ts` | Stale generated types from an older dev session. Delete `frontend/.next/dev/types` and run `npx next typegen`. |
| Frontend tests fail at import when run from Git Bash on Windows | Run them from PowerShell at the canonical path. |
| `docker compose up` for development collides with a production test | The two stacks use different project names (`autowok` and `autowok-prod`); do not override them to the same name. |
| Python is not on PATH | Use the full interpreter path, or the virtual environment's `python`. |

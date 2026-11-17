# Monitoring guide

What Autowok emits (logs, metrics, health, error reports), how to collect it, and what to alert on. Everything here works without an external provider; connecting one is configuration.

**Verification status.** Logs, metrics, health endpoints and the error-reporting interface were exercised by automated tests and against the production stack running locally. No external monitoring system (Prometheus, Grafana, Sentry, a log platform) was connected, so no dashboard or alert has been proven to fire.

## Health checks

| Endpoint | Meaning | Use for |
|---|---|---|
| `GET /api/v1/health`, `/api/v1/health/live` | The API process answers. Touches no dependency. | Container liveness (restart when it fails) |
| `GET /api/v1/ready` | 200 when PostgreSQL and Redis both answer; **503** otherwise, with `{"dependencies": {"database": bool, "redis": bool}}` | Load balancer readiness, deployment checks |
| `GET /api/v1/health/details` | Dependencies, live worker count, whether Groq/Meta/media URL are configured, error reporter in use | Operators and monitoring; requires `Authorization: Bearer <METRICS_TOKEN>` |
| `python -m app.worker healthcheck` | Exit 0 when the worker's heartbeat file is fresh | Worker container health check |

Liveness deliberately ignores the database: a short database outage should mark the API "not ready", not restart it. No endpoint returns credentials, connection strings, host names or versions. The proxy answers 404 for `/api/v1/health/details`, `/metrics` and the API docs, so they are reachable only from inside the network.

"External dependency availability" is reported as configuration presence only. The health check does not call Groq or Meta: doing so on every probe would spend rate limit and make Autowok's health depend on theirs. Their real availability shows in the request metrics below.

## Logs

One JSON object per line on stdout in production (`LOG_FORMAT=json`), readable text in development.

```json
{"timestamp": "2026-11-16T14:42:19.959+00:00", "level": "INFO", "service": "autowok-api",
 "environment": "production", "logger": "autowok.access", "message": "POST /api/v1/content/projects -> 201",
 "request_id": "7bf35c58...", "correlation_id": "7bf35c58...", "user_id": "…", "workspace_id": "…",
 "operation": "POST /api/v1/content/projects", "http_status": 201, "duration_ms": 41.2}
```

| Field | Notes |
|---|---|
| `timestamp`, `level`, `service`, `environment`, `logger`, `message` | Always present. `service` is `autowok-api` or `autowok-worker`. |
| `request_id` | One per HTTP request; returned in the `X-Request-ID` response header and in the body of an unexpected error. A client-supplied `X-Request-ID` is used if it is a plain token. |
| `correlation_id` | `X-Correlation-ID` from the caller if supplied, otherwise the request id; one per worker job. |
| `user_id`, `workspace_id` | Added once the request is authenticated and the workspace authorized. |
| `operation` | Method and route pattern (never the raw path), or `worker.<task>`. |
| `error_category` | On error reports: `backend`, `frontend`, `background_job`, `publishing`, `analytics_sync`. (`external_api` and `ai_provider` are reserved; Meta and Groq failures are currently tracked through the request metrics and on the job record, not as separate error reports.) |
| `exception_type`, `exception` | Traceback, on errors. |

Passwords, tokens, API keys, bearer values, OAuth codes and connection-string passwords are masked by a filter applied to every line and structured field. Request and response bodies are never logged. Health and metrics requests are not logged.

**Collection:** containers log to Docker's `json-file` driver with rotation (20 MB × 5 files). Ship them with your platform's agent (Fluent Bit, Vector, Promtail, a cloud agent) reading container stdout. Nothing in Autowok depends on a particular log platform.

To follow one request across the stack, search for its `request_id`; to follow a job, its `correlation_id`.

## Metrics

`GET /metrics` on the API, Prometheus text format, with `Authorization: Bearer <METRICS_TOKEN>`. It is not under `/api/v1` and the proxy does not route to it; scrape it from inside the Docker network (`backend:8000`). Labels never contain workspace, user or content identifiers: routes appear as patterns.

| Metric | Type | Labels |
|---|---|---|
| `autowok_http_requests_total` | counter | `method`, `route`, `status` |
| `autowok_http_request_duration_seconds` | histogram | `method`, `route` |
| `autowok_http_requests_in_flight` | gauge | |
| `autowok_rate_limited_total` | counter | `action` |
| `autowok_errors_total` | counter | `category` |
| `autowok_client_errors_total` | counter | `source` |
| `autowok_external_requests_total`, `autowok_external_request_duration_seconds` | counter, histogram | `service` (`meta`), `outcome` |
| `autowok_ai_requests_total`, `autowok_ai_request_duration_seconds` | counter, histogram | `operation`, `outcome` (`ok`, `rate_limited`, `timeout`, `auth_error`, `error`) |
| `autowok_ai_tokens_total` | counter | `kind` (`prompt`, `completion`), when Groq reports usage |
| `autowok_dependency_up` | gauge | `dependency` (`database`, `redis`) |
| `autowok_queue_depth` | gauge | `queue`: `publishing`, `scheduled_posts`, `analytics_sync`, `automation_events`, `automation_executions`, `agent_workflows` |
| `autowok_jobs_by_status` | gauge | `queue`, `status` (includes `failed`, `published`) |
| `autowok_analytics_last_success_timestamp_seconds` | gauge | |
| `autowok_workers_alive` | gauge | |
| `autowok_worker_counter_total` | counter | `name` |

The worker has no HTTP port. It writes its counters to Redis and the API includes them in the scrape as `autowok_worker_counter_total{name=...}`:

| `name` | Meaning |
|---|---|
| `iterations`, `iteration_seconds` | Worker loops and their total time |
| `task_runs:<task>`, `task_items:<task>`, `task_seconds:<task>`, `task_failures:<task>` | Per periodic task |
| `publishing:<status>`, `publishing_seconds` | Publishing attempts by resulting status (`published`, `failed`, `pending`), and time |
| `ai:<outcome>`, `ai_seconds`, `ai_tokens:<kind>` | Groq calls made by agent workflows |
| `external:meta:<outcome>` | Meta calls made by the worker |
| `errors:<category>` | Errors reported by the worker |

Queue and job gauges are computed from the database at scrape time (cached for 10 seconds) and are totals across all workspaces.

**Limitations.** API metrics are per process: with several API containers, scrape each one (or aggregate in your monitoring system). Worker counters are cumulative in Redis and reset if Redis data is lost. `scheduled_posts` depth includes posts scheduled for the future.

Example Prometheus scrape configuration, run inside the same Docker network:

```yaml
scrape_configs:
  - job_name: autowok
    metrics_path: /metrics
    authorization:
      credentials_file: /etc/prometheus/autowok-metrics-token
    static_configs:
      - targets: ["backend:8000"]
```

## Error reporting

All unexpected failures go through one function, `report_error(category, message, exc, **fields)` in `backend/app/core/error_reporting.py`. It writes a structured error log line, increments `autowok_errors_total{category}`, and forwards to the configured reporter.

| What | How it is captured |
|---|---|
| Backend exceptions | Global handler: logged with the request context; the client receives a generic message and the request id |
| Frontend runtime errors | Error boundaries and `window` error/rejection listeners post to `POST /api/v1/client-errors` (bounded fields, rate limited, de-duplicated in the browser) → category `frontend` |
| Failed background jobs | Worker: every task and job failure → `background_job` / `publishing` / `analytics_sync` |
| External API failures | Meta request metrics by outcome; failures are recorded on the job and in the audit log |
| AI provider failures | Groq request metrics by outcome; failed agent steps are recorded on the workflow |

**Using Sentry (optional).** Add `sentry-sdk` to the backend image and set `SENTRY_DSN`. The reporter then also sends each error with its category and context, with personal data collection off. If the DSN is set but the package is missing, start-up logs a warning and `/api/v1/health/details` shows `"error_reporting": "sentry-unavailable"`; errors continue to be logged. The Sentry path was exercised only with the package absent; sending to a real Sentry project was not tested.

**Another provider.** Implement the two-method `ErrorReporter` protocol and call `set_reporter()` at start-up.

## Alerts to configure

Suggested starting points; tune to your traffic.

| Alert | Condition | Meaning |
|---|---|---|
| API down | `/api/v1/health` fails for 1 minute | Process or proxy problem |
| Not ready | `/api/v1/ready` returns 503 for 2 minutes | Database or Redis unreachable |
| No worker | `autowok_workers_alive == 0` for 3 minutes | Nothing is being published |
| Publishing failing | increase in `autowok_jobs_by_status{queue="publishing",status="failed"}` | Token expired, permission lost, Meta outage |
| Publishing stuck | `autowok_queue_depth{queue="publishing"} > 0` for 15 minutes | Worker slow or blocked |
| Analytics stale | `time() - autowok_analytics_last_success_timestamp_seconds > 2 × sync interval` | Sync failing |
| Error rate | `rate(autowok_http_requests_total{status=~"5.."}[5m]) / rate(autowok_http_requests_total[5m]) > 0.02` | Application errors |
| Slow API | p95 of `autowok_http_request_duration_seconds` above the budget in [performance-report.md](performance-report.md) | Regression or load |
| Groq limits | rate of `autowok_ai_requests_total{outcome="rate_limited"}` | Free-tier limit reached |
| Abuse | sustained `autowok_rate_limited_total` | Probing or a misbehaving client |
| Backups | No new backup set for 26 hours | See [backup-recovery.md](backup-recovery.md) |
| Certificate | Expiry in under 14 days | Proxy cannot renew |

What to do when one fires: [incident-response.md](incident-response.md) and [troubleshooting.md](troubleshooting.md).

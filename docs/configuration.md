# Environment configuration guide

Every setting is an environment variable read by `backend/app/core/config.py`. Local development reads the root `.env` file; containers receive variables from Compose. The frontend has one build-time variable.

* Development template: [`.env.example`](../.env.example) → copy to `.env`.
* Staging and production template: [`.env.production.example`](../.env.production.example) → copy to `.env.production` on the server.

Neither real file is committed (`.gitignore` excludes `.env` and `.env.*`). Example files contain no secrets.

## Fail-safe start-up in production

When `APP_ENV` is `production` (or `prod`) the API and the worker refuse to start if any of these is true, and the error names the setting (never its value):

| Check | Setting |
|---|---|
| Debug mode is on | `APP_DEBUG` |
| Database password is empty or a known default (`autowok`, `postgres`, `password`, `changeme`) | `DATABASE_URL` |
| A browser origin is not `https://` | `CORS_ORIGINS` |
| Missing or malformed Fernet key | `AI_ENCRYPTION_KEY`, `TOKEN_ENCRYPTION_KEY` |
| The two encryption keys are identical | `AI_ENCRYPTION_KEY`, `TOKEN_ENCRYPTION_KEY` |
| Shorter than 32 characters | `MEDIA_URL_SIGNING_SECRET` |
| Meta app configured without its secret, a 32+ character state secret, or an `https://` redirect | `META_APP_SECRET`, `META_OAUTH_STATE_SECRET`, `META_REDIRECT_URI` |
| Metrics enabled without a 24+ character token | `METRICS_TOKEN` (or set `METRICS_ENABLED=false`) |
| Cross-site cookies requested | `SESSION_COOKIE_SAMESITE=none` |

Production also forces `Secure` cookies, switches logs to JSON, and turns off the interactive API documentation unless `API_DOCS_ENABLED=true`.

## Generating secrets

```sh
openssl rand -hex 32        # random strings: passwords, signing secrets, tokens, passphrases
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # Fernet keys
```

Use hex for database and Redis passwords: they are placed inside connection URLs, where characters such as `@`, `/` and `:` would need escaping.

## Reference

R = required in production. Defaults apply when a variable is unset.

### Application

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` (R) | `development` | `production` for staging and production. |
| `APP_DEBUG` | `false` | Must be `false` in production. |
| `APP_NAME` | `Autowok` | Shown in health responses. |
| `SERVICE_NAME` | `autowok-api` | Log field `service`; the worker reports `autowok-worker`. |
| `LOG_LEVEL` | `INFO` | |
| `LOG_FORMAT` | `auto` | `auto` = JSON in production, text otherwise; or `json` / `text`. |
| `API_V1_PREFIX` | `/api/v1` | |
| `API_DOCS_ENABLED` | unset | Unset = on outside production, off in production. |
| `CORS_ORIGINS` (R) | `http://localhost:3000` | Exact browser origins, comma-separated. Never `*`. With the bundled proxy this is the one public origin. |
| `ALLOWED_HOSTS` | empty | Host header allowlist. Empty disables the check. |
| `MAX_REQUEST_BODY_BYTES` | `1048576` | Limit for every request except media uploads. |
| `RELEASE_VERSION` | empty | Reported in the API version and error reports. |

### Sessions

| Variable | Default | Notes |
|---|---|---|
| `SESSION_COOKIE_NAME` | `autowok_session` | |
| `SESSION_COOKIE_SECURE` | `false` | Always on in production. |
| `SESSION_COOKIE_SAMESITE` | `lax` | `lax` or `strict` in production. |
| `SESSION_TTL_DAYS` | `30` | Absolute session lifetime, 1–365. |
| `SESSION_TOUCH_INTERVAL_SECONDS` | `300` | How often "last used" is written. 0 = every request. |

### Database and Redis

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` (R) | local dev URL | `postgresql+psycopg://user:password@host:5432/db`. Built by the production Compose file from `POSTGRES_*`. |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `5` / `10` | Per process. See sizing in [deployment.md](deployment.md#scaling-and-sizing). |
| `DB_POOL_TIMEOUT_SECONDS` | `30` | Wait for a free connection. |
| `DB_POOL_RECYCLE_SECONDS` | `1800` | Reconnect interval (protects against idle-connection drops). |
| `DB_CONNECT_TIMEOUT_SECONDS` | `5` | |
| `DB_STATEMENT_TIMEOUT_MS` | `30000` | Server-side limit per statement. 0 disables. |
| `REDIS_URL` (R) | `redis://localhost:6379/0` | Built by the production Compose file from `REDIS_PASSWORD`. |
| `REDIS_SOCKET_TIMEOUT_SECONDS` | `5` | Connect and read timeout. |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` (R), `REDIS_PASSWORD` (R) | | Used by the Compose files to create the services and build the two URLs. |

### Encryption and signing

| Variable | Notes |
|---|---|
| `AI_ENCRYPTION_KEY` (R) | Fernet key. Encrypts workspace AI provider keys at rest. |
| `AI_ENCRYPTION_KEY_PREVIOUS` | Previous key, set only while rotating. |
| `TOKEN_ENCRYPTION_KEY` (R) | Fernet key. Encrypts Meta user and Page tokens at rest. |
| `TOKEN_ENCRYPTION_KEY_PREVIOUS` | Previous key, set only while rotating. |
| `MEDIA_URL_SIGNING_SECRET` (R) | Signs the expiring media links that Meta fetches. |
| `MEDIA_SIGNED_URL_TTL_SECONDS` | `3600`. |

Rotation is described in [security/token-storage.md](security/token-storage.md) and [security/security-assessment.md](security/security-assessment.md#secret-rotation).

### Groq

| Variable | Default | Notes |
|---|---|---|
| `GROQ_API_KEY` | empty | Optional platform key, shared by workspaces that have not saved their own. Leave empty to require a key per workspace. |
| `GROQ_API_BASE_URL` | `https://api.groq.com/openai/v1` | Only the official host is accepted. |
| `GROQ_DEFAULT_MODEL` | empty | A model id from the live list in Settings → AI. |
| `GROQ_TIMEOUT_SECONDS` / `GROQ_MAX_RETRIES` | `60` / `2` | |
| `GROQ_ENABLED` | `true` | |
| `AGENT_GROQ_MODEL` and the other `AGENT_*` | | See [phase-11-multi-agent.md](phase-11-multi-agent.md). `AGENT_LEASE_SECONDS` must be greater than `AGENT_STEP_TIMEOUT_SECONDS`. |

Groq's free tier has per-model rate limits that Groq controls. Autowok adds its own limits (below) and reschedules agent steps when Groq answers 429.

### Meta

| Variable | Notes |
|---|---|
| `META_APP_ID`, `META_APP_SECRET` | From the Meta developer console. |
| `META_GRAPH_API_VERSION` | `v26.0`. |
| `META_REDIRECT_URI` | `https://<host>/api/v1/oauth/meta/callback`. Must match the Meta app exactly. |
| `META_OAUTH_STATE_SECRET` | 32+ characters. |
| `PUBLIC_MEDIA_BASE_URL` | Public HTTPS origin Meta can reach to fetch media. The production Compose file sets it to `PUBLIC_ORIGIN`. |

### Storage and uploads

| Variable | Default | Notes |
|---|---|---|
| `STORAGE_PROVIDER` | `local` | Only `local` exists. |
| `LOCAL_STORAGE_PATH` | `./storage/local` | `/app/storage/local` in containers (a named volume). |
| `MEDIA_MAX_IMAGE_BYTES` / `MEDIA_MAX_VIDEO_BYTES` | 8 MB / 100 MB | Enforced while the upload is received. Raise the proxy limit in `infrastructure/proxy/Caddyfile` if you raise the video limit above 110 MB. |
| `UPLOAD_MAX_CONCURRENT` | `4` | Uploads processed at once per API process. |

### Background worker

| Variable | Default | Notes |
|---|---|---|
| `WORKER_POLL_INTERVAL_SECONDS` | `15` | Longest wait between loops without a wake-up. |
| `WORKER_TASK_BUDGET_SECONDS` | `120` | Time per loop for analytics, automations and agents before publishing is checked again. |
| `WORKER_HOUSEKEEPING_INTERVAL_SECONDS` | `60` | Minimum interval for housekeeping scans. |
| `WORKER_HEARTBEAT_FILE` | empty | File touched every loop; the container health check reads it. |
| `WORKER_HEARTBEAT_TTL_SECONDS` | `120` | A heartbeat older than this means the worker is not available. |
| `PUBLISHING_*`, `SCHEDULE_*`, `ANALYTICS_*`, `AUTOMATION_*` | | See the phase 7–10 documents. |

### Monitoring

| Variable | Default | Notes |
|---|---|---|
| `METRICS_ENABLED` | `true` | |
| `METRICS_TOKEN` (R) | empty | Bearer token for `/metrics` and `/api/v1/health/details`. |
| `SENTRY_DSN` | empty | Optional. Requires the `sentry-sdk` package in the image ([monitoring.md](monitoring.md#error-reporting)). |

### Rate limits

Per user and per hour unless the name says otherwise. A rejected request gets HTTP 429 with `Retry-After` and a message naming the feature.

| Variable | Default | Applies to |
|---|---|---|
| `RATE_LIMIT_LOGIN_PER_ACCOUNT_15M` | 20 | Login attempts per account in 15 minutes, from any address (in addition to 10 per account+address and 60 per address). |
| `RATE_LIMIT_AI_GENERATE_PER_HOUR` | 30 | Content generation with Groq. |
| `RATE_LIMIT_AI_TOOLS_PER_HOUR` | 120 | Content intelligence tools; agent workflow planning and acceptance. |
| `RATE_LIMIT_RESEARCH_PER_HOUR` | 30 | Creating and running research. |
| `RATE_LIMIT_UPLOAD_PER_HOUR` | 120 | Media uploads. |
| `RATE_LIMIT_PUBLISH_PER_HOUR` | 60 | Publish now, retry. |
| `RATE_LIMIT_SCHEDULE_PER_HOUR` | 240 | Create, change, reschedule, retry a scheduled post. |
| `RATE_LIMIT_EXPORT_PER_HOUR` | 30 | Analytics report and CSV/PDF export. |
| `RATE_LIMIT_MEMBER_ADD_PER_HOUR` | 20 | Adding workspace members by email. |
| `RATE_LIMIT_PROVIDER_TEST_PER_HOUR` | 30 | AI provider tests and model listing (outbound calls). |
| `RATE_LIMIT_AUTOMATION_TEST_PER_HOUR` | 120 | Automation validation and dry runs. |
| `RATE_LIMIT_CLIENT_ERRORS_PER_HOUR` | 60 | Browser error reports, per address. |
| `RATE_LIMIT_WORKSPACE_CREATE_PER_DAY` | 10 | New workspaces per user per day. |
| `MAX_WORKSPACES_PER_USER` | 25 | Workspaces a user can own. |

Existing limits from earlier phases are unchanged: registration (5 per address per hour), Meta OAuth and discovery, agent workflow starts (10 per minute per user, plus `AGENT_MAX_ACTIVE_WORKFLOWS` and `AGENT_MAX_WORKFLOWS_PER_HOUR` per workspace), analytics refresh, and the automation execution limits.

All limits are counted in Redis and fail closed: if Redis is unavailable the limited request is refused with 503 rather than allowed without a limit.

### Email

There is no email service in Autowok (no verification mail, password reset or notification mail), so there is nothing to configure. In-app notifications are the only channel.

### Proxy and production Compose

| Variable | Notes |
|---|---|
| `SITE_ADDRESS` (R) | Host name the proxy serves, for example `app.example.com`. |
| `PUBLIC_ORIGIN` (R) | `https://` + that host. Compiled into the web image. |
| `ACME_EMAIL` (R) | Address for certificate expiry notices. |
| `FORWARDED_ALLOW_IPS` | Addresses allowed to set `X-Forwarded-For` (see [deployment.md](deployment.md#behind-another-proxy-or-load-balancer)). |
| `BACKEND_IMAGE` / `FRONTEND_IMAGE` | Image tags to run, when images are built by CI. |
| `BACKUP_PASSPHRASE`, `BACKUP_RETENTION_DAYS`, `BACKUP_HOST_DIR` | See [backup-recovery.md](backup-recovery.md). |

### Frontend (build time)

| Variable | Notes |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | Public API origin. Visible in the browser; never put a secret in a `NEXT_PUBLIC_` variable. |
| `CSP_EXTRA_IMG_SRC` | Extra image hosts allowed by the Content-Security-Policy. Defaults to Meta's CDN hosts, which serve post thumbnails in analytics. |
| `NEXT_OUTPUT` | `standalone` in the production image. |

# Production architecture

How Autowok is meant to run in production, in plain language, and why. This is a **recommendation awaiting approval**: no server, account, domain or DNS record exists yet.

Related: [HOSTING_COMPARISON.md](HOSTING_COMPARISON.md) (providers and prices) · [../deployment.md](../deployment.md) (technical reference for the Compose stack) · [../architecture.md](../architecture.md) (application internals).

## Recommended architecture

One Linux server (2 vCPU, 4 GB memory) runs the existing `docker-compose.prod.yml` without modification. Three small outside services protect and watch it.

```
                         your users' browsers          Meta (Facebook / Instagram)
                                  │                          │  downloads media through
                                  ▼                          ▼  signed, expiring links
                      ┌───────── app.your-domain ─────────────────┐
   only 80 and 443 →  │ proxy (Caddy): HTTPS certificate, routing │   ONE SERVER
                      │   /api/*  → backend (FastAPI)             │
                      │   others  → frontend (Next.js)            │
                      │                                           │
                      │ worker (publishing, scheduling, analytics,│
                      │         automations, AI agents)           │
                      │                                           │
                      │ postgres ─ all application data  ┐ private│
                      │ redis ─── rate limits, wake-ups  ┘ network│
                      │ media volume ─ uploaded files             │
                      └───────────┬───────────────────────────────┘
                                  │ outbound only
        ┌─────────────────────────┼──────────────────────────┬───────────────────┐
        ▼                         ▼                          ▼                   ▼
   Groq API                Meta Graph API          off-server backup      uptime monitor
   (AI, backend only)      (OAuth, publishing,     bucket (encrypted      (checks /api/v1/ready
                            insights)              copies, daily)          from outside)
```

| Part | What it is | Where it runs | Why this choice |
|---|---|---|---|
| Web app | Next.js standalone server (`frontend` container) | The server | Same address as the API, so the login cookie stays first-party (`SameSite=Lax`) and no cross-site rules are needed. |
| API | FastAPI on uvicorn (`backend` container) | The server | Already built, hardened and tested this way in Phase 12. |
| Worker | `python -m app.worker` (`worker` container) | The server | Must always be running, and must read the same media files the API saved. |
| Database | PostgreSQL 16 (`postgres` container) | The server, private network | Simplest and cheapest; backed up daily. A managed database is the upgrade path. |
| Redis | Redis 7 with a password and persistence (`redis` container) | The server, private network | Holds nothing permanent (rate-limit counters, wake-up signals), so it needs no backup. |
| Media | Files on the `media_data` volume | The server's disk | The only storage Autowok supports today. |
| HTTPS | Caddy obtains and renews a Let's Encrypt certificate | The server | Free and automatic once DNS points at the server. |
| Backups | `scripts/backup/backup.sh`, encrypted, daily, copied off the server | Server → storage bucket | A backup kept only on the server is lost with the server. |
| Monitoring | Uptime checks from outside; `/metrics` and structured logs inside | Outside service + the server | You learn about an outage from a message, not from a customer. |
| Releases | GitHub Actions builds images; a person approves; `scripts/deploy/deploy.sh` releases | GitHub + the server | Repeatable, and never automatic. |

### Why one server, and not a "serverless" platform

1. **It is the only option that needs no code changes.** The API and the worker share a media folder. Container platforms (Render, Railway, Fly.io) give a disk to one service only, so Autowok would first need S3-style object storage, which does not exist in the code ([HOSTING_COMPARISON.md](HOSTING_COMPARISON.md#option-3-not-possible-today-a-container-platform)).
2. **It is what was tested.** Phase 12 ran this exact stack locally, and Phase 13 rehearsed release, backup, rollback and restore on it ([STAGING_DEPLOYMENT.md](STAGING_DEPLOYMENT.md#local-rehearsal-what-has-been-proven-so-far)).
3. **It is the cheapest reliable option** (about €8–25 or $30 per month, all in).

### What you give up (limitations to accept knowingly)

| Limitation | What it means in practice | How it is reduced |
|---|---|---|
| Single point of failure | If the server or its disk fails, Autowok is down until it is rebuilt from backups (target: about 1–2 hours once practised). Scheduled posts due during the outage publish late, or are marked "missed" after 6 hours. | Provider-level server backups + off-server encrypted backups + a written, rehearsed restore procedure. |
| Data loss window | With one backup a day, up to 24 hours of data can be lost in a disaster. | Back up more often (the script can run hourly), or use a managed database with point-in-time recovery. |
| Short interruption on each release | The API and worker restart (seconds). Requests in flight get up to 30 seconds to finish; the worker finishes its current job first. | Release at quiet times. Scheduled posts are stored in the database and are not lost. |
| Media is tied to the server | Cannot spread across several servers until object storage is added. | Not needed at launch scale. |
| You maintain the server | Security updates, firewall, disk space. | Automatic security updates and a small monthly checklist ([PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md#after-launch-routine-care)). |
| Disk fills up | Uploaded videos (up to 100 MB each) and local backups grow. A 40 GB disk can fill within months of heavy video use. | Alert at 80% disk use; choose an 80 GB plan or add a volume. |

### How it grows

| Stage | Change | Downtime |
|---|---|---|
| More traffic | Resize the server (4 vCPU / 8 GB) | A few minutes |
| Slow AI workflows delay publishing | Run a second worker: `--scale worker=2` (jobs are claimed one worker at a time, see [DATABASE_DEPLOYMENT.md](DATABASE_DEPLOYMENT.md#connection-pooling)) | None |
| Database must survive server loss | Move PostgreSQL to a managed service | About 15 minutes |
| More than one server | Add object storage (development work), then several API/worker servers behind a load balancer | Planned project |

## Alternative architecture: server + managed PostgreSQL

Identical, except the `postgres` container is replaced by a managed database (Neon, Supabase, or the server provider's own). The provider handles database backups and can restore to a chosen minute. About $15–30 more per month. Choose this if losing a day of data is unacceptable, or once Autowok has paying customers. No code change; the switch is described in [DATABASE_DEPLOYMENT.md](DATABASE_DEPLOYMENT.md#using-a-managed-postgresql-service).

## Environments

| | Development | Staging | Production |
|---|---|---|---|
| Purpose | Writing code | Rehearsing a release with production settings | Real users |
| Where | Your computer (`docker-compose.yml`) | A separate, temporary server | The production server |
| Address | `localhost` | for example `staging.your-domain` | for example `app.your-domain` |
| Configuration file | `.env` | `.env.production` on the staging server | `.env.production` on the production server |
| `APP_ENV` | `development` | `production` (same safety checks) | `production` |
| Secrets | throwaway | **its own set** | **its own set** |
| Database | disposable | disposable, never a copy of production | real, backed up |
| Meta app | – | Meta app in *Development* mode, test users only | Meta app in *Live* mode, after App Review |
| Who can open it | you | you (keep the address private; see [STAGING_DEPLOYMENT.md](STAGING_DEPLOYMENT.md#keeping-staging-private)) | the public, only after you approve |

Staging and production must never share a server, a database, encryption keys or a Meta app secret. Staging on a separate server costs a few cents per hour and can be deleted between tests.

## Security boundaries

| Boundary | How it is enforced | Checked by |
|---|---|---|
| Only ports 80 and 443 are reachable | Compose publishes only the proxy; add the provider's firewall as a second layer (allow 22 from your address, 80, 443) | CI counts published ports; server firewall is a manual setup step |
| Database and Redis are unreachable from the internet | They sit on a Docker network marked `internal` and have passwords | Compose file; rehearsal |
| HTTPS only | Caddy redirects HTTP to HTTPS and sends HSTS; cookies are `Secure` and `HttpOnly` | Rehearsal (see staging document) |
| Requests for another host name are refused | `ALLOWED_HOSTS` | Rehearsal |
| Unsafe configuration cannot start | The API and worker refuse to start in production and name the setting | CI, `scripts/deploy/preflight.sh` |
| Secrets stay on the server | `.env.production` is never committed, never sent to GitHub, never built into an image | CI secret checks, `.gitignore`, `.dockerignore` |
| Groq key is backend-only | The web bundle receives exactly one variable, the public address | Code review: `NEXT_PUBLIC_API_BASE_URL` is the only `NEXT_PUBLIC_` variable |
| Monitoring endpoints are private | `/metrics`, `/docs`, `/api/v1/health/details` answer 404 at the proxy and need a token inside | Rehearsal |

## What this architecture does not include

Stated so nobody assumes otherwise: no CDN, no web application firewall, no second region, no automatic failover, no email sending (so no password reset by email), and no log search service. Each can be added later; none is required for a careful first launch.

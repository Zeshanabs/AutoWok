# Production deployment guide

How to deploy a fresh Autowok environment (staging or production), release a new version, and roll back. The stack is not tied to a cloud provider: any Linux host with Docker Engine and Docker Compose v2 can run it.

**Verification status.** The stack described here was built and run on a developer workstation (Docker Desktop) behind the bundled proxy with a locally issued certificate: see [Local verification](#what-was-verified-locally). It has **not** been deployed to a staging or production server, and no public certificate, DNS record or cloud resource has been created.

## What runs where

```
Internet ──443/80──▶ proxy (Caddy: HTTPS, routing, body limits)
                       ├── /api/*  ──▶ backend  (FastAPI, uvicorn, one process per container)
                       └── everything else ──▶ frontend (Next.js standalone server)
backend, worker ──▶ postgres (PostgreSQL 16)      internal network only
backend, worker ──▶ redis (Redis 7, AOF)          internal network only
backend, worker ──▶ media volume (uploaded files)
worker = python -m app.worker (publishing, scheduling, analytics, automations, AI agents)
```

| Service | Image | Published ports | Persistent data |
|---|---|---|---|
| `proxy` | `caddy:2.8-alpine` | 80, 443 | certificates (`caddy_data`) |
| `frontend` | `frontend/Dockerfile` target `runtime` | none | none |
| `backend` | `backend/Dockerfile` target `runtime` | none | media volume |
| `worker` | same image as `backend` | none | media volume |
| `postgres` | `postgres:16-alpine` | none | `postgres_data` |
| `redis` | `redis:7-alpine` | none | `redis_data` |
| `migrate`, `backup` | one-shot jobs (profile `ops`) | none | backups directory |

Only the proxy is reachable from outside. PostgreSQL and Redis sit on a Docker network marked `internal`, so they have no route to or from the internet. Application containers run as unprivileged users (uid 10001 for the API and worker, `node` for the web server) with a read-only root filesystem, all Linux capabilities dropped and `no-new-privileges`.

One public origin serves both the web app and the API. That keeps the session cookie `SameSite=Lax` and avoids cross-site CORS entirely.

## Requirements

* A Linux server with Docker Engine 24+ and the Compose v2 plugin. Start with 2 vCPU and 4 GB RAM; the Compose file limits the stack to about 4.2 GB in total.
* A DNS name pointing at the server, with ports 80 and 443 open. Port 80 is needed for certificate issuance and the HTTP→HTTPS redirect.
* A second location for backups that is not the server itself.
* For Meta features: a Meta app whose OAuth redirect URI is `https://<your host>/api/v1/oauth/meta/callback` ([meta-developer-setup.md](meta-developer-setup.md)).

## Deploy a fresh environment

1. **Get the code** onto the server (clone the repository or copy a release archive). The Compose file needs `docker-compose.prod.yml`, `infrastructure/proxy/Caddyfile`, `scripts/backup/`, and the `backend/` and `frontend/` directories if you build on the server.

2. **Create the configuration.**

   ```sh
   cp .env.production.example .env.production
   chmod 600 .env.production
   ```

   Fill in every value marked REQUIRED. Generate secrets on the server:

   ```sh
   openssl rand -hex 32          # passwords, signing secrets, METRICS_TOKEN, BACKUP_PASSPHRASE
   docker run --rm python:3.12-slim sh -c "pip -q install cryptography && python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
   ```

   Use two different Fernet keys for `AI_ENCRYPTION_KEY` and `TOKEN_ENCRYPTION_KEY`. Every variable is described in [configuration.md](configuration.md). Store a copy of the two encryption keys and the backup passphrase somewhere other than the server and the backups ([backup-recovery.md](backup-recovery.md#keys-and-configuration)).

3. **Validate and build.**

   ```sh
   C="docker compose --env-file .env.production -f docker-compose.prod.yml"
   $C config -q            # fails with the variable name if a required value is missing
   $C build                # or pull images built by CI and set BACKEND_IMAGE / FRONTEND_IMAGE
   ```

   `PUBLIC_ORIGIN` is compiled into the web image (the browser needs the API address and it is part of the Content-Security-Policy). Rebuild the web image if the public address changes.

4. **Create the schema.** Migrations are a separate, explicit step so that several API containers never race to run them.

   ```sh
   $C run --rm migrate
   ```

5. **Start.**

   ```sh
   $C up -d
   $C ps                    # every service should become "healthy"
   ```

   The proxy obtains a certificate on first start. Watch `docker compose ... logs proxy` if HTTPS does not come up; the usual causes are DNS not pointing at the server or port 80 being closed.

6. **Check.**

   ```sh
   curl -fsS https://<host>/api/v1/health      # {"status":"ok",...}
   curl -fsS https://<host>/api/v1/ready       # 200 only when database and Redis answer
   curl -s -o /dev/null -w '%{http_code}\n' https://<host>/metrics   # 404: not exposed publicly
   ```

   Then register the first account in the browser, create a workspace, and work through [the post-deployment checklist](#post-deployment-checklist).

7. **Schedule backups** ([backup-recovery.md](backup-recovery.md)) and connect monitoring ([monitoring.md](monitoring.md)).

### If the API will not start

In production the API refuses to start with unsafe configuration and names the setting, for example:

```
ConfigurationError: Invalid configuration. Unsafe production configuration: METRICS_TOKEN must be at least 24 characters ...
```

The message never contains a configured value. Fix the named variable in `.env.production` and run `up -d` again.

## Releasing a new version

```sh
C="docker compose --env-file .env.production -f docker-compose.prod.yml"
$C build                       # or pull the images for the release
$C run --rm backup             # always back up before a schema change
$C run --rm migrate            # applies only the new migrations
$C up -d --remove-orphans      # recreates changed containers
$C ps && curl -fsS https://<host>/api/v1/ready
```

What happens to work in progress:

* The API finishes in-flight requests for up to 30 seconds before stopping.
* The worker finishes the job it is running, then exits (up to 120 seconds are allowed). A job interrupted by a hard kill is recovered through its lease; see [architecture.md](architecture.md#background-work-and-recovery).
* Scheduled posts and queued jobs live in PostgreSQL, so a restart delays them by seconds and loses nothing.

Migrations in this project are additive (new tables, columns and indexes), so the previous application version keeps working against the new schema while containers are replaced. Check that assumption for each release before relying on it.

## Rolling back

1. Start the previous images: set `BACKEND_IMAGE` and `FRONTEND_IMAGE` to the previous tags (or check out the previous commit and rebuild), then `up -d`.
2. Only if the new schema breaks the old code, revert the last migration with the *new* image before starting the old one:

   ```sh
   $C run --rm migrate alembic downgrade -1
   ```

   Migration `20261116_0012` (indexes only) is reversible without data loss. Earlier migrations drop tables or columns on downgrade: read the migration before downgrading, and prefer restoring forward.
3. If data was damaged, restore the pre-release backup into a new database and switch to it ([backup-recovery.md](backup-recovery.md#restore-procedure)).

## Scaling and sizing

* **API:** one uvicorn process per container; add containers (`up -d --scale backend=3`) rather than processes. Each process holds up to `DB_POOL_SIZE + DB_MAX_OVERFLOW` (15 by default) database connections. Keep `containers × 15 + workers × 15` below PostgreSQL's `max_connections` (100 by default), or lower the pool settings.
* **Worker:** several workers can run at once; jobs are claimed atomically. One worker runs jobs one after another, so add a second worker if publishing must not wait behind long AI workflows (`--scale worker=2`).
* **Media:** uploads are files on the `media_data` volume, shared by the API and the worker. All containers that serve or publish media must mount the same volume, which ties them to one host or a shared filesystem. Object storage is not implemented (`STORAGE_PROVIDER` accepts only `local`).
* **Managed services:** to use a managed PostgreSQL or Redis, delete those services from the Compose file and set `DATABASE_URL` / `REDIS_URL` in `.env.production` (remove the two lines that build them in `x-backend-env`).

## Behind another proxy or load balancer

Rate limits and audit logs use the client address. uvicorn only trusts `X-Forwarded-For` from addresses in `FORWARDED_ALLOW_IPS`. The Compose file sets it to `*` because the API port is not published and only the bundled proxy can reach it. If you publish the API port or put a different proxy in front, set `FORWARDED_ALLOW_IPS` to that proxy's address, and make sure the outermost proxy overwrites `X-Forwarded-For` rather than appending to a client-supplied value.

## Environments

| | Development | Staging | Production |
|---|---|---|---|
| Compose file | `docker-compose.yml` | `docker-compose.prod.yml` | `docker-compose.prod.yml` |
| Configuration | `.env` (from `.env.example`) | `.env.production` on the staging host | `.env.production` on the production host |
| `APP_ENV` | `development` | `production` | `production` |
| Secrets | throwaway | unique to staging | unique to production |
| Meta app | test app / test users | test app | reviewed live app |
| Data | disposable | disposable, never a copy of production without scrubbing | real |

Staging runs with `APP_ENV=production` on purpose: it must pass the same start-up checks and use the same cookie, header and logging behaviour. Never share secrets, encryption keys or databases between environments.

## Post-deployment checklist

- [ ] `https://<host>/` loads with a valid certificate; `http://` redirects to `https://`.
- [ ] `/api/v1/ready` returns 200; `/metrics` and `/docs` return 404 from outside.
- [ ] Registration, login and logout work; the session cookie is `HttpOnly` and `Secure`.
- [ ] `docker compose ... ps` shows `worker` healthy.
- [ ] A backup has been taken, copied off the server, and restored once into a scratch database.
- [ ] Monitoring scrapes `/metrics` from inside the network and alerts are configured.
- [ ] Meta: connect a test Page, publish a test post, and confirm it appears. **Until this is done, live Meta publishing is unverified.**
- [ ] Groq: save a key in Settings → AI, run "Test connection", and run one AI workflow. **Until this is done, live Groq inference is unverified.**

## What was verified locally

On 2026-11-16, on Windows 11 with Docker Desktop 29.9, the production images were built and the full stack was started under a separate project name on localhost ports, with `SITE_ADDRESS=localhost` (Caddy's local certificate authority). Observed:

* All six services healthy; migrations 0001–0012 applied by the `migrate` job.
* Through the proxy: web pages and API reachable over HTTPS; HTTP redirected (308); `/metrics`, `/docs`, `/openapi.json` and `/api/v1/health/details` answered 404; registration, login, authenticated requests and logout worked; the session cookie carried `HttpOnly` and `Secure`; a 3 MB JSON body was rejected with 413; a non-image upload was rejected.
* Security headers present on API and web responses (CSP, HSTS, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`).
* Containers ran as uid 10001 / 1000 with a read-only root filesystem.
* The worker's heartbeat was visible in `/api/v1/health/details`; `/metrics` included worker counters and queue depth; logs were JSON.
* `docker stop` ended the worker in 2 seconds and the API in 3 seconds, both with exit code 0.
* With PostgreSQL stopped, `/api/v1/health` stayed 200 and `/api/v1/ready` reported `degraded`; both recovered after it restarted.
* A production image started without secrets exited with a configuration error naming the settings.

Not verified: a real domain and public certificate, a multi-host or scaled deployment, resource limits under load, the staging deployment workflow, and anything involving live Meta or Groq credentials.

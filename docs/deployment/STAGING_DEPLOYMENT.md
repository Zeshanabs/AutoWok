# Staging deployment

Staging is a private, temporary copy of production used to rehearse a release with real production settings before real users see it. This document is the step-by-step guide and the test plan.

**Status: NOT DEPLOYED.** No staging server exists. Creating one costs money (a few cents per hour) and needs your approval of the hosting choice ([HOSTING_COMPARISON.md](HOSTING_COMPARISON.md)). What has been proven so far is the [local rehearsal](#local-rehearsal-what-has-been-proven-so-far) below.

## What you need before starting

| Item | Who provides it | Cost |
|---|---|---|
| A server: 2 vCPU, 4 GB memory, Ubuntu 24.04 LTS, x86-64 | You order it at the approved provider | Hourly; delete it after testing |
| A host name for staging, for example `staging.your-domain.com` | You (DNS record at your domain registrar) | Free if you own a domain |
| A GitHub repository with Actions enabled | Exists | – |
| A Groq API key for testing | You (console.groq.com) | Free tier |
| A second Meta app, in Development mode | You (developers.facebook.com) | Free |
| A Facebook Page and an Instagram Business/Creator account used only for tests | You | Free |

A host name is required, not optional: HTTPS certificates are issued for names, and Meta only redirects to an exact HTTPS address.

## 1. Order the server

At the provider: Ubuntu 24.04, 2 vCPU / 4 GB, your SSH public key added, and a **firewall** that allows inbound TCP 22 (ideally only from your own IP address), 80 and 443, and nothing else.

## 2. Prepare the server

```sh
ssh root@<server address>

# Updates, automatic security patches
apt update && apt -y upgrade && apt -y install unattended-upgrades

# Docker Engine with the Compose plugin (Docker's official convenience script)
curl -fsSL https://get.docker.com | sh

# A non-root user that owns the deployment
adduser --disabled-password --gecos "" deploy
usermod -aG docker deploy
install -d -o deploy -g deploy /srv/autowok
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
# put the DEPLOYMENT public key (a new key made only for GitHub Actions) in:
nano /home/deploy/.ssh/authorized_keys

# 2 GB swap: protects against out-of-memory during image pulls on a 4 GB server
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

Membership of the `docker` group is equivalent to root on that server, so the `deploy` user's key must be protected like a root key.

## 3. Point the name at the server

At your DNS provider create an `A` record: `staging` → the server's IPv4 address (and `AAAA` for IPv6 if the server has one). Wait until `nslookup staging.your-domain.com` shows the address. **Changing DNS is your action; nothing in this repository does it.**

## 4. Put the deployment files and configuration on the server

From your computer, in the repository folder:

```sh
tar -czf - docker-compose.prod.yml infrastructure/proxy scripts/backup scripts/deploy .env.production.example \
  | ssh deploy@<server> "tar -xzf - -C /srv/autowok"
```

On the server, as `deploy`:

```sh
cd /srv/autowok
cp .env.production.example .env.production && chmod 600 .env.production
sh scripts/deploy/generate-secrets.sh        # staging gets its OWN secrets
nano .env.production                         # paste them; set SITE_ADDRESS, PUBLIC_ORIGIN, ALLOWED_HOSTS, ACME_EMAIL
sh scripts/deploy/preflight.sh               # must end with READY
```

Every variable is explained in [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md).

## 5. Let the server download images

Images are stored in GitHub's container registry and are private. On the server, once:

```sh
docker login ghcr.io -u <your GitHub user name>
# password: a GitHub personal access token with ONLY the "read:packages" permission
```

## 6. Connect GitHub Actions

In the GitHub repository: **Settings → Environments → New environment → `staging`**.

* Tick **Required reviewers** and add yourself. Every deployment then waits for your click.
* Secrets: `STAGING_SSH_HOST`, `STAGING_SSH_USER` (`deploy`), `STAGING_SSH_KEY` (the private half of the deployment key), `STAGING_SSH_KNOWN_HOSTS` (output of `ssh-keyscan <server>`; compare the fingerprint with the one the provider shows), `STAGING_DEPLOY_PATH` (`/srv/autowok`).
* Variable: `STAGING_PUBLIC_ORIGIN` = `https://staging.your-domain.com`.

## 7. Deploy

GitHub → **Actions → Deploy to staging → Run workflow** → choose the commit → approve.

The workflow builds the two images for that commit, copies the deployment files, and runs on the server:

```sh
sh scripts/deploy/deploy.sh release <backend image> <frontend image>
```

which checks the configuration, backs up (skipped on the first release, when the database is empty), **runs the database migrations**, starts everything, and waits until the API reports ready and the worker is healthy. It fails loudly if any step fails.

Without GitHub Actions (build on the server instead): clone the repository on the server, then

```sh
docker build --target runtime -t autowok-backend:manual backend
docker build --target runtime --build-arg NEXT_PUBLIC_API_BASE_URL=https://staging.your-domain.com -t autowok-frontend:manual frontend
sh scripts/deploy/deploy.sh release autowok-backend:manual autowok-frontend:manual
```

## 8. First checks

```sh
curl -fsS https://staging.your-domain.com/api/v1/health      # {"status":"ok",...}
curl -fsS https://staging.your-domain.com/api/v1/ready       # database and redis true
curl -s -o /dev/null -w '%{http_code}\n' https://staging.your-domain.com/metrics    # 404
curl -s -o /dev/null -w '%{http_code}\n' http://staging.your-domain.com/            # 308 (redirect to https)
sh scripts/deploy/deploy.sh status                            # every service "healthy"
```

## Keeping staging private

Staging has open registration like production, so anyone who finds the address could sign up. Until launch, choose one:

* **Recommended:** in the provider's firewall, allow ports 80/443 only from your own IP address during ordinary testing. Open them to everyone only for the two tests that need the outside world: certificate issuance (first start) and Meta downloading media during a publish test.
* Keep the address unguessable and delete the server after each test session.

Do not put a password prompt (HTTP basic auth) in front of the whole site: Meta's servers must be able to download media links without one.

## Meta app for staging

1. At developers.facebook.com create a **new** app for staging (do not reuse the future production app). Leave it in **Development** mode.
2. Add the **Facebook Login** product. Under its Settings, add the Valid OAuth Redirect URI exactly: `https://staging.your-domain.com/api/v1/oauth/meta/callback`.
3. Under App roles, add yourself (and any tester) as Administrator, Developer or Tester. In Development mode **only these people** can connect accounts, and only Pages/Instagram accounts they manage. That is enough for staging; App Review is needed only for production.
4. Copy the App ID and App secret into `.env.production` (`META_APP_ID`, `META_APP_SECRET`), set `META_REDIRECT_URI` to the same address as in step 2, run `sh scripts/deploy/preflight.sh`, then `docker compose --env-file .env.production --env-file release.env -f docker-compose.prod.yml up -d`.

The Instagram account must be a Business or Creator account linked to a Facebook Page you manage.

## Staging test plan

Record the result of every line. **"Mocked" means the automated test suite replaced the outside service with a fake**, which proves Autowok's own logic but says nothing about the real service. **"Real" means it must be done by a person on staging with real credentials.** A line is passed only when its real test was done; Autowok must not be described as working with Meta or Groq before then.

| # | Area | What to do on staging | Already covered by automated tests (mocked or local) | Real test on staging |
|---|---|---|---|---|
| 1 | Migrations | Release ran `migrate`; `alembic current` shows `20261117_0013` | Local PostgreSQL + CI | ☐ |
| 2 | Front end ↔ back end | Open the site; register; the dashboard loads data | Local production stack | ☐ |
| 3 | HTTPS and cookies | Padlock valid; `http://` redirects; in browser dev tools the `autowok_session` cookie shows `Secure`, `HttpOnly`, `SameSite=Lax` | Local stack (self-signed certificate) | ☐ real certificate |
| 4 | Authentication | Register, log out, log in, wrong password more than 10 times (rate limit message), "log out everywhere" | Automated (real logic, fake Redis) + local stack | ☐ |
| 5 | Workspace isolation | Two accounts in two browsers: account B opens a link to A's content, media and brand → "not found" | Automated: 27 paths; local stack: media | ☐ |
| 6 | Brand management | Create, edit, archive a brand | Automated | ☐ |
| 7 | Groq connectivity | Settings → AI: save the Groq key, "Test connection", pick a model | **Mocked only** | ☐ **real key required** |
| 8 | Research | Start a research project | Automated with a fake provider | ☐ With a Tavily or Brave key set: sources, findings and a report appear. Without a key: a clear "no search provider configured" message |
| 9 | Content creation and approval | Generate a draft with AI, edit, submit, approve as Owner; a Member cannot approve | **Groq mocked** | ☐ real Groq |
| 10 | Media uploads | Upload a JPEG, a PNG and a short MP4; a renamed `.html` file is rejected; delete one | Local stack: upload, read, isolation, signed link, delete | ☐ |
| 11 | Media survives a release | Deploy again; the uploaded files still open | Local stack | ☐ |
| 12 | Facebook connect | Settings → Social accounts → connect; choose the test Page | **Mocked only** | ☐ **real Meta app + test Page** |
| 13 | Instagram connect | Same, choose the linked Instagram account | **Mocked only** | ☐ **real account** |
| 14 | Publish to Facebook | Publish one approved text post and one image post to the **test Page**; confirm on Facebook; exactly one post each | **Mocked only** | ☐ **real** |
| 15 | Publish to Instagram | Publish one image to the **test account**; confirm on Instagram | **Mocked only** | ☐ **real** |
| 16 | Scheduling | Schedule a post 5 minutes ahead; it publishes once, on time | Automated with a fake clock and fake Meta | ☐ real |
| 17 | No duplicates across a restart | Schedule a post 3 minutes ahead; run a release (or `docker compose ... restart worker`) at about minute 2; exactly one post appears | Automated: crash recovery, lease loss, idempotency key; local: clean worker stop in 4 s | ☐ real |
| 18 | Analytics | After publishing, run an analytics refresh; numbers appear (Meta can take up to a day) | **Mocked only** | ☐ real |
| 19 | Automation safeguards | Create an automation; confirm it cannot publish or approve by itself, and that the hourly limit stops a loop | Automated | ☐ |
| 20 | AI agents | Run one multi-agent workflow; output arrives as a draft, nothing is published | **Groq mocked** | ☐ real Groq |
| 21 | Monitoring | On the server: `/api/v1/health/details` with the token shows one worker alive; stop the worker → `deploy.sh status` shows it; uptime monitor alerts when the API is stopped | Local stack | ☐ |
| 22 | Backup | `docker compose ... run --rm backup`; a new set appears; copy reaches the bucket | Local stack (no bucket) | ☐ |
| 23 | Restore | Restore the set into `autowok_restore_test`: "Row counts match" | Local stack | ☐ |
| 24 | Disaster rehearsal | New empty server → restore from the bucket copy → site works with old logins | Not tested anywhere | ☐ |
| 25 | Rollback | `sh scripts/deploy/deploy.sh rollback` returns to the previous images | Local stack | ☐ |

Tests 12–18 use only test assets you control. **Never point staging at a real business Page.**

After testing: write down what failed, delete or stop the server to stop paying, and keep the staging Meta app for next time.

## Local rehearsal: what has been proven so far

On 2026-11-17 the production images were built and the production Compose stack was run on a workstation (Docker Desktop on Windows), reachable only on `localhost`, with throwaway secrets, under a separate project name, and removed afterwards. It used `scripts/deploy/deploy.sh` exactly as a server would.

| Checked | Result |
|---|---|
| Configuration check on a complete configuration; on the unfilled template; on a file with 10 planted mistakes | READY; refused; all 10 reported by setting name, no value printed |
| First release: pull → preflight → (backup skipped, empty database) → 12 migrations → start → ready | Pass, 50 seconds |
| Second release: preflight → **backup** → migrate → start → ready; `release.env` and `release.previous.env` written | Pass, after fixing the backup image defect ([BACKUP_AND_RECOVERY.md](BACKUP_AND_RECOVERY.md#what-was-tested)) |
| Rollback to the previous images | Pass, ready in 16 seconds |
| Release naming an image that does not exist | Stopped at step 1; running version untouched |
| From outside: `/api/v1/health`, `/api/v1/ready` | 200 |
| From outside: `/metrics`, `/docs`, `/api/v1/health/details` | 404 |
| HTTP → HTTPS | 308 redirect; HSTS header present |
| Request with a foreign `Host` header | Not served by the application (the proxy answers with an empty page) |
| State-changing request without the CSRF header, or from a foreign origin | 403 |
| Session cookie | `HttpOnly`, `Secure`, `SameSite=lax` |
| Two accounts: B reads or lists A's media | 404 |
| Upload: valid image; HTML disguised as JPEG; 9 MB image | 201; 415; 413 |
| Media read by owner; without a session; by signed link without a session; with a tampered signature | 200; 401; 200; 403 |
| Media after the API and worker containers were replaced | Still readable (volume persisted) |
| Delete media; signed link afterwards | Archived; 404 |
| Logout, then use the session | 401 |
| Redis without the password | `NOAUTH Authentication required` |
| Ports reachable on the host | Only the two proxy ports |
| Worker stop (`SIGTERM`) | Exited cleanly in 4 seconds, code 0, "stopped" logged |
| API stop | 2 seconds, code 0 |
| Two workers running at once | Ran side by side without errors (no publishing job was in the queue, so job claiming under contention is covered by the automated tests only) |

**What this does not prove:** a real domain and public certificate; the GitHub workflows; anything on a Linux server; behaviour under load; and every real call to Meta or Groq. No Groq key or Meta credential exists on this workstation, so those were not contacted at all.

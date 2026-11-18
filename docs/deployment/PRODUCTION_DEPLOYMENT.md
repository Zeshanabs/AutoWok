# Production deployment

How Autowok goes live, in order. Production is the same stack and the same steps as staging, on its own server, with its own secrets, after staging has passed.

**Status: NOT DEPLOYED, and not approved.** No production server, domain, DNS record, certificate, Meta live app or GitHub `production` environment exists. Each of the following needs your explicit approval before it happens: paying for a server, buying or changing a domain, changing DNS, entering real production credentials, opening the site to the public, and switching on publishing for real accounts.

## The gates, in order

| Gate | Passed when |
|---|---|
| 1. Preparation | Configuration, scripts, workflows and documents exist and were rehearsed locally. **This is the current state.** |
| 2. Decisions | You chose the provider, region, domain and backup location ([HOSTING_COMPARISON.md](HOSTING_COMPARISON.md)) |
| 3. Staging | The full test plan in [STAGING_DEPLOYMENT.md](STAGING_DEPLOYMENT.md#staging-test-plan) passed with real Groq and Meta test credentials |
| 4. Meta approval | App Review and business verification are complete for the production Meta app (below) |
| 5. Launch checklist | Every critical line of [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md) is ticked |
| 6. Your go-ahead | You approve the production deployment in GitHub |

## Domain, DNS and HTTPS

### 1. Choose the address

One address serves both the web app and the API, for example `app.your-domain.com`. Keeping them on one address is deliberate: the login cookie stays first-party and no cross-site rules are needed. (The API lives under `/api/` on the same name; there is no separate API domain to configure.)

### 2. Domain

If you do not own a domain, you buy one at a registrar (typically $10–20 per year). **This is your purchase to make; nothing here registers a domain.**

### 3. DNS

At the registrar or DNS provider, create:

| Type | Name | Value |
|---|---|---|
| `A` | `app` | the production server's IPv4 address |
| `AAAA` | `app` | its IPv6 address (only if the server has one and the firewall allows 80/443 over IPv6) |

Use a short TTL (300 seconds) at first, so a mistake or a server move takes effect quickly. Check with `nslookup app.your-domain.com`. If the DNS provider offers a "proxy" switch (Cloudflare's orange cloud), leave it **off** for the first launch: the bundled proxy must receive traffic directly to obtain its certificate, and a second proxy changes how client addresses are detected ([../deployment.md](../deployment.md#behind-another-proxy-or-load-balancer)).

### 4. HTTPS certificate

Nothing to buy or install. When the stack starts with `SITE_ADDRESS=app.your-domain.com`, the proxy (Caddy) asks Let's Encrypt for a certificate, proves ownership over port 80, and renews it automatically about every 60 days. Requirements: the DNS record already points at the server, and ports 80 and 443 are open. Let's Encrypt limits repeated failed attempts, so get DNS right before the first start. `ACME_EMAIL` receives a warning if renewal ever fails.

### 5. Settings that must match the address

All of these follow from one decision. `scripts/deploy/preflight.sh` checks that they agree.

| Where | Setting | Value |
|---|---|---|
| `.env.production` | `SITE_ADDRESS` | `app.your-domain.com` |
| `.env.production` | `PUBLIC_ORIGIN` | `https://app.your-domain.com` → becomes the CORS allowed origin and the media link base automatically |
| `.env.production` | `ALLOWED_HOSTS` | `app.your-domain.com` |
| `.env.production` | `META_REDIRECT_URI` | `https://app.your-domain.com/api/v1/oauth/meta/callback` |
| GitHub `production` environment | variable `PRODUCTION_PUBLIC_ORIGIN` | `https://app.your-domain.com` (compiled into the web image) |
| Meta app → Facebook Login → Settings | Valid OAuth Redirect URIs | the same callback address, character for character |
| Meta app → Settings → Basic | App Domains | `your-domain.com` |

### 6. Verify after the first start

```sh
curl -sI http://app.your-domain.com/ | head -n 3            # 308 redirect to https
curl -sI https://app.your-domain.com/login | grep -i strict-transport-security
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://app.your-domain.com/api/v1/auth/login \
  -H 'Origin: https://evil.example' -H 'X-CSRF-Protection: 1' -H 'Content-Type: application/json' -d '{}'   # 403
```

In a browser: valid padlock; after logging in, developer tools → Application → Cookies shows `autowok_session` with **Secure**, **HttpOnly** and **SameSite = Lax**.

## Meta App Review and business verification

Autowok asks Meta for these permissions:

| Permission | Used for |
|---|---|
| `pages_show_list`, `pages_read_engagement`, `instagram_basic` | Finding the user's Pages and linked Instagram accounts (required to connect) |
| `pages_manage_posts`, `publish_video` | Publishing to a Facebook Page |
| `instagram_content_publish` | Publishing to Instagram |
| `read_insights`, `instagram_manage_insights` | Analytics |

While a Meta app is in **Development** mode, only people listed in its App roles can use it. To let customers connect their own accounts, Meta requires, for the production app:

1. **Business verification** of the company that owns the app (legal name, documents). Meta decides how long this takes.
2. **App Review with Advanced Access** for each permission above: a written explanation and a screen recording, per permission, showing exactly how Autowok uses it. The staging deployment is the natural place to record these.
3. In the app's Basic settings: an app icon, a category, a **privacy policy URL**, and **data deletion instructions** (a URL or a callback). **Autowok has no privacy policy or data-deletion page yet**; you need to write and host them.
4. Switching the app to **Live** mode.

Outcomes are Meta's decision and can take days to weeks, with rounds of questions. Plan the launch date around it. Until it is complete, production can still run with Meta features limited to people in the app's roles.

Also confirm before launch that `META_GRAPH_API_VERSION` (default `v26.0`) is a version Meta currently supports, in the app dashboard.

**Production OAuth and publishing must not be described as working until they were tested on the production address with the live app and an eligible account.**

## Production deployment steps

1. **Server.** Order and prepare it exactly as in [STAGING_DEPLOYMENT.md](STAGING_DEPLOYMENT.md#1-order-the-server) steps 1–2. Enable the provider's own server backups.
2. **DNS.** As above.
3. **Configuration.** Steps 4–5 of the staging guide, with **newly generated secrets** (never staging's), the production address, the production Meta app and the production Groq key. Save the four irreplaceable secrets in the password manager ([ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md#secrets-all-generated-by-generate-secretssh)).

   ```sh
   sh scripts/deploy/preflight.sh      # must print READY with no placeholder warnings you do not understand
   ```
4. **GitHub.** Create the `production` environment with **Required reviewers**, the five `PRODUCTION_*` secrets and the `PRODUCTION_PUBLIC_ORIGIN` variable. Protect the `main` branch (pull request required, CI must pass).
5. **Deploy.** Actions → **Deploy to production** → enter the commit that passed staging → type `deploy-production` → approve. The workflow refuses a commit without a successful CI run, reuses the backend image that staging verified, builds the web image for the production address, and runs `scripts/deploy/deploy.sh release` on the server (configuration check → backup → migrations → start → wait for ready).
6. **Verify.** The checks in section 6 above, then `sh scripts/deploy/deploy.sh status` on the server.
7. **Backups.** Install the two cron lines and the off-server copy; run one backup and one restore test now ([BACKUP_AND_RECOVERY.md](BACKUP_AND_RECOVERY.md#setting-it-up-on-the-server)).
8. **Monitoring.** Add uptime checks for `https://app.your-domain.com/api/v1/ready` (expects 200) and the home page; set the alert contact; add the backup heartbeat.
9. **First account.** Register the owner account immediately, before announcing the address.
10. **Controlled publishing test.** Connect one account you own, publish one post, confirm it appears once. Only then invite users.

### Exact commands on the server (reference)

```sh
cd /srv/autowok
C="docker compose --env-file .env.production --env-file release.env -f docker-compose.prod.yml"

sh scripts/deploy/preflight.sh                                    # check configuration
sh scripts/deploy/deploy.sh release <backend image> <frontend image>   # release (backup + migrate + start + verify)
sh scripts/deploy/deploy.sh status                                # what is running
sh scripts/deploy/deploy.sh rollback                              # return to the previous images
$C logs --tail 100 backend                                        # logs (also: worker, proxy, frontend)
$C run --rm backup                                                # backup now
$C run --rm migrate alembic current                               # schema revision
$C up -d --scale worker=2                                         # a second worker
```

Always include `--env-file release.env` in manual commands; it tells Compose which released images to use.

## What happens to work in progress during a release

| Thing | During a release |
|---|---|
| Requests being served | Get up to 30 seconds to finish; new ones wait a few seconds for the new container |
| A post being published at that moment | The worker finishes it before stopping (it has 120 seconds). If the worker were killed anyway, the job's lease expires and it is picked up again; a post Facebook already accepted is recognised by its stored id and **not sent twice**; an unclear answer is marked "outcome uncertain" for a person to check. |
| Scheduled posts | Stored in the database. A due post is picked up within seconds after the worker returns. Each scheduled post can create only one publishing job (unique key per schedule revision). |
| Logged-in users | Stay logged in (sessions are in the database) |
| Rate-limit counters | Kept (Redis persists to disk) |

These protections are covered by automated tests with a simulated Meta. Test 17 of the staging plan checks the same thing against the real one.

## After launch: routine care

| When | What |
|---|---|
| Daily (automatic) | Backup + off-server copy; uptime checks |
| Weekly | Look at `deploy.sh status`, disk space (`df -h`), failed publishing jobs in the app, the backup log |
| Monthly | Restore test; apply server updates and reboot at a quiet time (`apt update && apt upgrade`); review Dependabot pull requests |
| Each release | Staging first; then production with approval |
| Yearly, or when someone leaves | Rotate secrets ([../security/security-assessment.md](../security/security-assessment.md#secret-rotation)) |
| When an alert fires | [../incident-response.md](../incident-response.md), [../troubleshooting.md](../troubleshooting.md) |

## Known limitations at launch

Decide knowingly whether each is acceptable for your first users (details in the readiness audit):

* **Anyone who reaches the site can register.** There is no invitation-only mode and no email verification.
* **No password reset.** There is no email service. A user who forgets a password cannot recover the account without an operator.
* **Research needs a search key.** Web search works through Tavily or Brave once `RESEARCH_SEARCH_PROVIDER` and `RESEARCH_SEARCH_API_KEY` are set; it has not been verified with a live key. Reports list the provider's page summaries and are not analysed by an AI model.
* **Sentry is not wired in**; errors go to the server logs only.
* **One server.** See the limitations table in [PRODUCTION_ARCHITECTURE.md](PRODUCTION_ARCHITECTURE.md#what-you-give-up-limitations-to-accept-knowingly).

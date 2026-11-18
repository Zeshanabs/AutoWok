# Production launch checklist

Tick every line before real users are invited. **[C] = critical: production must not be declared ready while any [C] line is open.** Lines without [C] should be done or consciously accepted in writing.

How to read the "Evidence so far" column: *local* = proven on a workstation copy of the production stack on 2026-11-17 ([STAGING_DEPLOYMENT.md](STAGING_DEPLOYMENT.md#local-rehearsal-what-has-been-proven-so-far)); *tests* = automated tests, with outside services simulated; *none* = not yet done anywhere. A local or simulated result never ticks a box here: boxes are ticked on the real staging and production systems.

**Current state: every box is open. Nothing is deployed.**

## Decisions and accounts

- [ ] [C] Hosting provider, plan and region approved by the owner
- [ ] [C] Domain chosen (and bought, if needed) by the owner
- [ ] [C] Off-server backup location approved
- [ ] [C] Decision recorded on open registration, missing password reset and missing research provider ([PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md#known-limitations-at-launch))
- [ ] Two-factor authentication turned on for: hosting provider, domain registrar, GitHub, Meta, Groq, backup storage
- [ ] A second person (or a sealed note) can reach the password manager entry in an emergency

## Security

| | Check | Evidence so far |
|---|---|---|
| ☐ [C] | `sh scripts/deploy/preflight.sh` prints READY on the production server | local |
| ☐ [C] | Production secrets were generated on/for production and are not used anywhere else (not staging, not development) | none |
| ☐ [C] | `.env.production` is mode 600, owned by the deploy user, and not in git | script checks it |
| ☐ [C] | `AI_ENCRYPTION_KEY`, `TOKEN_ENCRYPTION_KEY`, `MEDIA_URL_SIGNING_SECRET`, `BACKUP_PASSPHRASE` saved in the password manager | none |
| ☐ [C] | Provider firewall: inbound 80 and 443 only, 22 restricted to known addresses | none |
| ☐ [C] | SSH: key login only, password login disabled; the deployment key is used by GitHub only | none |
| ☐ [C] | From outside: `/metrics`, `/docs`, `/openapi.json`, `/api/v1/health/details` return 404 | local |
| ☐ [C] | Database and Redis ports are not reachable from the internet (`nmap` or the provider's port check) | local (only proxy ports published) |
| ☐ | Automatic security updates enabled on the server | none |
| ☐ | Latest CI run on the release commit is green, including dependency audit and image scan | CI defined; GitHub results not confirmed |
| ☐ | `SECURITY.md` with a contact address added before the product is public | none |

## Domain and HTTPS

| | Check | Evidence so far |
|---|---|---|
| ☐ [C] | DNS `A` record points at the production server | none |
| ☐ [C] | `https://` loads with a valid public certificate | local (self-signed only) |
| ☐ [C] | `http://` redirects to `https://`; HSTS header present | local |
| ☐ [C] | Session cookie shows `Secure`, `HttpOnly`, `SameSite=Lax` in the browser | local |
| ☐ [C] | A state-changing request from another origin is refused (403) | local |
| ☐ | Certificate expiry monitored (uptime service or calendar) | none |

## Database

| | Check | Evidence so far |
|---|---|---|
| ☐ [C] | Migrations applied by the release; `alembic current` = newest revision | local |
| ☐ [C] | The release's migrations were run on staging first | none |
| ☐ [C] | No destructive migration in the release, or owner approval + verified backup recorded | all 12 current migrations are additive |
| ☐ | `/api/v1/ready` reports the database true | local |
| ☐ | Connection budget checked if more than one API/worker container runs | n/a at launch size |

## Backups and recovery

| | Check | Evidence so far |
|---|---|---|
| ☐ [C] | Nightly backup scheduled (cron) and one set produced on production | local (manual run) |
| ☐ [C] | Sets are copied off the server automatically; one copy confirmed in the bucket | none |
| ☐ [C] | One restore into a scratch database on production: "Row counts match" | local |
| ☐ [C] | Disaster rehearsal done once on staging: empty server → restore from the off-server copy → logins work | none |
| ☐ | Alert when no backup arrives for 26 hours | none |
| ☐ | Provider-level server backups/snapshots enabled | none |
| ☐ | Retention periods confirmed by the owner | proposal in BACKUP_AND_RECOVERY.md |

## Redis

| | Check | Evidence so far |
|---|---|---|
| ☐ [C] | Redis requires its password and is not published | local |
| ☐ | `/api/v1/ready` reports redis true | local |
| ☐ | Behaviour understood: if Redis is down, rate-limited actions (login, AI, upload, publish) are refused rather than allowed without limits | tests |

## Workers and scheduler

| | Check | Evidence so far |
|---|---|---|
| ☐ [C] | Worker container is healthy; `/api/v1/health/details` shows a live worker | local |
| ☐ [C] | A post scheduled a few minutes ahead publishes once, on time (staging, real account) | tests (simulated Meta) |
| ☐ [C] | A release or worker restart while a post is due produces exactly one post (staging) | tests: crash recovery, lease loss, idempotency |
| ☐ | Worker stops cleanly on restart | local (4 s, exit 0) |
| ☐ | Alert when no worker is alive for 3 minutes | none |
| ☐ | Failed-job handling understood: 3 attempts with growing delays, then "failed" and visible in the queue with the reason | tests |

## Media storage

| | Check | Evidence so far |
|---|---|---|
| ☐ [C] | Upload, view and delete work on production | local |
| ☐ [C] | Files survive a release (the `media_data` volume is in use) | local |
| ☐ [C] | Media is included in the backup set | local |
| ☐ | Wrong file types and oversized files are refused | local + tests |
| ☐ | Another workspace cannot open the file; signed links expire | local + tests |
| ☐ | Disk-space alert at 80% | none |

## Frontend

| | Check | Evidence so far |
|---|---|---|
| ☐ [C] | Web image was built with the production address (`PRODUCTION_PUBLIC_ORIGIN`) | workflow enforces it |
| ☐ | Login, dashboard, calendar, media, settings pages load without console errors | local build passes; 59 tests |
| ☐ | Error and "not found" pages appear instead of blank screens | present in code |
| ☐ | No secret in the browser bundle (only the public address) | code review |

## Backend

| | Check | Evidence so far |
|---|---|---|
| ☐ [C] | `/api/v1/health` and `/api/v1/ready` return 200 from outside | local |
| ☐ | Logs are JSON, contain request ids, and contain no secrets | local + tests |
| ☐ | A request for another host name is not served | local |
| ☐ | API stops gracefully on restart | local (2 s, exit 0) |

## Groq

| | Check | Evidence so far |
|---|---|---|
| ☐ [C] | A real Groq key works: "Test connection" succeeds and one generation completes (staging, then production) | **none: simulated only** |
| ☐ [C] | The key exists only in `.env.production` or encrypted in the database; not in the repository, the web bundle, or logs | code review + tests |
| ☐ | Owner decided: platform key (shared, your quota) or per-workspace keys | none |
| ☐ | Groq rate-limit behaviour seen once on staging (clear message, no crash) | tests |

## Meta OAuth

| | Check | Evidence so far |
|---|---|---|
| ☐ [C] | Production Meta app exists, with the exact redirect URI | none |
| ☐ [C] | Business verification complete | none (Meta's decision) |
| ☐ [C] | App Review approved for every permission in use; app is Live | none (Meta's decision) |
| ☐ [C] | Privacy policy URL and data-deletion instructions published | none: pages do not exist yet |
| ☐ [C] | Connecting an eligible account works on the production address | **none: simulated only** |
| ☐ | Graph API version confirmed as supported | none |

## Facebook publishing

| | Check | Evidence so far |
|---|---|---|
| ☐ [C] | Text post and image post published to a controlled Page on staging; each appears exactly once | **none: simulated only** |
| ☐ [C] | Same on production with one account you own, before inviting users | none |
| ☐ | A failure (revoked permission) shows a clear reason and does not retry forever | tests |

## Instagram publishing

| | Check | Evidence so far |
|---|---|---|
| ☐ [C] | Image published to a controlled Business/Creator account on staging; appears once | **none: simulated only** |
| ☐ [C] | Same on production with one account you own | none |
| ☐ | Meta can download the media link from the production address (no firewall or auth in the way) | local: signed link works without a session |

## Analytics

| | Check | Evidence so far |
|---|---|---|
| ☐ | Analytics sync runs after publishing on staging and shows numbers | **none: simulated only** |
| ☐ | Exports (CSV/PDF) download | tests |

## Monitoring

| | Check | Evidence so far |
|---|---|---|
| ☐ [C] | Outside uptime check on `/api/v1/ready` with an alert that reaches a person | none |
| ☐ [C] | Someone is named to receive alerts and knows [../incident-response.md](../incident-response.md) | none |
| ☐ | Alert tested once by stopping the API on staging | none |
| ☐ | Decision on error tracking: add Sentry (needs a dependency change) or rely on logs | none |

## CI/CD

| | Check | Evidence so far |
|---|---|---|
| ☐ [C] | CI is green on GitHub for the release commit | not confirmed |
| ☐ [C] | `production` GitHub environment has required reviewers | none |
| ☐ [C] | The staging workflow has run successfully at least once | none |
| ☐ | `main` is protected: pull request and passing CI required | none |
| ☐ | No workflow deploys automatically (all are manual) | true by design |

## Recovery procedures

| | Check | Evidence so far |
|---|---|---|
| ☐ [C] | `deploy.sh rollback` rehearsed on staging | local |
| ☐ [C] | The person on call has read [ROLLBACK_PROCEDURE.md](ROLLBACK_PROCEDURE.md) and knows the emergency stop | none |
| ☐ | Secret rotation steps located ([../security/security-assessment.md](../security/security-assessment.md#secret-rotation)) | documented |

## Sign-off

| | Name | Date |
|---|---|---|
| Staging test plan passed | | |
| All [C] lines ticked | | |
| Owner approves production launch | | |

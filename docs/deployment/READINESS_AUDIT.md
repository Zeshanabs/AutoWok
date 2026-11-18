# Deployment readiness audit (Phase 13)

Audit date: 2026-11-17. Scope: the existing `autowok/` project only. Method: reading the Phase 12 reports, the code and every configuration file; running the test suites; rehearsing migrations on a throwaway database; and running the production stack locally with the new release script. Nothing was deployed, no account or paid resource was created, and no real credential was used.

## Overall status: PREPARATION PASSED

Deployment configuration, scripts, workflows and documentation are ready and were rehearsed locally. **Staging has not been deployed and production has not been deployed.** Autowok is not production-ready: the open items below, especially real Meta and Groq verification, off-server backups and the owner's decisions, must be closed first.

Classification: **READY** (nothing more to do before staging) · **NEEDS FIX** (work to do, no outside dependency) · **BLOCKED** (cannot proceed without something outside this repository) · **REQUIRES MY DECISION** (the owner must choose).

## Fresh evidence gathered in this audit

| Check | Result |
|---|---|
| Backend lint (`ruff`) | Pass |
| Backend tests (in-memory database; Meta, Groq and Redis simulated) | 232 passed in 2 min 25 s |
| Frontend lint; tests | Pass; 59 passed |
| `npm audit` (production dependencies) | 0 high/critical; **1 moderate** (Next.js advisory GHSA-mfr8-8qww-v76h, fixed in 16.4.6; the affected feature is not used by Autowok) |
| All 12 migrations on a throwaway PostgreSQL 16: from empty, drift check, newest one reversed and re-applied | Pass; 48 tables; no invalid indexes |
| Production images build; Compose file valid; only ports 80/443 published | Pass |
| Local rehearsal of the production stack with `scripts/deploy/deploy.sh`: release, release with backup, rollback, failed release, restore, media, isolation, cookies, shutdown | Pass after one defect was fixed ([STAGING_DEPLOYMENT.md](STAGING_DEPLOYMENT.md#local-rehearsal-what-has-been-proven-so-far)) |

Not re-run in this audit: the full suite on PostgreSQL (last run in Phase 12; CI is defined to run it), `pip-audit` (Phase 12: clean), and the Trivy image scan (GitHub only).

## Audit table

| # | Area | Status | Finding |
|---|---|---|---|
| 1 | Phase 12 report | READY | Hardening, monitoring hooks, backup scripts, CI and a production Compose stack exist and were locally verified. It states plainly that nothing was deployed and Meta/Groq were never called for real. |
| 2 | Backend architecture | READY | FastAPI on uvicorn, one process per container, non-root, read-only filesystem, graceful shutdown (observed: 2 s, exit 0). |
| 3 | Frontend architecture | READY | Next.js standalone server, non-root. The only browser-visible variable is the public address. Error, not-found and loading pages exist. Production build passes. |
| 4 | Dockerfiles and Compose | READY (after fix) | Multi-stage images, health checks, capability drop, internal data network. **Defect found and fixed:** the `backup` job could not run in the production stack (see Security issues). |
| 5 | Environment variables | READY | Development (`.env`) and production (`.env.production`) are separate files and separate Compose files. The application refuses unsafe production settings. Added: secret generator and a preflight check. |
| 6 | PostgreSQL | READY for staging | Private network, strong password enforced, health check, pooling, statement timeout. Single instance on the server's disk: see item 20. |
| 7 | Redis | READY | Password required (verified), persistence on, not published, 256 MB cap with `noeviction`. Holds no durable data. Rate limits fail closed if it is down. |
| 8 | File and media storage | REQUIRES MY DECISION | Works and persists on a server volume (verified: files survive container replacement; type/size checks; workspace isolation; signed expiring links). But **only local disk storage exists** (`STORAGE_PROVIDER=local`). That is acceptable on one server and is why container platforms are ruled out. Object storage would be new development. Decide: launch on one server with a volume (recommended), or fund object-storage work first. |
| 9 | Background workers and scheduled jobs | READY for staging | One loop handles scheduling, publishing, analytics, automations and AI agents. Jobs live in PostgreSQL and are claimed atomically with leases; retries are capped (3 attempts, growing delay); each scheduled post has a unique key so it can create only one publishing job; a post Facebook already accepted is not re-sent after a crash. Health check by heartbeat; clean stop on `SIGTERM` (observed: 4 s). All duplicate-prevention evidence is from automated tests with a simulated Meta; the real check is staging test 17. |
| 10 | Authentication, sessions, cookies | READY, with a decision | Argon2id passwords, server-side sessions, `Secure`/`HttpOnly`/`SameSite=Lax` cookies (verified locally), CSRF header + origin check (verified), login rate limits. See items 21 and 22. |
| 11 | Facebook/Instagram OAuth configuration | BLOCKED | Code and configuration are ready (state secret, exact redirect URI, encrypted tokens). No Meta app credentials exist, so the flow has **never run against Meta**. Needs: a Meta app for staging (Development mode) and test accounts. |
| 12 | Meta permissions and publishing | BLOCKED | Requests `pages_show_list`, `pages_read_engagement`, `instagram_basic`, `pages_manage_posts`, `publish_video`, `instagram_content_publish`, `read_insights`, `instagram_manage_insights`. Public use needs Meta **business verification** and **App Review (Advanced Access)**, a privacy policy URL and data-deletion instructions (**neither page exists**), and Live mode. Timing is Meta's. `META_GRAPH_API_VERSION=v26.0` must be confirmed as supported in the Meta dashboard. |
| 13 | Groq | BLOCKED | Integration preserved; backend only; official host enforced; no fallback to any other paid provider. No `GROQ_API_KEY` is configured anywhere, so **no real Groq call has ever been made** from this project's tests. Needs a key for staging. Note from Phase 12: the Phase 6 "content intelligence" tools return rule-based text and do not call Groq. |
| 14 | Search provider | BLOCKED (needs a key) | Added after the audit at the owner's request: live web search through **Tavily** or **Brave** (`RESEARCH_SEARCH_PROVIDER`, `RESEARCH_SEARCH_API_KEY`). A run stores the sources, one finding per source summary and a report that states the findings are unverified provider summaries; no AI analysis of the sources is done. Tested with simulated provider answers only: **no live search has been made**, because no key exists. Without a key, research runs still end with a "not configured" message. |
| 15 | Logging | READY | JSON logs with request ids, secrets masked, rotation configured (20 MB × 5 per container). No central log search; logs are read on the server. |
| 16 | Monitoring and alerting | NEEDS FIX | Health, readiness and metrics endpoints exist and are correctly private. **Nothing watches them yet**: no uptime monitor, no alert, nobody named to receive one. Needs an outside uptime service (free tier is enough) after a server exists. |
| 17 | Error tracking | REQUIRES MY DECISION | Errors are logged and counted. `SENTRY_DSN` is accepted, but the `sentry-sdk` package is not installed, so it has no effect. Decide: add the dependency, or rely on logs. |
| 18 | Database migrations | READY | 13 additive migrations (the 13th, workspace invitations, was added and verified the same way after the audit); verified from empty; newest reversible; run as a separate job, never on API start; release script backs up first. |
| 19 | Backups | NEEDS FIX | Scripts are sound and now work in the production stack. Missing until a server and a bucket exist: the nightly schedule, **off-server copies**, an alert when backups stop, and a disaster rehearsal on another machine. |
| 20 | Single server / database durability | REQUIRES MY DECISION | Recommended design is one server. Worst case with daily backups: up to 24 h of data lost and 1–2 h of downtime. Accept, back up more often, or pay for a managed database ([HOSTING_COMPARISON.md](HOSTING_COMPARISON.md)). |
| 21 | Open registration | REQUIRES MY DECISION | Anyone who reaches the site can create an account and workspace (rate limited: 5 per address per hour). With a platform Groq key, strangers could use your Groq quota within the per-user limits. There is no switch to close registration; adding one is a small change that needs your approval. |
| 22 | Email | REQUIRES MY DECISION | Added after the audit at the owner's request: workspace invitations by email over SMTP (`SMTP_*` settings; migration `20261117_0013` adds one table). Tested with a simulated mail server only: **no real email has been sent**, because no SMTP account is configured. Still missing: email verification and **password reset**, so a user who forgets a password is locked out unless an operator intervenes. |
| 23 | CI | NEEDS FIX (verification) | Five jobs: backend tests, PostgreSQL integration and migrations, frontend lint/types/tests/build, dependency and secret checks, image build and scan. Extended in this phase (backup-image check, preflight, deployment bundle). The repository is on GitHub (`main` matches `origin/main`), but **whether the workflow has passed on GitHub was not confirmed** from this workstation. Open the Actions tab; then protect `main`. The Phase 13 changes are not committed or pushed. |
| 24 | CD | READY, inactive | Staging and production workflows are manual, need an approving reviewer, and hold no secrets. Neither has ever run; both need a server and GitHub environment secrets. Production additionally requires a typed confirmation and a green CI run for the commit. |
| 25 | Staging environment | BLOCKED | Needs the hosting decision and a server. |
| 26 | Domain and HTTPS | REQUIRES MY DECISION | Automatic certificates are built in. Needs a domain you own and a DNS record you create. |
| 27 | Secrets hygiene | READY | No environment file is tracked; CI scans for committed credentials; preflight prints only setting names (tested with planted secrets). |
| 28 | Dependencies | NEEDS FIX (minor) | Upgrade Next.js 16.4.3 → 16.4.6 for the moderate advisory. Not exploitable in Autowok (the affected feature is unused), so not a blocker. A dependency change; awaiting approval. |
| 29 | Development stack on this workstation | NEEDS FIX (local only) | The `autowok-backend` development container is restart-looping (`ModuleNotFoundError: prometheus_client`): its image predates Phase 12. Fix: `docker compose up --build -d`. Does not affect production images. Left untouched. |
| 30 | Known security items carried from Phase 12 | REQUIRES MY DECISION | Still open by choice: members can be added by email without consent (M2), several role-permission questions (L1–L4), no purge of old sessions/audit rows (L6), inline scripts allowed by the web Content-Security-Policy. None blocks staging. See [../security/security-assessment.md](../security/security-assessment.md). |

## Security issues found and fixed in this phase

| # | Issue | Severity | Fix | Verified |
|---|---|---|---|---|
| 1 | **Production backups could not run.** The `backup` job used an image without `openssl` and tried to install it at start, but it sits on the private network with no internet. Every backup, and therefore every release after the first, would have failed. Phase 12 had tested the script outside the production stack, where it could download the package. | High (no backups in production) | The job now uses `postgres:16`, which includes `openssl`. CI checks the image offline. | Backup, verify and restore ran inside the local production stack |
| 2 | **The staging workflow would fail on the first deployment**: it always ran a backup first, and a backup of an empty database is rejected. | Medium | `deploy.sh` skips the backup only when the database has no schema yet | First release rehearsed locally |
| 3 | **Released image names were not remembered on the server.** After a workflow deployment, any manual Compose command would have silently switched the stack to non-existent `:local` images; and there was no record to roll back to. | Medium | `deploy.sh` records `release.env` / `release.previous.env`; rollback command added | Release → release → rollback rehearsed |
| 4 | **Deployment files on the server could drift** from the commit being deployed (the workflow never copied them). | Low | Workflows copy the Compose file, proxy configuration and scripts for the deployed commit | Not run on GitHub yet |
| 5 | **No pre-start validation of a server's configuration** beyond the application's own start-up refusal: placeholders, mismatched addresses or reused secrets were caught late or not at all. | Low | `scripts/deploy/preflight.sh`; also run in CI | Tested with 10 planted mistakes |
| 6 | Workflow secrets were interpolated directly into shell text | Low (hardening) | Passed through environment variables instead | Review |
| 7 | Stale statement in `docs/ci-cd.md` that the repository has no remote and that production images are reused without rebuild (the web image must be rebuilt per address) | Documentation | Corrected | – |

No secret was found in the repository, and none was added.

## Critical blockers before production

1. Real Meta verification: app, test accounts, then App Review and business verification (items 11, 12).
2. Real Groq verification with a key (item 13).
3. A staging server and a passed staging test plan (item 25).
4. Off-server backups, a schedule, and a disaster rehearsal (item 19).
5. Monitoring with an alert that reaches a person (item 16).
6. The owner's decisions (items 8, 14, 17, 20, 21, 22, 26) and hosting approval.
7. CI confirmed green on GitHub (item 23).

## What requires the owner's approval (nothing below has been done)

Creating any hosting, storage or monitoring account · paying for a server · buying a domain · changing DNS · entering real production credentials · making any environment reachable by the public · deploying to staging or production · switching on publishing to real accounts · committing and pushing the Phase 13 changes · any dependency or feature change listed above.

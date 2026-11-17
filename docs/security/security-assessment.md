# Security assessment and controls (Phase 12)

Assessment date: 2026-11-16. Method: full read of every API route and the services they call, the worker, the Docker and CI configuration; then automated tests for each control (`backend/tests/test_phase12_security.py`, 48 tests) and checks against the production stack running locally. No testing was done against any production system, and nothing destructive was run.

**Scope of the evidence.** "Verified" below means verified by code review plus automated tests using in-memory fakes, and where stated, against the locally run production stack. Nothing here was verified on a staging or production deployment, and no penetration test by an independent party has been done.

## Summary

| Severity | Found | Fixed | Open |
|---|---|---|---|
| Critical | 0 | – | 0 |
| High | 6 | 6 | 0 |
| Medium | 9 | 8 | 1 (accepted, documented) |
| Low | 13 | 7 | 6 |
| Informational | 8 | 2 | 6 |

No cross-workspace access was found: every identifier taken from a path, body or query is checked against the caller's workspace membership on the server.

## Findings

### High

| # | Finding | Fix | Verified by |
|---|---|---|---|
| H1 | **Upload exhausts memory and disk.** The 100 MB limit applied only after the whole multipart body had been received and spooled; an image name bypassed the 8 MB image limit until ~200 MB was held in memory; unauthenticated requests were parsed before being refused; no rate limit. | Body size is enforced while the request is received (`BodyLimitMiddleware`: declared length, then a running count); uploads without a session cookie are refused before the body is read; the file is read once up to the limit for its type; processing runs off the event loop with bounded concurrency (`UPLOAD_MAX_CONCURRENT`); per-user rate limit; proxy body limit. | `test_upload_*`, `test_oversized_json_body_*`; 413 observed through the proxy |
| H2 | **Any member could permanently delete any content project**, including approved, scheduled and published ones, taking the publishing record and schedule with it, with no audit entry. | Owners and Admins can delete; a Member only their own draft. Content that is published, publishing, scheduled or of uncertain outcome cannot be deleted (409). Deletion is audited. | `test_content_deletion_rules` |
| H3 | **The platform Groq key could be drained.** Generation had no rate limit, and per-workspace AI limits multiplied because workspace creation was unlimited. | Per-user hourly limits on generation, AI tools and research; workspaces per user capped and creation rate limited. | `test_workspace_creation_and_ai_generation_are_limited` |
| H4 | **Duplicate Facebook post after a crash.** If the worker stopped after Facebook accepted the post but before the job was marked published, the recovered job posted again. | A recovered job whose post id is already stored is finished without calling Meta. An answer without an id on the final request is treated as "outcome uncertain" instead of retried. | `test_post_created_before_a_crash_is_never_published_twice`, `test_answer_without_an_id_*` |
| H5 | **Known vulnerabilities in dependencies** that parse untrusted input: 74 advisories across Pillow 11.0.0, Starlette 0.38.6, python-multipart 0.0.20 and cryptography 44.0.2. | Upgraded to Pillow 13.0.0, FastAPI 0.163.1 / Starlette 1.10.0, python-multipart 0.0.34, cryptography 50.0.2; full transitive lock (`constraints.txt`). | `pip-audit`: no known vulnerabilities; 231 tests pass. See [dependency-audit.md](../dependency-audit.md) |
| H6 | **Production could start with unsafe configuration**: default database password, no encryption keys, debug on, open API docs, open metrics. | Start-up fails closed in production and names the setting; docs off by default; metrics require a token. | `test_production_*`; observed with the production image |

### Medium

| # | Finding | Status |
|---|---|---|
| M1 | CSV export cells could run as spreadsheet formulas (captions and account names come from users and from Meta). | Fixed: cells starting with `= + - @` are neutralised. `test_csv_cells_cannot_run_as_formulas` |
| M2 | Adding a member by email reveals whether an account exists, and adds the person without their consent. | **Partly mitigated, accepted for now.** Rate limited per user (20/hour) and audited. A real fix is an invitation flow with acceptance, which is a new feature and was out of scope. |
| M3 | The research page fetcher could be pointed at internal addresses (SSRF). Not reachable today (no caller), but it would be as soon as a search provider is configured. | Fixed: public addresses only, connection pinned to the checked address, redirects re-validated, size limit. `test_fetcher_*` |
| M4 | List endpoints returned unbounded results (content projects across all workspaces; the queue endpoint loaded every job to count them). | Fixed for content projects (pagination, `X-Total-Count`) and the queue (SQL counts). Remaining unbounded lists are small by nature (members, providers, accounts) or bounded by an existing cap; see Low. |
| M5 | Rate limits keyed on network address even for per-user limits; no account-wide login limit; behind a proxy every user shared one address. | Fixed: user-keyed limits ignore the address; account-wide login limit added; the production image runs uvicorn with `--proxy-headers` and a configured trusted proxy. `test_user_rate_limit_*`, `test_login_has_an_account_wide_limit` |
| M6 | No request or correlation id, no structured logs, no error reporting: an incident could not be traced. | Fixed: see [monitoring.md](../monitoring.md). |
| M7 | Lease could expire during slow Instagram processing, letting a second worker publish the same post. | Fixed: the lease is renewed while waiting, and every checkpoint checks ownership and stops if the job was taken over. `test_worker_that_lost_its_lease_stops_without_writing` |
| M8 | Jobs abandoned by a crashing worker were reclaimed forever; an analytics job could stay "running" and block all later syncs for the account. | Fixed: attempt cap on recovery; unexpected errors end the job. `test_job_abandoned_repeatedly_is_stopped`, `test_analytics_job_never_stays_running_*` |
| M9 | Containers ran as root with development servers and published database ports. | Fixed in `docker-compose.prod.yml` and the `runtime` image targets: see [deployment.md](../deployment.md). The development Compose file now publishes the database and Redis on localhost only. |

### Low

Fixed: signed media URL with a non-ASCII signature returned 500 (now 422); downloads read whole files into memory (now streamed); AI tool routes returned 500 for a malformed id (now 422) and had no limit; HTTP client libraries could log Meta OAuth query strings at INFO (pinned to WARNING, and a redaction filter masks credentials in every log line); a configuration error could echo part of the environment (now names only); one bad due post blocked later ones in the scheduler; the Redis wake-up list could grow without bound.

Open:

| # | Finding | Why it is open |
|---|---|---|
| L1 | Any member can change research status, and run, cancel or delete research. | Changing it alters who may use the research feature; needs a product decision. |
| L2 | Any member can edit media metadata; media list is capped at 500 with no paging. | Same; paging needs a small UI change. |
| L3 | Admins can demote or remove other Admins and grant Admin. | Documented behaviour since Phase 1; confirm it is intended. |
| L4 | The Meta user token of a removed Admin stays stored (encrypted) until the workspace reconnects. | Needs a decision on what should happen to accounts they connected. |
| L5 | Meta error text is shown to members in publishing errors; some messages name environment variables. | Helpful to administrators; no secrets are included. |
| L6 | Sessions, OAuth state rows, audit logs and automation events are never purged. | Storage growth, not exposure. Needs retention periods to be chosen. |

### Informational

Fixed: the interactive API documentation was served without authentication (now off in production); the health endpoint disclosed the environment name (removed).

Open:

* The content, research and AI-tool routes use a local membership check that skips the owner-consistency cross-check done by the shared dependency. Membership itself is still enforced.
* The scheduled-post list applies its status filter after the row limit, so a filtered page can contain fewer rows than exist.
* `is_verified` is never enforced, because there is no email service to verify with. Open registration plus the limits above is the current posture.
* An Admin can approve their own content (no four-eyes rule).
* Videos and GIFs are stored unmodified, so their metadata is not stripped (images are re-encoded).
* The Phase 6 content intelligence services do not call Groq (they are constructed without a client) and return rule-based text. Four of their endpoints failed with HTTP 500 on every call; that is fixed and covered by a test, but they are still not model-backed. See the Phase 12 report.

## Controls, by area

### Authentication and sessions

| Control | State |
|---|---|
| Password hashing | Argon2id (`argon2-cffi`), 12+ characters with mixed character classes; timing equalised for unknown accounts. |
| Password reset | Not implemented (no email service). There is no reset flow to attack; an account owner who forgets a password cannot recover it without an operator. |
| Session token | 256-bit random, only its SHA-256 hash stored, delivered in a cookie only. |
| Cookie | `HttpOnly`; `Secure` forced in production; `SameSite=Lax` (`none` is rejected in production). Observed on the local production stack. |
| Expiry and revocation | Checked on every request; logout and "log out everywhere" revoke server-side. `test_invalid_expired_and_revoked_sessions_are_rejected` |
| Brute force | 10 per account+address and 20 per account per 15 minutes, 60 per address; registration 5 per address per hour. Fails closed without Redis. |
| CSRF | Unsafe methods need an allowed `Origin` and the `X-CSRF-Protection` header; credentialed CORS lists exact origins. `test_csrf_protection_requires_origin_and_header` |

### Authorization

Workspace membership and role are checked on the server for the object actually loaded. Publishing, scheduling, approving, automation management, provider credentials and social accounts require Owner or Admin. Editing approved content returns it to draft, and the worker re-validates approval and content version before publishing. Agent tools are a fixed allowlist scoped to the workflow's workspace, with no publish, approve, schedule, delete, HTTP or SQL tool. Automation actions are an allowlist that cannot approve, publish, schedule or edit content. Covered by `test_another_workspace_cannot_read_or_change_anything` (21 read paths and 6 write paths), `test_members_cannot_publish_approve_or_schedule`, and the per-phase isolation tests.

### API

| Threat | Protection |
|---|---|
| SQL injection | SQLAlchemy bound parameters throughout; the only raw SQL is `SELECT 1`. Sort and filter parameters are allowlisted. |
| XSS | React escapes output; no `dangerouslySetInnerHTML`; uploads are content-sniffed (no SVG or HTML) and served with `nosniff`; Content-Security-Policy on both origins. |
| CSRF | See above. |
| IDOR / broken access control | See Authorization. |
| SSRF | Custom AI endpoints: host allowlist, public addresses, pinned connection, no redirects. Research fetcher: see M3. |
| Unsafe uploads | Magic-byte detection, Pillow verification, 40-megapixel limit, images re-encoded (metadata stripped), server-generated storage names, size limits enforced while receiving. |
| Request smuggling | One proxy (Caddy) in front of one HTTP server (uvicorn/h11), both strict about `Content-Length` and `Transfer-Encoding`; no second parsing layer. Re-check if another proxy or CDN is added. |
| Denial of service | Body limits, rate limits, bounded concurrency for uploads and AI calls, database statement timeout, timeouts on every external call, paginated lists, proxy header and read timeouts. |
| Unsafe deserialization | JSON only, validated by Pydantic; no pickle or YAML loading of user data. |

### Secrets

* No secret is committed (`.env*` ignored; CI checks tracked files and credential patterns).
* Only `NEXT_PUBLIC_API_BASE_URL` reaches the browser bundle; it is a public URL.
* Groq keys and Meta tokens stay on the server, Fernet-encrypted at rest with keys held outside the database, and are never returned by the API.
* Logs: a redaction filter masks passwords, tokens, API keys, bearer values, OAuth codes and connection-string passwords in every log line and structured field (`test_log_redaction_*`).
* Error responses: unexpected errors return a generic message and a request id (`test_unhandled_error_returns_generic_message_with_request_id`).

### Security headers

| Header | API | Web app |
|---|---|---|
| `Content-Security-Policy` | `default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'` | `default-src 'self'`; scripts and styles from self plus inline; images, media and connections limited to self and the API origin (plus Meta's CDN for images); `object-src 'none'`; `frame-ancestors 'none'`; `form-action 'self'` |
| `Strict-Transport-Security` | 1 year, subdomains (when cookies are secure) | 1 year, subdomains (production build) |
| `X-Content-Type-Options` | `nosniff` | `nosniff` |
| `X-Frame-Options` | `DENY` | `DENY` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | same |
| `Permissions-Policy` | camera, microphone, geolocation off | same |
| `Cross-Origin-Opener-Policy` | `same-origin` | `same-origin` |
| `Cache-Control` | `no-store` on JSON | framework defaults |

**Known weakness:** the web policy allows inline scripts (`'unsafe-inline'`). Next.js needs inline bootstrap scripts, and the alternative (a per-request nonce) requires every page to be rendered per request instead of prerendered, per the framework's own documentation. The exposure is limited because the app renders no user-supplied HTML, but a strict nonce-based policy would be stronger; it is a performance trade-off to decide deliberately.

## Secret rotation

| Secret | Procedure | Effect |
|---|---|---|
| `AI_ENCRYPTION_KEY` | Generate a new key. Set it as `AI_ENCRYPTION_KEY` and the old one as `AI_ENCRYPTION_KEY_PREVIOUS`. Restart. Run `python scripts/rotate_encryption_keys.py --scope ai --dry-run` in the backend container, then without `--dry-run`, to re-encrypt. Remove the previous key and restart. | None for users. |
| `TOKEN_ENCRYPTION_KEY` | Same, with `TOKEN_ENCRYPTION_KEY_PREVIOUS` and `--scope meta` ([token-storage.md](token-storage.md)). | None for users. |
| `MEDIA_URL_SIGNING_SECRET` | Replace and restart. | Outstanding signed media links stop working; in-flight publishing jobs retry with new links. Rotate when no publishing is in progress. |
| `META_OAUTH_STATE_SECRET` | Replace and restart. | A Meta authorization in progress must be started again. |
| `META_APP_SECRET` | Reset it in the Meta developer console, update, restart. | None if done together. |
| `GROQ_API_KEY` | Create a new key in the Groq console, update, restart, revoke the old key. | None. Workspace keys are rotated by their owners in Settings → AI. |
| `POSTGRES_PASSWORD` | `ALTER ROLE ... PASSWORD` in PostgreSQL, update `.env.production`, restart API and worker. | A few seconds of errors during the restart. |
| `REDIS_PASSWORD` | Update `.env.production`, recreate Redis, API and worker together. | Rate-limit counters reset. |
| `METRICS_TOKEN` | Replace, restart the API, update the monitoring system. | Scrapes fail until updated. |
| `BACKUP_PASSPHRASE` | Replace for future backups; keep the old one until backups made with it expire. | None. |
| Session cookies | Not a configured secret. To invalidate every session, run `UPDATE sessions SET revoked_at = now() WHERE revoked_at IS NULL`. | Everyone signs in again. |

Rotate immediately after any suspected exposure, when someone with access leaves, and otherwise on a schedule you set (for example yearly for encryption keys, quarterly for service credentials). Rotation of the two Fernet keys with the script was not re-tested in Phase 12; it is covered by the Phase 3 tests.

## Verification performed

| Test area | Evidence |
|---|---|
| Cross-workspace access | 27 paths as an outsider, all 404 |
| Unauthorized publishing, approval, scheduling | Member receives 403; unapproved content rejected for the Owner too |
| Session expiration and invalid tokens | Forged, expired and revoked sessions rejected |
| File upload attacks | Oversized, disguised HTML, SVG, junk-as-JPEG all rejected |
| Injection | Parameter binding by construction; formula injection neutralised; no SQL built from input |
| CSRF | Missing origin, wrong origin and missing header rejected |
| Rate limits | Login, generation, workspace creation, client errors, user-keyed limit |
| Secret exposure | Redaction tests; audit log scan in the end-to-end test; API responses checked for keys and tokens |
| Agent tool restrictions | Phase 11 tests plus the end-to-end test: AI output enters as a draft, nothing is approved or published |
| Automation restrictions | Phase 10 tests plus the end-to-end test |
| Export access control | Outsider receives 404 for the export; export rate limited |

## Reporting a vulnerability

Send reports to the security contact you designate for your deployment, and add a `SECURITY.md` with that address before the repository or product is public. None is configured yet.

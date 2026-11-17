# Incident response guide

What to do when something goes wrong in production: who decides, the first fifteen minutes, runbooks for the likely incidents, and what to record afterwards.

This is a starting procedure for a small team. Fill in the names, contact details and legal obligations for your organisation before going live; the placeholders are marked.

## Severity

| Level | Meaning | Examples | Respond |
|---|---|---|---|
| SEV 1 | Data exposed or at risk, or the service is down for everyone | A credential or encryption key leaked; one workspace can see another's data; posts published to the wrong account; database lost | Immediately, all hands |
| SEV 2 | A core function is broken for many users | Nothing publishes; nobody can log in; AI features down for all | Within 30 minutes |
| SEV 3 | Degraded or partial | Analytics stale; one workspace's account failing; slow pages | Same working day |

## Roles

| Role | Who (fill in) | Does |
|---|---|---|
| Incident lead | _name_ | Decides, coordinates, keeps the timeline |
| Operator | _name_ | Runs commands on the server |
| Communicator | _name_ | Tells users and stakeholders what is known |

One person may hold several roles. Agree on one channel for the incident and write down times as you go.

## First fifteen minutes

1. **Confirm and classify.** What is failing, for whom, since when? Pick a severity.
2. **Stabilise before diagnosing.** If data is being exposed or wrong content is being published, stop that first (see the runbooks). A brief outage is better than continued harm.
3. **Preserve evidence.** Do not delete containers, volumes or logs. Save logs before restarting anything:

   ```sh
   C="docker compose --env-file .env.production -f docker-compose.prod.yml"
   mkdir -p incident-$(date -u +%Y%m%dT%H%M) && cd $_
   for s in proxy backend worker postgres redis; do $C logs --since 6h $s > $s.log 2>&1; done
   $C ps > ps.txt
   ```

4. **Look.** `$C ps`, `/api/v1/ready`, error log lines, the metrics in [monitoring.md](monitoring.md#alerts-to-configure). Recent deployments and configuration changes are the most common cause: check what changed.
5. **Communicate.** Tell affected users what is happening in plain words, even if the cause is not known yet.

## Runbooks

### Stop all publishing (wrong content, wrong account, runaway jobs)

```sh
$C stop worker
```

Nothing is published while the worker is stopped. Scheduled posts and queued jobs stay in the database. Investigate, cancel the affected jobs in the app (Publishing → Cancel, Calendar → Cancel), then `$C up -d worker`. Posts whose time passed more than 6 hours ago will be marked missed, not published late.

To stop automations or AI workflows only, set `AUTOMATION_ENABLED=false` or `AGENTS_ENABLED=false` in `.env.production` and recreate the API and worker.

### A secret may have leaked

Treat as SEV 1. For the leaked secret, follow the rotation table in [security-assessment.md](security/security-assessment.md#secret-rotation). In addition:

| Leaked | Also do |
|---|---|
| `.env.production` or a server compromise | Rotate **everything** in the file. Assume the database was readable. |
| `TOKEN_ENCRYPTION_KEY` together with database access or a backup | The stored Meta tokens must be considered exposed. Reset the Meta app secret (this invalidates the app's tokens), and have every workspace reconnect its accounts. |
| `AI_ENCRYPTION_KEY` together with database access or a backup | Stored AI provider keys are exposed. Tell workspace owners to revoke and replace their Groq keys. |
| `GROQ_API_KEY` | Revoke it in the Groq console first, then replace it. Check Groq usage for abuse. |
| A session cookie or suspected account takeover | Revoke that user's sessions (`UPDATE sessions SET revoked_at = now() WHERE user_id = '<id>' AND revoked_at IS NULL`); the user must choose a new password. There is no self-service password reset: an operator has to set it. |
| The backup passphrase and a backup | The backup contents are exposed: handle as a database leak. |

Then find how it leaked (logs, a commit, a shared screen, a compromised machine) and close that path.

### Suspected cross-workspace access

1. Take the API offline if exposure is ongoing: `$C stop backend`.
2. Identify the request from the report (time, user, URL) and find it in the logs by `request_id`, `user_id` or `workspace_id`.
3. The audit log table records who did what in which workspace. Query it for the affected workspace and time range.
4. Do not restart until the access check that failed is understood and fixed. Add a test to `backend/tests/test_phase12_security.py` that reproduces it.

### Service down

| Check | If so |
|---|---|
| `$C ps` shows a container restarting | `$C logs <service>`. A configuration error names the setting. |
| `/api/v1/ready` returns 503 | The body says whether the database or Redis is unreachable. Restore that service; the API and worker reconnect. |
| Proxy up, API healthy, users still fail | Certificate or DNS. `$C logs proxy`. |
| Started after a deployment | Roll back ([deployment.md](deployment.md#rolling-back)). |
| Host out of disk | Logs are rotated; check the media volume, the backup directory and PostgreSQL. |

### Database lost or corrupted

1. Stop the API and worker so nothing writes to a damaged database.
2. Do not delete the damaged volume.
3. Restore the latest verified backup into a **new** database and switch to it ([backup-recovery.md](backup-recovery.md#restore-procedure)).
4. Tell users what period of work was lost (the time since that backup).
5. Review the calendar: posts scheduled inside the lost period are gone and must be scheduled again.

### Meta or Groq outage

Nothing to fix on your side. Publishing jobs retry with backoff and then fail visibly; AI workflows wait and retry. Tell users; afterwards, failed posts can be retried from the Publishing page. Watch `autowok_external_requests_total{service="meta"}` and `autowok_ai_requests_total` by outcome.

### Abuse or overload

Sustained `autowok_rate_limited_total` or a spike in requests from few addresses. Limits are per user and per address; lower the relevant `RATE_LIMIT_*` value, deactivate the abusing account (`UPDATE users SET is_active = false WHERE id = '<id>'`, which ends its sessions on the next request), and block addresses at the proxy or firewall if needed.

## After the incident

Within a few days, write down, without blame:

* Timeline: detection, decisions, actions, recovery (with times).
* Impact: who was affected, for how long, what data.
* Cause, and why it was not caught earlier.
* What limited the damage and what made it worse.
* Actions, each with an owner and a date: a test that would have caught it, an alert that would have fired sooner, a change to this guide.

## Notification duties

If personal data was exposed, you may be legally required to notify a regulator and the affected people within a fixed time (for example 72 hours under GDPR), and Meta's platform terms have their own incident-reporting requirements for data obtained from Meta. **Confirm the obligations that apply to you with legal counsel before launch and record them here**: _regulator, deadline, contact, who decides_.

## Contacts (fill in)

| Who | Contact |
|---|---|
| Incident lead / on-call | |
| Hosting provider support | |
| Domain and DNS provider | |
| Meta developer support | https://developers.facebook.com/support |
| Groq support | https://console.groq.com |
| Legal / data protection contact | |

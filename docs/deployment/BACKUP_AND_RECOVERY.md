# Backup and recovery (production plan)

What is backed up, how often, how long copies are kept, where they go, and how to get everything back. The script-level reference (file formats, encryption details) is [../backup-recovery.md](../backup-recovery.md).

**Status.** No production backup exists, because no production exists. The backup, verify and restore scripts were run on 2026-11-17 inside a local copy of the production stack (results at the end). Off-server copying and the nightly schedule are **written but not yet set up or tested**: they need a storage account you approve.

## The short version

1. Every night the server makes one encrypted backup set: the database and all uploaded media.
2. The set is copied to storage **outside** the server.
3. Backups older than the retention period are removed.
4. Once a month, a person restores the newest backup into a scratch database to prove it works.
5. Four secrets are kept in a password manager, because backups are useless without them.

## What must survive

| Thing | Where it lives | How it is protected |
|---|---|---|
| Database (accounts, workspaces, brands, content, schedules, analytics, automations) | `postgres_data` volume | Nightly encrypted dump |
| Uploaded media | `media_data` volume | Archived in the same nightly set |
| `AI_ENCRYPTION_KEY`, `TOKEN_ENCRYPTION_KEY` | `.env.production` only (deliberately not in the database) | **Password manager.** Without them a restored database cannot read saved Groq keys or Facebook/Instagram tokens. |
| `BACKUP_PASSPHRASE` | `.env.production` | **Password manager.** Without it no backup can be opened. Never stored with the backups. |
| `MEDIA_URL_SIGNING_SECRET` and the rest of `.env.production` | The server | Password manager copy (can be regenerated, at the cost of reconnecting things) |
| Redis | `redis_data` volume | Not backed up: it holds only rate-limit counters and wake-up signals |
| HTTPS certificates | `caddy_data` volume | Not backed up: re-issued automatically |

## Schedule and retention policy

| Copy | How often | Kept for | Purpose |
|---|---|---|---|
| Local backup sets on the server (`BACKUP_HOST_DIR`) | Nightly, and automatically before every release | 14 days (`BACKUP_RETENTION_DAYS`) | Fast restore after a mistake |
| Off-server copy (storage bucket) | Right after each nightly backup | 30 daily copies; then one per month for 12 months (set as lifecycle rules on the bucket) | Survives loss of the server or the provider account being locked |
| Provider's whole-server backup/snapshot | Daily or weekly (provider option, about +20% of the server price) | 7 copies | Fastest way to rebuild the whole server |

Resulting targets (to tune, not guarantees):

* **Data you could lose (RPO):** up to 24 hours. To shrink it, run the backup more often (it does not block the application), or move to a managed database with point-in-time recovery.
* **Time to be running again (RTO):** about 1–2 hours for a practised person with a small database: new server (15 min), install Docker and copy configuration (20 min), restore (minutes), DNS (minutes to an hour).

The retention numbers are a starting proposal. Longer retention costs more storage; legal or customer requirements may demand specific periods. **This is a decision for you.**

## Setting it up on the server

### 1. Nightly backup

```sh
crontab -e
```

```cron
# Autowok: encrypted database + media backup at 02:15 UTC
15 2 * * * cd /srv/autowok && docker compose --env-file .env.production --env-file release.env -f docker-compose.prod.yml run --rm backup >> /var/log/autowok-backup.log 2>&1
```

The job refuses to run without `BACKUP_PASSPHRASE`, checks that the dump is readable before trusting it, writes checksums and a manifest with the row count of every table, and removes its own files if it fails halfway.

### 2. Copy off the server

Any tool that copies a folder to object storage works. With `rclone` (one-time `rclone config` to add the bucket, using an access key limited to that one bucket):

```cron
# Autowok: copy new backup sets off the server at 02:45 UTC. "copy" never deletes anything in the bucket.
45 2 * * * rclone copy /srv/autowok/backups autowok-backups:YOUR-BUCKET/autowok --max-age 48h >> /var/log/autowok-backup.log 2>&1
```

On the bucket itself: turn on versioning or object lock if available, and add lifecycle rules for the retention above. Use an access key that can write but not delete, so a compromised server cannot erase its own backups. The sets are already encrypted before they leave the server.

### 3. Know when it stops working

A backup that silently stopped is the most common way backups fail. Set up one of:

* a "heartbeat" check at the uptime monitor (a URL the cron job calls after success; the monitor alerts if 26 hours pass without a call), or
* a weekly calendar reminder to look at `ls /srv/autowok/backups | tail -3`.

### 4. Monthly restore test

```sh
C="docker compose --env-file .env.production --env-file release.env -f docker-compose.prod.yml"
SET=$(ls backups | tail -n 1)
$C run --rm --entrypoint sh backup /scripts/verify.sh /backups/$SET
$C run --rm -e PGDATABASE=postgres --entrypoint sh backup /scripts/restore.sh /backups/$SET autowok_restore_test
# expect: "Row counts match for 48 tables"
$C exec postgres sh -c 'psql -U "$POSTGRES_USER" -d postgres -c "drop database autowok_restore_test"'
```

The restore script only ever creates a **new** database and refuses to touch an existing one, so this test cannot harm live data. The final `drop database` removes only the scratch copy; check the name before pressing Enter.

## Restore procedure

Use this when data was lost or damaged. If only the application is misbehaving after a release, roll back first ([ROLLBACK_PROCEDURE.md](ROLLBACK_PROCEDURE.md)); a restore is the last resort because everything created after the backup is lost.

### A. The server is fine, the data is not

```sh
cd /srv/autowok
C="docker compose --env-file .env.production --env-file release.env -f docker-compose.prod.yml"
ls backups                                    # choose the set from before the damage

# 1. Verify the set
$C run --rm --entrypoint sh backup /scripts/verify.sh /backups/<set>

# 2. Restore into a NEW database (never over the live one)
$C run --rm -e PGDATABASE=postgres --entrypoint sh backup \
  /scripts/restore.sh /backups/<set> autowok_restore_YYYYMMDD

# 3. Look at it before switching (recent content, accounts)
$C exec postgres sh -c 'psql -U "$POSTGRES_USER" -d autowok_restore_YYYYMMDD -c "select count(*) from users"'

# 4. Switch the application to it
$C stop backend worker
nano .env.production                          # set POSTGRES_DB=autowok_restore_YYYYMMDD
$C run --rm migrate                           # brings an older backup up to the current schema
$C up -d
curl -fsS https://<your address>/api/v1/ready
```

The damaged database stays in place, untouched, until you decide to delete it.

To restore media: extract into an empty folder first (`-e RESTORE_MEDIA_DIR=/backups/media-restore` on the restore command), compare, then copy the missing files into the media volume.

### B. The server is gone

1. Create a new server and prepare it as in [STAGING_DEPLOYMENT.md](STAGING_DEPLOYMENT.md#2-prepare-the-server) (or restore the provider's whole-server snapshot, which is faster, then continue from step 4 with the newest off-server backup if it is more recent).
2. Copy the deployment files and recreate `.env.production` **from the password manager**, with the same encryption keys and backup passphrase.
3. Download the newest backup set from the bucket into `backups/`.
4. Start the database only (`$C up -d postgres`), then restore as in A.2 using a new database name, and set `POSTGRES_DB` to it.
5. Restore media into the volume, run `sh scripts/deploy/deploy.sh release <images>`, and point DNS at the new server's address.

### After any restore

* Posts scheduled for a time that passed while the system was down are published late only within 6 hours (`SCHEDULE_MAX_LATENESS_SECONDS`); older ones are marked "missed". Review the calendar.
* A Facebook post whose final request had already been sent when the backup was taken is marked "outcome uncertain" for a person to check. It is never sent a second time.
* If the encryption keys were lost, every workspace must enter its Groq key again and reconnect its Facebook/Instagram accounts.
* Tell affected users what was lost and from when.

## What was tested

Run on 2026-11-17 on a workstation, in a local copy of the production stack (private Docker network, production settings, throwaway data and secrets):

| Test | Result |
|---|---|
| Backup through the production `backup` job | **First attempt failed**: the job's container had no `openssl` and, being on the private network, could not install it. Fixed by using the `postgres:16` image, which includes it; CI now checks the image offline. |
| Backup after the fix, triggered automatically by a release | Encrypted database dump + encrypted media archive + checksums + manifest |
| Verify | Checksums OK; dump readable (48 tables); media archive readable |
| Restore into a new database | 2 seconds; row counts matched for 48 tables; schema revision `20261116_0012` |
| Restore over the live database | Refused |
| First release with an empty database | Backup correctly skipped (nothing to back up) |

Also covered by the earlier Phase 12 test ([../backup-recovery.md](../backup-recovery.md#recovery-test)): wrong passphrase rejected, tampered file detected, restored media byte-identical.

**Not tested:** the cron schedule, off-server copying, bucket retention rules, restoring on a different machine (scenario B), a backup taken under heavy use, and point-in-time recovery. Scenario B must be rehearsed on staging before production launch ([PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md)).

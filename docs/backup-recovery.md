# Backup and recovery guide

What must be backed up, how, how to restore, and what was tested.

## What holds state

| Data | Where | Lost if not backed up |
|---|---|---|
| Everything the application records | PostgreSQL (`postgres_data` volume) | Accounts, workspaces, brands, content, schedules, publishing history, analytics, automations, AI workflows |
| Uploaded media | `media_data` volume (`/app/storage/local`) | Images and videos attached to content |
| Encryption keys and secrets | `.env.production` | Stored AI provider keys and Meta tokens become unreadable; see below |
| Redis | `redis_data` volume | Nothing durable: rate-limit counters and worker wake-ups only. Not backed up. |
| TLS certificates | `caddy_data` volume | Re-issued automatically |

## Targets

These are operational targets to tune to your needs, not guarantees.

| | Target with the defaults below | Depends on |
|---|---|---|
| Recovery point objective (RPO): data you can lose | 24 hours with a daily backup; minutes with WAL archiving | `BACKUP` schedule; point-in-time recovery setup |
| Recovery time objective (RTO): time to be running again | About 1 hour for a small database | Database size, where backups are stored, practice |

Measured locally: restoring a database of about 190,000 rows (8.7 MB compressed dump) took 4 seconds. Restore time grows with size; measure it with your own data.

## Database backups

`scripts/backup/backup.sh` writes one timestamped set per run:

```
<BACKUP_DIR>/<UTC timestamp>/
  database.dump.enc   pg_dump custom format, compressed, encrypted
  media.tar.gz.enc    media files, encrypted
  SHA256SUMS          checksums of both files
  MANIFEST            time, schema revision, row count of every table
```

* **Consistency:** `pg_dump` takes a consistent snapshot without blocking the application.
* **Encryption:** AES-256-CBC with a PBKDF2-derived key (`openssl enc`), using `BACKUP_PASSPHRASE`. The script refuses to write an unencrypted backup unless `BACKUP_ALLOW_UNENCRYPTED=1` is set for a test.
* **Integrity:** the dump is read back with `pg_restore --list` before it is encrypted, and checksums are recorded.
* **Retention:** sets older than `BACKUP_RETENTION_DAYS` (default 14) are deleted. Only directories named like a timestamp are ever removed. A failed run removes its own incomplete set.
* The script only reads from the database.

Run it:

```sh
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backup
```

Schedule it daily with cron on the host:

```cron
15 2 * * * cd /srv/autowok && docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backup >> /var/log/autowok-backup.log 2>&1
```

`BACKUP_HOST_DIR` should be a mount of storage that is not the server's own disk (a network volume, or a directory that a sync job copies to object storage with versioning and a retention lock). A backup that lives only on the server it protects is lost with that server. Alert when no new set has appeared for 26 hours.

### Point-in-time recovery

A daily dump gives an RPO of up to a day. For a smaller RPO use PostgreSQL's continuous archiving (base backup plus WAL), which the bundled `postgres` container is not configured for. The practical options are a managed PostgreSQL service with point-in-time recovery, or a tool such as pgBackRest or WAL-G against your own server. This is not set up or tested in this repository.

## Media backups

Media is archived in the same run as the database, so the two are consistent to within the duration of the run (a file uploaded during the run can be in the database dump and missing from the archive, or the reverse; the application reports a missing file per asset rather than failing).

Uploaded files are never modified after upload and are stored under generated names, so an incremental copy (`rsync`, or object storage sync with versioning) is a good complement between full backups. There is no storage versioning for the local volume itself: a file deleted from the volume can only be recovered from a backup. In the application, "deleting" a media asset archives it and keeps the file.

## Keys and configuration

`AI_ENCRYPTION_KEY` and `TOKEN_ENCRYPTION_KEY` are **not** in the database, by design. Without them a restored database still works, but every saved AI provider key and every connected Meta account must be entered or connected again.

* Keep a copy of `.env.production` (or at least the two encryption keys, `MEDIA_URL_SIGNING_SECRET` and `BACKUP_PASSPHRASE`) in a secret manager or password vault, with access limited to the people who would perform a recovery.
* Do not store the backup passphrase next to the backups, and do not put encryption keys in the backup directory.
* After rotating a key ([security-assessment.md](security/security-assessment.md#secret-rotation)), update the stored copy. Keep the previous key until every backup taken under it has expired.

## Restore procedure

`scripts/backup/restore.sh <set> <new database name>` creates a **new** database, restores into it, and compares the row count of every table with the manifest. It refuses to run if the target database already exists, so it cannot overwrite live data. Media is extracted only into an empty directory.

1. **Verify the set** (checksums, decryption, readable dump). Do this on a schedule too, not only when you need the backup:

   ```sh
   docker compose --env-file .env.production -f docker-compose.prod.yml run --rm \
     --entrypoint sh backup /scripts/verify.sh /backups/<timestamp>
   ```

2. **Restore into a new database:**

   ```sh
   docker compose --env-file .env.production -f docker-compose.prod.yml run --rm \
     -e PGDATABASE=postgres --entrypoint sh backup \
     /scripts/restore.sh /backups/<timestamp> autowok_restore_20261116
   ```

   The script ends with `Row counts match for N tables` or lists every mismatch.

3. **Check it** before switching: connect to the new database and look at recent content, schedules and accounts.

4. **Switch the application** (the deliberate, manual step):

   ```sh
   C="docker compose --env-file .env.production -f docker-compose.prod.yml"
   $C stop backend worker
   # set POSTGRES_DB=autowok_restore_20261116 in .env.production
   $C run --rm migrate          # brings an older backup up to the current schema
   $C up -d
   ```

   The damaged database is left in place until you decide to drop it.

5. **Restore media** if needed: extract into an empty directory with `RESTORE_MEDIA_DIR`, compare, then copy into the media volume.

6. **After a restore:** posts that were scheduled for a time that has passed are marked "missed" after `SCHEDULE_MAX_LATENESS_SECONDS` (6 hours) rather than published late; review the calendar. Publishing jobs that were in progress at backup time are recovered by the worker as described in [architecture.md](architecture.md#background-work-and-recovery); a Facebook post whose final request had been sent is marked "outcome uncertain" for a person to check, never re-sent.

## Recovery test

**Tested on 2026-11-16, locally, against a throwaway PostgreSQL 16 container holding the seeded performance dataset (about 190,000 rows across 48 tables) and two sample media files. No production or shared data was involved.**

| Step | Result |
|---|---|
| Backup without a passphrase | Refused (exit 2) |
| Backup | 8.7 MB encrypted dump, encrypted media archive, checksums, manifest |
| Verify | Checksums OK, dump readable (48 tables), media archive readable |
| Verify with the wrong passphrase | Decryption failed |
| Restore over the existing database | Refused |
| Restore into a new database | 4 seconds; row counts matched for 48 tables; schema revision `20261116_0012` |
| Restored media | Byte-identical to the original |
| One byte appended to the encrypted dump | Checksum verification failed |

Not tested: restoring on a different host, a backup taken during heavy writes, retention expiry over real days, point-in-time recovery, and the cron schedule. Repeat the restore test on staging after deployment and at least quarterly.

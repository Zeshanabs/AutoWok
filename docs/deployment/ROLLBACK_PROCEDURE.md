# Rollback procedure

What to do when a release goes wrong. Written to be followed under pressure: start at the top, stop as soon as the system is healthy.

**Status.** Level 1 was rehearsed on a local copy of the production stack on 2026-11-17 (rollback completed and the API was ready again in 16 seconds). Levels 2 and 3 were exercised only as separate pieces (downgrade of the newest migration; restore into a new database). Nothing has been rehearsed on a real server yet; do so on staging.

## First: decide in two minutes

```sh
cd /srv/autowok
sh scripts/deploy/deploy.sh status
curl -s -o /dev/null -w '%{http_code}\n' https://<your address>/api/v1/ready
docker compose --env-file .env.production --env-file release.env -f docker-compose.prod.yml logs --tail 50 backend worker
```

| What you see | Do |
|---|---|
| The release script itself failed and said so | See "If the release script stopped" below |
| Site is up, one feature is broken, no data is being damaged | Consider fixing forward with a new release. Otherwise Level 1. |
| Site is down or erroring since the release | **Level 1** |
| Old version cannot work with the new database schema | **Level 2** |
| Data was deleted or corrupted | Stop the worker, then **Level 3** |
| Wrong things are being published | **Emergency stop** first |

### Emergency stop (publishing must stop now)

```sh
C="docker compose --env-file .env.production --env-file release.env -f docker-compose.prod.yml"
$C stop worker
```

Nothing is published or scheduled while the worker is stopped; the website keeps working and nothing is lost. Due posts wait, and are published when the worker returns if they are less than 6 hours late (later ones are marked "missed"). Start it again with `$C up -d worker`.

## If the release script stopped

`scripts/deploy/deploy.sh release` stops at the first failing step and says which.

| Stopped at | State | Action |
|---|---|---|
| Pull, or preflight | Nothing was changed; the old version is still running | Fix the cause (image name, registry login, configuration) and release again |
| Backup | Nothing was changed | Fix the backup (disk full? passphrase?) and release again. Do not skip the backup. |
| Migrations | Migrations run inside a database transaction, so a failure is rolled back and the schema stays at an earlier, consistent revision. The old version is still running. | Read the error. Check `... run --rm migrate alembic current`. Fix the migration in a new commit; do not edit the database by hand. |
| Start / verify ("did not become ready") | New containers are running but unhealthy | Level 1 (the script prints the exact command) |

## Level 1: return to the previous images (no database change)

This is the normal rollback. It is safe because Autowok's migrations only add things, so the previous version runs correctly on the newer schema.

```sh
sh scripts/deploy/deploy.sh rollback
```

It starts the images recorded in `release.previous.env`, waits until the API reports ready and the worker is healthy, and records the result. The release that was replaced is noted in `release.failed.env`.

If the failed release never finished (so it was never recorded), the script's error message told you to run:

```sh
cp release.env release.previous.env && sh scripts/deploy/deploy.sh rollback
```

Then confirm: `curl -fsS https://<your address>/api/v1/ready`, log in, open the calendar.

By hand, without the script: put the previous two image names in `release.env`, then `docker compose --env-file .env.production --env-file release.env -f docker-compose.prod.yml up -d --no-build`.

## Level 2: also revert the newest migration

Only when Level 1 fails **because of the schema** (errors in the old version's log naming a table or column). This can delete data: read the table in [DATABASE_DEPLOYMENT.md](DATABASE_DEPLOYMENT.md#rolling-back-a-migration) first. For anything except an index-only migration, **get the owner's explicit approval before continuing.**

```sh
C="docker compose --env-file .env.production -f docker-compose.prod.yml"

# 1. Stop writers
$C stop backend worker

# 2. Back up the current state (yes, again)
$C run --rm backup

# 3. Revert ONE migration, using the NEW image (it contains the migration being reverted)
BACKEND_IMAGE=<new backend image, from release.failed.env> $C run --rm migrate alembic downgrade -1
BACKEND_IMAGE=<new backend image> $C run --rm migrate alembic current

# 4. Start the previous version
sh scripts/deploy/deploy.sh rollback
```

Never downgrade more than one step, and never downgrade a migration that has been live for more than a short time: the data created since then would be destroyed.

## Level 3: restore the pre-release backup

When data was damaged. Everything created after the backup is lost, so stop and think about whether a targeted repair is possible first.

Every release makes a backup immediately before migrating. It is the newest folder in `backups/` from before the release.

1. `$C stop backend worker`
2. Follow [BACKUP_AND_RECOVERY.md → Restore procedure → A](BACKUP_AND_RECOVERY.md#a-the-server-is-fine-the-data-is-not): verify the set, restore it into a **new** database, inspect it, set `POSTGRES_DB` to the new name.
3. Start the **previous** images: `sh scripts/deploy/deploy.sh rollback`. Do **not** run migrations: the restored database is at the schema the previous version expects.
4. Review scheduled posts and any post published between the backup and the restore: the restored database does not know about them. Check the Facebook/Instagram accounts and do not republish by hand without checking.

The damaged database is left in place for investigation.

## Rolling back configuration

If the cause was a changed setting rather than new code: restore the previous `.env.production` (keep a dated copy before every edit: `cp .env.production .env.production.bak-YYYYMMDD && chmod 600 .env.production.bak-*`), run `sh scripts/deploy/preflight.sh`, then `docker compose --env-file .env.production --env-file release.env -f docker-compose.prod.yml up -d`.

## Rolling back the web address or DNS

DNS changes take up to the record's TTL to spread. Keep the TTL at 300 seconds around a launch or a server move, and keep the old server running until traffic has moved.

## Afterwards

1. Write down what happened and when ([../incident-response.md](../incident-response.md)).
2. Do not delete `release.failed.env`, the logs or the pre-release backup until the cause is understood.
3. Fix the cause in a new commit, pass CI, deploy to staging, repeat the failed scenario there, and only then release to production again.

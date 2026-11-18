# Database deployment and migrations

How the production PostgreSQL database is configured, how schema changes ("migrations") are applied safely, and how to undo one. Backups and restores are in [BACKUP_AND_RECOVERY.md](BACKUP_AND_RECOVERY.md).

**Status.** No production or staging database exists. Everything below was exercised on throwaway local databases only (results at the end).

## What a migration is

Autowok's tables are created and changed by numbered scripts in `backend/alembic/versions/` (12 so far, `0001` to `0012`). The database remembers which script it is at. "Running migrations" means: apply every script newer than that, in order. A new, empty database runs all twelve; an existing one runs only what is new.

## Production database configuration

| Setting | Value | Why |
|---|---|---|
| Engine | PostgreSQL 16 (`postgres:16-alpine` container) | Same major version as development, CI and all tests |
| Network | Docker network `data`, marked `internal` | No route to or from the internet; no port is published |
| Credentials | `POSTGRES_USER` + a 64-character random `POSTGRES_PASSWORD` | The API refuses to start with an empty or default password |
| Storage | Named volume `postgres_data` | Survives container replacement and server reboots |
| Health check | `pg_isready` every 10 seconds | The API and worker wait for it before starting |
| Memory | Limited to 1 GB, 256 MB shared memory | Fits the 4 GB server |
| Statement timeout | 30 seconds (`DB_STATEMENT_TIMEOUT_MS`) | A runaway query cannot hold the database |
| Connect timeout | 5 seconds | A database outage fails fast instead of hanging requests |

Health from the application's side: `GET /api/v1/ready` returns 200 only when the database (and Redis) answer, and 503 otherwise. The release script waits for it, and the uptime monitor should watch it.

### Connection pooling

Each API or worker process keeps its own small pool of database connections and reuses them (opening a connection per request would be slow).

| Setting | Default | Meaning |
|---|---|---|
| `DB_POOL_SIZE` | 5 | Connections kept open per process |
| `DB_MAX_OVERFLOW` | 10 | Extra connections allowed during a burst |
| `DB_POOL_TIMEOUT_SECONDS` | 30 | Wait for a free connection before failing |
| `DB_POOL_RECYCLE_SECONDS` | 1800 | Reconnect periodically, so idle connections dropped by a firewall are never used |

Budget: every process can use up to 15 connections; PostgreSQL allows 100. The standard stack (1 API + 1 worker) uses at most 30. Keep `(API containers + workers) × 15` under about 90; beyond that, lower the pool settings or add a pooler such as PgBouncer. **A separate pooler is not needed at launch size** and is not included.

With a managed database on a small plan, check its connection limit first: some entry plans allow far fewer than 100.

## Applying migrations

Migrations are a separate, explicit step. The production API image never migrates on start, so two containers can never race to change the schema.

**Normal path: do nothing special.** `scripts/deploy/deploy.sh release ...` (which the GitHub workflows call) always runs, in this order: configuration check → **backup** → migrate → start → verify. The backup is skipped only on the very first release, when the database is still empty.

By hand, the same steps are:

```sh
C="docker compose --env-file .env.production --env-file release.env -f docker-compose.prod.yml"
$C run --rm backup            # 1. always first
$C run --rm migrate           # 2. alembic upgrade head
$C up -d                      # 3. start the new version
```

Useful checks:

```sh
$C run --rm migrate alembic current     # which revision the database is at
$C run --rm migrate alembic history     # all revisions, newest first
$C run --rm migrate alembic check       # do the models and the schema agree?
```

### Rules for every release that contains a migration

1. **Read the migration file** before releasing. Additive changes (new table, new column that allows empty values, new index) are safe. Anything that drops or renames a table or column, changes a column's type, or rewrites data is **destructive**.
2. **Rehearse it on staging first**, against staging's own database, using the same release command.
3. **A destructive migration is never run on production without your explicit approval and a verified backup** (a backup that was restored into a scratch database, not merely created). This is a hard rule of this project.
4. Prefer two-step changes for anything destructive: release 1 stops using the old column; a later release removes it. Then the previous application version always works with the current schema, and a rollback never needs a database change.
5. Large tables: creating an index locks writes to that table while it builds. Autowok's tables are small at launch; revisit before adding indexes to tables with millions of rows.

All twelve existing migrations are additive when applied (they only create tables, columns, constraints and indexes).

## Rolling back a migration

**Default answer: do not.** Roll back the application instead ([ROLLBACK_PROCEDURE.md](ROLLBACK_PROCEDURE.md)). Because migrations are additive, the previous application version runs correctly against the newer schema; the extra tables or columns are simply unused.

Revert the schema only when the new schema itself breaks the old version. Then:

```sh
$C run --rm backup                              # a backup of the current state first
$C run --rm migrate alembic downgrade -1        # run with the NEW image: it contains the migration being reverted
```

**Downgrading can destroy data.** A downgrade removes whatever the migration added, including the rows in it:

| Migration | Downgrade removes |
|---|---|
| `0012` index optimization | Indexes only. No data loss. Tested. |
| `0011` agents | All AI agent workflows and their history |
| `0010` automations | All automations, their runs, notifications and tasks |
| `0009` analytics | All collected analytics |
| `0008` scheduling | All scheduled posts |
| `0007` media and publishing | All media records and publishing history |
| `0001`–`0006` | Accounts, workspaces, brands, research, content |

So only the newest migration is ever a candidate for downgrade, only right after it was applied, and for anything other than `0012`-style index changes you need explicit approval. If data was already damaged, restore the pre-release backup into a new database instead ([BACKUP_AND_RECOVERY.md](BACKUP_AND_RECOVERY.md#restore-procedure)).

## Using a managed PostgreSQL service

Optional ([HOSTING_COMPARISON.md](HOSTING_COMPARISON.md#option-2-alternative-the-same-server-with-a-managed-database)). The application code does not change. This procedure is **written but not tested**; rehearse it on staging.

1. Create a PostgreSQL 16 database at the provider, in the region nearest the server. Require TLS.
2. In `docker-compose.prod.yml`, in the `x-backend-env` block, delete the `DATABASE_URL:` line; delete the `postgres` service and the `depends_on: postgres` entries; point the `backup` service's `PGHOST`, `PGUSER`, `PGPASSWORD`, `PGDATABASE` at the managed database and move it off the internal network so it can reach the provider.
3. In `.env.production` set `DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require`.
4. Use the provider's **direct** connection address for migrations. If the provider offers a "pooled" address (PgBouncer in transaction mode), it can be used by the API, but check the provider's notes for prepared statements first.
5. Lower `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` if the plan's connection limit is small.
6. Keep running Autowok's own backup as well: an independent copy protects against a mistake in the provider account.

## What was tested, and where

| Test | Where | Result |
|---|---|---|
| All 12 migrations from an empty database | Throwaway local PostgreSQL 16 container, 2026-11-17 | Applied; 48 tables; revision `20261116_0012` |
| Models match the schema (`alembic check`) | Same | No drift |
| Newest migration is reversible (`downgrade -1`, then `upgrade head`) | Same | Pass; no invalid indexes |
| Migrations through the production `migrate` job, on the private network, with production settings | Local rehearsal of the production stack, 2026-11-17 | Pass |
| A second release against a database that already has a schema: backup, then migrate (nothing new to apply), then start | Same | Pass |
| Same checks on every change | GitHub Actions `backend-integration` job | Defined; **its results on GitHub have not been confirmed from this workstation** |

Not tested: any migration against a staging or production database (neither exists), migrations on a large data set, and the managed-database procedure.

#!/bin/sh
# Restore a backup set into a database, then compare row counts with the manifest.
#
# Usage: restore.sh <backup set directory> <target database name>
#
# Safety rules (the script refuses to continue otherwise):
#   * The target database must NOT already exist. The script creates it and
#     restores into it; it never drops, truncates or overwrites anything.
#   * To replace a live database, restore to a new name first, verify it, then
#     switch the application to it (docs/backup-recovery.md). That switch is a
#     deliberate, manual step and is not done here.
#
# Environment: PGHOST PGUSER PGPASSWORD (a role allowed to create databases),
#   PGDATABASE (any existing database to connect through, default "postgres"),
#   BACKUP_PASSPHRASE (when the set is encrypted),
#   RESTORE_MEDIA_DIR (optional: an EMPTY directory to extract media into).
set -eu

SET="${1:?usage: restore.sh <backup set directory> <target database name>}"
TARGET_DB="${2:?usage: restore.sh <backup set directory> <target database name>}"
: "${PGHOST:?}" "${PGUSER:?}"
ADMIN_DB="${PGDATABASE:-postgres}"
command -v openssl >/dev/null 2>&1 || apk add --no-cache openssl >/dev/null 2>&1 || true

case "$TARGET_DB" in
  *[!a-z0-9_]*|"") echo "Target database name may contain only a-z, 0-9 and _." >&2; exit 2 ;;
esac
EXISTS="$(psql -d "$ADMIN_DB" -Atc "select 1 from pg_database where datname = '$TARGET_DB'")"
if [ "$EXISTS" = "1" ]; then
  echo "Database \"$TARGET_DB\" already exists. Refusing to restore over existing data." >&2
  echo "Choose a new name, for example ${TARGET_DB}_restore_$(date -u +%Y%m%d)." >&2
  exit 2
fi

echo "Verifying checksums"
( cd "$SET" && sha256sum -c SHA256SUMS )

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
if [ -f "$SET/database.dump.enc" ]; then
  : "${BACKUP_PASSPHRASE:?BACKUP_PASSPHRASE is required for an encrypted backup}"
  openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_PASSPHRASE -in "$SET/database.dump.enc" -out "$WORK/database.dump"
else
  cp "$SET/database.dump" "$WORK/database.dump"
fi

echo "Creating database $TARGET_DB and restoring"
STARTED="$(date +%s)"
psql -d "$ADMIN_DB" -v ON_ERROR_STOP=1 -qc "create database \"$TARGET_DB\""
pg_restore --dbname "$TARGET_DB" --no-owner --no-privileges --exit-on-error --jobs 2 "$WORK/database.dump"
echo "Restore finished in $(( $(date +%s) - STARTED )) seconds"

echo "Comparing row counts with the manifest"
FAILED=0
COMPARED=0
while IFS='=' read -r table expected; do
  case "$table" in ""|created_utc|database|server_version|schema_revision|tables_in_dump|encrypted|media|media_files|---*) continue ;; esac
  actual="$(psql -d "$TARGET_DB" -Atc "select count(*) from \"$table\"" 2>/dev/null || echo missing)"
  COMPARED=$((COMPARED + 1))
  if [ "$actual" != "$expected" ]; then
    echo "MISMATCH $table: backup=$expected restored=$actual" >&2
    FAILED=1
  fi
done < "$SET/MANIFEST"
[ "$COMPARED" -gt 0 ] || { echo "No tables were compared; the manifest is incomplete." >&2; exit 3; }
[ "$FAILED" = "0" ] || { echo "Row counts differ. The restored database is left in place for inspection." >&2; exit 3; }
echo "Row counts match for $COMPARED tables"
echo "Schema revision: $(psql -d "$TARGET_DB" -Atc 'select version_num from alembic_version')"

if [ -n "${RESTORE_MEDIA_DIR:-}" ]; then
  [ -d "$RESTORE_MEDIA_DIR" ] || mkdir -p "$RESTORE_MEDIA_DIR"
  if [ -n "$(ls -A "$RESTORE_MEDIA_DIR")" ]; then
    echo "RESTORE_MEDIA_DIR is not empty. Refusing to extract over existing files." >&2
    exit 2
  fi
  if [ -f "$SET/media.tar.gz.enc" ]; then
    openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_PASSPHRASE -in "$SET/media.tar.gz.enc" | tar -xzf - -C "$RESTORE_MEDIA_DIR"
  elif [ -f "$SET/media.tar.gz" ]; then
    tar -xzf "$SET/media.tar.gz" -C "$RESTORE_MEDIA_DIR"
  fi
  echo "Media extracted: $(find "$RESTORE_MEDIA_DIR" -type f | wc -l) files"
fi
echo "OK: $SET restored into database $TARGET_DB"

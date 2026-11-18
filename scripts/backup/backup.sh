#!/bin/sh
# Autowok backup: PostgreSQL dump + media archive, encrypted, with checksums.
#
# Required environment:
#   PGHOST PGUSER PGPASSWORD PGDATABASE   connection to the database to back up
#   BACKUP_DIR                            where backups are written (mount an off-host location)
#   BACKUP_PASSPHRASE                     encryption passphrase (see below)
# Optional:
#   MEDIA_DIR                             media storage directory (skipped if unset or missing)
#   BACKUP_RETENTION_DAYS                 delete backup sets older than this (default 14, 0 = keep all)
#   BACKUP_ALLOW_UNENCRYPTED=1            allow running without a passphrase (testing only)
#
# Output: $BACKUP_DIR/<UTC timestamp>/
#   database.dump[.enc]   pg_dump custom format (compressed, restorable with pg_restore)
#   media.tar.gz[.enc]    media files
#   SHA256SUMS            checksums of the files above
#   MANIFEST              what was backed up, when, and table row counts
#
# Encryption: AES-256-CBC with a PBKDF2-derived key (openssl). The passphrase
# must be stored somewhere other than the backups themselves.
# This script only reads from the database. It never modifies or deletes data.
set -eu

: "${PGHOST:?}" "${PGUSER:?}" "${PGDATABASE:?}" "${BACKUP_DIR:?}"
RETENTION="${BACKUP_RETENTION_DAYS:-14}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARGET="$BACKUP_DIR/$STAMP"

if [ -z "${BACKUP_PASSPHRASE:-}" ] && [ "${BACKUP_ALLOW_UNENCRYPTED:-0}" != "1" ]; then
  echo "BACKUP_PASSPHRASE is not set. Refusing to write an unencrypted backup." >&2
  exit 2
fi
if [ -n "${BACKUP_PASSPHRASE:-}" ] && ! command -v openssl >/dev/null 2>&1; then
  # Works only where the container has internet access; the production "backup"
  # service has none and uses an image that already contains openssl.
  apk add --no-cache openssl >/dev/null 2>&1 || { echo "openssl is required for encryption and is not installed in this image." >&2; exit 2; }
fi

umask 077
mkdir -p "$TARGET"
cleanup() { [ "${OK:-0}" = "1" ] || { echo "Backup failed; removing incomplete set $TARGET" >&2; rm -rf "$TARGET"; }; }
trap cleanup EXIT

encrypt() { # encrypt <file> : replaces it with <file>.enc
  if [ -n "${BACKUP_PASSPHRASE:-}" ]; then
    openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass env:BACKUP_PASSPHRASE -in "$1" -out "$1.enc"
    rm -f "$1"
  fi
}

echo "[$(date -u +%H:%M:%S)] Dumping database $PGDATABASE from $PGHOST"
pg_dump --format=custom --compress=6 --no-owner --no-privileges --file "$TARGET/database.dump"
# The dump must be readable before it is trusted.
pg_restore --list "$TARGET/database.dump" > "$TARGET/.toc"
TABLES="$(grep -c ' TABLE DATA ' "$TARGET/.toc" || true)"
rm -f "$TARGET/.toc"
[ "$TABLES" -gt 0 ] || { echo "The dump contains no table data." >&2; exit 3; }

{
  echo "created_utc=$STAMP"
  echo "database=$PGDATABASE"
  echo "server_version=$(psql -Atc 'show server_version')"
  echo "schema_revision=$(psql -Atc 'select version_num from alembic_version' 2>/dev/null || echo unknown)"
  echo "tables_in_dump=$TABLES"
  echo "encrypted=$([ -n "${BACKUP_PASSPHRASE:-}" ] && echo yes || echo no)"
  echo "--- row counts"
  psql -Atc "select format('%s=%s', c.relname, (xpath('/row/n/text()', query_to_xml(format('select count(*) as n from %I', c.relname), false, true, '')))[1]::text) from pg_class c join pg_namespace n on n.oid = c.relnamespace where c.relkind = 'r' and n.nspname = 'public' order by 1"
} > "$TARGET/MANIFEST"
encrypt "$TARGET/database.dump"

if [ -n "${MEDIA_DIR:-}" ] && [ -d "$MEDIA_DIR" ]; then
  echo "[$(date -u +%H:%M:%S)] Archiving media from $MEDIA_DIR"
  tar -czf "$TARGET/media.tar.gz" -C "$MEDIA_DIR" .
  echo "media_files=$(tar -tzf "$TARGET/media.tar.gz" | grep -vc '/$' || true)" >> "$TARGET/MANIFEST"
  encrypt "$TARGET/media.tar.gz"
else
  echo "media=skipped (MEDIA_DIR not set or missing)" >> "$TARGET/MANIFEST"
fi

( cd "$TARGET" && sha256sum database.dump* media.tar.gz* 2>/dev/null > SHA256SUMS )
OK=1
echo "[$(date -u +%H:%M:%S)] Backup written to $TARGET"
ls -l "$TARGET"

if [ "$RETENTION" -gt 0 ] 2>/dev/null; then
  # Only directories named like a timestamp are ever removed.
  find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '20??????T??????Z' -mtime "+$RETENTION" -print -exec rm -rf {} \; | sed 's/^/Removed expired backup: /'
fi

#!/bin/sh
# Verify a backup set without restoring it: checksums, decryption and that the
# dump is a readable PostgreSQL archive.
#
# Usage: verify.sh <backup set directory>
# Environment: BACKUP_PASSPHRASE (when the set is encrypted)
set -eu

SET="${1:?usage: verify.sh <backup set directory>}"
[ -f "$SET/SHA256SUMS" ] || { echo "Not a backup set: $SET" >&2; exit 2; }
command -v openssl >/dev/null 2>&1 || apk add --no-cache openssl >/dev/null 2>&1 || true

echo "Checking checksums"
( cd "$SET" && sha256sum -c SHA256SUMS )

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
if [ -f "$SET/database.dump.enc" ]; then
  : "${BACKUP_PASSPHRASE:?BACKUP_PASSPHRASE is required for an encrypted backup}"
  openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_PASSPHRASE -in "$SET/database.dump.enc" -out "$WORK/database.dump"
else
  cp "$SET/database.dump" "$WORK/database.dump"
fi
TABLES="$(pg_restore --list "$WORK/database.dump" | grep -c ' TABLE DATA ' || true)"
[ "$TABLES" -gt 0 ] || { echo "The dump is not readable or contains no data." >&2; exit 3; }
echo "Dump is readable: $TABLES tables with data"

if [ -f "$SET/media.tar.gz.enc" ]; then
  openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_PASSPHRASE -in "$SET/media.tar.gz.enc" | tar -tzf - >/dev/null
  echo "Media archive is readable"
elif [ -f "$SET/media.tar.gz" ]; then
  tar -tzf "$SET/media.tar.gz" >/dev/null
  echo "Media archive is readable"
fi
echo "OK: $SET"

#!/bin/sh
# Print a fresh set of secrets for .env.production.
#
# Usage (on the server, or on your own machine):
#   sh scripts/deploy/generate-secrets.sh
#
# Copy the printed lines into .env.production, replacing the empty lines of the
# same name. Nothing is written to disk and nothing is sent anywhere.
#
# Rules:
#   * Run it once per environment. Staging and production must NOT share secrets.
#   * The output is secret. Do not paste it into chat, email, tickets or git.
#   * Save a copy of AI_ENCRYPTION_KEY, TOKEN_ENCRYPTION_KEY, MEDIA_URL_SIGNING_SECRET
#     and BACKUP_PASSPHRASE in a password manager. Without the two encryption keys a
#     restored database cannot read saved Groq keys or Meta tokens; without the
#     passphrase the backups cannot be opened.
#
# Needs only openssl. A Fernet key is 32 random bytes in URL-safe base64, which
# is exactly what the fernet() function below produces.
set -eu

command -v openssl >/dev/null 2>&1 || { echo "openssl is required." >&2; exit 2; }

hex() { openssl rand -hex 32; }
fernet() { openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n'; }

cat <<EOF
# --- generated $(date -u +%Y-%m-%dT%H:%M:%SZ) by scripts/deploy/generate-secrets.sh ---
POSTGRES_PASSWORD=$(hex)
REDIS_PASSWORD=$(hex)
AI_ENCRYPTION_KEY=$(fernet)
TOKEN_ENCRYPTION_KEY=$(fernet)
MEDIA_URL_SIGNING_SECRET=$(hex)
METRICS_TOKEN=$(hex)
META_OAUTH_STATE_SECRET=$(hex)
BACKUP_PASSPHRASE=$(hex)
EOF

#!/bin/sh
# Check an Autowok staging/production configuration BEFORE anything is started.
#
# Usage (from the directory that holds docker-compose.prod.yml):
#   sh scripts/deploy/preflight.sh                 # checks ./.env.production
#   sh scripts/deploy/preflight.sh path/to/file    # checks another file (static checks only)
#
# What it does:
#   1. Static checks on the file: required values present, long enough, not
#      placeholders, consistent with each other, not shared between settings.
#   2. "docker compose config" (when Docker is available).
#   3. Loads the configuration with the application's own start-up checks, in
#      the backend image, without starting any service (when the image exists).
#
# It never prints a configured value, only the NAME of a setting and the problem.
# It changes nothing. Exit status: 0 = ready, 1 = problems found, 2 = cannot run.
#
# Environment:
#   PREFLIGHT_ALLOW_PLACEHOLDERS=1   accept example.com addresses (CI only)
#   PREFLIGHT_SKIP_DOCKER=1          static checks only
set -eu

ENV_FILE="${1:-.env.production}"
[ -f "$ENV_FILE" ] || { echo "Configuration file not found: $ENV_FILE" >&2; exit 2; }

ERRORS=0
WARNINGS=0
fail() { ERRORS=$((ERRORS + 1)); echo "  FAIL  $*"; }
warn() { WARNINGS=$((WARNINGS + 1)); echo "  WARN  $*"; }
pass() { echo "  ok    $*"; }

# Value of KEY in the file: last assignment wins; inline comments, surrounding
# quotes, trailing spaces and Windows line endings are removed.
get() {
  sed -n "s/^[[:space:]]*$1=//p" "$ENV_FILE" | tail -n 1 | tr -d '\r' \
    | sed -e 's/[[:space:]]#.*$//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
          -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/"
}
len() { printf '%s' "$1" | wc -c | tr -d ' '; }

echo "Checking $ENV_FILE"

# --- the file itself ---------------------------------------------------------
if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if git ls-files --error-unmatch "$ENV_FILE" >/dev/null 2>&1; then
    fail "$ENV_FILE is tracked by git. Remove it from the repository and rotate every secret in it."
  else
    pass "not tracked by git"
  fi
fi
case "$(uname -s 2>/dev/null || echo unknown)" in
  Linux|Darwin)
    MODE="$(stat -c %a "$ENV_FILE" 2>/dev/null || stat -f %Lp "$ENV_FILE" 2>/dev/null || echo "")"
    case "$MODE" in
      600|400) pass "readable only by its owner" ;;
      "") : ;;
      *) warn "file mode is $MODE; run: chmod 600 $ENV_FILE" ;;
    esac ;;
esac

# --- environment and public address -----------------------------------------
[ "$(get APP_ENV)" = "production" ] && pass "APP_ENV is production" \
  || fail "APP_ENV must be 'production' (staging uses 'production' too, so it runs the same safety checks)"

SITE="$(get SITE_ADDRESS)"; ORIGIN="$(get PUBLIC_ORIGIN)"; HOSTS="$(get ALLOWED_HOSTS)"; MAIL="$(get ACME_EMAIL)"
for name in SITE_ADDRESS PUBLIC_ORIGIN ALLOWED_HOSTS ACME_EMAIL; do
  [ -n "$(get "$name")" ] || fail "$name is empty"
done
if [ -n "$SITE" ] && [ -n "$ORIGIN" ]; then
  [ "$ORIGIN" = "https://$SITE" ] && pass "PUBLIC_ORIGIN is https:// + SITE_ADDRESS" \
    || fail "PUBLIC_ORIGIN must be exactly https:// followed by SITE_ADDRESS (no path, no trailing slash)"
  case ",$HOSTS," in
    *",$SITE,"*) pass "ALLOWED_HOSTS contains SITE_ADDRESS" ;;
    *) fail "ALLOWED_HOSTS must contain SITE_ADDRESS" ;;
  esac
fi
if [ "${PREFLIGHT_ALLOW_PLACEHOLDERS:-0}" != "1" ]; then
  for name in SITE_ADDRESS PUBLIC_ORIGIN ALLOWED_HOSTS ACME_EMAIL META_REDIRECT_URI; do
    case "$(get "$name")" in
      *example.com*|*example.org*) fail "$name still contains the example.com placeholder" ;;
    esac
  done
  case "$SITE" in
    localhost|127.*) warn "SITE_ADDRESS is local: the proxy will use a self-signed certificate (fine for a local rehearsal only)" ;;
  esac
fi
case "$MAIL" in *@*.*) : ;; "") : ;; *) fail "ACME_EMAIL is not an email address" ;; esac

# --- secrets: present, long enough, safe inside a URL, and all different --------
check_hex_secret() { # name minimum-length url-safe(yes/no)
  value="$(get "$1")"
  if [ -z "$value" ]; then fail "$1 is empty"; return; fi
  if [ "$(len "$value")" -lt "$2" ]; then fail "$1 is shorter than $2 characters"; return; fi
  if [ "$3" = "yes" ]; then
    case "$value" in
      *[!A-Za-z0-9]*) fail "$1 may contain only letters and digits (it is placed inside a connection URL); use: openssl rand -hex 32"; return ;;
    esac
  fi
  pass "$1 is set"
}
check_fernet() { # name
  value="$(get "$1")"
  if [ -z "$value" ]; then fail "$1 is empty"; return; fi
  if printf '%s' "$value" | grep -Eq '^[A-Za-z0-9_-]{43}=$'; then pass "$1 looks like a Fernet key"
  else fail "$1 is not a Fernet key (44 characters of URL-safe base64); see scripts/deploy/generate-secrets.sh"; fi
}
check_hex_secret POSTGRES_PASSWORD 32 yes
check_hex_secret REDIS_PASSWORD 32 yes
check_fernet AI_ENCRYPTION_KEY
check_fernet TOKEN_ENCRYPTION_KEY
check_hex_secret MEDIA_URL_SIGNING_SECRET 32 no
check_hex_secret BACKUP_PASSPHRASE 32 no
case "$(get METRICS_ENABLED)" in
  false|False|0) warn "METRICS_ENABLED is off: /metrics and the worker-alive check will not be available" ;;
  *) check_hex_secret METRICS_TOKEN 24 no ;;
esac
case "$(get POSTGRES_PASSWORD)" in autowok|postgres|password|changeme) fail "POSTGRES_PASSWORD is a known default" ;; esac

SECRET_NAMES="POSTGRES_PASSWORD REDIS_PASSWORD AI_ENCRYPTION_KEY TOKEN_ENCRYPTION_KEY MEDIA_URL_SIGNING_SECRET METRICS_TOKEN META_OAUTH_STATE_SECRET META_APP_SECRET BACKUP_PASSPHRASE"
DUPLICATES=0
for a in $SECRET_NAMES; do
  va="$(get "$a")"; [ -n "$va" ] || continue
  for b in $SECRET_NAMES; do
    # Compare each pair once (a < b alphabetically).
    [ "$(printf '%s\n%s\n' "$a" "$b" | sort | head -n 1)" = "$a" ] && [ "$a" != "$b" ] || continue
    if [ "$va" = "$(get "$b")" ]; then fail "$a and $b have the same value; every secret must be different"; DUPLICATES=1; fi
  done
done
[ "$DUPLICATES" = "0" ] && pass "no secret is reused for two settings"
for prev in AI_ENCRYPTION_KEY_PREVIOUS TOKEN_ENCRYPTION_KEY_PREVIOUS; do
  [ -z "$(get "$prev")" ] || warn "$prev is set: correct only while a key rotation is in progress"
done

# --- Meta ----------------------------------------------------------------------
if [ -n "$(get META_APP_ID)" ]; then
  [ -n "$(get META_APP_SECRET)" ] || fail "META_APP_SECRET is empty but META_APP_ID is set"
  check_hex_secret META_OAUTH_STATE_SECRET 32 no
  if [ "$(get META_REDIRECT_URI)" = "$ORIGIN/api/v1/oauth/meta/callback" ]; then
    pass "META_REDIRECT_URI matches PUBLIC_ORIGIN (it must also be listed, character for character, in the Meta app)"
  else
    fail "META_REDIRECT_URI must be exactly PUBLIC_ORIGIN + /api/v1/oauth/meta/callback"
  fi
  VERSION="$(get META_GRAPH_API_VERSION)"
  if [ -n "$VERSION" ] && ! printf '%s' "$VERSION" | grep -Eq '^v[0-9]+\.[0-9]+$'; then
    fail "META_GRAPH_API_VERSION must look like v26.0"
  fi
else
  warn "META_APP_ID is empty: connecting and publishing to Facebook/Instagram will be unavailable"
fi

# --- Groq and research ------------------------------------------------------------
[ -n "$(get GROQ_API_KEY)" ] && pass "GROQ_API_KEY is set (platform key, server side only)" \
  || warn "GROQ_API_KEY is empty: each workspace must save its own Groq key in Settings > AI"
case "$(get GROQ_API_KEY)" in ""|gsk_*) : ;; *) warn "GROQ_API_KEY does not start with gsk_; check that it is a Groq key" ;; esac
case "$(get RESEARCH_SEARCH_PROVIDER)" in
  "") warn "RESEARCH_SEARCH_PROVIDER is empty: research runs will report that no search provider is configured" ;;
  groq|tavily|brave)
    [ -n "$(get RESEARCH_SEARCH_API_KEY)" ] && pass "RESEARCH_SEARCH_PROVIDER is supported and has a key" \
      || fail "RESEARCH_SEARCH_API_KEY is empty but RESEARCH_SEARCH_PROVIDER is set" ;;
  *) fail "RESEARCH_SEARCH_PROVIDER must be groq, tavily or brave (or empty)" ;;
esac

# --- backups ------------------------------------------------------------------------
case "$(get BACKUP_HOST_DIR)" in
  ""|./backups|backups) warn "BACKUP_HOST_DIR is on the server's own disk: copy backups off the server (docs/deployment/BACKUP_AND_RECOVERY.md)" ;;
esac

# --- Docker checks ---------------------------------------------------------------
if [ "${PREFLIGHT_SKIP_DOCKER:-0}" = "1" ] || ! command -v docker >/dev/null 2>&1; then
  echo "  --    Docker checks skipped"
elif [ ! -f docker-compose.prod.yml ]; then
  echo "  --    docker-compose.prod.yml is not in this directory; Docker checks skipped"
else
  if docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml config -q 2>/tmp/autowok-preflight.$$; then
    pass "docker-compose.prod.yml accepts this configuration"
  else
    fail "docker compose rejected the configuration: $(head -n 3 /tmp/autowok-preflight.$$ | tr '\n' ' ')"
  fi
  rm -f /tmp/autowok-preflight.$$
  IMAGE="${BACKEND_IMAGE:-autowok-backend:local}"
  if [ "$ENV_FILE" != ".env.production" ] && [ "$ENV_FILE" != "./.env.production" ]; then
    echo "  --    application start-up check skipped (it only runs for ./.env.production)"
  elif ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "  --    application start-up check skipped (image $IMAGE is not on this machine yet)"
  else
    # Loads the settings exactly as the API and worker do. No service is started,
    # and the application's message names settings, never values.
    if OUT="$(docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml run --rm --no-deps -T backend \
        python -c 'from app.core.config import get_settings; get_settings(); print("configuration accepted")' 2>&1)"; then
      pass "the application accepts this configuration"
    else
      fail "the application refused this configuration: $(printf '%s' "$OUT" | grep -E 'ConfigurationError|Unsafe production' | tail -n 1 | cut -c1-600)"
    fi
  fi
fi

echo
if [ "$ERRORS" -gt 0 ]; then
  echo "NOT READY: $ERRORS problem(s), $WARNINGS warning(s). Fix the FAIL lines and run this again."
  exit 1
fi
echo "READY: no problems, $WARNINGS warning(s)."

#!/bin/sh
# Release, roll back or inspect an Autowok staging/production stack.
# Runs ON THE SERVER, from the directory that holds docker-compose.prod.yml and
# .env.production. The GitHub workflows call it over SSH; a person can run the
# same commands by hand.
#
#   sh scripts/deploy/deploy.sh release <backend image> <frontend image> [--skip-migrations]
#   sh scripts/deploy/deploy.sh rollback
#   sh scripts/deploy/deploy.sh status
#
# "release" does, in order, and stops at the first failure:
#   1. pull        the two images (skipped for images that exist only locally)
#   2. preflight   configuration checks (scripts/deploy/preflight.sh), including
#                  the application's own start-up checks in the new image
#   3. backup      encrypted database + media backup (skipped only when the
#                  database is still empty, that is on the very first release)
#   4. migrate     alembic upgrade head, as a one-shot job
#   5. start       docker compose up -d
#   6. verify      waits for /api/v1/ready and a healthy worker
#   7. record      writes release.env (and keeps the old one as release.previous.env)
#
# "rollback" starts the images recorded in release.previous.env. It does NOT
# touch the database: see docs/deployment/ROLLBACK_PROCEDURE.md before reverting
# a migration or restoring a backup.
#
# release.env holds only the two image names (no secrets). Use it for every
# manual Compose command so the stack keeps running the released images:
#   docker compose --env-file .env.production --env-file release.env -f docker-compose.prod.yml ps
#
# Optional environment:
#   AUTOWOK_COMPOSE_OVERRIDE   path of an extra Compose file (for example a
#                              staging override); applied after docker-compose.prod.yml
#   DEPLOY_READY_TIMEOUT       seconds to wait for readiness (default 180)
set -eu

ENV_FILE=".env.production"
RELEASE_FILE="release.env"
PREVIOUS_FILE="release.previous.env"
READY_TIMEOUT="${DEPLOY_READY_TIMEOUT:-180}"

[ -f docker-compose.prod.yml ] || { echo "Run this from the directory that holds docker-compose.prod.yml." >&2; exit 2; }
[ -f "$ENV_FILE" ] || { echo "$ENV_FILE is missing. Create it from .env.production.example first." >&2; exit 2; }

compose() {
  if [ -n "${AUTOWOK_COMPOSE_OVERRIDE:-}" ]; then
    docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml -f "$AUTOWOK_COMPOSE_OVERRIDE" "$@"
  else
    docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml "$@"
  fi
}
log() { echo "[$(date -u +%H:%M:%S)] $*"; }

read_release() { # file -> sets BACKEND_IMAGE and FRONTEND_IMAGE
  BACKEND_IMAGE="$(sed -n 's/^BACKEND_IMAGE=//p' "$1" | tail -n 1)"
  FRONTEND_IMAGE="$(sed -n 's/^FRONTEND_IMAGE=//p' "$1" | tail -n 1)"
  [ -n "$BACKEND_IMAGE" ] && [ -n "$FRONTEND_IMAGE" ] || { echo "$1 does not name both images." >&2; exit 2; }
  export BACKEND_IMAGE FRONTEND_IMAGE
}

write_release() { # file
  umask 077
  {
    echo "# Written by scripts/deploy/deploy.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ). Image names only, no secrets."
    echo "BACKEND_IMAGE=$BACKEND_IMAGE"
    echo "FRONTEND_IMAGE=$FRONTEND_IMAGE"
  } > "$1"
}

wait_until_ready() {
  log "Waiting up to ${READY_TIMEOUT}s for the API to report ready and the worker to be healthy"
  elapsed=0
  while [ "$elapsed" -lt "$READY_TIMEOUT" ]; do
    if compose exec -T backend python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/ready', timeout=4).status == 200 else 1)" >/dev/null 2>&1 \
      && compose exec -T worker python -m app.worker healthcheck >/dev/null 2>&1; then
      log "Ready: database and Redis answer, worker heartbeat is fresh"
      return 0
    fi
    sleep 5
    elapsed=$((elapsed + 5))
  done
  return 1
}

database_has_schema() {
  compose up -d postgres >/dev/null
  n=0
  until compose exec -T postgres sh -c 'pg_isready -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; do
    n=$((n + 1)); [ "$n" -lt 30 ] || { echo "PostgreSQL did not become ready." >&2; exit 1; }
    sleep 2
  done
  count="$(compose exec -T postgres sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -Atc \"select count(*) from information_schema.tables where table_schema = 'public' and table_name = 'alembic_version'\"" | tr -d '[:space:]')"
  [ "$count" = "1" ]
}

command="${1:-}"
case "$command" in
  release)
    NEW_BACKEND="${2:?usage: deploy.sh release <backend image> <frontend image> [--skip-migrations]}"
    NEW_FRONTEND="${3:?usage: deploy.sh release <backend image> <frontend image> [--skip-migrations]}"
    SKIP_MIGRATIONS="${4:-}"

    BACKEND_IMAGE="$NEW_BACKEND"; FRONTEND_IMAGE="$NEW_FRONTEND"
    export BACKEND_IMAGE FRONTEND_IMAGE

    log "Step 1/7 pull images"
    for image in "$BACKEND_IMAGE" "$FRONTEND_IMAGE"; do
      case "$image" in
        */*) docker pull -q "$image" >/dev/null ;;
        *)   docker image inspect "$image" >/dev/null 2>&1 || { echo "Local image $image does not exist. Build it first." >&2; exit 1; } ;;
      esac
    done

    # Static checks, then the application's own start-up checks in the NEW image,
    # before anything running is touched.
    log "Step 2/7 preflight"
    sh scripts/deploy/preflight.sh "$ENV_FILE"

    log "Step 3/7 backup"
    if database_has_schema; then
      compose run --rm backup
    else
      log "The database has no schema yet (first release): nothing to back up"
    fi

    log "Step 4/7 migrations"
    if [ "$SKIP_MIGRATIONS" = "--skip-migrations" ]; then
      log "Skipped on request"
    else
      compose run --rm migrate
    fi

    log "Step 5/7 start $BACKEND_IMAGE and $FRONTEND_IMAGE"
    compose up -d --no-build --remove-orphans

    log "Step 6/7 verify"
    if ! wait_until_ready; then
      echo "The new version did not become ready within ${READY_TIMEOUT}s." >&2
      compose ps >&2 || true
      if [ -f "$RELEASE_FILE" ]; then
        echo "The previous release is still recorded in $RELEASE_FILE. To return to it run:" >&2
        echo "  cp $RELEASE_FILE $PREVIOUS_FILE && sh scripts/deploy/deploy.sh rollback" >&2
      fi
      echo "Then read docs/deployment/ROLLBACK_PROCEDURE.md." >&2
      exit 1
    fi

    log "Step 7/7 record the release"
    [ -f "$RELEASE_FILE" ] && cp "$RELEASE_FILE" "$PREVIOUS_FILE"
    write_release "$RELEASE_FILE"
    log "Released. Current images are recorded in $RELEASE_FILE"
    ;;

  rollback)
    [ -f "$PREVIOUS_FILE" ] || { echo "No previous release is recorded ($PREVIOUS_FILE is missing)." >&2; exit 2; }
    read_release "$PREVIOUS_FILE"
    log "Rolling back to $BACKEND_IMAGE and $FRONTEND_IMAGE (the database is not changed)"
    compose up -d --no-build --remove-orphans
    if ! wait_until_ready; then
      echo "The previous version did not become ready either. See docs/deployment/ROLLBACK_PROCEDURE.md." >&2
      compose ps >&2 || true
      exit 1
    fi
    # The rolled-back images become the current release; the failed one is kept for reference.
    if [ -f "$RELEASE_FILE" ]; then cp "$RELEASE_FILE" release.failed.env; fi
    write_release "$RELEASE_FILE"
    log "Rolled back. The release that was replaced is recorded in release.failed.env"
    ;;

  status)
    if [ -f "$RELEASE_FILE" ]; then read_release "$RELEASE_FILE"; echo "Current release:  $BACKEND_IMAGE  $FRONTEND_IMAGE"; else echo "Current release:  none recorded"; fi
    if [ -f "$PREVIOUS_FILE" ]; then
      echo "Previous release: $(sed -n 's/^BACKEND_IMAGE=//p' "$PREVIOUS_FILE")  $(sed -n 's/^FRONTEND_IMAGE=//p' "$PREVIOUS_FILE")"
    fi
    compose ps
    ;;

  *)
    sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
    ;;
esac

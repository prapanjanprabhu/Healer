#!/usr/bin/env bash
# Automated backup/restore rehearsal (docs/backup-and-restore.md).
#
# Runs `make backup`, restores the dump into a scratch database exactly as
# `make restore` does, compares row counts for every table between the live
# `healer` database and the restored copy, then cleans up (drops the scratch
# database and deletes the dump file it made). Exits non-zero on any
# mismatch or error, so this is safe to run in CI or by hand against a
# running `make up` stack.
set -euo pipefail

# On Windows Git Bash, MSYS rewrites bare /tmp/... paths passed through to
# `docker compose exec`/`cp` into host Windows paths before Docker ever sees
# them, breaking the in-container pg_dump/pg_restore file paths below. This
# is a no-op on Linux/macOS.
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"

cd "$(dirname "$0")/.."

COMPOSE="docker compose -f docker-compose.yml --env-file .env"
PGUSER="${POSTGRES_USER:-healer}"
LIVE_DB="${POSTGRES_DB:-healer}"

echo "==> Snapshotting table row counts before the backup"
# Captured now, not after backup+restore completes, because tables like
# metrics_snapshots keep receiving writes from the live system for the
# entire duration of this script — comparing against counts taken after
# restore would spuriously fail on that ongoing drift, not on an actual
# restore defect.
TABLES="$($COMPOSE exec -T postgres psql -U "$PGUSER" -d "$LIVE_DB" -Atc \
  "select tablename from pg_tables where schemaname = 'public' order by 1" </dev/null)"
declare -A PRE_COUNTS
while IFS= read -r TABLE; do
  [ -z "$TABLE" ] && continue
  PRE_COUNTS["$TABLE"]="$($COMPOSE exec -T postgres psql -U "$PGUSER" -d "$LIVE_DB" -Atc "select count(*) from \"$TABLE\"" </dev/null)"
done <<< "$TABLES"

echo "==> Taking a backup"
BACKUP_OUTPUT="$(make backup)"
echo "$BACKUP_OUTPUT"
DUMP_FILE="$(echo "$BACKUP_OUTPUT" | sed -n 's/^backup written to //p')"
if [ -z "$DUMP_FILE" ]; then
  echo "FAIL: could not parse the backup file path from 'make backup' output" >&2
  exit 1
fi

echo "==> Restoring into a scratch database"
RESTORE_OUTPUT="$(make restore FILE="$DUMP_FILE")"
echo "$RESTORE_OUTPUT"
RESTORE_DB="$(echo "$RESTORE_OUTPUT" | sed -n 's/^restored into database \([^ ]*\).*/\1/p')"
if [ -z "$RESTORE_DB" ]; then
  echo "FAIL: could not parse the restored database name from 'make restore' output" >&2
  exit 1
fi

cleanup() {
  echo "==> Cleaning up (dropping $RESTORE_DB, removing $DUMP_FILE)"
  $COMPOSE exec -T postgres dropdb -U "$PGUSER" --if-exists "$RESTORE_DB" </dev/null || true
  rm -f "$DUMP_FILE"
}
trap cleanup EXIT

echo "==> Comparing restored row counts against the pre-backup snapshot"
FAILED=0
while IFS= read -r TABLE; do
  [ -z "$TABLE" ] && continue
  PRE_COUNT="${PRE_COUNTS[$TABLE]}"
  RESTORE_COUNT="$($COMPOSE exec -T postgres psql -U "$PGUSER" -d "$RESTORE_DB" -Atc "select count(*) from \"$TABLE\"" </dev/null)"
  if [ "$PRE_COUNT" != "$RESTORE_COUNT" ]; then
    echo "FAIL: $TABLE — pre-backup=$PRE_COUNT restored=$RESTORE_COUNT" >&2
    FAILED=1
  else
    echo "OK:   $TABLE — $PRE_COUNT rows"
  fi
done <<< "$TABLES"

if [ "$FAILED" -ne 0 ]; then
  echo "==> Backup/restore rehearsal FAILED: row counts diverged" >&2
  exit 1
fi

echo "==> Backup/restore rehearsal PASSED: every table matched"

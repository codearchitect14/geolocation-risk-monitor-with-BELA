#!/usr/bin/env bash
# Backup and restore drill for the development cluster (see docs/runbook.md).
#
#   infra/ops/backup_drill.sh [backup-dir]
#
# 1. dumps the application database in custom format (compressed, restorable in parallel; FULL=1 includes place_embeddings)
# 2. restores the dump into a scratch database
# 3. compares row counts of the main tables, checks the extensions, and verifies the audit hash chain in the restored copy
# 4. drops the scratch database
# Prints a JSON summary with the timings. The source database is only read.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PGBIN="${PGBIN:-/opt/homebrew/opt/postgresql@17/bin}"
PGDATA="${PGDATA:-$ROOT/.local/pgdata}"
PGPORT="${PGPORT:-5433}"
DB_NAME="${DB_NAME:-meridian}"
DB_USER="${DB_USER:-meridian}"
SCRATCH="${SCRATCH_DB:-meridian_restore_drill}"
OUT="${1:-$ROOT/.local/backups}"
JOBS="${JOBS:-4}"
# place_embeddings is 10 GB of derived data that `make etl-embed` rebuilds. Excluding its rows keeps routine backups small
# and the restore fast; set FULL=1 to include everything (the index rebuild then takes much longer).
EXCLUDE=(--exclude-table-data=place_embeddings)
[ "${FULL:-0}" = "1" ] && EXCLUDE=()
mkdir -p "$OUT"
chmod 700 "$OUT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP="$OUT/$DB_NAME-$STAMP.dump"
export PGHOST="$PGDATA" PGPORT PGUSER="$DB_USER"

now() { python3 -c 'import time; print(time.time())'; }
secs() { python3 -c "print(round($2 - $1, 1))"; }

T0=$(now)
"$PGBIN/pg_dump" --format=custom --compress=zstd:3 --no-owner "${EXCLUDE[@]}" --file "$DUMP" "$DB_NAME"
T1=$(now)
"$PGBIN/dropdb" --if-exists "$SCRATCH"
"$PGBIN/createdb" "$SCRATCH"
# Extensions need superuser rights; the restore creates them from the dump. Ownership is not restored (--no-owner above).
"$PGBIN/pg_restore" --dbname "$SCRATCH" --jobs "$JOBS" --no-owner "$DUMP" 2> "$OUT/restore-$STAMP.log" || true
T2=$(now)

count() { "$PGBIN/psql" -X -A -t -d "$1" -c "SELECT count(*) FROM $2"; }
TABLES="places place_aliases events event_sources tenants users assets exposures alerts audit_log"
ROWS="{"
OK=true
for t in $TABLES; do
  a=$(count "$DB_NAME" "$t" 2>/dev/null || echo -1)
  b=$(count "$SCRATCH" "$t" 2>/dev/null || echo -2)
  [ "$a" = "$b" ] || OK=false
  ROWS="$ROWS\"$t\": [$a, $b],"
done
ROWS="${ROWS%,}}"
EXT=$("$PGBIN/psql" -X -A -t -d "$SCRATCH" -c "SELECT string_agg(extname, ',' ORDER BY extname) FROM pg_extension WHERE extname IN ('postgis','vector','pg_trgm')")
CHAIN=$("$PGBIN/psql" -X -A -t -d "$SCRATCH" -c "SELECT first_bad_id IS NULL FROM audit_verify()" 2>/dev/null || echo "unknown")
"$PGBIN/dropdb" "$SCRATCH"
SIZE=$(du -h "$DUMP" | cut -f1)
cat <<JSON
{"dump": "$DUMP", "dump_size": "$SIZE", "dump_seconds": $(secs "$T0" "$T1"), "restore_seconds": $(secs "$T1" "$T2"),
 "row_counts_source_vs_restored": $ROWS, "row_counts_match": $OK, "extensions_restored": "$EXT", "audit_chain_intact": "$CHAIN"}
JSON

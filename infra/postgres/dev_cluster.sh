#!/usr/bin/env bash
# Local PostgreSQL 17 cluster with PostGIS and pgvector, for development without Docker.
# Data lives in .local/pgdata (git-ignored). Listens on localhost only.
#
#   infra/postgres/dev_cluster.sh init|start|stop|status|psql|reset
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PGBIN="${PGBIN:-/opt/homebrew/opt/postgresql@17/bin}"
PGDATA="${PGDATA:-$ROOT/.local/pgdata}"
PGPORT="${PGPORT:-5433}"
DB_NAME="${DB_NAME:-meridian}"
DB_USER="${DB_USER:-meridian}"

case "${1:-}" in
  init)
    if [ -d "$PGDATA" ]; then echo "cluster already exists at $PGDATA"; exit 0; fi
    mkdir -p "$PGDATA"
    "$PGBIN/initdb" -D "$PGDATA" -E UTF8 --locale=en_US.UTF-8 --auth-local=trust --auth-host=scram-sha-256 -U postgres >/dev/null
    cat >> "$PGDATA/postgresql.conf" <<CONF
listen_addresses = 'localhost'
port = $PGPORT
unix_socket_directories = '$PGDATA'
shared_buffers = 2GB
maintenance_work_mem = 2GB
work_mem = 64MB
effective_cache_size = 8GB
max_wal_size = 8GB
synchronous_commit = off
shared_preload_libraries = 'pg_stat_statements'
pg_stat_statements.track = all
CONF
    "$PGBIN/pg_ctl" -D "$PGDATA" -l "$PGDATA/server.log" -w start >/dev/null
    "$PGBIN/psql" -h "$PGDATA" -p "$PGPORT" -U postgres -qc "CREATE ROLE $DB_USER LOGIN SUPERUSER PASSWORD '$DB_USER'"
    "$PGBIN/createdb" -h "$PGDATA" -p "$PGPORT" -U postgres -O "$DB_USER" "$DB_NAME"
    echo "created database $DB_NAME on port $PGPORT"
    ;;
  start)  "$PGBIN/pg_ctl" -D "$PGDATA" -l "$PGDATA/server.log" -w start ;;
  stop)   "$PGBIN/pg_ctl" -D "$PGDATA" -m fast stop ;;
  status) "$PGBIN/pg_ctl" -D "$PGDATA" status ;;
  psql)   shift; "$PGBIN/psql" -h "$PGDATA" -p "$PGPORT" -U "$DB_USER" "$DB_NAME" "$@" ;;
  reset)
    "$PGBIN/pg_ctl" -D "$PGDATA" -m immediate stop 2>/dev/null || true
    rm -rf "$PGDATA"
    "$0" init
    ;;
  *) echo "usage: $0 init|start|stop|status|psql|reset" >&2; exit 2 ;;
esac

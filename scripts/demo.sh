#!/usr/bin/env bash
# Bring up a seeded demonstration environment from a clean clone.
#
#   scripts/demo.sh up        install, build, seed, and start everything (what `make demo` runs)
#   scripts/demo.sh down      stop the API and the web server
#   scripts/demo.sh status    show what is running
#   scripts/demo.sh reset     stop, then delete the demo database cluster (asks first)
#
# What it does, in order: check prerequisites; create the Python environment; install web dependencies; download the small
# data files (GeoNames cities, Natural Earth boundaries) with checksum verification; create and start the local PostgreSQL
# cluster; apply migrations; build the demo place knowledge base (cities of 15,000 people or more); load the synthetic business
# history; load the recorded earthquake feed as history; create the demo tenant, accounts, and assets; build and start the API
# and the web application. Sign-in details are printed once at the end of a first run.
#
# Not part of the demo and not needed for it: the entity linking model (about 33 GB), the local language model, and the
# map tile build. News processing therefore does not run in the demo; the incidents come from the recorded feed.
# Every step is repeatable: a second run skips what exists.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
LOCAL="$ROOT/.local"
mkdir -p "$LOCAL"
API_PORT="${API_PORT:-8090}"
WEB_PORT="${WEB_PORT:-3000}"
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://meridian:meridian@localhost:5433/meridian}"
STARTED=$(date +%s)
declare -a TIMES=()
ISSUED=0
SEED_OUT=""

step() { STEP_NAME="$1"; STEP_START=$(date +%s); printf '\n==> %s\n' "$1"; }
done_step() { TIMES+=("$(printf '%-52s %4ss' "$STEP_NAME" "$(( $(date +%s) - STEP_START ))")"); }

need() { command -v "$1" > /dev/null 2>&1 || { echo "Missing prerequisite: $1. $2" >&2; exit 1; }; }

prerequisites() {
  step "Check prerequisites"
  need python3 "Install Python 3.11 or newer."
  python3 - <<'PYV' || { echo "Python 3.11 or newer is required." >&2; exit 1; }
import sys
sys.exit(0 if sys.version_info >= (3, 11) else 1)
PYV
  need node "Install Node.js 20 or newer."
  need npm "Install Node.js 20 or newer."
  need curl "Install curl."
  PGBIN="${PGBIN:-/opt/homebrew/opt/postgresql@17/bin}"
  [ -x "$PGBIN/pg_ctl" ] || { echo "PostgreSQL 17 binaries not found in $PGBIN (set PGBIN). The cluster also needs PostGIS and pgvector." >&2; exit 1; }
  export PGBIN
  done_step
}

python_env() {
  step "Python environment"
  [ -x "$PY" ] || python3 -m venv .venv
  "$PY" -c "import meridian" 2> /dev/null || .venv/bin/pip install --quiet -e ".[dev]"
  done_step
}

web_install() {
  step "Web dependencies"
  [ -d apps/web/node_modules ] || (cd apps/web && npm ci --no-audit --no-fund)
  done_step
}

download_data() {
  step "Small data files (checksum verified)"
  "$PY" data/scripts/download_geonames.py --small
  "$PY" data/scripts/download_natural_earth.py
  "$PY" data/scripts/verify_manifest.py || echo "Checksum differences are listed above; files that are not part of the demo can be ignored."
  done_step
}

database() {
  step "PostgreSQL cluster and migrations"
  infra/postgres/dev_cluster.sh init
  infra/postgres/dev_cluster.sh status > /dev/null 2>&1 || infra/postgres/dev_cluster.sh start
  (cd apps/api && PYTHONPATH=. "$PY" -m alembic upgrade head)
  done_step
}

knowledge_base() {
  step "Demo place knowledge base"
  local have
  have=$(cd apps/api && PYTHONPATH=. "$PY" -c "from meridian.db import connect; print(connect().execute('SELECT count(*) FROM places').fetchone()[0])" 2> /dev/null || echo 0)
  if [ "${have:-0}" -gt 0 ]; then
    echo "places table already holds $have rows; leaving it as it is"
  else
    (cd apps/api && PYTHONPATH=. "$PY" -m meridian.etl build --demo)
  fi
  done_step
}

demo_data() {
  step "Synthetic business history and illustrative asset portfolios"
  "$PY" data/scripts/generate_demo_business_data.py
  (cd apps/api && PYTHONPATH=. "$PY" -m meridian.business.loader)
  "$PY" data/scripts/generate_demo_assets.py
  done_step

  step "Recorded earthquake feed (history)"
  (cd apps/api && PYTHONPATH=. "$PY" -m meridian.events replay --preload 1.0)
  done_step

  step "Demo tenant, accounts, assets, and exposures"
  # The passwords exist only in this output and in the hashes in the database; they are never written to a file.
  SEED_OUT=$(cd apps/api && PYTHONPATH=. "$PY" -m meridian.demo seed --assets "${DEMO_ASSETS:-120}" 2> "$LOCAL/demo-seed.log")
  cat "$LOCAL/demo-seed.log"
  case "$SEED_OUT" in *"Demo sign-in details"*) ISSUED=1 ;; esac
  done_step
}

start_servers() {
  step "Build and start the API and the web application"
  stop_servers quiet
  # A demonstration is usually shown from one address (a projector, a shared network), so the per-address limit is raised.
  (cd apps/api && MS_ENV=development MS_COOKIE_SECURE=false MS_RATE_IP_PER_MINUTE=3000 PYTHONPATH=. nohup "$PY" -m uvicorn meridian.api.main:create_app --factory \
     --host 127.0.0.1 --port "$API_PORT" --no-server-header > "$LOCAL/api.log" 2>&1 & echo $! > "$LOCAL/api.pid")
  (cd apps/api && PYTHONPATH=. MS_ENV=development nohup "$PY" -m meridian.api.worker > "$LOCAL/worker.log" 2>&1 & echo $! > "$LOCAL/worker.pid")
  if [ "${SKIP_WEB_BUILD:-0}" != "1" ]; then
    (cd apps/web && NEXT_PUBLIC_DEMO_MODE=1 NEXT_PUBLIC_DEMO_VIEWER="demo-viewer@example.com" npm run build > "$LOCAL/web-build.log" 2>&1) \
      || { echo "Web build failed; see $LOCAL/web-build.log" >&2; exit 1; }
  fi
  (cd apps/web && MS_API_URL="http://127.0.0.1:$API_PORT" nohup npm run start -- -p "$WEB_PORT" > "$LOCAL/web.log" 2>&1 & echo $! > "$LOCAL/web.pid")
  for _ in $(seq 1 60); do
    curl -fs "http://127.0.0.1:$API_PORT/api/v1/health/ready" > /dev/null 2>&1 && curl -fs "http://127.0.0.1:$WEB_PORT/" > /dev/null 2>&1 && break
    sleep 1
  done
  curl -fs "http://127.0.0.1:$API_PORT/api/v1/health/ready" > /dev/null || { echo "API did not become ready; see $LOCAL/api.log" >&2; exit 1; }
  done_step
}

stop_servers() {
  for name in web worker api; do
    if [ -f "$LOCAL/$name.pid" ]; then
      pid=$(cat "$LOCAL/$name.pid")
      # npm starts a child; stop the whole group of children first
      pkill -P "$pid" 2> /dev/null || true
      kill "$pid" 2> /dev/null || true
      rm -f "$LOCAL/$name.pid"
    fi
  done
  [ "${1:-}" = "quiet" ] || echo "stopped"
}

summary() {
  printf '\n%s\n' "Timings"
  printf '  %s\n' "${TIMES[@]}"
  printf '  %-52s %4ss\n' "Total" "$(( $(date +%s) - STARTED ))"
  cat <<TXT

The demonstration is running:
  Web application   http://127.0.0.1:$WEB_PORT/        (sign in at /login)
  API documentation http://127.0.0.1:$API_PORT/api/docs

TXT
  if [ "${ISSUED:-0}" = "1" ]; then
    echo "$SEED_OUT"
  else
    echo "The accounts already existed; passwords are not shown again. Issue new ones with: make demo-rotate"
  fi
  cat <<TXT
Replay the recorded feed live (new incidents appear on the map):  make replay
Stop the demonstration:                                            make demo-down
Everything shown is synthetic or illustrative. Signals are situational awareness derived from public news and public data
feeds. They are not official warnings. Verify with local authorities and follow their guidance.
TXT
}

case "${1:-up}" in
  up)
    prerequisites
    python_env
    web_install
    download_data
    database
    knowledge_base
    demo_data
    start_servers
    summary
    ;;
  down) stop_servers ;;
  status)
    for name in api worker web; do
      if [ -f "$LOCAL/$name.pid" ] && kill -0 "$(cat "$LOCAL/$name.pid")" 2> /dev/null; then echo "$name: running (pid $(cat "$LOCAL/$name.pid"))"; else echo "$name: stopped"; fi
    done
    infra/postgres/dev_cluster.sh status 2>&1 | head -1
    ;;
  reset)
    read -r -p "Delete the local demo database cluster in .local/pgdata? Type yes: " answer
    [ "$answer" = "yes" ] || { echo "cancelled"; exit 1; }
    stop_servers quiet
    infra/postgres/dev_cluster.sh stop || true
    rm -rf "$LOCAL/pgdata" "$LOCAL/demo-seed.log"
    echo "deleted"
    ;;
  *) echo "usage: $0 up|down|status|reset" >&2; exit 2 ;;
esac

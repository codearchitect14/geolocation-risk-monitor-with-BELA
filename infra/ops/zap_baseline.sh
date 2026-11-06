#!/usr/bin/env bash
# OWASP ZAP baseline (passive scan plus API import and spider) without Docker, using a local ZAP install.
#
#   ZAP_HOME=.local/tools/ZAP.app/Contents/Java infra/ops/zap_baseline.sh
#
# Needs the API on 127.0.0.1:8090 (make api-up) and optionally the web app on 127.0.0.1:3000 (make web-start). Signs in as the
# local test manager account so authenticated GET endpoints are scanned too. Writes .local/zap/zap-report.json and .html.
# Where Docker is available, `make zap` runs the official baseline image instead.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ZAP_HOME="${ZAP_HOME:-$ROOT/.local/tools/ZAP.app/Contents/Java}"
API="${API_URL:-http://127.0.0.1:8090}"
WEB="${WEB_URL:-http://127.0.0.1:3000}"
EMAIL="${PERF_EMAIL:-perf-manager@example.org}"
PASSWORD="${PERF_PASSWORD:-perf passphrase 2026!}"
OUT="$ROOT/.local/zap"
mkdir -p "$OUT"
JAR="$OUT/cookies.txt"
curl -s -c "$JAR" -H 'Content-Type: application/json' -d "{\"email\": \"$EMAIL\", \"password\": \"$PASSWORD\"}" "$API/api/v1/auth/login" > /dev/null
COOKIE="$(awk '$6 ~ /^ms_(access|csrf)$/ {printf "%s=%s; ", $6, $7}' "$JAR")"
[ -n "$COOKIE" ] || { echo "sign-in failed" >&2; exit 1; }

WEB_CONTEXT=""
if curl -s -o /dev/null "$WEB"; then WEB_CONTEXT=", \"$WEB\""; fi
cat > "$OUT/plan.yaml" <<YAML
env:
  contexts:
    - name: meridian
      urls: ["$API"$WEB_CONTEXT]
      includePaths: ["$API.*"$( [ -n "$WEB_CONTEXT" ] && echo ", \"$WEB.*\"")]
  parameters:
    failOnError: false
    progressToStdout: true
jobs:
  - type: replacer
    rules:
      - description: session
        matchType: REQ_HEADER
        matchString: Cookie
        replacementString: "$COOKIE"
        initiators: []
  - type: openapi
    parameters:
      apiUrl: "$API/api/openapi.json"
      targetUrl: "$API"
  - type: spider
    parameters:
      url: "$API/api/v1/health"
      maxDuration: 1
$( [ -n "$WEB_CONTEXT" ] && printf '  - type: spider\n    parameters:\n      url: "%s/"\n      maxDuration: 3\n' "$WEB")
  - type: passiveScan-wait
    parameters:
      maxDuration: 5
  - type: report
    parameters:
      template: traditional-json
      reportDir: "$OUT"
      reportFile: zap-report
  - type: report
    parameters:
      template: traditional-html
      reportDir: "$OUT"
      reportFile: zap-report
YAML
"$ZAP_HOME/zap.sh" -cmd -silent -dir "$OUT/home" -autorun "$OUT/plan.yaml"

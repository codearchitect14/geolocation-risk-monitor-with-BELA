PY ?= .venv/bin/python
SCRIPTS := data/scripts

.PHONY: business-data demo-assets metrics-refresh pdf-setup api-up api-worker api-openapi api-cov api-security valkey-up valkey-down zap events-demo events-usgs events-nws events-status events-smoke events-synth events-report eval-throughput eval-gkg nel-index nel-up nel-down llm-fetch llm-up llm-down eval-cache eval-train eval geo-up db-init db-start db-stop db-reset db-upgrade etl etl-embed etl-quality etl-plans etl-report help setup data data-small data-geonames data-natural-earth data-eupeg data-wikidata \
	harvest harvest-daemon harvest-status backfill-gkg verify-data data-report tasks \
	validate-gold lint typecheck test check-style check

help:
	@echo "setup           create .venv and install dependencies"
	@echo "data            download static sources (GeoNames, Natural Earth, EUPEG) and print counts"
	@echo "data-small      same, skipping the large GeoNames files"
	@echo "data-wikidata   stream the Wikidata dump and build the place subset (hours)"
	@echo "harvest         run every configured harvest job once"
	@echo "harvest-daemon  run the harvest jobs on their intervals"
	@echo "harvest-status  show job health"
	@echo "verify-data     verify checksums recorded in data/manifest.yaml"
	@echo "db-init         create the local PostgreSQL 17 cluster (PostGIS, pgvector)"
	@echo "db-upgrade      apply Alembic migrations"
	@echo "etl             build the place knowledge base from data/raw"
	@echo "etl-embed       compute place embeddings (EMBED_LIMIT=N to bound)"
	@echo "etl-quality     run quality checks and the 1,000 name search evaluation"
	@echo "etl-plans       measure query latency and write docs/query_plans.md"
	@echo "check           lint, type check, tests, and the character check"

setup:
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]"

data: data-geonames data-natural-earth data-eupeg verify-data data-report

data-small:
	$(PY) $(SCRIPTS)/download_geonames.py --small
	$(MAKE) data-natural-earth data-eupeg verify-data data-report

data-geonames:
	$(PY) $(SCRIPTS)/download_geonames.py

data-natural-earth:
	$(PY) $(SCRIPTS)/download_natural_earth.py

data-eupeg:
	$(PY) $(SCRIPTS)/download_eupeg.py

data-wikidata:
	$(PY) $(SCRIPTS)/build_wikidata_subset.py

harvest:
	$(PY) $(SCRIPTS)/scheduler.py --once

harvest-daemon:
	$(PY) $(SCRIPTS)/scheduler.py

harvest-status:
	$(PY) $(SCRIPTS)/scheduler.py --report

backfill-gkg:
	$(PY) $(SCRIPTS)/download_gkg.py --start $(START) --end $(END) --every $(or $(EVERY),4)

verify-data:
	$(PY) $(SCRIPTS)/verify_manifest.py

data-report:
	$(PY) $(SCRIPTS)/row_counts.py

tasks:
	$(PY) $(SCRIPTS)/prepare_label_studio_tasks.py

validate-gold:
	$(PY) $(SCRIPTS)/validate_gold.py

lint:
	.venv/bin/ruff check data infra apps services

typecheck:
	.venv/bin/mypy data/scripts apps/api/meridian services/nel services/geo

test:
	.venv/bin/pytest -q

check-style:
	$(PY) infra/ci/check_no_em_dash.py .

check: lint typecheck test check-style

API := apps/api
APIRUN := cd $(API) && PYTHONPATH=. ../../$(PY)

db-init:
	infra/postgres/dev_cluster.sh init

db-start:
	infra/postgres/dev_cluster.sh start

db-stop:
	infra/postgres/dev_cluster.sh stop

db-reset:
	infra/postgres/dev_cluster.sh reset

db-upgrade:
	cd $(API) && ../../.venv/bin/alembic upgrade head

etl: db-upgrade
	$(APIRUN) -m meridian.etl build

etl-embed:
	$(APIRUN) -m meridian.etl embed $(if $(EMBED_LIMIT),--limit $(EMBED_LIMIT),)

etl-quality:
	$(APIRUN) -m meridian.etl quality
	$(PY) apps/api/meridian/etl/render_report.py

etl-plans:
	$(APIRUN) -m meridian.etl plans

# Backend API (phase 5)
valkey-up:
	mkdir -p .local && (valkey-server --port 6379 --save "" --appendonly no --bind 127.0.0.1 > .local/valkey.log 2>&1 & echo $$! > .local/valkey.pid)

valkey-down:
	-kill `cat .local/valkey.pid` && rm -f .local/valkey.pid

# Phase 7: synthetic business history (36 months, seed 42), loaded with its metric views, and illustrative demo assets.
business-data:
	$(PY) data/scripts/generate_demo_business_data.py
	cd apps/api && PYTHONPATH=. ../../.venv/bin/python -m meridian.business.loader

demo-assets:
	$(PY) data/scripts/generate_demo_assets.py

metrics-refresh:
	cd apps/api && PYTHONPATH=. ../../.venv/bin/python -c "from meridian.db import connect; c = connect(); c.execute('SELECT refresh_metrics()'); c.commit()"

# PDF reports: native libraries for WeasyPrint (macOS) and the browser used for report maps.
pdf-setup:
	brew install pango
	.venv/bin/playwright install chromium

api-up:
	mkdir -p .local && cd $(API) && MS_ENV=development MS_COOKIE_SECURE=false PYTHONPATH=. ../../.venv/bin/uvicorn meridian.api.main:create_app --factory --host 127.0.0.1 --port 8090 --no-server-header

api-worker:
	$(APIRUN) -m meridian.api.worker

api-openapi:
	$(PY) apps/api/export_openapi.py

api-cov:
	$(PY) -m pytest apps/api/tests/test_api_*.py -q --cov=apps/api/meridian/api --cov=apps/api/meridian/notify --cov-report=term-missing:skip-covered

api-security:
	$(PY) -m bandit -q -r apps/api/meridian/api apps/api/meridian/notify.py -ll || true
	PIPAPI_PYTHON_LOCATION=$(CURDIR)/$(PY) $(PY) -m pip_audit --progress-spinner off

# OWASP ZAP baseline needs Docker and a running API (make api-up). Not run in the development environment used for phase 5.
zap:
	docker run --rm --network host -v $(CURDIR)/.local:/zap/wrk ghcr.io/zaproxy/zaproxy:stable zap-baseline.py -t http://127.0.0.1:8090/api/openapi.json -f openapi -r zap-report.html

# Event pipeline (phase 4); the demo tenant is synthetic
events-demo:
	$(APIRUN) -m meridian.events demo-tenant

events-usgs:
	$(APIRUN) -m meridian.events ingest-usgs $(if $(REPLAY),--replay,)

events-nws:
	$(APIRUN) -m meridian.events ingest-nws $(if $(REPLAY),--replay,)

events-status:
	$(APIRUN) -m meridian.events update-status

events-smoke:
	$(APIRUN) -m meridian.events.smoke

events-synth:
	$(APIRUN) -m meridian.events.synth_eval

events-report:
	$(APIRUN) -m meridian.events report

# Entity linking engine (phase 3)
nel-index:
	$(PY) services/nel/prepare_index.py

nel-up:
	mkdir -p .local && cd services/nel && (PYTHONPATH=.:../../apps/api ../../.venv/bin/uvicorn nel_service.app:app --host 127.0.0.1 --port 8082 > ../../.local/nel.log 2>&1 & echo $$! > ../../.local/nel.pid)

nel-down:
	-kill `cat .local/nel.pid` && rm -f .local/nel.pid

llm-fetch:
	$(PY) services/llm/fetch_model.py

llm-up:
	mkdir -p .local && (services/llm/run_server.sh > .local/llm.log 2>&1 & echo $$! > .local/llm.pid)

llm-down:
	services/llm/run_server.sh stop

geo-up:
	cd services/geo && (PYTHONPATH=.:../../apps/api ../../.venv/bin/uvicorn geo_service.app:app --host 127.0.0.1 --port 8083 > ../../.local/geo.log 2>&1 & echo $$! > ../../.local/geo.pid)

eval-cache:
	$(APIRUN) -m meridian.eval cache-nel

eval-throughput:
	$(APIRUN) -m meridian.eval throughput --articles 10000 --workers 4

eval-gkg:
	$(APIRUN) -m meridian.eval.gkg_agreement 200

eval-train:
	$(APIRUN) -m meridian.eval train

eval:
	$(APIRUN) -m meridian.eval evaluate
	$(APIRUN) -m meridian.eval.render_report

# --- Web (phase 8) ---
.PHONY: web-install web-dev web-build web-start web-check web-e2e web-axe web-quality web-screens web-images web-geo web-seed web-cross
WEB := apps/web

web-install:
	cd $(WEB) && npm ci

web-dev:
	cd $(WEB) && npm run dev

web-build:
	cd $(WEB) && npm run build

web-start:
	cd $(WEB) && npm run start

web-check:
	cd $(WEB) && npm run lint && npm run typecheck && npm run format:check && npm test

web-e2e:
	cd $(WEB) && npx playwright test --project=chromium

web-cross:
	cd $(WEB) && npm run e2e:cross

web-axe:
	cd $(WEB) && node scripts/axe-report.mjs

web-quality:
	cd $(WEB) && node scripts/quality.mjs

web-screens:
	cd $(WEB) && node scripts/screens.mjs

web-images:
	cd $(WEB) && npm run images

web-geo:
	$(PY) data/scripts/export_web_geo.py

# Local test data for the application: illustrative assets near current incidents in the web-e2e tenant.
# Needs the API running (make api-up) and the test accounts from `meridian.api.cli create-user`.
web-seed:
	$(PY) data/scripts/seed_web_tenant.py

# --- Performance (phase 10); data is synthetic and the scenarios use their own tenants (slug prefix perf-) ---
.PHONY: perf-api perf-seed perf-recompute perf-upload perf-load perf-cleanup scans
perf-api:
	mkdir -p .local && cd $(API) && MS_ENV=development MS_COOKIE_SECURE=false MS_RATE_IP_PER_MINUTE=1000000 MS_RATE_USER_PER_MINUTE=1000000 \
		MS_LOGIN_IP_PER_MINUTE=100000 MS_LOGIN_ACCOUNT_PER_15MIN=100000 PYTHONPATH=. ../../.venv/bin/uvicorn meridian.api.main:create_app \
		--factory --host 127.0.0.1 --port 8090 --no-server-header --no-access-log

perf-seed:
	$(PY) infra/perf/bulk_load.py seed --tenants 100 --assets 500 --large 5000

perf-recompute:
	$(PY) infra/perf/bulk_load.py recompute --events 40

perf-upload:
	$(PY) infra/perf/bulk_load.py upload --rows 10000 --chunk 5000 --repeat 10

perf-load:
	cd infra/perf && ../../$(PY) -m locust -f locustfile.py --headless --host http://127.0.0.1:8090 -u 50 -r 1 -t 5m \
		--csv ../../.local/perf/locust --csv-full-history --only-summary

perf-cleanup:
	$(PY) infra/perf/bulk_load.py cleanup

# Security scans (phase 10)
scans:
	$(PY) -m bandit -q -r apps services data infra -x apps/api/tests,apps/web/node_modules,services/nel/tests -ll
	PIPAPI_PYTHON_LOCATION=$(CURDIR)/$(PY) $(PY) -m pip_audit --progress-spinner off
	cd apps/web && npm audit --omit=dev
	gitleaks detect --source . --no-banner -c .gitleaks.toml
	trivy fs --scanners vuln,secret,misconfig --severity HIGH,CRITICAL --skip-dirs node_modules,.venv,.next,.local,data/raw .

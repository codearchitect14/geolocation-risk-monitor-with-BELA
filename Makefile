PY ?= .venv/bin/python
SCRIPTS := data/scripts

.PHONY: db-init db-start db-stop db-reset db-upgrade etl etl-embed etl-quality etl-plans etl-report help setup data data-small data-geonames data-natural-earth data-eupeg data-wikidata \
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
	.venv/bin/ruff check data infra apps

typecheck:
	.venv/bin/mypy data/scripts apps/api/meridian

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

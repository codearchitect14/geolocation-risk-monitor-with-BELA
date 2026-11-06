# PostgreSQL 17 with PostGIS and pgvector. Not built on the development machine: build and test
# before use. The extensions pg_trgm and pgcrypto ship with the base image's contrib package.
FROM postgis/postgis:17-3.5

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-17-pgvector \
    && rm -rf /var/lib/apt/lists/*

# The image's entrypoint supports starting directly as the postgres user when the data volume is owned by it (uid 999).
# Nothing in the container needs root after the packages above are installed.
USER postgres
HEALTHCHECK --interval=15s --timeout=5s --retries=5 CMD pg_isready -U "${POSTGRES_USER:-postgres}" || exit 1

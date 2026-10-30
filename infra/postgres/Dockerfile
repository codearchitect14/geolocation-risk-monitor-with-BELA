# PostgreSQL 17 with PostGIS and pgvector. Not built on the development machine: build and test
# before use. The extensions pg_trgm and pgcrypto ship with the base image's contrib package.
FROM postgis/postgis:17-3.5

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-17-pgvector \
    && rm -rf /var/lib/apt/lists/*

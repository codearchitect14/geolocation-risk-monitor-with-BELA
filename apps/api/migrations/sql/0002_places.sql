-- Reference tables, configuration, and the unified place knowledge base.

CREATE TABLE ref_country_info (
    iso2        char(2) PRIMARY KEY,
    iso3        char(3) NOT NULL,
    name        text NOT NULL,
    capital     text,
    continent   char(2),
    geonames_id bigint,
    languages   text,
    population  bigint
);

-- Natural Earth polygons used to validate country and region assignments.
CREATE TABLE ref_countries (
    ne_id        bigserial PRIMARY KEY,
    iso2         char(2),
    adm0_a3      text NOT NULL,
    name         text NOT NULL,
    wikidata_qid text,
    geom         geometry(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX ref_countries_geom_gix ON ref_countries USING gist (geom);
CREATE INDEX ref_countries_iso2_ix ON ref_countries (iso2);
CREATE INDEX ref_countries_qid_ix ON ref_countries (wikidata_qid);

CREATE TABLE ref_admin1 (
    ne_id        bigserial PRIMARY KEY,
    iso2         char(2),
    adm1_code    text,
    iso_3166_2   text,
    name         text NOT NULL,
    geonames_id  bigint,
    wikidata_qid text,
    geom         geometry(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX ref_admin1_geom_gix ON ref_admin1 USING gist (geom);
CREATE INDEX ref_admin1_gn_ix ON ref_admin1 (geonames_id);
CREATE INDEX ref_admin1_qid_ix ON ref_admin1 (wikidata_qid);

-- Configurable uncertainty radius by place type and population.
CREATE TABLE place_uncertainty_rules (
    place_type     text NOT NULL,
    min_population bigint NOT NULL DEFAULT 0,
    uncertainty_km real NOT NULL CHECK (uncertainty_km > 0),
    location_level text NOT NULL
        CHECK (location_level IN ('facility', 'city', 'admin2', 'admin1', 'country', 'natural')),
    polygon_based  boolean NOT NULL DEFAULT false,
    country_level  boolean NOT NULL DEFAULT false,
    PRIMARY KEY (place_type, min_population)
);

CREATE TABLE places (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    qid              text UNIQUE,
    geonames_id      bigint UNIQUE,
    name             text NOT NULL,
    name_normalized  text NOT NULL,
    type             text NOT NULL CHECK (type IN (
        'airport', 'seaport', 'railway_station', 'power_station', 'refinery', 'factory', 'dam',
        'bridge', 'tunnel', 'border_crossing', 'military_base', 'hospital', 'stadium',
        'city', 'town', 'village', 'country', 'admin1', 'admin2', 'admin_region',
        'river', 'lake', 'island', 'mountain')),
    country_code     char(2),
    admin1_code      text,
    admin2_code      text,
    admin1_name      text,
    admin2_name      text,
    population       bigint,
    lat              double precision NOT NULL CHECK (lat BETWEEN -90 AND 90),
    lon              double precision NOT NULL CHECK (lon BETWEEN -180 AND 180),
    centroid         geometry(Point, 4326) NOT NULL,
    geom             geometry(Geometry, 4326) NOT NULL,
    bbox_west        double precision,
    bbox_south       double precision,
    bbox_east        double precision,
    bbox_north       double precision,
    has_polygon      boolean NOT NULL DEFAULT false,
    uncertainty_km   real,
    location_level   text,
    country_level    boolean NOT NULL DEFAULT false,
    parent_place_id  bigint REFERENCES places (id) ON DELETE SET NULL,
    h3_cell          bigint,
    sitelinks        integer,
    description      text,
    website          text,
    source           text NOT NULL CHECK (source IN ('wikidata', 'geonames', 'merged')),
    merge_method     text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    CHECK (qid IS NOT NULL OR geonames_id IS NOT NULL)
);
CREATE INDEX places_centroid_gix ON places USING gist (centroid);
CREATE INDEX places_centroid_geog_gix ON places USING gist ((centroid::geography));
CREATE INDEX places_geom_gix ON places USING gist (geom) WHERE has_polygon;
CREATE INDEX places_name_trgm_ix ON places USING gin (name_normalized gin_trgm_ops);
CREATE INDEX places_name_ix ON places (name_normalized);
CREATE INDEX places_country_type_ix ON places (country_code, type);
CREATE INDEX places_parent_ix ON places (parent_place_id);
CREATE INDEX places_h3_ix ON places (h3_cell);
CREATE INDEX places_population_ix ON places (population DESC NULLS LAST);

CREATE TABLE place_aliases (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    place_id         bigint NOT NULL REFERENCES places (id) ON DELETE CASCADE,
    alias            text NOT NULL,
    alias_normalized text NOT NULL,
    language         text,
    type             text NOT NULL DEFAULT 'alias'
        CHECK (type IN ('label', 'alias', 'preferred', 'short', 'historic', 'iata', 'icao', 'abbr')),
    source           text NOT NULL CHECK (source IN ('wikidata', 'geonames'))
);
CREATE INDEX place_aliases_place_ix ON place_aliases (place_id);
CREATE INDEX place_aliases_norm_ix ON place_aliases (alias_normalized);
CREATE INDEX place_aliases_trgm_ix ON place_aliases USING gin (alias_normalized gin_trgm_ops);
CREATE UNIQUE INDEX place_aliases_unique_ix ON place_aliases (place_id, alias_normalized, language, type)
    NULLS NOT DISTINCT;

CREATE TABLE place_embeddings (
    id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    place_id  bigint NOT NULL REFERENCES places (id) ON DELETE CASCADE,
    kind      text NOT NULL CHECK (kind IN ('name', 'alias', 'description')),
    language  text,
    text      text NOT NULL,
    model     text NOT NULL,
    embedding vector(1024) NOT NULL
);
CREATE INDEX place_embeddings_place_ix ON place_embeddings (place_id);
-- The HNSW index is built by the embedding job after bulk loading (faster than incremental).

CREATE TABLE place_merge_review (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    qid          text,
    geonames_id  bigint,
    place_id     bigint REFERENCES places (id) ON DELETE CASCADE,
    reason       text NOT NULL,
    distance_km  real,
    detail       text,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX place_merge_review_reason_ix ON place_merge_review (reason);

CREATE TABLE place_hierarchy_issues (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    place_id   bigint NOT NULL REFERENCES places (id) ON DELETE CASCADE,
    parent_id  bigint,
    issue      text NOT NULL,
    detail     text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE etl_runs (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    step        text NOT NULL,
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    status      text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'ok', 'failed')),
    stats       jsonb NOT NULL DEFAULT '{}'
);

-- QIDs already looked up through the Wikidata API, so non-places and failures are not fetched again.
CREATE TABLE wikidata_entity_cache (
    qid        text PRIMARY KEY,
    status     text NOT NULL CHECK (status IN ('place', 'not_a_place', 'no_coordinates', 'missing')),
    place_type text,
    fetched_at timestamptz NOT NULL DEFAULT now()
);

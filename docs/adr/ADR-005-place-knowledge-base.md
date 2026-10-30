# ADR-005: Unified place knowledge base

- Status: accepted
- Date: 2026-10-30

## Context

Linking and geolocation need one table of places with stable coordinates, types, hierarchy,
and uncertainty, built from Wikidata (entities the entity linker knows), GeoNames (coverage of
small places and administrative codes), and Natural Earth (polygons).

## Decision

1. **Identity.** One row per real place. `qid` and `geonames_id` are both unique and either may
   be null. Records are merged, in order, by Wikidata property P1566, then by normalized name,
   country, compatible type family, and a distance threshold by type. Anything unresolved is
   inserted as its own place. Conflicts go to `place_merge_review` and are never silently
   dropped: duplicate GeoNames claims, coordinates that disagree by more than twice the type
   threshold, type family mismatches, ambiguous matches, and match collisions.
2. **Types.** Facility, settlement, administrative, and natural types are listed in
   `meridian/geo/taxonomy.py`. Settlements are classified by population (city from 100,000, town
   from 10,000) so the uncertainty radius is consistent across sources.
3. **Scope of GeoNames.** Settlements with population of at least 1,000, administrative
   divisions, and facility types. Minor dams, bridges, and tunnels are excluded because GeoNames
   has no importance signal for them; notable ones come from Wikidata.
4. **Scope of Wikidata.** Entities with coordinates inside the class hierarchy below the seed
   classes. Natural features need at least three sitelinks.
5. **Uncertainty radius.** Stored in `place_uncertainty_rules`, editable without a code change:
   facility 2 km, village 5 km, town 10 km, city 25 km, city above one million 40 km, admin-2
   30 km when no polygon exists, admin-1 100 km when no polygon exists, natural features 10 to
   25 km. Countries and admin-1 regions use Natural Earth polygons, and a country is flagged
   `country_level` so it is never matched against site assets.
6. **Hierarchy.** Parents come from GeoNames codes, then Wikidata P131, then admin-1 polygons,
   then the country code. Cycles are broken and recorded; country mismatches and parents that
   do not outrank the child are recorded in `place_hierarchy_issues`.
7. **Embeddings.** bge-m3, 1024 dimensions, stored per text (name with location context,
   alias, description) with an HNSW cosine index built after bulk load.

## Consequences

- The merge is deterministic and can be re-run, but it truncates the place tables and is
  refused while mentions, events, assets, or alerts exist (override with `--force`).
- A place without a Wikidata or GeoNames id cannot exist (database check).
- Thresholds in `merge.py` and `taxonomy.py` are initial values; revisit them with the review
  list and the gold sets in phase 3.

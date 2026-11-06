# Data guide

Signals are situational awareness derived from public news and public data feeds. They are not official warnings. Verify with local
authorities and follow their guidance.

`data/README.md` is the detailed reference for acquisition, layout, and the licensing register. This guide says what data the
product needs, which parts the demonstration uses, and how to build the full set.

## What the product reads

| Data | Used for | Size | Demonstration | Full build |
|---|---|---|---|---|
| GeoNames | Places, names, populations | cities15000 about 2 MB; all countries about 1.5 GB; alternate names about 0.7 GB | cities of 15,000 people or more (31,700 places), no aliases | all places of 1,000 people or more with aliases |
| Wikidata subset | Qualified places, ids used by the linking model, descriptions | stream of the dump (many hours) | not used | `make data-wikidata`, then `make etl` |
| Natural Earth | Country and region boundaries | 220 MB | used (reference tables) | used |
| USGS, NWS, FIRMS, ReliefWeb | Hazard incidents | small, daily files | recorded sample of 160 earthquakes (committed) | `make harvest-daemon` |
| GDELT, news pages | News incidents | metadata and snippets of at most 300 characters | not used | `make harvest`, entity linking and model services |
| BELA checkpoint and entity index | Place linking in news | about 33 GB | not used | `data/raw/models/bela` (see `docs/adr/ADR-006`) |
| Local language model | Headline labels, place adjudication | about 2.5 GB | not used | `make llm-fetch` |
| Business history | Revenue dashboards | generated | synthetic, generated | same |
| Asset portfolios | Customer sites | generated | illustrative, generated | tenants upload their own |

All business and portfolio data in the repository and in the demonstration is generated and labeled synthetic or illustrative.

## The place knowledge base

Each place has a name, type, country, coordinates, population, hierarchy, aliases, and an **uncertainty radius** by type and size,
which exposure scoring and the map use. Build steps (`make etl`): reference tables, staging of GeoNames and Wikidata, merge by
identifier and then by name and distance with ambiguous merges sent to a review table, hierarchy, and finalization (H3 cells,
uncertainty). Embeddings for vector search are separate (`make etl-embed`, hours, 10 GB). `docs/place_kb_report.md` has the
quality checks for the full build. The demonstration builds a reduced version with `python -m meridian.etl build --demo`
(about ten seconds): cities only, no aliases, no hierarchy, no embeddings; place search and asset geocoding by city work, and
linking news text does not.

## Rebuilding

```bash
make data-small      # GeoNames small files, Natural Earth, EUPEG; then verify and count
make data            # the same with the large GeoNames files
make data-wikidata   # Wikidata subset (many hours)
make etl             # place knowledge base from data/raw
make etl-embed       # embeddings for vector search
make harvest         # one pass over the configured feeds (make harvest-daemon to keep running)
make business-data   # synthetic business history, with its metric views
make demo-assets     # illustrative asset portfolios for the synthetic tenants
make replay-seed     # rebuild the committed earthquake replay seed from harvested USGS files
```

Every download script is idempotent, resumable, and checks size and SHA-256 against `data/manifest.yaml`; `make verify-data`
re-checks. Source notes and known gaps are in `data/README.md`.

## Retention and privacy

Full article text is never stored: the database keeps the link, the title, and a snippet of at most 300 characters. Tenant assets
are confidential and never leave the tenant: not in logs, not in notifications by default, not in corrections. Tenant data is
purged after each tenant's retention setting (default 365 days); the audit log is not purged. Corrections leave a tenant only
with consent and without tenant identifiers or free text.

## Replay seed

`data/seed/replays/usgs_earthquakes.jsonl` holds 160 earthquake records (magnitude 4.5 and above) from the USGS feed, reduced to the
fields the normalizer reads. `make replay` re-times them so the newest is one minute old, loads the oldest 70 percent as history, and
plays the rest with the real gaps divided by `SPEED` (default 1800, at most two seconds between records). Replayed incidents say so
in their summary. The records are public domain.

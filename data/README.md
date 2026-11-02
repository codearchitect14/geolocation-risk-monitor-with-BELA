# Dataset folder

This folder holds every dataset used by the platform: how it is acquired, where it is
stored, what it may be used for, and how to rebuild it. Raw downloads are git-ignored.
Small curated files (gold sets, seed data, manifests) are committed.

Signals derived from these sources are situational awareness derived from public news and
public data feeds. They are not official warnings. Verify with local authorities and follow
their guidance.

## Layout

```
data/
  manifest.yaml         machine-readable source registry (URL, license, checksums, last run)
  README.md             this file, including the licensing register
  raw/                  git-ignored, created by the scripts
    knowledge_base/wikidata/   places.parquet, names.parquet, class_map.json
    gazetteer/geonames/        GeoNames dump files
    boundaries/natural_earth/  one folder per layer: shapefile and GeoJSON
    news/gdelt/                GDELT DOC harvest, one JSONL per day
    news/gdelt_gkg/            GKG V2Locations baseline, one gzip JSONL per 15-minute file
    news/articles/             article fetch metadata and snippets (at most 300 characters)
    news/cc_news/              per-language parquet slices
    hazards/usgs/              earthquake events, one JSONL per event day
    hazards/nws/               weather alerts, one JSONL per fetch day
    hazards/firms/             fire detections, one CSV per source and window
    hazards/reliefweb/         optional reports and disasters
    eval/eupeg/                converted evaluation corpora (<corpus>.jsonl) and original files
    eval/mewsli_x/             optional linking benchmark
    models/bela/               BELA checkpoints, entity index, embeddings (about 33 GB with the float16 copy)
    models/llm/                local language model (GGUF)
    _status/                   per-job heartbeat files read by `make harvest-status`
  processed/            git-ignored parquet outputs of later ETL phases, plus row_counts.*
  gold/                 hand-labeled evaluation sets (committed, small)
  annotation/           Label Studio configurations, guidelines, generated task files
  synthetic/            generated business data (a later phase)
  seed/                 committed demo seed and replay files (a later phase)
  scripts/              acquisition scripts and shared helpers
  tests/                unit tests for the scripts
```

## Setup

```
make setup                    # creates .venv and installs dependencies
cp .env.example .env          # then fill in the values described below
```

| Variable | Purpose |
|---|---|
| `MS_CONTACT` | Contact string placed in the User-Agent of every request. Required by NWS. |
| `NWS_USER_AGENT` | Optional full User-Agent for api.weather.gov. |
| `FIRMS_MAP_KEY` | Free key from the NASA FIRMS "Get MAP_KEY" form. |
| `RELIEFWEB_APPNAME` | Approved appname for the optional ReliefWeb source. |
| `HF_TOKEN` | Optional Hugging Face token for dataset downloads. |
| `MS_DATA_DIR` | Optional location of `raw/` and `logs/` (default: this folder). |

## Rebuilding the data

```
make data-small        # GeoNames (small files), Natural Earth, EUPEG; then verify and count
make data              # the same including allCountries and alternateNamesV2
make data-wikidata     # streams the Wikidata dump and builds the place subset (many hours)
make harvest           # run each configured harvest job once
make harvest-daemon    # run the jobs on their intervals until stopped
make harvest-status    # job health: runs, failures, last success
make verify-data       # verify sizes and SHA-256 against manifest.yaml
make data-report       # row counts into data/processed/row_counts.{json,md}
make backfill-gkg START=2026-08-01 END=2026-10-29 EVERY=4
make tasks             # build Label Studio task files from harvested titles
make validate-gold     # validate gold sets and show progress against quotas
```

Every download script is idempotent (it skips files that already match), resumable
(partial files continue from where they stopped), checksum-verified (sizes and SHA-256 are
recorded in `manifest.yaml` and compared on later runs), and logged to `data/logs/`.

### Scheduled harvesting

`data/scripts/scheduler.py` runs these jobs at fixed intervals and records a heartbeat per job:

| Job | Script | Interval | Needs |
|---|---|---|---|
| `usgs` | `pull_usgs.py` | 5 minutes | nothing |
| `nws` | `pull_nws.py` | 5 minutes | `MS_CONTACT` or `NWS_USER_AGENT` |
| `firms` | `pull_firms.py` | 3 hours | `FIRMS_MAP_KEY` |
| `gdelt` | `harvest_gdelt.py` | 30 minutes | nothing |
| `reliefweb` | `pull_reliefweb.py` | 6 hours | `RELIEFWEB_APPNAME` |

Jobs whose credentials are missing are skipped with a warning. For unattended operation run
`make harvest-daemon` under launchd, systemd, or a container supervisor, or call
`scheduler.py --once` from cron. The phase 1 exit check is `make harvest-status` showing no
`ATTENTION` rows after 48 hours.

GDELT enforces one request per five seconds. The harvester spaces requests at 5.5 seconds and
backs off on HTTP 429. A full pass over the topic matrix (16 topics, 5 languages) takes about
eight minutes.

## Source notes

- **Wikidata.** `build_wikidata_subset.py` reads the official JSON dump as a stream and never
  stores it. It keeps entities that have a coordinate location (P625) and whose instance of
  (P31) falls inside the class hierarchy below the seed classes, which are listed in the script.
  The plan said to verify class IDs; two corrections resulted: `Q1378139` is "robotic
  spacecraft", so border crossings use `Q55599109` and `Q757292`, and seaports use `Q15310171`
  together with `Q44782` (port) and `Q492425` (container terminal). Entities without
  coordinates cannot be placed and are excluded; administrative regions come from Natural Earth
  polygons. The community Parquet route (option A) is not implemented because its schema has
  not been verified. The dump pass cannot be resumed; the later class filter can be rerun with
  `--filter-only`.
- **GeoNames.** The server provides no checksums, so the recorded hash is that of the first
  download.
- **Natural Earth.** The admin-1 GeoJSON omits `type_en`, `valid_from`, `valid_to`, and
  `gadm_level` (columns that depend on GADM data). The shapefile in `raw/` is the unmodified
  download and must not be redistributed. The `type` column is kept; confirm its provenance
  before redistributing derived files.
- **GDELT GKG.** The `V2Locations` layout was checked against a live file: nine `#` separated
  subfields (type, name, country code, ADM1, ADM2, latitude, longitude, feature id, character
  offset) and 27 tab separated columns. Raw zip files are deleted after parsing.
- **Article text.** The fetcher honors robots.txt, rate limits per domain, blocks private
  addresses, caps response size, and writes only metadata and a snippet of at most 300
  characters. Full text exists only in memory during linking.
- **EUPEG.** Corpora are fetched from a pinned commit and converted to one JSONL document per
  line with character offsets. TR-News annotations use shifted offsets; they are repaired and
  flagged with `offset_repaired`. GeoCorpora is excluded. Hu2014 and Ju2016 files are
  downloaded unconverted because they carry no character offsets or gold coordinates.
- **Multilingual CC-News.** The `main` branch of the dataset contains only a loading script,
  so parquet files come from the auto-converted revision, pinned by commit.
- **GDACS.** Not ingested until reuse and attribution terms are confirmed in writing.

## Licensing register

The application footer and the methodology page must credit every source marked "yes" in the
last column. The project builds on the open-source BELA and BLINK releases and is not
affiliated with their authors.

| Source (`id`) | License or terms | Required attribution | Redistribution | Credited in UI |
|---|---|---|---|---|
| Wikidata (`wikidata`) | CC0 1.0 | Wikidata | Allowed | yes |
| GeoNames (`geonames`) | Creative Commons Attribution (confirm version and wording on geonames.org) | GeoNames (geonames.org) | Allowed with attribution | yes |
| Natural Earth (`natural_earth`) | Public domain (United States); check local law elsewhere | Made with Natural Earth | Allowed; keep GADM dependent columns out | yes |
| GDELT DOC (`gdelt_doc`) | Free for research use; metadata only | GDELT Project | Metadata only; publishers keep copyright | yes |
| GDELT GKG (`gdelt_gkg`) | Free for research use; metadata only | GDELT Project | Metadata only | yes |
| Article text (`article_text`) | Publisher copyright | Link to the original article | Snippets of at most 300 characters | yes |
| Multilingual CC-News (`cc_news`) | Publisher copyright; non-commercial testing | intfloat/multilingual_cc_news; CloverSearch/cc-news-mutlilingual | Not redistributed | no (testing only) |
| USGS earthquakes (`usgs`) | Public domain | U.S. Geological Survey | Allowed | yes |
| NWS alerts (`nws`) | Open data, free for any purpose per NWS | National Weather Service | Allowed | yes |
| NASA FIRMS (`firms`) | Free with MAP_KEY | NASA FIRMS | Follow the NASA FIRMS data use policy | yes |
| ReliefWeb (`reliefweb`) | Open access; some content belongs to original sources | ReliefWeb (UN OCHA) | Title, snippet, and link only | yes, when used |
| GDACS (`gdacs`) | Reuse terms not confirmed | not applicable | Excluded | no |
| EUPEG corpora (`eupeg`) | Repository GPL-3.0; each corpus keeps its authors' license | Corpus authors and EUPEG authors | Evaluation use only; not redistributed | methodology page |
| Mewsli-X (`mewsli_x`) | Apache-2.0 per dataset card | Mewsli-X authors | Allowed under Apache-2.0 | methodology page |
| BELA (`bela`) | MIT (Meta Platforms); mirror repository declares MIT | Meta AI BELA authors; the project is not affiliated with them | Allowed under MIT | methodology page |
| XLM-R tokenizer (`xlmr_tokenizer`) | MIT | Facebook AI (XLM-R authors) | Allowed | methodology page |
| Qwen3-4B-Instruct-2507 (`qwen3_gguf`) | Apache-2.0 | Qwen team (Alibaba Cloud); GGUF build by unsloth | Allowed under Apache-2.0 | methodology page |
| bge-m3 (`bge_m3`) | MIT | BAAI | Allowed | methodology page |
| Gold sets (`gold`) | Own work | Project annotators | Committed | no |
| Basemap (`basemap`) | ODbL for OpenStreetMap derived tiles | OpenStreetMap contributors | Per ODbL | yes, when tiles are used |

Hazard feed operators state that automated alerts should not be used for decisions without
confirmation. That message is preserved wherever hazard records are shown.

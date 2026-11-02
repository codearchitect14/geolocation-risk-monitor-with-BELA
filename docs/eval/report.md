# Place linking evaluation

Generated 2026-11-02 11:08 by `make eval`. BELA checkpoint `model_wiki.ckpt`, configuration `geo_config_v1`.

## Data and protocol

- Corpora: the public geoparsing corpora LGL, TR-News, GeoWebNews, GeoVirus, and a seeded sample of WikToR, converted by `data/scripts/download_eupeg.py`. Documents are split 50/50 by hash into **dev** (used to train the re-ranker and to fit calibration) and **test** (all figures below). Test split: 787 documents, 6,466 gold toponyms; dev split: 761 documents.
- Each gold toponym has a character span and coordinates. Systems that detect their own spans (S4 to S6) are matched to gold spans by overlap (intersection over union of at least 0.4). **A gold toponym with no matching prediction counts as wrong** in the first accuracy columns; the 'matched only' columns exclude them.
- S1 and S2 are given the gold spans, so they measure disambiguation only; detection is not applicable to them.
- The ambiguous subset is the gold toponyms whose name matches at least two places in the knowledge base (2,969 of 6,466).
- S3 (GDELT's own extracted locations) has no gold to score against on the public corpora, which predate GDELT's article coverage. It is compared with the hybrid system as an agreement study on current news (last section).
- Not evaluated: the hand-labeled mention and event gold sets (no annotation has been done), BLINK re-ranking (S7, see ADR-002), event type and severity F1 (phase 4), NIL handling, and the Mewsli-X sanity check.

## Results on the test split

| System | Detection P / R / F1 | Acc 25 km | Acc 161 km | Acc 25 km (matched) | Acc 161 km (matched) | Median km | Mean km | Error-curve AUC (lower is better) |
|---|---|---|---|---|---|---|---|---|
| S1 largest-population GeoNames match | n/a (gold spans given) | 41.6% | 43.8% | 55.8% | 58.7% | 2.1 | 2,129 | 0.5246 |
| S2 GeoNames with country and region context | n/a (gold spans given) | 48.1% | 50.5% | 64.4% | 67.6% | 0.8 | 1,703 | 0.4755 |
| S4 BELA alone | 60.7% / 34.8% / 44.2% | 25.9% | 29.8% | 74.4% | 85.9% | 0.4 | 390 | 0.7166 |
| S5 BELA + type filter + routing + gazetteer fallback + context re-ranking | 41.1% / 77.0% / 53.6% | 58.6% | 65.7% | 76.0% | 85.2% | 0.2 | 513 | 0.3671 |
| S6 S5 + local model adjudication | 43.2% / 76.8% / 55.3% | 58.7% | 65.8% | 76.4% | 85.7% | 0.2 | 514 | 0.3668 |

### Ambiguous names only

| System | Detection P / R / F1 | Acc 25 km | Acc 161 km | Acc 25 km (matched) | Acc 161 km (matched) | Median km | Mean km | AUC |
|---|---|---|---|---|---|---|---|---|
| S1 largest-population GeoNames match | n/a (gold spans given) | 42.4% | 45.2% | 42.5% | 45.3% | 442 | 2,651 | 0.4701 |
| S2 GeoNames with country and region context | n/a (gold spans given) | 55.2% | 58.6% | 55.4% | 58.7% | 4.1 | 2,056 | 0.3727 |
| S4 BELA alone | n/a / 33.8% / n/a | 24.8% | 26.1% | 73.5% | 77.3% | 0.0 | 754 | 0.7334 |
| S5 BELA + type filter + routing + gazetteer fallback + context re-ranking | n/a / 84.4% / n/a | 66.8% | 69.5% | 79.2% | 82.4% | 0.2 | 702 | 0.3044 |
| S6 S5 + local model adjudication | n/a / 84.0% / n/a | 66.8% | 69.5% | 79.5% | 82.7% | 0.2 | 719 | 0.3048 |

### By corpus (accuracy within 161 km, all gold toponyms)

| System | geovirus | geowebnews | lgl | tr-news | wiktor |
|---|---|---|---|---|---|
| S1 | 1.3% | 58.3% | 57.8% | 71.0% | 15.6% |
| S2 | 1.3% | 57.9% | 64.5% | 73.8% | 42.3% |
| S4 | 51.1% | 24.5% | 32.0% | 38.0% | 3.8% |
| S5 | 73.2% | 58.6% | 66.4% | 70.0% | 63.0% |
| S6 | 73.0% | 59.0% | 67.0% | 69.8% | 61.9% |

## Routing (S5, test split)

| Route | Mentions | Share |
|---|---|---|
| accept | 1,362 | 5.4% |
| adjudicate | 2,153 | 8.5% |
| fallback | 8,241 | 32.4% |
| unresolved | 13,671 | 53.8% |

## Local model use (S6, test split)

Mentions adjudicated by the local model: 1,484 of 11,480 resolved mentions (12.9%). Run time 1307 s.

## Throughput and latency (BELA stage on the Apple GPU)

| Measure | Value |
|---|---|
| Documents | 1548 |
| Passages | 5843 |
| Passages per second | 22.06 |
| Document request p50 / p95 | 0.149 s / 0.311 s |

## Calibration of the confidence by route

Isotonic regression fitted on the dev split; the target is a prediction within 25 km. Figures are on the test split.

- `accept`: expected calibration error 0.0478 before and 0.044 after (dev 688 predictions, test 799).
- `adjudicate`: expected calibration error 0.1075 before and 0.0162 after (dev 1,168 predictions, test 1,302).
- `fallback`: expected calibration error 0.1165 before and 0.0237 after (dev 2,808 predictions, test 2,868).

## Throughput test on real articles

10,000 news articles (en, es, de) through the complete pipeline (chunking, BELA, routing, fallback, re-ranking, event location; no local model) with 4 client workers.

| Measure | Value |
|---|---|
| Articles | 10,000 |
| Failures | 0 |
| Total time | 43.6 minutes |
| Articles per second | 3.82 |
| Mentions per article | 39.2 |
| Latency p50 / p95 | 0.857 s / 2.199 s |
| Passed | yes |

## Agreement with GDELT's own locations (system S3)

Sample: 108 current English news articles (150 sampled, 42 could not be fetched, robots.txt honored) with the locations GDELT's GKG extracted for them. There is no gold, so this measures agreement between two automatic systems; where they differ either may be right.

| Measure | Value |
|---|---|
| GDELT city and state locations that the hybrid also found (within 25 km, 161 km for states) | 79.3% of 739 |
| Hybrid city and region places that GDELT also lists | 36.9% of 1,825 |
| Hybrid event location within range of GDELT's first location | 34.7% of 95 articles |

## Targets

| Target | Result | Status |
|---|---|---|
| Hybrid beats the best gazetteer baseline by at least 5 points of accuracy within 161 km on the ambiguous subset | +10.9 points (S6 69.5% vs 58.6%) | met |
| Median error at most 25 km on the event gold set for facility and city events | event gold set not built | not evaluated |
| BELA stage at least 20 passages per second on the target GPU | 22.06 passages per second | met |
| At most 25 percent of mentions needing LLM adjudication | 12.9% of resolved mentions | met |

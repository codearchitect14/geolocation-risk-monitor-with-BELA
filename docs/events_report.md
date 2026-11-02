# Event pipeline report (phase 4)

Signals are situational awareness derived from public news and public data feeds. They are not official warnings. Verify with local
authorities and follow their guidance.

Rules version: `events_config_v1`. All runs below are on the development machine (Apple M5 Pro; the local model and entity linker run
on the GPU). Demo data are synthetic and labeled.

## What was built

Normalizers for USGS, NWS (with cached zone polygons), FIRMS (density clustering), and ReliefWeb; a news path (local model label,
place linking, event location); idempotent clustering with revisions, supersession, and cancellation; status lifecycle; exposure
scoring with every component stored; alert rules with de-duplication, maintenance windows, reopening, and watch zones. Design:
`docs/adr/ADR-008-event-pipeline.md`.

## Exit criterion

`apps/api/tests/test_events_e2e.py` ingests a plant fire article that names "Springfield, Illinois" and a USGS earthquake near
Springfield, Missouri, against a tenant with a site near each town. Result: the fire event is located in Illinois, a second outlet
merges into it and confirms it, the quake forms its own event, the Illinois site alerts for the fire and the Missouri site does not,
and the Missouri site alerts for the quake. Private-person reports, non-disruptions, articles with no place, and future-dated
articles create no event. The suite has 223 passing tests (70 for this phase plus 4 service tests and 1 date test).

## Measured results

| Check | Result | Basis |
|---|---|---|
| Real USGS files (357 records, Oct 2026) | 173 events, 162 below minimum magnitude, 20 small and far from assets, 2 invalid, 1 alert | synthetic demo tenant with 150 sites |
| Real NWS file (518 alerts) | 288 usable alerts became 49 events; 230 ignored (Small Craft Advisory and similar, or no resolvable area); 0 alerts | demo tenant has no sites in those zones |
| Classifier smoke set (37 author-written headlines) | type 97.3%, private-person flag 100%, severity exact 37.9%, severity within one level 100% | not a gold evaluation |
| Exposure alerts, 400 synthetic scenarios x 30 assets | at least low: precision 0.38, recall 0.93; at least medium: 0.46 / 0.61; at least high: 0.49 / 0.23 | ground truth radii independent of scoring parameters |
| News replay, 53 real CC-News articles (keyword filtered headlines) | 34 events from 43 kept reports (merges across outlets rare in a random sample), 10 non-disruptions and 6 private-person reports dropped, 1 without a place | testing use only |
| News throughput | about 30 s per article with model adjudication on, dominated by the language model | the run was stopped at 53 articles |

## Limits and honest gaps

- **No event gold set exists.** Event type and severity F1 on real labeled events, and detection delay against hazard feed times,
  are not measured. The smoke set is small, written by the team, and cannot estimate real accuracy. Severity exact match is
  low because severity is a judgment; a labeled set is needed before severity is trusted.
- **FIRMS and ReliefWeb** are implemented and unit tested but were not run on real data (no key or appname available here).
- **GDELT** data was not available (rate limited in phase 1), so cross-source confirmation was exercised with tests and a small
  CC-News sample, not with a live news stream.
- **Synthetic exposure evaluation:** precision is limited by design. A city-level report carries 25 km of uncertainty, so sites
  inside that distance are flagged for a 5 km fire. Region-level reports have recall of about 0.16 at `medium`. The parameters were
  not tuned to this set.
- **Location confidence** of news events is not calibrated against real events.
- A bare ambiguous headline place with the model stage off can choose the wrong town; qualified mentions resolve correctly
  (see ADR-008).
- **Speed:** model adjudication makes news ingestion slow (about 30 s per article here). Higher parallelism or a smaller adjudication
  gate is the next lever.

## Reproduce

```
make events-demo events-usgs REPLAY=1 events-nws REPLAY=1 events-report
make events-smoke events-synth
.venv/bin/pytest apps/api/tests/test_events_*.py
```

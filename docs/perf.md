# Performance (phase 10)

Signals are situational awareness derived from public news and public data feeds. They are not official warnings. Verify with local
authorities and follow their guidance.

All figures are from one development machine (Apple M5 Pro, one API process, PostgreSQL 17 on the same machine, load generator on
the same machine) on 2026-11-04. They show how the application behaves and what changed; they are not a sizing guarantee for another
environment. Data is synthetic and labeled: 101 generated tenants with 55,000 assets, one of them (5,000 assets) used by the
simulated users, on top of the existing development data (525,000 places, 255 incidents). Request limits were raised for the run
(`make perf-api`) so the application is measured, not the limiter, which has its own tests.

Reproduce: `make perf-api`, `make perf-seed`, `make perf-load`, `make perf-upload`, `make perf-recompute`, `make perf-cleanup`.

## Targets and results

| Scenario | Target (plan) | Result | Met |
|---|---|---|---|
| 50 concurrent users on the map and dashboards | p95 documented | all requests p50 4 ms, p95 10 ms, p99 24 ms; 115 requests per second; 20,693 requests, 0 failures | yes |
| Upload of 10,000 assets | documented | 10,000 rows accepted in 0.9 s (two requests of 5,000 rows; 0.40 s and 0.49 s); 1,000-row uploads p50 86 ms, p95 87 ms | yes |
| Ingestion of 10,000 articles | documented | 3.82 articles per second with 4 workers (2,619 s total), p50 0.86 s, p95 2.2 s per article, 0 failures. Measured in phase 5 (`docs/eval/throughput.json`); not repeated because the news path is unchanged when the model server and linker are up. | yes (earlier run) |
| Exposure recomputation, 100 tenants with 500 assets each | documented | one pass over the 40 newest incidents for all tenants (95,001 perf assets after the upload test): 1.5 s (p50 4 ms, p95 106 ms per incident); tenant by tenant, 101 tenants: 1.9 s (p50 18 ms, p95 21 ms per tenant) | yes |
| Map: 60 frames per second panning with 5,000 markers | plan 6, task 8 | not measured in a browser (see below) | not verified |

The upload cap is 5,000 rows per file (`MS_MAX_UPLOAD_ROWS`); 10,000 assets are therefore two uploads.

Exposure recomputation stored only 79 exposures because the generated assets are spread over the world and few incidents are near
them; the time measures the spatial search over all assets, which is the cost that grows with asset count.

## Load test: 50 users, 5 minutes then 3 minutes

Each simulated user signs in, then repeats what the screens do (weights in parentheses): map screen (5: incidents for the viewport,
zones, alerts, then ten pages of 200 assets), overview (4), asset list (3), incident detail (3), alert queue, sources, asset search,
place search (1 each), with 1 to 3 seconds of think time. Ramp 1 user per second to 50.

"Before" is the API as it was at the end of phase 9 (connection per use, original Row Level Security policy). "After" has the
connection pool, the index friendly policy, and the asset paging index (`docs/db_tuning.md`).

| Request | Requests (after) | p50 ms before | p50 ms after | p95 ms before | p95 ms after | p99 ms after |
|---|--:|--:|--:|--:|--:|--:|
| GET /alerts (limit 200) | 2011 | 14 | 3 | 27 | 7 | 11 |
| GET /alerts (queue) | 250 | 15 | 4 | 30 | 8 | 30 |
| GET /analytics/operations | 877 | 12 | 3 | 25 | 7 | 10 |
| GET /assets (map page of 200) | 11340 | 41 | 3 | 57 | 6 | 10 |
| GET /assets (page of 100) | 687 | 41 | 4 | 58 | 10 | 16 |
| GET /assets (search) | 222 | 42 | 6 | 62 | 13 | 36 |
| GET /briefings | 877 | 13 | 3 | 26 | 6 | 10 |
| GET /events (limit 200) | 927 | 26 | 10 | 53 | 28 | 52 |
| GET /events (map viewport) | 1134 | 22 | 5 | 35 | 12 | 38 |
| GET /events/{id} | 703 | 27 | 6 | 50 | 13 | 73 |
| GET /places/search | 242 | 22 | 11 | 44 | 28 | 38 |
| GET /sources | 239 | 15 | 4 | 31 | 10 | 17 |
| GET /zones | 1134 | 18 | 3 | 32 | 7 | 10 |
| POST /auth/login | 50 | 59 | 82 | 76 | 120 | 120 |
| All requests | 20693 | 37 | 4 | 55 | 10 | 24 |

Sign-in is slower in the second run because all 50 users sign in within a few seconds and each sign-in spends about 45 ms of
CPU on Argon2id, which is intended. The two runs also differ in length (5 minutes and 3 minutes), so request counts are not comparable.

## Capacity: 50 users with no think time

The same scenario without waiting between actions, to find what one API process can sustain (75 seconds, 0 failures in all three):

| Build | Requests per second | p50 ms | p95 ms | p99 ms |
|---|--:|--:|--:|--:|
| Phase 9 | 220 | 220 | 280 | 310 |
| With connection pool | 335 | 140 | 190 | 210 |
| With pool, index friendly policy, paging index | 429 | 110 | 150 | 170 |

The single process is CPU bound at this point; production runs several processes (`uvicorn --workers`), and the pool is per process.

## Not measured

- **Browser frame rate with 5,000 markers.** The map uses a clustered GPU circle layer and symbol layers (phase 9), which is designed
  for this, but no frame rate was measured. Needs a headed browser with GPU profiling.
- **A second machine for the load generator**, so generator and server share CPU here, which makes the results slightly pessimistic.
- **Report generation under load** (PDF, map images), which runs in child processes inside the request.
- **Valkey**: runs used the in-process rate limiter.

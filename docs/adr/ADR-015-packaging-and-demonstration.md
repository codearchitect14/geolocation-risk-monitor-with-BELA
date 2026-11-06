# ADR-015: Packaging and the demonstration

Status: accepted (phase 11)

## Context

A reviewer must be able to clone the repository, run one command, and use every page with realistic data. The full data set does not
allow that: the Wikidata subset takes hours, the linking model is about 33 GB, and the embeddings are 10 GB.

## Decisions

1. **A reduced place knowledge base for the demonstration.** `python -m meridian.etl build --demo` builds from the GeoNames
   cities file (31,700 places of 15,000 people or more), with no aliases, no hierarchy, and no Wikidata. It takes about ten seconds. The
   full build is unchanged. The demonstration therefore cannot link news text, and says so.
2. **Incidents from a recorded feed.** A committed, public domain sample of 160 USGS earthquake records is re-timed so the newest is
   one minute old and goes through the normal ingestion, exposure, and alert code. `make replay` plays the newest 30 percent live with
   compressed gaps. Replayed incidents say so in their summary.
3. **Accounts with generated passwords.** `python -m meridian.demo seed` creates a demonstration tenant and six accounts, one per
   role. Passwords are 24 random characters, printed once, stored as Argon2id hashes, and never written to a file. A second run reveals
   nothing; `--rotate` issues new ones. The public demonstration publishes only the read-only viewer.
4. **One orchestrating script.** `scripts/demo.sh` runs the steps in order, skips what exists, prints timings, and starts the
   servers. It uses the development database cluster, not containers, because Docker is not required to try the product.
5. **A separate container stack for production-style use.** `infra/compose` and `infra/docker` define Caddy, web, API, worker,
   migrations, PostgreSQL, and Valkey with resource limits, restart policies, health checks, log rotation, hardened containers, and an
   internal network. The API image installs `apps/api/requirements.txt`, a runtime subset of the project dependencies that was
   checked by installing it into a clean environment and running the API tests. The stack has not been built or started.

## Consequences

- `make demo` took 46 seconds on the development machine with the downloads, the Python environment, and the web build already cached.
  A truly clean clone adds the installation of the Python and Node dependencies, the downloads, and the first web build, which were not
  timed from scratch; the 20 minute target is plausible but unverified.
- The demonstration and the full system differ in what they can show; the walkthrough and the login page say what is synthetic or
  re-timed.
- The container files are untested by construction until a machine with Docker builds them.
- A defect found while capturing screenshots (the map and incident pages refetching without end because the request address
  contained the current time) was fixed and now has an end-to-end regression test.

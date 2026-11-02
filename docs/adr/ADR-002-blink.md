# ADR-002: BLINK (spike B)

- Status: accepted (no-go for this build)
- Date: 2026-10-30

## Context

The plan treats BLINK as optional: cross-encoder re-ranking of English candidates when BELA and the gazetteer
disagree, and linking of tenant asset mentions to a private catalog. The upstream repository is archived and
targets old Python and PyTorch versions.

## Decision

**No-go for this build; the feature flags stay off.** The spike was not run: BLINK's requirements (an old
`pytorch-transformers`, `faiss`, and several gigabytes of pretrained models) do not install on Python 3.14, and
running it would need the pinned isolated container the plan describes, which cannot be built on this machine. No
claim about BLINK's quality is made.

The interfaces are defined so the feature can be added later without changing the pipeline: the re-ranker takes
a `blink_score` feature (absent today), and `services/blink` documents the two endpoints. Both private-catalog linking
and cross-encoder re-ranking can be approached today with the local language model (for adjudication) and
bge-m3 embeddings (for asset name matching), which is what phase 6 will use.

## Consequences

- System 7 of the evaluation (system 6 plus BLINK re-ranking) is not run and is reported as not evaluated.
- Revisit only if a pinned container for BLINK is built and the evaluation shows a gain over system 6.

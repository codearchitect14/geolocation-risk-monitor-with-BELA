# ADR-006: BELA runtime and entity index (spike A)

- Status: accepted
- Date: 2026-10-30

## Context

The plan names BELA as the primary linker and asks (ADR-001) whether to use the bundled entity index or rebuild
one limited to places. The published inference wrapper (`multiel`) depends on `faiss-gpu`, `fairscale`, `hydra`,
and a pinned `protobuf`, none of which install on the development machine (Python 3.14, Apple silicon).

## Findings

- The released files are a 16.47 million entity index (QIDs) and a 19.8 GB float32 matrix of 300 dimensional
  entity vectors (exactly 1,200 bytes per row). Entity vectors are produced by an entity encoder that is **not
  released**, so vectors cannot be computed for places that are missing from the bundled index. Rebuilding an index
  "with BELA's entity encoder" is therefore not possible; the choice is between the bundled index and its subset.
- The checkpoints load with `weights_only=True` (plain tensors, no pickled code) and contain exactly five parts: the
  XLM-R large encoder, a projection to 300 dimensions, the mention detector, the span encoder, and the link
  classifier.
- Mention detection on the Apple GPU works with the released weights. On a four sentence probe the `wiki` checkpoint
  found the place spans (Port of Rotterdam, Valencia, Dayton, Ohio, Netherlands); the `e2e` checkpoint also tagged
  general concepts ("fire", "incendio"), which is noise for this use.

## Decision

1. Reimplement inference in `services/nel/nel_service` (about 400 lines: tokenizer, model, index, linker). It needs
   only torch, transformers, and sentencepiece, and is verified against the checkpoint keys. The code follows the
   MIT licensed BELA source; the project is not affiliated with its authors.
2. Keep the **full** index on the device as float16 (9.9 GB, chunks of one million rows) so that BELA's own
   behavior is preserved, including competition from non-place entities. A second compact matrix holds only the
   rows whose QID is in the `places` table. Each mention therefore gets BELA's top candidates and the best place
   candidates, which the type filter and router need.
3. Use `model_wiki.ckpt` by default; `model_e2e.ckpt` is evaluated as an alternative.
4. Candidates are scored with BELA's own classification head for every one of the top ten, not only the top-1.

## Consequences

- Only places that exist in Wikidata with a Wikipedia based entity vector can be linked by BELA. GeoNames-only
  places (small settlements, most facilities) reach the pipeline through the gazetteer fallback.
- Memory: about 11 GB of device memory for the service. The language model needs about 4.4 GB and bge-m3 about 1.2 GB;
  all fit on a 24 GB machine but not alongside other heavy workloads.
- Overlapping spans are resolved after detection by keeping the highest scoring span; the released code returns
  overlapping spans unchanged.

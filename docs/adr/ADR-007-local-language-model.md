# ADR-007: Local language model (spike C)

- Status: accepted
- Date: 2026-10-30

## Context

The plan calls for a 3B to 4B model served by llama.cpp with JSON-schema constrained output, used for event
labelling, adjudication of ambiguous place choices, and briefing text.

## Decision

- Model: Qwen3-4B-Instruct-2507 (Apache-2.0), quantized to Q4_K_M. The authors publish no GGUF files, so the build
  from the `unsloth/Qwen3-4B-Instruct-2507-GGUF` repository is used at a pinned revision. The download script
  verifies the SHA-256 reported by the Hub (`services/llm/fetch_model.py`).
- Server: `llama-server` from Homebrew (llama.cpp 0.7.0, Metal), all layers offloaded, localhost only, two slots,
  temperature 0 (`services/llm/run_server.sh`).
- Client (`meridian/llm/client.py`) sends a JSON schema in `response_format` and validates the reply with pydantic.
  Article text is wrapped in delimiters, and the system prompt states it is untrusted data.
- Prompts are versioned (`event_label_v1`, `adjudicate_v1`) and the version is stored with each decision.

## Spike results (`docs/spikes/spike_c_llm.json`)

| Measure | Result |
|---|---|
| Prompts | 21 (10 event labels, 5 place choices, 5 briefings, 1 injection attempt) |
| Schema-valid outputs | 21 of 21 |
| Event type correct | 10 of 10 headlines (4 of 10 before type definitions were added to the prompt) |
| Place choice correct | 5 of 5 |
| Injected instruction obeyed | no |
| Speed | median 80 tokens per second |
| Server memory | about 4.4 GB resident |

The headline sample is a smoke test, not an accuracy estimate: 10 items cannot support a rate. Event label accuracy
is measured on the event gold set in phase 4. One output needs review: an M6.1 earthquake received severity 1, so
severity guidance in the prompt should be tightened before it feeds exposure scores.

## Consequences

- Two lessons from the spike are now rules: ask for the reason before the label (so the model reasons before it
  commits), and put definitions of every label in the prompt.
- Constrained decoding guarantees valid JSON but not correct content; every model output is an input to a score and
  is shown with its evidence, never the final alert decision (plan section 10).

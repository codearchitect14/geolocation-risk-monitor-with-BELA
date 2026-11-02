# Local language model

Qwen3-4B-Instruct-2507 (Apache-2.0), Q4_K_M, served by llama.cpp with Metal. See `docs/adr/ADR-007-local-language-model.md`.

```
brew install llama.cpp
make llm-fetch     # downloads the GGUF (2.5 GB) and verifies its SHA-256
make llm-up        # llama-server on 127.0.0.1:8081, all layers on the GPU
make llm-down
.venv/bin/python services/llm/spike_prompts.py   # spike C: 21 prompts, speed, schema validity
```

The server binds to localhost and has no tools or network access beyond the model itself. Clients go through
`meridian.llm.client.LlmClient`, which enforces a JSON schema, temperature 0, token and time limits, and wraps article
text in delimiters as untrusted data.

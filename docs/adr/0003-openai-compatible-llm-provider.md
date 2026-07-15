# 0003. LLM via any OpenAI-compatible endpoint (DeepSeek default)

- **Status:** Accepted (documenting a decision already in the code)
- **Date:** 2026-07-14

## Context
Two core features call an LLM: parsing extracted cookbook text into structured recipes
(`services/ingestion.py`) and reading grocery photos for the pantry scan
(`services/pantry_vision.py`). Both go through one helper, `services/llm.py::chat_completion`,
which POSTs to `{OPENAI_BASE_URL}/chat/completions` with `OPENAI_API_KEY` and `OPENAI_MODEL`.

## Decision
Depend on the **OpenAI Chat Completions API shape**, not on a specific vendor. Provider,
model, and key are the three env vars `OPENAI_BASE_URL` / `OPENAI_MODEL` / `OPENAI_API_KEY`.
Default to DeepSeek; keep a deterministic non-LLM fallback path when no key is set so local
dev and CI work offline.

## Alternatives considered
- **Hard-code one vendor SDK (OpenAI or Anthropic native).** Rejected: locks us in and makes
  self-hosting/cost-tuning harder. The friend-group deploy benefits from swapping providers.
- **A full abstraction layer over multiple native SDKs.** Rejected as premature: the
  OpenAI-compatible surface already covers OpenAI, DeepSeek, OpenRouter (a gateway to
  Anthropic/Gemini/etc.), Together, and local vLLM/Ollama. Build the abstraction only if a
  must-have provider is *not* OpenAI-compatible.

## Consequences
- Swap providers with config, no code change; costs and models are tunable per deployment.
- **Caveat (tracked):** the pantry photo scan sends multimodal `image_url` parts and asks for
  `response_format: json_object`. The chosen model must support vision *in OpenAI format* —
  the default `deepseek-v4-flash` likely does not. Text parsing works on any decent chat
  model; vision must be verified per provider before relying on it.
- Operational risk: an API key is real money. Cap/rate-limit it; the offline fallback keeps
  dev/CI from spending.

# GitHub Copilot Pro — Available AI Models

> Source: [GitHub Docs — Supported AI models in GitHub Copilot](https://docs.github.com/en/copilot/reference/ai-models/supported-models)
> Last verified: March 12, 2026

---

## ⚠️ Important: Chat UI vs Inference API

| | Copilot Chat UI | `models.github.ai/inference` API |
|---|---|---|
| Claude (Anthropic) | ✅ Available | ❌ Not available |
| GPT-4.1 / GPT-5 (OpenAI) | ✅ Available | ✅ Available |
| Meta, Mistral, xAI, etc. | ✅ Available | ✅ Available |

**Claude models can only be used interactively in the Copilot Chat UI.** For programmatic use via the GitHub Models API (e.g. the agent pipeline), use OpenAI or other supported models.

### Available models via `models.github.ai/inference` API (as of March 2026)

| Model ID | Tier | Notes |
|----------|------|-------|
| `openai/gpt-4.1` | high (50/day) | Best quality — researcher, writer, editor |
| `openai/gpt-4o` | high (50/day) | GPT-4o fallback |
| `openai/gpt-4.1-mini` | low (500/day) | Budget — orchestrator, publisher, indexer |
| `openai/gpt-4.1-nano` | low (500/day) | Cheapest fallback |
| `openai/gpt-5` | custom | Available but custom limits |
| `openai/gpt-5-mini` | custom | Available but custom limits |
| `meta/llama-4-maverick-17b-128e-instruct-fp8` | — | Open weights option |
| `xai/grok-3` | custom | — |
| `mistral-ai/mistral-medium-2505` | — | — |

---

## OpenAI

| Model | Status |
|-------|--------|
| GPT-4.1 | GA |
| GPT-5 mini | GA |
| GPT-5.1 | GA |
| GPT-5.1-Codex | GA |
| GPT-5.1-Codex-Mini | Public Preview |
| GPT-5.1-Codex-Max | GA |
| GPT-5.2 | GA |
| GPT-5.2-Codex | GA |
| GPT-5.3-Codex | GA |
| GPT-5.4 | GA |

## Anthropic

| Model | Status |
|-------|--------|
| Claude Haiku 4.5 | GA |
| Claude Sonnet 4 | GA |
| Claude Sonnet 4.5 | GA |
| Claude Sonnet 4.6 | GA |
| Claude Opus 4.5 | GA |
| Claude Opus 4.6 | GA |

## Google

| Model | Status |
|-------|--------|
| Gemini 2.5 Pro | GA |
| Gemini 3 Flash | Public Preview |
| Gemini 3 Pro | Public Preview |
| Gemini 3.1 Pro | Public Preview |

## xAI

| Model | Status |
|-------|--------|
| Grok Code Fast 1 | GA |

## Fine-tuned

| Model | Base | Status |
|-------|------|--------|
| Raptor mini | GPT-5 mini | Public Preview |

---

## Not included in Pro

| Model | Available In |
|-------|-------------|
| Claude Opus 4.6 (fast mode) | Pro+ only |
| Goldeneye | Free tier experiment only |

---

## Notes

- **GA (Generally Available)** — stable and production-ready.
- **Public Preview** — available to use but may change; not recommended for production.
- Models consume **premium requests** at different multipliers. Zero-multiplier models (GPT-4.1, GPT-5 mini, Grok Code Fast 1, Raptor mini) do not count against your monthly allowance.
- Pro plan includes **300 premium requests/month**. Additional requests available at $0.04/request.

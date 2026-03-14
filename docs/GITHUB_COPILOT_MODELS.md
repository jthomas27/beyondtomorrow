# GitHub Copilot Pro+ — Available AI Models

> Source: Live catalog via `https://models.github.ai/catalog/models`
> Last verified: March 14, 2026

**Copilot Pro+ gives unlimited premium requests across all tiers.**

---

## ⚠️ Important: Chat UI vs Inference API

| | Copilot Chat UI | `models.github.ai/inference` API |
|---|---|---|
| Claude (Anthropic) | ✅ Available | ❌ Not available |
| GPT-4.1 / GPT-5 (OpenAI) | ✅ Available | ✅ Available |
| Meta, Mistral, xAI, DeepSeek, etc. | ✅ Available | ✅ Available |

**Claude models can only be used interactively in the Copilot Chat UI.** For programmatic use via the GitHub Models API (e.g. the agent pipeline), use OpenAI or other supported models.

---

## API Models — Live Catalog

Token limits are per-request. With Pro+, there are no daily request caps. The tier labels are legacy from the free/Pro plans.

### CUSTOM TIER (flagship + reasoning models)

| Model ID | Max Input | Max Output | Modalities | Capabilities |
|----------|-----------|------------|------------|--------------|
| `openai/gpt-5` | 200,000 | 100,000 | text+image → text | agents, agentsV2, reasoning, tool-calling, streaming |
| `openai/gpt-5-chat` | 200,000 | 100,000 | text+image → text | agents, agentsV2, reasoning, tool-calling, streaming |
| `openai/gpt-5-mini` | 200,000 | 100,000 | text+image → text | agents, agentsV2, reasoning, tool-calling, streaming |
| `openai/gpt-5-nano` | 200,000 | 100,000 | text+image → text | agents, agentsV2, reasoning, tool-calling, streaming |
| `openai/o1` | 200,000 | 100,000 | text+image → text | agents, agentsV2, reasoning, tool-calling |
| `openai/o1-mini` | 128,000 | 65,536 | text → text | reasoning, streaming, agentsV2 |
| `openai/o1-preview` | 128,000 | 32,768 | text → text | agentsV2, reasoning |
| `openai/o3` | 200,000 | 100,000 | text+image → text | agents, agentsV2, reasoning, tool-calling, streaming |
| `openai/o3-mini` | 200,000 | 100,000 | text → text | agents, agentsV2, reasoning, tool-calling, streaming |
| `openai/o4-mini` | 200,000 | 100,000 | text+image → text | agents, agentsV2, reasoning, tool-calling, streaming |
| `deepseek/deepseek-r1` | 128,000 | 4,096 | text → text | reasoning, streaming, tool-calling |
| `deepseek/deepseek-r1-0528` | 128,000 | 4,096 | text → text | agentsV2, reasoning, streaming, tool-calling |
| `xai/grok-3` | 131,072 | 4,096 | text → text | agentsV2 |
| `xai/grok-3-mini` | 131,072 | 4,096 | text → text | agentsV2 |
| `microsoft/mai-ds-r1` | 128,000 | 4,096 | text → text | agentsV2, reasoning, streaming |

### HIGH TIER

| Model ID | Max Input | Max Output | Modalities | Capabilities |
|----------|-----------|------------|------------|--------------|
| `openai/gpt-4.1` | 1,048,576 | 32,768 | text+image → text | agents, agentsV2, tool-calling, streaming |
| `openai/gpt-4o` | 131,072 | 16,384 | text+image+audio → text | agents, agentsV2, assistants, tool-calling, streaming |
| `meta/llama-4-maverick-17b-128e-instruct-fp8` | 1,000,000 | 4,096 | text+image → text | agents, agentsV2, assistants, tool-calling, streaming |
| `meta/llama-4-scout-17b-16e-instruct` | 10,000,000 | 4,096 | text+image → text | agents, assistants, tool-calling, streaming |
| `meta/llama-3.3-70b-instruct` | 128,000 | 4,096 | text → text | agentsV2, streaming |
| `meta/llama-3.2-90b-vision-instruct` | 128,000 | 4,096 | text+image+audio → text | streaming |
| `meta/meta-llama-3.1-405b-instruct` | 131,072 | 4,096 | text → text | agents |
| `deepseek/deepseek-v3-0324` | 128,000 | 4,096 | text → text | agentsV2, streaming, tool-calling |
| `ai21-labs/ai21-jamba-1.5-large` | 262,144 | 4,096 | text → text | streaming, tool-calling |
| `cohere/cohere-command-r-plus-08-2024` | 131,072 | 4,096 | text → text | streaming, tool-calling |

### LOW TIER

| Model ID | Max Input | Max Output | Modalities | Capabilities |
|----------|-----------|------------|------------|--------------|
| `openai/gpt-4.1-mini` | 1,048,576 | 32,768 | text+image → text | agents, agentsV2, tool-calling, streaming |
| `openai/gpt-4.1-nano` | 1,048,576 | 32,768 | text+image → text | agents, agentsV2, tool-calling, streaming |
| `openai/gpt-4o-mini` | 131,072 | 4,096 | text+image+audio → text | agents, agentsV2, assistants, tool-calling, streaming |
| `mistral-ai/mistral-medium-2505` | 128,000 | 4,096 | text+image → text | streaming, tool-calling |
| `mistral-ai/mistral-small-2503` | 128,000 | 4,096 | text+image → text | agents, assistants, tool-calling, streaming |
| `mistral-ai/codestral-2501` | 256,000 | 4,096 | text → text | streaming |
| `mistral-ai/ministral-3b` | 131,072 | 4,096 | text → text | streaming, tool-calling |
| `meta/llama-3.2-11b-vision-instruct` | 128,000 | 4,096 | text+image+audio → text | streaming |
| `meta/meta-llama-3.1-8b-instruct` | 131,072 | 4,096 | text → text | streaming |
| `cohere/cohere-command-a` | 131,072 | 4,096 | text → text | — |
| `cohere/cohere-command-r-08-2024` | 131,072 | 4,096 | text → text | streaming |
| `microsoft/phi-4` | 16,384 | 16,384 | text → text | — |
| `microsoft/phi-4-mini-instruct` | 128,000 | 4,096 | text → text | — |
| `microsoft/phi-4-mini-reasoning` | 128,000 | 4,096 | text → text | reasoning |
| `microsoft/phi-4-multimodal-instruct` | 128,000 | 4,096 | audio+image+text → text | streaming |
| `microsoft/phi-4-reasoning` | 32,768 | 4,096 | text → text | reasoning, streaming |

### EMBEDDINGS TIER

| Model ID | Max Input | Output | Modalities |
|----------|-----------|--------|------------|
| `openai/text-embedding-3-large` | 8,191 | — | text → embeddings |
| `openai/text-embedding-3-small` | 8,191 | — | text → embeddings |

---

## Pipeline Model Assignments (recommended)

| Agent | Model | Reason |
|-------|-------|--------|
| Researcher | `openai/gpt-5` | 200k context, reasoning, tool-calling |
| Writer | `openai/gpt-5` | Best prose quality |
| Editor | `openai/gpt-5` | Reasoning for fact-check |
| Orchestrator | `openai/gpt-5-mini` | Fast routing, 200k context |
| Publisher | `openai/gpt-5-mini` | Deterministic metadata extraction + Ghost API call |
| Indexer | `openai/gpt-5-mini` | Minimal reasoning needed |

---

## Notes

- **Copilot Pro+** — unlimited premium requests. No daily caps apply.
- **Copilot Pro** — 300 premium requests/month; custom-tier models counted at higher multiplier.
- Claude models (Haiku/Sonnet/Opus) are available in the **Copilot Chat UI only** — not via the inference API.
- The `gpt-5-chat` variant is the conversational-optimised version of `gpt-5` (same token limits).
- `meta/llama-4-scout-17b-16e-instruct` has a 10M token context window — largest available.

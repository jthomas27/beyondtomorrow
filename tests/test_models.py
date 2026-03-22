import asyncio
import os
from openai import AsyncOpenAI

token = os.environ["GITHUB_TOKEN"]
client = AsyncOpenAI(base_url="https://models.github.ai/inference", api_key=token)

MODELS = [
    "gpt-4o-mini",
    "gpt-4o",
    "claude-3-5-sonnet",
    "claude-3-haiku",
    "claude-3-opus",
    "anthropic/claude-3-5-sonnet",
    "anthropic/claude-3-haiku",
    "anthropic/claude-3-7-sonnet",
    "claude-3-7-sonnet-20250219",
    "claude-3-5-sonnet-20241022",
    "claude-3-5-haiku-20241022",
    "Meta-Llama-3.1-8B-Instruct",
    "Meta-Llama-3.1-70B-Instruct",
    "Mistral-large",
    "Mistral-small",
]

async def main():
    for model in MODELS:
        try:
            r = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=5,
            )
            print(f"OK: {model}")
        except Exception as e:
            print(f"FAIL {model}: {str(e)[:100]}")

asyncio.run(main())

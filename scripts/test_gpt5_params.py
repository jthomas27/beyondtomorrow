"""Test whether gpt-5 accepts max_completion_tokens vs max_tokens."""
import asyncio
import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

client = AsyncOpenAI(
    base_url="https://models.inference.ai.azure.com",
    api_key=os.environ["GITHUB_TOKEN"],
)


async def test_gpt5():
    for model in ["openai/gpt-5", "openai/gpt-5-mini"]:
        print(f"\n--- {model} ---")
        for param, kwargs in [
            ("max_completion_tokens", {"max_completion_tokens": 50}),
            ("max_tokens", {"max_tokens": 50}),
        ]:
            try:
                r = await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "Say hi."}],
                    **kwargs,
                )
                print(f"  {param}: OK -> {r.choices[0].message.content[:40]!r}")
            except Exception as e:
                print(f"  {param}: FAILED {type(e).__name__} [{getattr(e, 'status_code', '?')}]: {str(e)[:120]}")


asyncio.run(test_gpt5())

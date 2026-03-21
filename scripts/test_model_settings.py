import asyncio, os
from dotenv import load_dotenv
load_dotenv()
from pipeline.setup import init_github_models
from pipeline._sdk import Agent, Runner, ModelSettings, set_default_openai_client

CASES = [
    ("openai/gpt-5",      ModelSettings(extra_body={"max_completion_tokens": 200})),
    ("openai/gpt-5-mini", ModelSettings(extra_body={"max_completion_tokens": 200})),
    ("openai/gpt-4.1",    ModelSettings(temperature=0.7, max_tokens=200)),
]

async def test():
    client = init_github_models()
    set_default_openai_client(client)
    for model, settings in CASES:
        agent = Agent(
            name="T",
            instructions="You are a helpful assistant. Answer concisely.",
            model=model,
            model_settings=settings,
        )
        try:
            r = await asyncio.wait_for(Runner.run(agent, input="What is 2+2? Answer in one sentence."), timeout=30)
            out = str(r.final_output)[:80]
            print(f"{model}: OK -> {out!r}")
        except Exception as e:
            code = getattr(e, "status_code", "?")
            print(f"{model}: FAIL {type(e).__name__} [{code}]: {str(e)[:120]}")

asyncio.run(test())

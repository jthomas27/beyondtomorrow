import asyncio, os
from openai import AsyncOpenAI
from dotenv import load_dotenv
load_dotenv()
client = AsyncOpenAI(base_url='https://models.github.ai/inference', api_key=os.environ['GITHUB_TOKEN'])
async def test():
    for model in ['openai/gpt-5', 'openai/gpt-5-mini', 'openai/gpt-4.1']:
        try:
            r = await client.chat.completions.create(model=model, messages=[{'role':'user','content':'Hi'}], max_tokens=10)
            print(f'{model}: OK -> {r.choices[0].message.content!r}')
        except Exception as e:
            print(f'{model}: FAIL [{getattr(e,"status_code","?")}] {str(e)[:120]}')
asyncio.run(test())

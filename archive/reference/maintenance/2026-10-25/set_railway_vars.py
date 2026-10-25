"""
One-shot script: copy LinkedIn vars from .env to the Railway email-worker service.
Run from project root: .venv/bin/python scripts/set_railway_vars.py
"""
import asyncio
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

RAILWAY_TOKEN = os.environ.get("RAILWAY_TOKEN", "").strip()
PROJECT_ID = "752fdaea-fd96-4521-bec6-b7d5ef451270"
ENVIRONMENT_ID = "c9dfebe4-097a-4151-be37-2b1fcd414e74"
SERVICE_ID = "15b13afb-8515-49e9-ab38-7e138069064f"  # email-worker

KEYS = [
    "LINKEDIN_CLIENT_ID",
    "LINKEDIN_CLIENT_SECRET",
    "LINKEDIN_ACCESS_TOKEN",
    "LINKEDIN_PERSON_URN",
    "LINKEDIN_TOKEN_EXPIRES",
]


async def main() -> None:
    missing = [k for k in KEYS if not os.environ.get(k, "").strip()]
    if missing:
        print(f"ERROR: missing from .env: {missing}")
        sys.exit(1)

    vars_to_set = {k: os.environ[k] for k in KEYS}

    mutation = """
    mutation UpsertVariables($input: VariableCollectionUpsertInput!) {
      variableCollectionUpsert(input: $input)
    }
    """
    payload = {
        "query": mutation,
        "variables": {
            "input": {
                "projectId": PROJECT_ID,
                "environmentId": ENVIRONMENT_ID,
                "serviceId": SERVICE_ID,
                "variables": vars_to_set,
            }
        },
    }

    headers = {
        "Authorization": f"Bearer {RAILWAY_TOKEN}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://backboard.railway.com/graphql/v2",
            json=payload,
            headers=headers,
            timeout=15,
        )

    if r.status_code != 200:
        print(f"HTTP {r.status_code}: {r.text}")
        sys.exit(1)

    data = r.json()
    if "errors" in data:
        print(f"GraphQL errors: {data['errors']}")
        sys.exit(1)

    print(f"Success — {len(vars_to_set)} variables set on email-worker:")
    for k in KEYS:
        v = vars_to_set[k]
        print(f"  ✓ {k}: {v[:8]}...")


asyncio.run(main())

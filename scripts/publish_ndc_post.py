"""Directly publish the NDC draft to Ghost, bypassing the agent layer."""
import asyncio
import os
import sys

sys.path.insert(0, "/Users/jeremiah/Projects/BeyondTomorrow.World")
os.chdir("/Users/jeremiah/Projects/BeyondTomorrow.World")

from dotenv import load_dotenv
load_dotenv()

from pipeline.setup import init_github_models
init_github_models()

from pipeline.tools.ghost import publish_file_to_ghost
import json


async def main():
    # publish_file_to_ghost is a FunctionTool — invoke via on_invoke_tool
    result = await publish_file_to_ghost.on_invoke_tool(
        ctx=None,
        input=json.dumps({
            "filename": "2026-03-20-explore-the-failure-of.md",
            "feature_image_url": "https://beyondtomorrow.world/content/images/2026/03/marc-olivier-jodoin-NqOInJ-ttqM-unsplash-3.jpg",
            "status": "published",
        }),
    )
    print(result)


asyncio.run(main())

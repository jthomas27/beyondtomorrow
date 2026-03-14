"""Resume the blog pipeline from the Writer step using an existing research file in the DB."""
import asyncio
import re
import sys

sys.path.insert(0, "/Users/jeremiah/Projects/BeyondTomorrow.World")

from agents._sdk import Runner
from agents.setup import init_github_models, ensure_db_schema
from agents.definitions import writer, editor, publisher, indexer


async def run() -> None:
    init_github_models()
    await ensure_db_schema()

    research_file = "2026-03-12-research-iran-war-ai-energy.json"
    date_prefix = "2026-03-12"
    feature_image = "https://beyondtomorrow.world/content/images/2026/03/futuristic-city-3.png"

    # Override to gpt-5-mini for quick resume runs
    writer_agent = writer.clone(handoffs=[], model="openai/gpt-5-mini")
    editor_agent = editor.clone(handoffs=[], model="openai/gpt-5-mini")
    publisher_agent = publisher.clone(handoffs=[])
    indexer_agent = indexer.clone(handoffs=[])

    # --- Writer ---
    print("Running Writer...")
    wr = await Runner.run(
        writer_agent,
        input=(
            f"Write a blog post based on the following research.\n"
            f"Research file: {research_file}\n"
            f"Original task: BLOG: [TEST] Iran war oil prices and AI energy costs. This is a TEST POST.\n"
            f"Feature image URL: {feature_image}\n\n"
            f"Read the research file, write the post, and save it as "
            f"{date_prefix}-iran-ai-energy-costs.md "
            f"(bare filename only — do NOT prefix with research/)."
        ),
        max_turns=10,
    )
    draft_output = wr.final_output
    print("Writer done:", draft_output)
    m = re.search(r"[\w.\-]+\.md", draft_output)
    draft_file = m.group(0) if m else f"{date_prefix}-iran-ai-energy-costs.md"

    # --- Editor ---
    print("\nRunning Editor...")
    edited_name = draft_file.replace(".md", "-edited.md")
    er = await Runner.run(
        editor_agent,
        input=(
            f"Edit and fact-check this blog post draft.\n"
            f"Draft file: {draft_file}\n"
            f"Research file (for fact-checking): {research_file}\n\n"
            f"Save the edited version as {edited_name} "
            f"(bare filename only — do NOT prefix with research/)."
        ),
        max_turns=10,
    )
    edited_output = er.final_output
    print("Editor done:", edited_output)
    m2 = re.search(r"[\w.\-]+-edited\.md", edited_output)
    edited_file = m2.group(0) if m2 else edited_name

    # --- Publisher ---
    print("\nRunning Publisher...")
    pr = await Runner.run(
        publisher_agent,
        input=(
            f"Publish this blog post to Ghost CMS as a draft.\n"
            f"Post file: {edited_file}\n"
            f"Call publish_to_ghost with filename='{edited_file}' and status='draft'."
        ),
        max_turns=5,
    )
    print("Publisher done:", pr.final_output)

    # --- Indexer ---
    print("\nRunning Indexer...")
    ir = await Runner.run(
        indexer_agent,
        input=f"Index this research file into the knowledge corpus: {research_file}",
        max_turns=10,
    )
    print("Indexer done:", ir.final_output)


asyncio.run(run())

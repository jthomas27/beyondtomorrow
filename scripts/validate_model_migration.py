"""Live, bounded SDK tool-call checks. No database, publishing, or messaging tools.

Run from the project root: .venv/bin/python -m scripts.validate_model_migration
"""
import asyncio
import argparse
import json
import re
from dataclasses import replace
from pathlib import Path

from agents import Agent, Runner, function_tool
from agents.tracing import set_tracing_disabled
from dotenv import load_dotenv
from pydantic import BaseModel

from pipeline.config_loader import get_models
from pipeline.definitions import model_settings_for
from pipeline.setup import init_openai


class ProbeResult(BaseModel):
    verified: bool
    value: int


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research-file", type=Path, help="Additionally validate Writer/Editor using saved research, with file tools only")
    parser.add_argument("--editorial-only", action="store_true", help="Reuse prior SDK probes and run only the article check")
    parser.add_argument("--case-label", default="sol", help="Distinct local artifact label")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9-]+", args.case_label) or (args.editorial_only and not args.research_file):
        parser.error("Use a lowercase case label and supply research for editorial-only checks")
    if args.research_file:
        from pipeline.main import _require_research_evidence
        _require_research_evidence(args.research_file.read_text())
    load_dotenv(".env")
    set_tracing_disabled(True)
    client = init_openai()
    try:
        for role in (() if args.editorial_only else ("researcher", "writer", "editor", "orchestrator", "publisher", "indexer")):
            calls = []

            @function_tool
            def read_fixture() -> str:
                """Read the fixed validation fact; has no external side effects."""
                calls.append(True)
                return json.dumps({"value": 42, "verified": True})

            cfg = get_models()["agents"][role]
            agent = Agent(
                name=role,
                model=cfg["model"],
                model_settings=replace(model_settings_for(role), tool_choice="auto"),
                instructions="Call read_fixture once, then return its verified and value fields. Do not guess.",
                tools=[read_fixture], output_type=ProbeResult,
            )
            try:
                result = await Runner.run(agent, "Verify the fixture.", max_turns=4)
                assert calls and result.final_output == ProbeResult(verified=True, value=42)
                usage = result.context_wrapper.usage
                print(f"PASS {role} {cfg['model']} turns={len(result.raw_responses)} input={usage.input_tokens} output={usage.output_tokens}", flush=True)
            except Exception as exc:
                # Do not expose response bodies, headers, or credential-bearing exceptions.
                print(f"FAIL {role} {cfg['model']} {type(exc).__name__} status={getattr(exc, 'status_code', None)}")
                raise SystemExit(1) from None
        specialist = Agent(
            name="ValidationSpecialist", model=get_models()["agents"]["writer"]["model"],
            model_settings=model_settings_for("writer"),
            instructions="Return verified=true and value=42 as the fixed handoff validation result.",
            output_type=ProbeResult,
        )
        router = Agent(
            name="ValidationRouter", model=get_models()["agents"]["orchestrator"]["model"],
            model_settings=model_settings_for("orchestrator"),
            instructions="Transfer this task to ValidationSpecialist immediately.", handoffs=[specialist],
        )
        if not args.editorial_only:
            result = await Runner.run(router, "Validate the handoff.", max_turns=4)
            assert result.last_agent.name == "ValidationSpecialist"
            assert result.final_output == ProbeResult(verified=True, value=42)
            print("PASS Luna-to-Sol SDK handoff", flush=True)
        if args.research_file:
            from pipeline.definitions import writer, editor
            from pipeline.main import _compact_research
            from pipeline.tools import read_research_file, write_research_file

            # Strip every external tool and handoff. Only local validation files can be written.
            research = args.research_file.read_text()
            evidence = _compact_research(research, max_chars=8000)
            data = json.loads(research)
            topic = data.get("topic", "the supplied research findings")
            brief = data.get("evaluation_instruction", "")
            source_urls = {source["url"].rstrip("/") for source in data["source_list"]}
            draft = f"migration-validation-{args.case_label}-draft.md"
            edited = f"migration-validation-{args.case_label}-draft-edited.md"
            metrics = []
            for original, task, expected in (
                (writer, f"Write a validation article about {topic}. Save it as {draft}. {brief}\nResearch:\n{evidence}", draft),
                (editor, f"Edit {draft}, verifying claims against the evidence below. Save as {edited}. {brief}\nResearch:\n{evidence}", edited),
            ):
                agent = original.clone(handoffs=[], tools=[read_research_file, write_research_file])
                before = (Path("research") / expected).stat().st_mtime_ns if (Path("research") / expected).exists() else 0
                result = await asyncio.wait_for(Runner.run(agent, task, max_turns=6), timeout=300)
                path = Path("research") / expected
                assert path.exists() and path.stat().st_mtime_ns > before, f"{original.name} did not save output"
                content = path.read_text()
                assert content.startswith("---") and len(content.split()) >= 500, f"{original.name} output incomplete"
                assert "https://" in content, f"{original.name} output has no source links"
                usage = result.context_wrapper.usage
                links = set(re.findall(r"\]\((https?://[^)]+)\)", content))
                unknown = [url for url in links if url.split("#")[0].rstrip("/") not in source_urls]
                assert not unknown, f"{original.name} introduced source URLs outside the supplied evidence"
                metrics.append({"agent": original.name, "model": original.model, "input_tokens": usage.input_tokens,
                                "output_tokens": usage.output_tokens, "words": len(content.split()), "sources": sorted(links), "file": str(path)})
                print(f"PASS {original.name} saved={expected} words={len(content.split())} input={usage.input_tokens} output={usage.output_tokens}", flush=True)
            (Path("research") / f"migration-validation-{args.case_label}-metrics.json").write_text(json.dumps(metrics, indent=2))
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())

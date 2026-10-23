"""Migration contracts: wire parameters, tool loop, retry policy, and evidence."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from agents import Agent, Runner, function_tool, set_tracing_disabled
from agents.models.openai_responses import OpenAIResponsesModel
from agents.usage import Usage
from openai import AsyncOpenAI, BadRequestError

from pipeline.config_loader import get_models
from pipeline.definitions import model_settings_for
from pipeline.main import _compact_research, _fix_title_via_llm, _run_agent_with_fallback, _require_research_evidence
from pipeline.model_usage import ModelUsageHooks


@pytest.mark.parametrize("role", ["researcher", "writer", "editor", "publisher", "indexer", "orchestrator"])
async def test_responses_tool_loop_serializes_supported_parameters(role):
    """Exercise the installed SDK through HTTP serialization and a complete tool round trip."""
    set_tracing_disabled(True)
    requests = []
    calls = []

    @function_tool
    def read_fact() -> str:
        """Read a local test fact."""
        calls.append(True)
        return "42"

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        assert request.url.path == "/v1/responses"
        assert "max_output_tokens" in body
        assert "max_completion_tokens" not in body and "max_tokens" not in body
        if role in {"researcher", "writer", "editor"}:
            assert body["reasoning"]["effort"] == "low"
            assert "temperature" not in body
        else:
            assert body["reasoning"]["effort"] == "none"
        output = ([{"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "read_fact", "arguments": "{}", "status": "completed"}]
                  if len(requests) == 1 else
                  [{"type": "message", "id": "msg_1", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": "42", "annotations": []}]}])
        return httpx.Response(200, json={
            "id": f"resp_{len(requests)}", "object": "response", "created_at": 1,
            "model": body["model"], "status": "completed", "output": output,
            "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
            "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
        })

    async with AsyncOpenAI(api_key="test", http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))) as client:
        agent = Agent(name=role, model=OpenAIResponsesModel(get_models()["agents"][role]["model"], client),
                      model_settings=model_settings_for(role), tools=[read_fact])
        result = await Runner.run(agent, "Read the fact.", max_turns=3)
    assert result.final_output == "42" and calls == [True]
    assert len(requests) == 2
    assert any(item.get("type") == "function_call_output" for item in requests[1]["input"])


async def test_usage_logs_each_completed_turn_using_actual_model(mocker):
    log_call = mocker.patch("pipeline.model_usage.log_model_call", new=AsyncMock())
    hook = ModelUsageHooks(object(), run_log=SimpleNamespace(run_id="test-run"))
    agent = SimpleNamespace(name="Writer", model="gpt-6-luna")
    await hook.on_llm_end(None, agent, SimpleNamespace(usage=Usage(input_tokens=12, output_tokens=3)))
    assert log_call.call_args.args[1] == "gpt-6-luna"
    assert log_call.call_args.kwargs == {"tokens_in": 12, "tokens_out": 3, "run_id": "test-run", "phase": "writer"}


async def test_content_budget_exhaustion_cannot_be_swallowed(mocker):
    from pipeline.degradation import ModelBudgetExceeded
    mocker.patch("pipeline.degradation.check_model_budget", new=AsyncMock(return_value={"available": False}))
    mocker.patch("pipeline.guardrails.check_model_budget", new=AsyncMock(return_value={"rpm_exceeded": False, "pct": 99}))
    run = mocker.patch("pipeline._sdk.Runner.run", new=AsyncMock())
    agent = Agent(name="Writer", model="gpt-6.1-sol", model_settings=model_settings_for("writer"))
    with pytest.raises(ModelBudgetExceeded):
        await _run_agent_with_fallback(agent, "test", agent_name="Writer", pool=object())
    run.assert_not_awaited()


async def test_413_retry_preserves_reasoning_and_does_not_downgrade(mocker):
    from openai import APIStatusError
    agent = Agent(name="Writer", model="gpt-6.1-sol", model_settings=model_settings_for("writer"))
    original = agent.model_settings
    observed = []
    async def run(current, **kwargs):
        observed.append((current.model, current.model_settings))
        if len(observed) == 1:
            raise APIStatusError("large", response=httpx.Response(413, request=httpx.Request("POST", "https://example.test")), body=None)
        return SimpleNamespace(final_output="saved", raw_responses=[])
    mocker.patch("pipeline._sdk.Runner.run", side_effect=run)
    mocker.patch("pipeline.main.asyncio.sleep", new=AsyncMock())
    await _run_agent_with_fallback(agent, "test", agent_name="Writer", pool=None)
    assert observed[1][0] == "gpt-6.1-sol"
    assert observed[1][1].reasoning.effort == "low"
    assert observed[1][1].temperature is None
    assert observed[1][1].max_tokens == original.max_tokens - 500
    assert agent.model_settings is original


async def test_bad_parameter_fails_without_retries(mocker):
    run = mocker.patch("pipeline._sdk.Runner.run", new=AsyncMock(side_effect=BadRequestError(
        "unsupported parameter", response=httpx.Response(400, request=httpx.Request("POST", "https://example.test")), body=None)))
    agent = Agent(name="Writer", model="gpt-6.1-sol", model_settings=model_settings_for("writer"))
    with pytest.raises(BadRequestError):
        await _run_agent_with_fallback(agent, "test", agent_name="Writer", pool=None)
    run.assert_awaited_once()


def test_editor_context_preserves_claim_sources_and_uncertainty():
    data = {"key_findings": [{"finding": "A supported claim", "confidence": "medium", "sources": ["https://example.test/study"]}],
            "gaps": ["Conflicting measurement"], "suggested_angles": ["padding " * 2000]}
    compact = _compact_research(json.dumps(data), max_chars=8000)
    assert "https://example.test/study" in compact
    assert "Conflicting measurement" in compact
    assert len(compact) < 8100


async def test_title_repair_uses_luna_responses_and_validates_length(tmp_path):
    path = tmp_path / "post.md"
    path.write_text("---\ntitle: This title is far too long and really ought to be shortened today\n---\nBody")
    client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(output_text="A Better Title With Five Words"))))
    assert await _fix_title_via_llm(client, path)
    args = client.responses.create.call_args.kwargs
    assert args["model"] == "gpt-6-luna" and args["reasoning"].effort == "none"
    assert "max_output_tokens" in args and "messages" not in args
    assert "Body" in path.read_text()


@pytest.mark.parametrize("research", ["not json", "null", "{}", '{"key_findings": [], "source_list": []}'])
def test_missing_evidence_stops_writing(research):
    with pytest.raises(RuntimeError, match="defer writing"):
        _require_research_evidence(research)


def test_evidence_gate_requires_association_not_just_urls():
    data = {"key_findings": [{"finding": "Supported", "sources": ["https://example.test/a"]}],
            "source_list": [{"url": f"https://example.test/{suffix}"} for suffix in "abc"]}
    _require_research_evidence(json.dumps(data))
    data["key_findings"][0]["sources"] = ["https://unrelated.test"]
    with pytest.raises(RuntimeError):
        _require_research_evidence(json.dumps(data))


def test_missing_agent_configuration_keeps_safe_settings(monkeypatch):
    import pipeline.definitions as definitions
    monkeypatch.setattr(definitions, "_models", {})
    assert model_settings_for("writer").reasoning.effort == "low"
    assert model_settings_for("writer").temperature is None
    assert model_settings_for("publisher").reasoning.effort == "none"


async def test_publisher_timeout_does_not_replay_external_tools(mocker):
    import asyncio
    run = mocker.patch("pipeline._sdk.Runner.run", new=AsyncMock(side_effect=asyncio.TimeoutError()))
    agent = Agent(name="Publisher", model="gpt-6-luna", model_settings=model_settings_for("publisher"))
    with pytest.raises(asyncio.TimeoutError):
        await _run_agent_with_fallback(agent, "test", agent_name="Publisher", pool=None)
    run.assert_awaited_once()


async def test_research_model_metadata_comes_from_execution(mocker):
    mocker.patch("pipeline._sdk.Runner.run", new=AsyncMock(return_value=SimpleNamespace(
        final_output='{"model_used":"invented-name"}', raw_responses=[])))
    agent = Agent(name="Researcher", model="gpt-6.1-sol", model_settings=model_settings_for("researcher"))
    output, _, _ = await _run_agent_with_fallback(agent, "test", agent_name="Researcher", pool=None)
    assert json.loads(output)["model_used"] == "gpt-6.1-sol"


async def test_truncated_research_is_not_returned_as_success(mocker):
    mocker.patch("pipeline._sdk.Runner.run", new=AsyncMock(return_value=SimpleNamespace(
        final_output='{"key_findings": [', raw_responses=[])))
    agent = Agent(name="Researcher", model="gpt-6.1-sol", model_settings=model_settings_for("researcher"))
    with pytest.raises(RuntimeError, match="before caching"):
        await _run_agent_with_fallback(agent, "test", agent_name="Researcher", pool=None)


def test_truncated_cache_is_ignored_on_retry(tmp_path):
    from pipeline.main import _valid_research_cache
    path = tmp_path / "research.json"
    path.write_text('{"key_findings": [')
    assert not _valid_research_cache(path)
    path.write_text('{"key_findings": [], "source_list": [], "gaps": ["No evidence"]}')
    assert _valid_research_cache(path)


def test_blog_retry_ignores_evidence_gap_cache_but_research_can_reuse_it(tmp_path):
    from pipeline.main import _valid_research_cache
    path = tmp_path / "research.json"
    path.write_text(json.dumps({"key_findings": [], "source_list": [], "gaps": ["Blocked publishers"]}))
    assert _valid_research_cache(path)
    assert not _valid_research_cache(path, require_evidence=True)
    sources = [f"https://source{i}.example/report" for i in range(3)]
    path.write_text(json.dumps({"source_list": [{"url": url} for url in sources], "key_findings": [{"finding": "Supported claim", "sources": [sources[0]]}]}))
    assert _valid_research_cache(path, require_evidence=True)


async def test_source_validation_retries_get_when_head_is_rejected(mocker):
    from pipeline.main import _sanitise_research_sources
    client = AsyncMock()
    client.head.return_value.status_code = 405
    client.get.return_value.status_code = 200
    cls = mocker.patch("httpx.AsyncClient")
    cls.return_value.__aenter__.return_value = client
    data = {"source_list": [{"url": "https://nasdaq.com/news/report"}], "key_findings": []}
    result = await _sanitise_research_sources(json.dumps(data))
    assert json.loads(result)["source_list"] == data["source_list"]
    client.get.assert_awaited_once_with("https://nasdaq.com/news/report")

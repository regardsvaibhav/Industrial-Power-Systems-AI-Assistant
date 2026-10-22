"""LLM path tests with a mocked OpenAI-compatible endpoint (no network, no key)."""

import json

import httpx

from app.assistant import Assistant
from app.llm.client import LLMClient, parse_json_object


def mock_llm(settings, handler):
    s = settings.model_copy(
        update={
            "llm_api_key": __import__("pydantic").SecretStr("test-key"),
            "llm_price_input_per_mtok": 1.0,
            "llm_price_output_per_mtok": 2.0,
        }
    )
    return s, LLMClient(s, transport=httpx.MockTransport(handler))


def completion(content="", tool_calls=None, pt=100, ct=20):
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return httpx.Response(
        200, json={"choices": [{"message": msg}], "usage": {"prompt_tokens": pt, "completion_tokens": ct}}
    )


def test_llm_answer_citations_validated(settings, store, assistant):
    seen = {}

    def handler(req):
        body = json.loads(req.content)
        seen["body"] = body
        return completion(
            json.dumps(
                {
                    "abstain": False,
                    "answer": "The polarization index is the ratio of the 10-minute to the 1-minute insulation resistance reading [S1][S9].",
                    "citations": ["S1", "S9"],
                }
            )
        )

    s, llm = mock_llm(settings, handler)
    a = Assistant(s, store=store, llm=llm)
    r = a.ask("What is the polarization index?")
    assert r.status == "answered" and r.mode == "llm"
    assert [c.id for c in r.citations] == ["S1"]  # invented S9 removed
    assert "[S9]" not in r.answer
    assert any("unknown sources" in w for w in r.warnings)
    assert r.usage.llm_calls == 1 and r.usage.cost_usd == round((100 * 1 + 20 * 2) / 1e6, 6)
    # sources are delimited and the key is only in the header, never in the prompt
    prompt = seen["body"]["messages"][1]["content"]
    assert '<source id="S1"' in prompt and "test-key" not in prompt


def test_llm_without_valid_citations_abstains(settings, store, assistant):
    s, llm = mock_llm(
        settings, lambda req: completion(json.dumps({"abstain": False, "answer": "It is 42.", "citations": []}))
    )
    r = Assistant(s, store=store, llm=llm).ask("What is the polarization index?")
    assert r.status == "abstained"


def test_llm_garbage_output_abstains(settings, store, assistant):
    s, llm = mock_llm(settings, lambda req: completion("Sure! Here's a poem instead."))
    assert Assistant(s, store=store, llm=llm).ask("What is the polarization index?").status == "abstained"


def test_llm_outage_falls_back_to_extractive(settings, store, assistant):
    s, llm = mock_llm(settings, lambda req: httpx.Response(503, text="overloaded"))
    r = Assistant(s, store=store, llm=llm).ask("What is the polarization index?")
    assert r.status == "answered"
    assert any("LLM unavailable" in w for w in r.warnings)


def test_llm_tool_call_is_validated_and_computed_in_python(settings, store, assistant):
    def handler(req):
        body = json.loads(req.content)
        assert body.get("tools")
        call = {
            "id": "1",
            "type": "function",
            "function": {
                "name": "three_phase_power",
                "arguments": json.dumps({"voltage_ll_v": 400, "current_a": 100, "power_factor": 0.85}),
            },
        }
        return completion(tool_calls=[call])

    s, llm = mock_llm(settings, handler)
    r = Assistant(s, store=store, llm=llm).ask("Real power for 400 V, 100 A, pf 0.85 three-phase?")
    assert r.status == "calculation"
    assert r.calculation.outputs["real_power"].value == 58.89


def test_llm_tool_call_with_bad_args_is_rejected(settings, store, assistant):
    def handler(req):
        call = {
            "id": "1",
            "type": "function",
            "function": {
                "name": "three_phase_power",
                "arguments": json.dumps({"voltage_ll_v": 400, "current_a": 100, "power_factor": 7}),
            },
        }
        return completion(tool_calls=[call])

    s, llm = mock_llm(settings, handler)
    r = Assistant(s, store=store, llm=llm).ask("Compute power for 400 V and 100 A at pf 7")
    assert r.status == "needs_clarification"


def test_llm_unknown_tool_ignored(settings, store, assistant):
    def handler(req):
        call = {"id": "1", "type": "function", "function": {"name": "os_system", "arguments": '{"cmd": "ls"}'}}
        return completion(tool_calls=[call])

    s, llm = mock_llm(settings, handler)
    r = Assistant(s, store=store, llm=llm).ask(
        "Calculate the real power of a 400 V three-phase motor drawing 100 A at 0.85 power factor"
    )
    # falls back to the rule-based parser; the unknown tool never runs
    assert r.status == "calculation" and r.calculation.tool == "three_phase_power"


def test_parse_json_object_variants():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('Here: {"a": 2} thanks') == {"a": 2}
    assert parse_json_object("no json") is None

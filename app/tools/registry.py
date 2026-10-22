"""Whitelist of calculation tools exposed to the API and to the LLM.

Only tools in TOOLS can run. Arguments are validated by the tool's Pydantic model
before any computation, so an LLM-proposed call cannot execute arbitrary code or pass
unvalidated values.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from app.tools import power
from app.tools.models import CalcResult


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    fn: Callable[[BaseModel], CalcResult]


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "three_phase_power",
            "Real, reactive and apparent power of a balanced three-phase load from line-to-line voltage, line current and power factor.",
            power.ThreePhasePowerInput,
            power.three_phase_power,
        ),
        Tool(
            "power_factor",
            "Power factor from real power and apparent or reactive power; optionally capacitor kvar to reach a target power factor.",
            power.PowerFactorInput,
            power.power_factor,
        ),
        Tool(
            "transformer_loading",
            "Transformer loading percentage, status band, headroom, currents and optional losses/efficiency.",
            power.TransformerLoadingInput,
            power.transformer_loading,
        ),
        Tool(
            "generation_demand_balance",
            "Generation vs demand balance, reserve margin and N-1 check from generator capacities and demand.",
            power.GenerationDemandInput,
            power.generation_demand_balance,
        ),
        Tool(
            "load_shedding_scenario",
            "Hypothetical priority-based load-shedding plan for a generation shortfall. Educational only.",
            power.LoadSheddingInput,
            power.load_shedding_scenario,
        ),
        Tool(
            "voltage_drop",
            "Feeder voltage drop from current, length, conductor R and X and power factor.",
            power.VoltageDropInput,
            power.voltage_drop,
        ),
        Tool(
            "short_circuit_transformer",
            "Three-phase fault current at a transformer secondary from kVA, voltage, %Z and optional source fault level.",
            power.ShortCircuitInput,
            power.short_circuit_transformer,
        ),
    ]
}


class UnknownToolError(KeyError):
    pass


def run_tool(name: str, args: dict) -> CalcResult:
    """Validate `args` against the tool's schema and run it. Raises UnknownToolError or ValidationError."""
    tool = TOOLS.get(name)
    if tool is None:
        raise UnknownToolError(name)
    return tool.fn(tool.input_model.model_validate(args))


def openai_tool_specs() -> list[dict]:
    """Function-calling schemas for OpenAI-compatible chat completions."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_model.model_json_schema(),
            },
        }
        for t in TOOLS.values()
    ]

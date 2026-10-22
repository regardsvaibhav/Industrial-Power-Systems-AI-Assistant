"""Unit tests for the calculation tools. Expected values are worked by hand (see the
examples in data/corpus_src) rather than copied from the implementation."""

import math

import pytest
from pydantic import ValidationError

from app.tools import power as p
from app.tools.registry import TOOLS, UnknownToolError, openai_tool_specs, run_tool


def out(res, key):
    v = res.outputs[key]
    return v.value if hasattr(v, "value") else v


# ------------------------------------------------------------- three-phase power
def test_three_phase_power_worked_example():
    r = p.three_phase_power(p.ThreePhasePowerInput(voltage_ll_v=400, current_a=100, power_factor=0.85))
    assert out(r, "apparent_power") == pytest.approx(69.282, abs=1e-3)
    assert out(r, "real_power") == pytest.approx(58.890, abs=1e-3)
    assert out(r, "reactive_power") == pytest.approx(36.497, abs=1e-3)
    assert r.outputs["real_power"].unit == "kW"


def test_three_phase_unity_pf_has_no_reactive_power():
    r = p.three_phase_power(p.ThreePhasePowerInput(voltage_ll_v=480, current_a=10, power_factor=1.0))
    assert out(r, "reactive_power") == 0
    assert out(r, "real_power") == pytest.approx(math.sqrt(3) * 4.8, abs=1e-3)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"voltage_ll_v": 0, "current_a": 1, "power_factor": 0.9},
        {"voltage_ll_v": 400, "current_a": -5, "power_factor": 0.9},
        {"voltage_ll_v": 400, "current_a": 5, "power_factor": 1.2},
        {"voltage_ll_v": 400, "current_a": 5, "power_factor": 0},
        {"voltage_ll_v": "abc", "current_a": 5, "power_factor": 0.9},
    ],
)
def test_three_phase_rejects_invalid(kwargs):
    with pytest.raises(ValidationError):
        p.ThreePhasePowerInput(**kwargs)


# ------------------------------------------------------------- power factor
def test_power_factor_from_kva():
    r = p.power_factor(p.PowerFactorInput(real_power_kw=80, apparent_power_kva=100))
    assert out(r, "power_factor") == pytest.approx(0.8)
    assert out(r, "reactive_power") == pytest.approx(60)


def test_power_factor_from_kvar():
    r = p.power_factor(p.PowerFactorInput(real_power_kw=30, reactive_power_kvar=40))
    assert out(r, "power_factor") == pytest.approx(0.6)
    assert out(r, "apparent_power") == pytest.approx(50)


def test_capacitor_sizing_worked_example():
    # IPS-02 example: 500 kW, 0.75 -> 0.95 needs ~277 kvar
    s1 = 500 / 0.75
    r = p.power_factor(p.PowerFactorInput(real_power_kw=500, apparent_power_kva=s1, target_power_factor=0.95))
    assert out(r, "capacitor_kvar_required") == pytest.approx(276.6, abs=0.1)
    assert out(r, "apparent_power_after") == pytest.approx(526.3, abs=0.1)
    assert out(r, "apparent_power_released") == pytest.approx(140.4, abs=0.1)


def test_power_factor_target_below_current_warns():
    r = p.power_factor(p.PowerFactorInput(real_power_kw=90, apparent_power_kva=100, target_power_factor=0.85))
    assert out(r, "capacitor_kvar_required") == 0
    assert r.warnings


def test_power_factor_requires_exactly_one_of_s_or_q():
    with pytest.raises(ValidationError):
        p.PowerFactorInput(real_power_kw=10)
    with pytest.raises(ValidationError):
        p.PowerFactorInput(real_power_kw=10, apparent_power_kva=20, reactive_power_kvar=5)
    with pytest.raises(ValidationError):
        p.PowerFactorInput(real_power_kw=100, apparent_power_kva=50)


# ------------------------------------------------------------- transformer loading
def test_transformer_loading_from_kw_and_pf():
    # IPS-03 example: 720 kW at 0.8 PF on 1000 kVA -> 90 %, high
    r = p.transformer_loading(p.TransformerLoadingInput(rated_kva=1000, load_kw=720, power_factor=0.8))
    assert out(r, "loading") == pytest.approx(90.0)
    assert out(r, "status") == "high"
    assert out(r, "headroom") == pytest.approx(100)


def test_transformer_currents_and_efficiency():
    r = p.transformer_loading(
        p.TransformerLoadingInput(
            rated_kva=1000,
            load_kw=675,
            power_factor=0.9,
            secondary_voltage_ll_v=400,
            no_load_loss_kw=1.5,
            full_load_loss_kw=10.5,
        )
    )
    assert out(r, "loading") == pytest.approx(75.0)
    assert out(r, "full_load_current") == pytest.approx(1443.4, abs=0.1)
    assert out(r, "load_loss") == pytest.approx(5.906, abs=1e-3)
    assert out(r, "efficiency") == pytest.approx(98.91, abs=0.01)
    assert out(r, "max_efficiency_at_loading") == pytest.approx(37.8, abs=0.1)


@pytest.mark.parametrize(
    "pct,band", [(50, "normal"), (80, "normal"), (80.01, "high"), (100, "high"), (100.5, "overloaded")]
)
def test_loading_bands(pct, band):
    assert p.loading_band(pct) == band


def test_transformer_overload_warns():
    r = p.transformer_loading(p.TransformerLoadingInput(rated_kva=500, load_kva=600))
    assert out(r, "status") == "overloaded"
    assert out(r, "headroom") == pytest.approx(-100)
    assert r.warnings


def test_transformer_requires_load():
    with pytest.raises(ValidationError):
        p.TransformerLoadingInput(rated_kva=500, load_kw=100)
    with pytest.raises(ValidationError):
        p.TransformerLoadingInput(rated_kva=500, load_kva=100, no_load_loss_kw=1)


# ------------------------------------------------------------- generation-demand balance
def test_balance_surplus_and_n1():
    r = p.generation_demand_balance(
        p.GenerationDemandInput(generator_capacities_mw=[50, 50, 50], demand_mw=100, required_reserve_mw=20)
    )
    assert out(r, "balance") == 50
    assert out(r, "reserve_margin") == 50.0
    assert out(r, "status") == "adequate"
    assert out(r, "n_minus_1_secure") is True


def test_balance_deficit_and_not_n1():
    r = p.generation_demand_balance(p.GenerationDemandInput(generator_capacities_mw=[2.0], demand_mw=3.6))
    assert out(r, "balance") == pytest.approx(-1.6)
    assert out(r, "status") == "deficit"
    assert out(r, "n_minus_1_secure") is False
    assert r.warnings


def test_balance_insufficient_reserve():
    r = p.generation_demand_balance(
        p.GenerationDemandInput(generator_capacities_mw=[60, 50], demand_mw=100, required_reserve_mw=20)
    )
    assert out(r, "status") == "insufficient_reserve"


def test_balance_rejects_bad_capacities():
    for caps in ([], [0], [-5], [float("nan")]):
        with pytest.raises(ValidationError):
            p.GenerationDemandInput(generator_capacities_mw=caps, demand_mw=10)


# ------------------------------------------------------------- load shedding
LOADS = [
    {"name": "Fire pumps", "mw": 0.3, "priority": 1},
    {"name": "Process line A", "mw": 1.3, "priority": 2},
    {"name": "Compressors", "mw": 0.8, "priority": 3},
    {"name": "Batch mixers", "mw": 0.6, "priority": 3},
    {"name": "Office HVAC", "mw": 0.4, "priority": 4},
    {"name": "EV chargers", "mw": 0.2, "priority": 4},
]


def test_load_shedding_ips05_example():
    # Demand 3.6 MW, 2.0 MW available, 0.2 MW reserve -> shed 1.8 MW
    r = p.load_shedding_scenario(p.LoadSheddingInput(available_generation_mw=2.0, loads=LOADS, required_reserve_mw=0.2))
    assert out(r, "total_demand") == pytest.approx(3.6)
    assert out(r, "shed_required") == pytest.approx(1.8)
    names = [x["name"] for x in out(r, "loads_shed")]
    assert names == ["Office HVAC", "EV chargers", "Compressors", "Batch mixers"]
    assert out(r, "shed_total") == pytest.approx(2.0)
    assert out(r, "requirement_met") is True
    assert "Fire pumps" not in names


def test_load_shedding_never_sheds_critical():
    r = p.load_shedding_scenario(p.LoadSheddingInput(available_generation_mw=0.5, loads=LOADS, allow_essential=True))
    names = [x["name"] for x in out(r, "loads_shed")]
    assert "Fire pumps" not in names
    assert out(r, "requirement_met") is True  # shed 3.3 MW >= 3.1 MW


def test_load_shedding_reports_uncovered_deficit():
    r = p.load_shedding_scenario(p.LoadSheddingInput(available_generation_mw=0.5, loads=LOADS))
    assert out(r, "requirement_met") is False
    assert any("does not cover" in w for w in r.warnings)


def test_load_shedding_no_deficit_sheds_nothing():
    r = p.load_shedding_scenario(p.LoadSheddingInput(available_generation_mw=10, loads=LOADS))
    assert out(r, "loads_shed") == []
    assert out(r, "shed_required") == 0


def test_load_shedding_rejects_bad_priority():
    with pytest.raises(ValidationError):
        p.LoadSheddingInput(available_generation_mw=1, loads=[{"name": "x", "mw": 1, "priority": 7}])


# ------------------------------------------------------------- voltage drop
def test_voltage_drop_worked_example():
    r = p.voltage_drop(
        p.VoltageDropInput(
            voltage_ll_v=400,
            current_a=150,
            length_m=120,
            resistance_ohm_per_km=0.153,
            reactance_ohm_per_km=0.08,
            power_factor=0.85,
        )
    )
    assert out(r, "voltage_drop") == pytest.approx(5.37, abs=0.01)
    assert out(r, "voltage_drop_percent") == pytest.approx(1.34, abs=0.01)
    assert not r.warnings


def test_voltage_drop_single_phase_and_warning():
    r = p.voltage_drop(
        p.VoltageDropInput(
            voltage_ll_v=230,
            current_a=32,
            length_m=60,
            resistance_ohm_per_km=4.61,
            reactance_ohm_per_km=0,
            power_factor=1,
            phases=1,
        )
    )
    # 2 * 32 * 0.06 * 4.61 = 17.70 V = 7.70 %
    assert out(r, "voltage_drop") == pytest.approx(17.70, abs=0.01)
    assert any("5%" in w for w in r.warnings)


def test_voltage_drop_rejects_two_phase():
    with pytest.raises(ValidationError):
        p.VoltageDropInput(voltage_ll_v=400, current_a=1, length_m=1, resistance_ohm_per_km=1, phases=2)


# ------------------------------------------------------------- short circuit
def test_short_circuit_infinite_bus():
    r = p.short_circuit_transformer(
        p.ShortCircuitInput(transformer_kva=1000, secondary_voltage_ll_v=400, impedance_percent=6)
    )
    assert out(r, "fault_current") == pytest.approx(24.06, abs=0.01)
    assert out(r, "fault_mva") == pytest.approx(16.67, abs=0.01)


def test_short_circuit_with_source():
    r = p.short_circuit_transformer(
        p.ShortCircuitInput(transformer_kva=1000, secondary_voltage_ll_v=400, impedance_percent=6, source_fault_mva=250)
    )
    assert out(r, "total_impedance_pu") == pytest.approx(0.064)
    assert out(r, "fault_current") == pytest.approx(22.55, abs=0.01)


# ------------------------------------------------------------- registry
def test_registry_runs_validated_tool():
    r = run_tool("three_phase_power", {"voltage_ll_v": 400, "current_a": 100, "power_factor": 0.85})
    assert r.tool == "three_phase_power"


def test_registry_rejects_unknown_tool_and_bad_args():
    with pytest.raises(UnknownToolError):
        run_tool("os_system", {"cmd": "rm -rf /"})
    with pytest.raises(ValidationError):
        run_tool("three_phase_power", {"voltage_ll_v": "__import__('os')"})


def test_openai_specs_cover_all_tools():
    specs = openai_tool_specs()
    assert {s["function"]["name"] for s in specs} == set(TOOLS)
    for s in specs:
        assert s["function"]["parameters"]["type"] == "object"

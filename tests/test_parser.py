import pytest

from app.tools.parser import find_quantities, parse_calculation


def test_unit_scaling():
    qs = {(m.unit, m.value) for m in find_quantities("11 kV, 2.5 MVA, 0.4 kA, 1.2 km, 300 kvar, 2 MVAr")}
    assert ("v", 11000) in qs and ("kva", 2500) in qs and ("a", 400) in qs and ("m", 1200) in qs
    assert ("kvar", 300) in qs and ("kvar", 2000) in qs


@pytest.mark.parametrize(
    "q,tool,expect",
    [
        (
            "Real power of a 690 V three-phase load at 200 A, pf 0.9?",
            "three_phase_power",
            {"voltage_ll_v": 690, "current_a": 200, "power_factor": 0.9},
        ),
        (
            "A 2 MVA transformer carries 1.5 MW at 0.9 power factor. What is the loading?",
            "transformer_loading",
            {"rated_kva": 2000, "load_kw": 1500, "power_factor": 0.9},
        ),
        (
            "Fault current of a 2500 kVA 400 V transformer with 6.25% impedance",
            "short_circuit_transformer",
            {"transformer_kva": 2500, "impedance_percent": 6.25},
        ),
    ],
)
def test_parse(q, tool, expect):
    intent = parse_calculation(q)
    assert intent.tool == tool and not intent.missing
    for k, v in expect.items():
        assert intent.args[k] == pytest.approx(v)


def test_conceptual_question_is_not_a_calculation():
    assert parse_calculation("What is short-circuit current?") is None
    assert parse_calculation("Explain under-frequency load shedding") is None

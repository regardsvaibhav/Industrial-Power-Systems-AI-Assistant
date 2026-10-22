"""Rule-based extraction of calculation requests from natural language.

Used when no LLM is configured, and as a fallback/cross-check when the LLM's
tool call is missing or invalid. It recognises explicit quantities with units
("400 V", "1000 kVA", "0.85 pf", "6 %Z") and calculation keywords. It is
deliberately conservative: if a required input is missing it reports what is
missing rather than guessing a default.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

NUM = r"(\d+(?:[.,]\d+)?)"


@dataclass
class Mention:
    value: float
    unit: str
    start: int
    end: int


@dataclass
class CalcIntent:
    tool: str
    args: dict
    missing: list[str] = field(default_factory=list)


# Order matters: longer units first so "kVA" is not read as "kV" + "A".
UNIT_PATTERNS: list[tuple[str, str, float]] = [
    (r"mva(?!r)", "kva", 1000.0),
    (r"kva(?!r)", "kva", 1.0),
    (r"mvar", "kvar", 1000.0),
    (r"kvar", "kvar", 1.0),
    (r"mw", "mw", 1.0),
    (r"kw", "kw", 1.0),
    (r"ka", "a", 1000.0),
    (r"kv", "v", 1000.0),
    (r"ohms?\s*(?:/|per)\s*km", "ohm_per_km", 1.0),
    (r"km", "m", 1000.0),
    (r"(?:amps?|amperes?|a)", "a", 1.0),
    (r"(?:volts?|v)", "v", 1.0),
    (r"(?:metres?|meters?|m)", "m", 1.0),
    (r"(?:%|percent)", "pct", 1.0),
]
_UNIT_RE = re.compile(NUM + r"\s*(" + "|".join(f"(?:{p})" for p, _, _ in UNIT_PATTERNS) + r")(?![a-z])", re.IGNORECASE)
_PF_RE = re.compile(
    r"(?:power\s+factor|pf|p\.f\.)\s*(?:of|is|=|:|at|to|from)?\s*(0?\.\d+|1(?:\.0+)?)\b|\b(0?\.\d+|1\.0+)\s*(?:power\s+factor|pf|lagging|leading)",
    re.IGNORECASE,
)


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def find_quantities(text: str) -> list[Mention]:
    out: list[Mention] = []
    for m in _UNIT_RE.finditer(text):
        raw_unit = m.group(2).lower()
        for pat, unit, scale in UNIT_PATTERNS:
            if re.fullmatch(pat, raw_unit, re.IGNORECASE):
                out.append(Mention(_num(m.group(1)) * scale, unit, m.start(), m.end()))
                break
    return out


def find_power_factors(text: str) -> list[tuple[float, int]]:
    res = []
    for m in _PF_RE.finditer(text):
        v = m.group(1) or m.group(2)
        val = _num(v)
        if 0 < val <= 1:
            res.append((val, m.start()))
    return res


def _of(qs: list[Mention], unit: str) -> list[Mention]:
    return [x for x in qs if x.unit == unit]


def _near(text: str, mention: Mention, words: tuple[str, ...], window: int = 30) -> bool:
    lo = max(0, mention.start - window)
    ctx = text[lo : mention.end + window].lower()
    return any(w in ctx for w in words)


def _after(text: str, mention: Mention, words: tuple[str, ...], window: int = 25) -> bool:
    ctx = text[max(0, mention.start - window) : mention.start].lower()
    return any(w in ctx for w in words)


# --------------------------------------------------------------------------- detectors
def _short_circuit(t: str, qs: list[Mention]) -> CalcIntent | None:
    if not re.search(r"short[\s-]?circuit|fault\s+(?:current|level)|prospective\s+fault", t, re.I):
        return None
    args: dict = {}
    kvas = _of(qs, "kva")
    src = [k for k in kvas if _near(t, k, ("source", "utility", "upstream", "grid", "fault level", "primary"), 25)]
    tx = [k for k in kvas if k not in src]
    if tx:
        args["transformer_kva"] = tx[0].value
    if src:
        args["source_fault_mva"] = src[0].value / 1000
    vs = _of(qs, "v")
    if vs:
        sec = [v for v in vs if _near(t, v, ("secondary", "lv", "low voltage"), 20)]
        args["secondary_voltage_ll_v"] = (sec or [min(vs, key=lambda v: v.value)])[0].value
    pct = _of(qs, "pct")
    imp = [p for p in pct if _near(t, p, ("imped", "%z", "z ", "z=", "z of"), 20)] or pct
    if imp:
        args["impedance_percent"] = imp[0].value
    m = re.search(r"(?:z|impedance)\s*(?:=|of|is)?\s*" + NUM + r"\s*%", t, re.I)
    if m and "impedance_percent" not in args:
        args["impedance_percent"] = _num(m.group(1))
    req = ["transformer_kva", "secondary_voltage_ll_v", "impedance_percent"]
    return CalcIntent("short_circuit_transformer", args, [r for r in req if r not in args])


def _voltage_drop(t: str, qs: list[Mention], pfs: list[tuple[float, int]]) -> CalcIntent | None:
    if not re.search(r"voltage\s+drop|volt\s+drop", t, re.I):
        return None
    args: dict = {}
    vs = _of(qs, "v")
    if vs:
        args["voltage_ll_v"] = vs[0].value
    amps = _of(qs, "a")
    if amps:
        args["current_a"] = amps[0].value
    ms = _of(qs, "m")
    if ms:
        args["length_m"] = ms[0].value
    ohms = _of(qs, "ohm_per_km")
    for o in ohms:
        if re.search(r"\b(?:x|reactance)\s*(?:=|of|is)?\s*$", t[max(0, o.start - 15) : o.start], re.I):
            args["reactance_ohm_per_km"] = o.value
        elif "resistance_ohm_per_km" not in args:
            args["resistance_ohm_per_km"] = o.value
    if pfs:
        args["power_factor"] = pfs[0][0]
    if re.search(r"single[\s-]?phase|1[\s-]?phase", t, re.I):
        args["phases"] = 1
    req = ["voltage_ll_v", "current_a", "length_m", "resistance_ohm_per_km"]
    return CalcIntent("voltage_drop", args, [r for r in req if r not in args])


def _power_factor(t: str, qs: list[Mention], pfs: list[tuple[float, int]]) -> CalcIntent | None:
    correction = re.search(r"capacitor|correct|improv|raise|kvar\s+(?:is\s+)?(?:needed|required)", t, re.I)
    if not (correction or re.search(r"power\s+factor|\bpf\b", t, re.I)):
        return None
    kw, kva, kvar = _of(qs, "kw"), _of(qs, "kva"), _of(qs, "kvar")
    mw = _of(qs, "mw")
    if not kw and mw:
        kw = [Mention(m.value * 1000, "kw", m.start, m.end) for m in mw]
    if not kw:
        return None
    if re.search(r"transformer", t, re.I) and not correction:
        return None  # transformer loading questions mention PF too
    args: dict = {"real_power_kw": kw[0].value}
    if kva:
        args["apparent_power_kva"] = kva[0].value
    elif kvar and not correction:
        args["reactive_power_kvar"] = kvar[0].value
    elif kvar and correction:
        args["reactive_power_kvar"] = kvar[0].value
    missing: list[str] = []
    if correction:
        # existing PF and target PF: target follows "to"/"target"; existing is the other
        tgt = [
            v
            for v, pos in pfs
            if re.search(
                r"(?:to|target|reach|achieve|of)\s*(?:a\s+)?(?:power\s+factor\s+(?:of\s+)?|pf\s+(?:of\s+)?)?$",
                t[max(0, pos - 25) : pos],
                re.I,
            )
        ]
        m_ft = re.search(r"\bfrom\s+(0?\.\d+)\s+to\s+(0?\.\d+|1(?:\.0+)?)\b", t)
        m_to = re.search(r"\bto\s+(0?\.\d+|1\.0+)\b", t)
        if m_ft:
            target, existing = _num(m_ft.group(2)), [_num(m_ft.group(1))]
        else:
            target = _num(m_to.group(1)) if m_to else (tgt[-1] if tgt else None)
            existing = [v for v, _ in pfs if v != target]
        if target is not None:
            args["target_power_factor"] = target
        else:
            missing.append("target_power_factor")
        if "apparent_power_kva" not in args and "reactive_power_kvar" not in args:
            if existing:
                args["apparent_power_kva"] = round(args["real_power_kw"] / existing[0], 9)
            else:
                missing.append("existing power factor (or apparent_power_kva / reactive_power_kvar)")
    elif "apparent_power_kva" not in args and "reactive_power_kvar" not in args:
        missing.append("apparent_power_kva or reactive_power_kvar")
    return CalcIntent("power_factor", args, missing)


def _transformer(t: str, qs: list[Mention], pfs: list[tuple[float, int]]) -> CalcIntent | None:
    if not (re.search(r"transformer", t, re.I) and re.search(r"load|overload|utili[sz]|capacity|headroom", t, re.I)):
        return None
    args: dict = {}
    kvas = _of(qs, "kva")
    rated = [k for k in kvas if _after(t, k, ("rated", "rating", "nameplate")) or _near(t, k, ("transformer",), 18)]
    rated_m = rated[0] if rated else (kvas[0] if kvas else None)
    if rated_m:
        args["rated_kva"] = rated_m.value
    loads = [k for k in kvas if k is not rated_m]
    kw = _of(qs, "kw") or [Mention(m.value * 1000, "kw", m.start, m.end) for m in _of(qs, "mw")]
    if kw:
        args["load_kw"] = kw[0].value
        if pfs:
            args["power_factor"] = pfs[0][0]
    if loads and "load_kw" not in args:
        args["load_kva"] = loads[0].value
    vs = _of(qs, "v")
    if vs:
        args["secondary_voltage_ll_v"] = min(vs, key=lambda v: v.value).value
    nll = re.search(r"no[\s-]?load\s+loss(?:es)?\s*(?:of|is|=)?\s*" + NUM + r"\s*kw", t, re.I)
    fll = re.search(r"(?:full[\s-]?load|load|copper)\s+loss(?:es)?\s*(?:of|is|=)?\s*" + NUM + r"\s*kw", t, re.I)
    if nll and fll and nll.start() != fll.start():
        args["no_load_loss_kw"] = _num(nll.group(1))
        args["full_load_loss_kw"] = _num(fll.group(1))
        # loss mentions are not loads
        loss_vals = {args["no_load_loss_kw"], args["full_load_loss_kw"]}
        if args.get("load_kw") in loss_vals:
            other = [k for k in kw if k.value not in loss_vals]
            if other:
                args["load_kw"] = other[0].value
            else:
                args.pop("load_kw")
    missing = []
    if "rated_kva" not in args:
        missing.append("rated_kva")
    if "load_kva" not in args and not ("load_kw" in args and "power_factor" in args):
        missing.append("load_kva, or load_kw and power_factor")
    return CalcIntent("transformer_loading", args, missing)


_WORDNUM = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def _generators(t: str) -> list[float]:
    caps: list[float] = []
    # "3 x 50 MW", "three 50 MW generators", "2 units of 20 MW"
    for m in re.finditer(
        r"\b(\d+|"
        + "|".join(_WORDNUM)
        + r")\s*(?:x|×|\*)?\s*(?:units?\s+of\s+|generators?\s+of\s+|gas\s+engines?\s+of\s+)?"
        + NUM
        + r"\s*mw\s*(?:(?:gas|steam|diesel|hydro|wind)\s+)?(?:generators?|units?|gensets?|engines?|turbines?)?",
        t,
        re.I,
    ):
        n_raw = m.group(1).lower()
        n = _WORDNUM.get(n_raw) or int(n_raw)
        full = m.group(0).lower()
        is_group = re.search(r"x|×|\*|units?\s+of|generators?\s+of|engines?\s+of", full) or (
            n_raw in _WORDNUM and re.search(r"generators?|units?|gensets?|engines?|turbines?", full)
        )
        if is_group and n <= 50:
            caps += [_num(m.group(2))] * n
    if caps:
        return caps
    # "generators of 50, 50 and 30 MW" / "units rated 40 MW, 30 MW and 20 MW"
    m = re.search(
        r"(?:generators?|units?|gensets?|generation)[^.]*?((?:\d+(?:\.\d+)?\s*(?:mw)?\s*(?:,|and|\+)\s*)+\d+(?:\.\d+)?)\s*mw",
        t,
        re.I,
    )
    if m:
        return [_num(x) for x in re.findall(r"\d+(?:\.\d+)?", m.group(1))]
    m = re.search(
        r"(?:generation|generating\s+capacity|available\s+capacity|supply)\s*(?:of|is|=|:)?\s*" + NUM + r"\s*mw",
        t,
        re.I,
    )
    if m:
        return [_num(m.group(1))]
    return []


def _balance(t: str, qs: list[Mention]) -> CalcIntent | None:
    if not re.search(r"demand|reserve|balance|n-1|n\s*-\s*1|surplus|deficit|enough\s+generation", t, re.I):
        return None
    if re.search(r"\bshed", t, re.I):
        return None
    if not _of(qs, "mw"):
        return None
    args: dict = {}
    caps = _generators(t)
    if caps:
        args["generator_capacities_mw"] = caps
    dm = re.search(r"(?:demand|load)\s*(?:of|is|=|:|at)?\s*" + NUM + r"\s*mw", t, re.I) or re.search(
        NUM + r"\s*mw\s+(?:of\s+)?(?:demand|load)", t, re.I
    )
    if dm:
        args["demand_mw"] = _num(dm.group(1))
    rm = re.search(r"reserve\s*(?:requirement)?\s*(?:of|is|=|:)?\s*" + NUM + r"\s*mw", t, re.I) or re.search(
        NUM + r"\s*mw\s+(?:of\s+)?(?:spinning\s+)?reserve", t, re.I
    )
    if rm:
        args["required_reserve_mw"] = _num(rm.group(1))
    req = ["generator_capacities_mw", "demand_mw"]
    return CalcIntent("generation_demand_balance", args, [r for r in req if r not in args])


_LOAD_ITEM = re.compile(
    r"([A-Za-z][A-Za-z0-9 /&-]{1,40}?)\s*[(:]\s*" + NUM + r"\s*mw\s*,?\s*(?:priority|p)\s*([1-4])\s*\)?", re.I
)


def _load_shedding(t: str) -> CalcIntent | None:
    if not re.search(r"\bshed|load[\s-]?shedding", t, re.I):
        return None
    if not re.search(NUM + r"\s*mw", t, re.I):
        return None  # no power quantities: a conceptual question, not a calculation
    args: dict = {}
    m = re.search(
        r"(?:available\s+generation|generation\s+available|generation|available\s+capacity|supply)\s*(?:of|is|=|:|drops\s+to|falls\s+to)?\s*"
        + NUM
        + r"\s*mw",
        t,
        re.I,
    ) or re.search(NUM + r"\s*mw\s+(?:of\s+)?(?:available\s+)?generation", t, re.I)
    if m:
        args["available_generation_mw"] = _num(m.group(1))
    rm = re.search(r"reserve\s*(?:of|is|=|:)?\s*" + NUM + r"\s*mw", t, re.I) or re.search(
        NUM + r"\s*mw\s+(?:of\s+)?reserve", t, re.I
    )
    if rm:
        args["required_reserve_mw"] = _num(rm.group(1))
    loads = [{"name": n.strip(" ,;-").strip(), "mw": _num(v), "priority": int(p)} for n, v, p in _LOAD_ITEM.findall(t)]
    if loads:
        args["loads"] = loads
    if re.search(r"allow(?:ing)?\s+(?:shedding\s+)?essential|including\s+essential", t, re.I):
        args["allow_essential"] = True
    req = ["available_generation_mw", "loads"]
    return CalcIntent("load_shedding_scenario", args, [r for r in req if r not in args])


def _three_phase(t: str, qs: list[Mention], pfs: list[tuple[float, int]]) -> CalcIntent | None:
    vs, amps = _of(qs, "v"), _of(qs, "a")
    asks_power = re.search(r"\b(?:power|kw|kva|kvar|real|reactive|apparent)\b", t, re.I)
    if not (vs and amps and asks_power):
        return None
    if re.search(r"single[\s-]?phase", t, re.I):
        return None  # tool is three-phase only; let the caller abstain/clarify
    args: dict = {"voltage_ll_v": vs[0].value, "current_a": amps[0].value}
    missing = []
    if pfs:
        args["power_factor"] = pfs[0][0]
    else:
        missing.append("power_factor")
    return CalcIntent("three_phase_power", args, missing)


CALC_HINT_RE = re.compile(
    r"\b(?:calculate|compute|determine|estimate|work\s+out|what\s+is\s+the|how\s+(?:much|many|big)|find|size)\b", re.I
)


def parse_calculation(text: str) -> CalcIntent | None:
    """Return the detected calculation intent (possibly with missing inputs), or None."""
    qs = find_quantities(text)
    pfs = find_power_factors(text)
    for detector in (
        lambda: _load_shedding(text),
        lambda: _short_circuit(text, qs),
        lambda: _voltage_drop(text, qs, pfs),
        lambda: _transformer(text, qs, pfs),
        lambda: _balance(text, qs),
        lambda: _power_factor(text, qs, pfs),
        lambda: _three_phase(text, qs, pfs),
    ):
        intent = detector()
        if intent is None:
            continue
        # Conceptual questions ("what is short-circuit current?") have no numbers: not a calc.
        if not intent.args and not re.search(r"\d", text):
            continue
        return intent
    return None

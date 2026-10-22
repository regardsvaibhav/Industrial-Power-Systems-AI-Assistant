"""Deterministic power-system calculations.

Every tool takes a validated Pydantic input model with units in the field names and
returns a CalcResult. The LLM never does this arithmetic: it may only choose a tool
and propose arguments, which are validated here before anything is computed.

Conventions
- Voltages are line-to-line RMS unless stated otherwise.
- Three-phase formulas assume a balanced, sinusoidal system at fundamental frequency.
- Power factor is a magnitude in (0, 1]; lagging (inductive) unless stated.
"""

from __future__ import annotations

import math
from enum import IntEnum

from pydantic import BaseModel, Field, field_validator, model_validator

from app.tools.models import CalcResult, q

SQRT3 = math.sqrt(3)
BALANCED = "Balanced three-phase system with sinusoidal voltage and current."


# ---------------------------------------------------------------- three-phase power


class ThreePhasePowerInput(BaseModel):
    voltage_ll_v: float = Field(..., gt=0, le=1_000_000, description="Line-to-line voltage in volts")
    current_a: float = Field(..., gt=0, le=1_000_000, description="Line current in amperes")
    power_factor: float = Field(..., gt=0, le=1, description="Displacement power factor (0-1]")


def three_phase_power(inp: ThreePhasePowerInput) -> CalcResult:
    s_va = SQRT3 * inp.voltage_ll_v * inp.current_a
    p_w = s_va * inp.power_factor
    q_var = s_va * math.sin(math.acos(inp.power_factor))
    return CalcResult(
        tool="three_phase_power",
        inputs={
            "voltage_ll": q(inp.voltage_ll_v, "V"),
            "current": q(inp.current_a, "A"),
            "power_factor": inp.power_factor,
        },
        outputs={
            "apparent_power": q(s_va / 1e3, "kVA"),
            "real_power": q(p_w / 1e3, "kW"),
            "reactive_power": q(q_var / 1e3, "kvar"),
            "phase_angle": q(math.degrees(math.acos(inp.power_factor)), "deg", 2),
        },
        formula=["S = sqrt(3) * V_LL * I", "P = S * PF", "Q = S * sin(acos(PF))"],
        assumptions=[BALANCED, "Power is electrical input, not shaft output."],
    )


# ---------------------------------------------------------------- power factor


class PowerFactorInput(BaseModel):
    real_power_kw: float = Field(..., gt=0, le=1e7)
    apparent_power_kva: float | None = Field(None, gt=0, le=1e7)
    reactive_power_kvar: float | None = Field(None, ge=0, le=1e7)
    target_power_factor: float | None = Field(None, gt=0, le=1, description="Optional correction target")

    @model_validator(mode="after")
    def _one_of(self) -> PowerFactorInput:
        if (self.apparent_power_kva is None) == (self.reactive_power_kvar is None):
            raise ValueError("Provide exactly one of apparent_power_kva or reactive_power_kvar")
        if self.apparent_power_kva is not None and self.apparent_power_kva < self.real_power_kw:
            raise ValueError("apparent_power_kva cannot be smaller than real_power_kw")
        return self


def power_factor(inp: PowerFactorInput) -> CalcResult:
    p = inp.real_power_kw
    if inp.apparent_power_kva is not None:
        s = inp.apparent_power_kva
        qv = math.sqrt(max(s * s - p * p, 0.0))
    else:
        qv = inp.reactive_power_kvar
        s = math.hypot(p, qv)
    pf = p / s
    outputs: dict = {
        "power_factor": round(pf, 4),
        "apparent_power": q(s, "kVA"),
        "reactive_power": q(qv, "kvar"),
        "phase_angle": q(math.degrees(math.acos(pf)), "deg", 2),
    }
    formula = ["PF = P / S", "S^2 = P^2 + Q^2"]
    warnings: list[str] = []
    if inp.target_power_factor is not None:
        tgt = inp.target_power_factor
        if tgt <= pf:
            warnings.append(f"Target PF {tgt} is not above the existing PF {pf:.3f}; no correction needed.")
            qc = 0.0
        else:
            qc = p * (math.tan(math.acos(pf)) - math.tan(math.acos(tgt)))
        s_new = p / max(tgt, pf)
        outputs |= {
            "capacitor_kvar_required": q(qc, "kvar"),
            "apparent_power_after": q(s_new, "kVA"),
            "apparent_power_released": q(s - s_new, "kVA"),
        }
        formula.append("Qc = P * (tan(acos(PF1)) - tan(acos(PF2)))")
        if tgt > 0.99:
            warnings.append("Targets above 0.99 risk leading PF at light load; check for overcorrection.")
    return CalcResult(
        tool="power_factor",
        inputs={k: v for k, v in inp.model_dump().items() if v is not None},
        outputs=outputs,
        formula=formula,
        assumptions=[
            "Displacement power factor only; harmonic distortion is not included.",
            "Lagging (inductive) load; real power is constant during correction.",
        ],
        warnings=warnings,
    )


# ---------------------------------------------------------------- transformer loading


class TransformerLoadingInput(BaseModel):
    rated_kva: float = Field(..., gt=0, le=2e6)
    load_kw: float | None = Field(None, gt=0, le=2e6)
    power_factor: float | None = Field(None, gt=0, le=1)
    load_kva: float | None = Field(None, gt=0, le=2e6)
    secondary_voltage_ll_v: float | None = Field(None, gt=0, le=1e6)
    no_load_loss_kw: float | None = Field(None, ge=0, le=1e4)
    full_load_loss_kw: float | None = Field(None, ge=0, le=1e5)

    @model_validator(mode="after")
    def _load_given(self) -> TransformerLoadingInput:
        if self.load_kva is None and (self.load_kw is None or self.power_factor is None):
            raise ValueError("Provide load_kva, or both load_kw and power_factor")
        if (self.no_load_loss_kw is None) != (self.full_load_loss_kw is None):
            raise ValueError("Provide both no_load_loss_kw and full_load_loss_kw, or neither")
        return self


def loading_band(loading_pct: float) -> str:
    """Planning bands from IPS-03: <=80 normal, 80-100 high, >100 overloaded."""
    if loading_pct > 100:
        return "overloaded"
    if loading_pct > 80:
        return "high"
    return "normal"


def transformer_loading(inp: TransformerLoadingInput) -> CalcResult:
    s = inp.load_kva if inp.load_kva is not None else inp.load_kw / inp.power_factor
    frac = s / inp.rated_kva
    pct = frac * 100
    band = loading_band(pct)
    outputs: dict = {
        "load_apparent_power": q(s, "kVA"),
        "loading": q(pct, "%", 2),
        "status": band,
        "headroom": q(inp.rated_kva - s, "kVA"),
    }
    formula = ["Loading % = S_load / S_rated * 100"]
    if inp.secondary_voltage_ll_v:
        outputs["full_load_current"] = q(inp.rated_kva * 1e3 / (SQRT3 * inp.secondary_voltage_ll_v), "A", 1)
        outputs["load_current"] = q(s * 1e3 / (SQRT3 * inp.secondary_voltage_ll_v), "A", 1)
        formula.append("I = S / (sqrt(3) * V_LL)")
    if inp.no_load_loss_kw is not None:
        load_loss = inp.full_load_loss_kw * frac**2
        total = inp.no_load_loss_kw + load_loss
        p_out = inp.load_kw if inp.load_kw is not None else None
        outputs["load_loss"] = q(load_loss, "kW")
        outputs["total_loss"] = q(total, "kW")
        if p_out is not None:
            outputs["efficiency"] = q(100 * p_out / (p_out + total), "%", 2)
        if inp.full_load_loss_kw > 0:
            outputs["max_efficiency_at_loading"] = q(
                100 * math.sqrt(inp.no_load_loss_kw / inp.full_load_loss_kw), "%", 1
            )
        formula += [
            "P_load_loss = P_load_loss_rated * (S/S_rated)^2",
            "Efficiency = P_out / (P_out + P_no_load + P_load_loss)",
        ]
    warnings = []
    if band == "overloaded":
        warnings.append("Load exceeds nameplate rating; assess with a recognised loading guide and manufacturer data.")
    return CalcResult(
        tool="transformer_loading",
        inputs={k: v for k, v in inp.model_dump().items() if v is not None},
        outputs=outputs,
        formula=formula,
        assumptions=[
            "Rating refers to the cooling stage in service (e.g. ONAN).",
            "Status bands are planning guidance (<=80% normal, 80-100% high, >100% overloaded), not protection settings.",
            "Ambient temperature and harmonic derating are not considered.",
        ],
        warnings=warnings,
    )


# ---------------------------------------------------------------- generation-demand balance


class GenerationDemandInput(BaseModel):
    generator_capacities_mw: list[float] = Field(..., min_length=1, max_length=200)
    demand_mw: float = Field(..., gt=0, le=1e6)
    required_reserve_mw: float = Field(0.0, ge=0, le=1e6)

    @field_validator("generator_capacities_mw")
    @classmethod
    def _positive(cls, v: list[float]) -> list[float]:
        if any((not math.isfinite(x)) or x <= 0 or x > 1e5 for x in v):
            raise ValueError("Each generator capacity must be > 0 and <= 100000 MW")
        return v


def generation_demand_balance(inp: GenerationDemandInput) -> CalcResult:
    gen = sum(inp.generator_capacities_mw)
    largest = max(inp.generator_capacities_mw)
    balance = gen - inp.demand_mw
    reserve_margin = 100 * balance / inp.demand_mw
    n1_capacity = gen - largest
    n1_secure = n1_capacity >= inp.demand_mw
    if balance < 0:
        status = "deficit"
    elif balance < inp.required_reserve_mw:
        status = "insufficient_reserve"
    else:
        status = "adequate"
    warnings = []
    if not n1_secure:
        warnings.append(
            f"Loss of the largest unit ({largest:g} MW) would leave {n1_capacity:g} MW for "
            f"{inp.demand_mw:g} MW demand: not N-1 secure."
        )
    return CalcResult(
        tool="generation_demand_balance",
        inputs=inp.model_dump(),
        outputs={
            "total_available_generation": q(gen, "MW"),
            "balance": q(balance, "MW"),
            "reserve_margin": q(reserve_margin, "%", 2),
            "status": status,
            "largest_unit": q(largest, "MW"),
            "n_minus_1_secure": n1_secure,
            "capacity_after_largest_unit_loss": q(n1_capacity, "MW"),
        },
        formula=[
            "Balance = sum(available generation) - demand",
            "Reserve margin % = Balance / demand * 100",
            "N-1 secure if (generation - largest unit) >= demand",
        ],
        assumptions=[
            "Capacities are available (dispatchable) MW, not nameplate of offline units.",
            "Steady-state energy balance only; losses are included in demand; no dynamics or network limits.",
        ],
        warnings=warnings,
    )


# ---------------------------------------------------------------- load shedding (hypothetical)


class Priority(IntEnum):
    CRITICAL = 1
    ESSENTIAL = 2
    IMPORTANT = 3
    NON_ESSENTIAL = 4


class LoadItem(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    mw: float = Field(..., gt=0, le=1e5)
    priority: Priority


class LoadSheddingInput(BaseModel):
    available_generation_mw: float = Field(..., ge=0, le=1e6)
    loads: list[LoadItem] = Field(..., min_length=1, max_length=500)
    required_reserve_mw: float = Field(0.0, ge=0, le=1e6)
    allow_essential: bool = Field(False, description="Allow shedding priority-2 (essential) loads as last resort")


def load_shedding_scenario(inp: LoadSheddingInput) -> CalcResult:
    """Greedy priority-based shedding plan for a HYPOTHETICAL steady-state scenario.

    Order: priority 4 first, then 3, then (only if allowed) 2; within a tier, larger
    loads first. Priority-1 (critical) loads are never shed.
    """
    demand = sum(ld.mw for ld in inp.loads)
    required = demand - inp.available_generation_mw + inp.required_reserve_mw
    sheddable_tiers = [Priority.NON_ESSENTIAL, Priority.IMPORTANT]
    if inp.allow_essential:
        sheddable_tiers.append(Priority.ESSENTIAL)

    shed: list[dict] = []
    shed_total = 0.0
    if required > 0:
        for tier in sheddable_tiers:
            for ld in sorted((x for x in inp.loads if x.priority == tier), key=lambda x: -x.mw):
                if shed_total >= required:
                    break
                shed.append({"name": ld.name, "mw": ld.mw, "priority": int(ld.priority)})
                shed_total += ld.mw
            if shed_total >= required:
                break

    covered = shed_total >= required or required <= 0
    remaining = demand - shed_total
    warnings = ["Hypothetical planning scenario for education only; not an operating instruction."]
    if not covered:
        warnings.append(
            f"Shedding all permitted loads ({shed_total:g} MW) does not cover the requirement of "
            f"{required:g} MW. Critical loads are never shed; consider additional generation."
        )
    return CalcResult(
        tool="load_shedding_scenario",
        inputs=inp.model_dump(mode="json"),
        outputs={
            "total_demand": q(demand, "MW"),
            "shed_required": q(max(required, 0.0), "MW"),
            "shed_total": q(shed_total, "MW"),
            "loads_shed": shed,
            "remaining_demand": q(remaining, "MW"),
            "resulting_reserve": q(inp.available_generation_mw - remaining, "MW"),
            "requirement_met": covered,
        },
        formula=["Shed required = demand - available generation + required reserve"],
        assumptions=[
            "Steady-state balance; ignores load damping, frequency dynamics and relay delays.",
            "Priority 1 (critical) loads are never shed; priority 2 only if allow_essential is true.",
            "Within a priority tier, larger loads are shed first to minimise switching operations.",
        ],
        warnings=warnings,
    )


# ---------------------------------------------------------------- voltage drop


class VoltageDropInput(BaseModel):
    voltage_ll_v: float = Field(..., gt=0, le=1e6)
    current_a: float = Field(..., gt=0, le=1e5)
    length_m: float = Field(..., gt=0, le=1e5, description="One-way route length in metres")
    resistance_ohm_per_km: float = Field(..., gt=0, le=100)
    reactance_ohm_per_km: float = Field(0.08, ge=0, le=100)
    power_factor: float = Field(0.85, gt=0, le=1)
    phases: int = Field(3, description="3 for three-phase, 1 for single-phase two-wire")

    @field_validator("phases")
    @classmethod
    def _phases(cls, v: int) -> int:
        if v not in (1, 3):
            raise ValueError("phases must be 1 or 3")
        return v


def voltage_drop(inp: VoltageDropInput) -> CalcResult:
    k = SQRT3 if inp.phases == 3 else 2.0
    sin_phi = math.sin(math.acos(inp.power_factor))
    z_eff = inp.resistance_ohm_per_km * inp.power_factor + inp.reactance_ohm_per_km * sin_phi
    vd = k * inp.current_a * (inp.length_m / 1000) * z_eff
    pct = 100 * vd / inp.voltage_ll_v
    warnings = []
    if pct > 5:
        warnings.append("Voltage drop exceeds 5%, a common total design recommendation.")
    elif pct > 3:
        warnings.append("Voltage drop exceeds 3%, a common feeder/branch design recommendation.")
    return CalcResult(
        tool="voltage_drop",
        inputs=inp.model_dump(),
        outputs={
            "voltage_drop": q(vd, "V", 2),
            "voltage_drop_percent": q(pct, "%", 2),
            "receiving_end_voltage": q(inp.voltage_ll_v - vd, "V", 1),
        },
        formula=[
            ("VD = sqrt(3)" if inp.phases == 3 else "VD = 2") + " * I * L * (R cos(phi) + X sin(phi))",
        ],
        assumptions=[
            "Approximate formula (neglects the small quadrature component); valid for typical feeder drops.",
            "R should be at conductor operating temperature.",
        ],
        warnings=warnings,
    )


# ---------------------------------------------------------------- short circuit


class ShortCircuitInput(BaseModel):
    transformer_kva: float = Field(..., gt=0, le=2e6)
    secondary_voltage_ll_v: float = Field(..., gt=0, le=1e6)
    impedance_percent: float = Field(..., gt=0.5, le=30)
    source_fault_mva: float | None = Field(None, gt=0, le=1e6, description="Upstream fault level; None = infinite bus")


def short_circuit_transformer(inp: ShortCircuitInput) -> CalcResult:
    i_fl = inp.transformer_kva * 1e3 / (SQRT3 * inp.secondary_voltage_ll_v)
    z_tx = inp.impedance_percent / 100
    z_src = 0.0 if inp.source_fault_mva is None else (inp.transformer_kva / 1e3) / inp.source_fault_mva
    z_tot = z_tx + z_src
    i_sc = i_fl / z_tot
    assumptions = [
        "Three-phase bolted fault at the transformer secondary terminals.",
        "Source and transformer impedances added arithmetically (same X/R assumed).",
        "Motor contribution and cable impedance are not included.",
    ]
    if inp.source_fault_mva is None:
        assumptions.append(
            "Infinite source: conservative for equipment ratings, NOT conservative for protection or arc-flash studies."
        )
    return CalcResult(
        tool="short_circuit_transformer",
        inputs={k: v for k, v in inp.model_dump().items() if v is not None},
        outputs={
            "full_load_current": q(i_fl, "A", 1),
            "source_impedance_pu": round(z_src, 5),
            "total_impedance_pu": round(z_tot, 5),
            "fault_current": q(i_sc / 1e3, "kA", 2),
            "fault_mva": q(SQRT3 * inp.secondary_voltage_ll_v * i_sc / 1e6, "MVA", 2),
        },
        formula=["I_FL = S / (sqrt(3) * V_LL)", "Z_src = S_tx / S_sc_source", "I_sc = I_FL / (Z_tx + Z_src)"],
        assumptions=assumptions,
    )

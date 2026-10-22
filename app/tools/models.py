"""Shared result models for the engineering calculation tools."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Quantity(BaseModel):
    value: float
    unit: str

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return f"{self.value:g} {self.unit}"


class CalcResult(BaseModel):
    """Structured output of every calculation tool.

    `outputs` holds rounded values for display; full-precision math happens inside the
    tool. `formula` and `assumptions` make the result auditable.
    """

    tool: str
    inputs: dict[str, Quantity | str | float | list | dict]
    outputs: dict[str, Quantity | bool | float | str | list | dict]
    formula: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def q(value: float, unit: str, ndigits: int = 3) -> Quantity:
    """Round to `ndigits` significant-ish decimals for display without hiding precision loss."""
    return Quantity(value=round(value, ndigits), unit=unit)

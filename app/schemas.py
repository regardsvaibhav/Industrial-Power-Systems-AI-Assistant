"""API request/response models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.tools.models import CalcResult

DOC_ID_PATTERN = r"^[0-9a-f]{16}$"


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    doc_ids: list[str] | None = Field(None, max_length=50, description="Restrict retrieval to these documents")
    top_k: int | None = Field(None, ge=1, le=20)

    @field_validator("question")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("question must not be blank")
        return v

    @field_validator("doc_ids")
    @classmethod
    def _ids(cls, v: list[str] | None) -> list[str] | None:
        import re

        if v is not None:
            for d in v:
                if not re.fullmatch(DOC_ID_PATTERN, d):
                    raise ValueError("invalid doc_id")
        return v or None


class Citation(BaseModel):
    id: str  # "S1"...
    chunk_id: str
    doc_id: str
    title: str
    filename: str
    page: int
    page_end: int | None = None  # set when the cited passage continues onto the next page
    section: str = ""
    snippet: str
    score: float
    flagged: bool = False  # chunk contained instruction-like text that was removed


class Grounding(BaseModel):
    supported_sentences: int
    total_sentences: int
    score: float  # supported / total (1.0 when answer is empty/abstained)
    unsupported_numbers: list[str] = Field(default_factory=list)


class UsageInfo(BaseModel):
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


Status = Literal["answered", "abstained", "needs_clarification", "calculation", "rejected"]


class ChatResponse(BaseModel):
    status: Status
    answer: str
    mode: Literal["llm", "extractive"]
    citations: list[Citation] = Field(default_factory=list)
    calculation: CalcResult | None = None
    missing_inputs: list[str] = Field(default_factory=list)
    grounding: Grounding | None = None
    warnings: list[str] = Field(default_factory=list)
    retrieval_top_score: float | None = None
    latency_ms: float = 0.0
    usage: UsageInfo = Field(default_factory=UsageInfo)


class CalcRequest(BaseModel):
    tool: str = Field(..., min_length=1, max_length=64)
    args: dict


class DocumentInfo(BaseModel):
    doc_id: str
    title: str
    filename: str
    pages: int
    chunks: int


class IngestResponse(BaseModel):
    doc_id: str
    title: str
    filename: str
    pages: int
    chunks: int
    duplicate: bool = False

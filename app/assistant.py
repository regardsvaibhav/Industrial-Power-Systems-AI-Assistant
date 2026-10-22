"""Orchestrates one question: safety checks -> calculation routing -> retrieval -> grounded answer."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from pydantic import ValidationError

from app.config import Settings
from app.llm.client import LLMClient, LLMError, Usage
from app.rag.generate import Generated, extractive_answer, label_sources, llm_answer
from app.rag.grounding import check_grounding, numbers_in
from app.rag.pdf import chunk_pdf, parse_pdf
from app.rag.store import Hit, VectorStore, stem, tokenize
from app.schemas import ChatResponse, Citation, IngestResponse, UsageInfo
from app.security import looks_like_injection, strip_injected_sentences
from app.tools.models import CalcResult
from app.tools.parser import CalcIntent, parse_calculation
from app.tools.registry import TOOLS, openai_tool_specs, run_tool

log = logging.getLogger(__name__)

CALC_SYSTEM_PROMPT = """You extract arguments for engineering calculation tools.
Call exactly one tool whose required inputs are ALL explicitly stated in the user's question.
Copy values exactly as given, converting only units into the units named in the parameter names (e.g. kV -> V, MVA -> kVA where the parameter is in kVA).
Never compute results yourself and never invent missing values.
If no tool fits, or a required value is missing, do not call a tool; instead reply with JSON {"missing": ["<parameter>", ...]}."""

VAGUE_WORDS = frozenset(
    "value values limit limits rating ratings number numbers tell explain mean means good ok okay normal right correct "
    "use need much many size best typical usually work works thing things one ones answer help please".split()
)
GENERIC_WORDS = frozenset(
    "stand stands specify specified affect affects mean means meaning need needed use used using happen happens cause "
    "causes work works difference explain describe give list required recommended typical typically main important "
    "example examples common commonly define definition called purpose role effect effects reason reasons way ways "
    "tell know get make made happen important consider considered best good better should".split()
)
GENERIC_STEMS = frozenset(stem(w) for w in GENERIC_WORDS)
VAGUE_STEMS = frozenset(stem(w) for w in VAGUE_WORDS)
PRONOUN_RE = re.compile(r"\b(?:it|this|that|these|those|they|them|its)\b", re.I)
CALC_WORD_RE = re.compile(r"\b(?:calculate|compute|work out|how (?:much|many)|what (?:is|are) the)\b", re.I)


def format_calc_answer(res: CalcResult) -> str:
    parts = []
    for k, v in res.outputs.items():
        if isinstance(v, list | dict):
            continue
        label = k.replace("_", " ")
        parts.append(f"{label}: {v.value:g} {v.unit}" if hasattr(v, "unit") else f"{label}: {v}")
    text = f"Result of the `{res.tool}` tool: " + "; ".join(parts) + "."
    shed = res.outputs.get("loads_shed")
    if isinstance(shed, list):
        names = ", ".join(f"{x['name']} ({x['mw']:g} MW, P{x['priority']})" for x in shed) or "none"
        text += f" Loads to shed (in order): {names}."
    return text


class Assistant:
    def __init__(self, settings: Settings, store: VectorStore | None = None, llm: LLMClient | None = None) -> None:
        self.settings = settings
        self.store = store or VectorStore(settings.chroma_dir, settings.collection_name)
        self.llm = llm if llm is not None else (LLMClient(settings) if settings.llm_enabled else None)

    @property
    def mode(self) -> str:
        return "llm" if self.llm else "extractive"

    # ------------------------------------------------------------------ ingestion
    def ingest_bytes(self, data: bytes, filename: str) -> IngestResponse:
        s = self.settings
        parsed = parse_pdf(data, filename, max_pages=s.max_pdf_pages, max_bytes=s.max_upload_mb * 1024 * 1024)
        if self.store.has_document(parsed.doc_id):
            n = next((d["chunks"] for d in self.store.list_documents() if d["doc_id"] == parsed.doc_id), 0)
            return IngestResponse(
                doc_id=parsed.doc_id,
                title=parsed.title,
                filename=filename,
                pages=parsed.page_count,
                chunks=n,
                duplicate=True,
            )
        chunks = chunk_pdf(parsed, filename, s.chunk_size_chars, s.chunk_overlap_chars)
        s.upload_dir.mkdir(parents=True, exist_ok=True)
        # Stored under a server-generated name (content hash), never the client filename.
        (s.upload_dir / f"{parsed.doc_id}.pdf").write_bytes(data)
        self.store.add_chunks(chunks)
        return IngestResponse(
            doc_id=parsed.doc_id, title=parsed.title, filename=filename, pages=parsed.page_count, chunks=len(chunks)
        )

    def pdf_path(self, doc_id: str) -> Path | None:
        if not re.fullmatch(r"[0-9a-f]{16}", doc_id):
            return None
        p = self.settings.upload_dir / f"{doc_id}.pdf"
        return p if p.is_file() else None

    def delete_document(self, doc_id: str) -> int:
        n = self.store.delete_document(doc_id)
        p = self.pdf_path(doc_id)
        if p:
            p.unlink(missing_ok=True)
        return n

    def ingest_directory(self, directory: Path) -> list[IngestResponse]:
        return [self.ingest_bytes(p.read_bytes(), p.name) for p in sorted(directory.glob("*.pdf"))]

    # ------------------------------------------------------------------ helpers
    def _is_vague(self, question: str) -> bool:
        content = [t for t in tokenize(question) if t not in VAGUE_STEMS and not t.isdigit()]
        if not content:
            return True
        return bool(PRONOUN_RE.search(question)) and len(content) <= 1

    def _out_of_corpus(self, question: str) -> bool:
        """Extractive-mode guard for questions about things the corpus never mentions.

        True if a proper noun / acronym in the question (e.g. "IEEE", "India") never occurs
        in the corpus, or if at least `unknown_term_abstain_ratio` of the question's
        non-generic terms are unknown. The LLM path relies on the model abstaining instead.
        """
        toks = [t for t in set(tokenize(question)) if not re.fullmatch(r"[\d.]+", t) and t not in GENERIC_STEMS]
        unknown = {t for t in toks if not self.store.knows_token(t)}
        if not toks:
            return False
        words = re.findall(r"[A-Za-z][A-Za-z0-9-]*", question)
        named = {
            stem(w.lower()) for i, w in enumerate(words) if (i > 0 and w[0].isupper()) or (len(w) > 1 and w.isupper())
        }
        if unknown & named:
            return True
        return len(unknown) / len(toks) >= self.settings.unknown_term_abstain_ratio

    def _relevant(self, question: str, hits: list[Hit]) -> bool:
        """Evidence gate: semantic similarity, or exact matches on the question's terms.

        The lexical path covers acronyms and codes (e.g. "ONAF") that a small embedding
        model represents poorly.
        """
        s = self.settings
        if max(h.semantic for h in hits) >= s.min_relevance:
            return True
        q = set(tokenize(question))
        if not q:
            return False
        for h in hits:
            if h.semantic >= s.min_relevance_lexical_floor and len(q & set(tokenize(h.text))) / len(q) >= 0.5:
                return True
        return False

    def _llm_calc(self, question: str, usage: Usage) -> CalcIntent | None:
        assert self.llm is not None
        reply = self.llm.chat(
            [{"role": "system", "content": CALC_SYSTEM_PROMPT}, {"role": "user", "content": question}],
            tools=openai_tool_specs(),
        )
        usage.add(reply.usage)
        for call in reply.tool_calls:
            if call["name"] in TOOLS and isinstance(call["arguments"], dict):
                return CalcIntent(call["name"], call["arguments"])
        return None

    def _citations(self, sources: dict[str, Hit], used: list[str], flagged: set[str]) -> list[Citation]:
        out = []
        for sid in used:
            h = sources[sid]
            m = h.metadata
            out.append(
                Citation(
                    id=sid,
                    chunk_id=h.chunk_id,
                    doc_id=m["doc_id"],
                    title=m["title"],
                    filename=m["filename"],
                    page=int(m["page"]),
                    section=m.get("section", ""),
                    snippet=h.text[:500],
                    score=round(h.semantic, 4),
                    flagged=sid in flagged,
                )
            )
        return out

    # ------------------------------------------------------------------ main entry
    def ask(self, question: str, doc_ids: list[str] | None = None, top_k: int | None = None) -> ChatResponse:
        t0 = time.perf_counter()
        usage = Usage()
        warnings: list[str] = []

        def done(**kw) -> ChatResponse:
            return ChatResponse(
                mode=self.mode,
                warnings=warnings,
                latency_ms=round((time.perf_counter() - t0) * 1000, 1),
                usage=UsageInfo(
                    llm_calls=usage.calls,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    cost_usd=round(usage.cost_usd, 6),
                ),
                **kw,
            )

        # 1. Prompt-injection screen on the user's question.
        if looks_like_injection(question):
            return done(
                status="rejected",
                answer="This request looks like an attempt to override the assistant's instructions, so it was not processed. "
                "Please ask a power-systems question.",
            )

        # 2. Calculation routing (deterministic tools; the LLM may only extract arguments).
        intent = parse_calculation(question)
        if self.llm and (intent is not None or CALC_WORD_RE.search(question)) and re.search(r"\d", question):
            try:
                llm_intent = self._llm_calc(question, usage)
                if llm_intent is not None:
                    intent = llm_intent
            except LLMError as exc:
                warnings.append(f"LLM argument extraction failed ({exc}); used rule-based parser.")
        if intent is not None:
            if intent.missing:
                return done(
                    status="needs_clarification",
                    answer=f"To run the {intent.tool.replace('_', ' ')} calculation I need: {', '.join(intent.missing)}. "
                    "Please provide these values with units, or use the calculator panel.",
                    missing_inputs=intent.missing,
                )
            try:
                result = run_tool(intent.tool, intent.args)
            except ValidationError as exc:
                errs = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5])
                return done(
                    status="needs_clarification",
                    answer=f"The inputs for {intent.tool.replace('_', ' ')} are not valid ({errs}). Please check the values.",
                    missing_inputs=[str(e["loc"][0]) for e in exc.errors() if e["loc"]],
                )
            refs = [
                h
                for h in self.store.search(question, k=2, doc_ids=doc_ids)
                if h.semantic >= self.settings.min_relevance
            ]
            sources = label_sources(refs)
            return done(
                status="calculation",
                answer=format_calc_answer(result),
                calculation=result,
                citations=self._citations(sources, list(sources), set()),
            )

        # 3. Ambiguity check.
        if self._is_vague(question):
            return done(
                status="needs_clarification",
                answer="Your question is ambiguous. Please say which equipment or quantity you mean "
                "(for example 'transformer loading limit' or 'voltage drop limit for feeders') and give any values with units.",
            )

        # 4. Retrieval.
        k = top_k or self.settings.top_k
        hits = self.store.search(question, k=k, doc_ids=doc_ids)
        top = hits[0].semantic if hits else 0.0
        if not hits or not self._relevant(question, hits):
            return done(
                status="abstained",
                answer="I could not find sufficiently relevant evidence in the indexed documents to answer this. "
                "Try rephrasing, selecting other documents, or uploading a document that covers the topic.",
                retrieval_top_score=round(top, 4),
            )
        if not self.llm and self._out_of_corpus(question):
            return done(
                status="abstained",
                answer="The question uses terms that do not appear in the indexed documents, so I cannot answer it "
                "from the available evidence.",
                retrieval_top_score=round(top, 4),
            )

        # 5. Treat retrieved text as untrusted: drop instruction-like sentences.
        sources = label_sources(hits)
        texts: dict[str, str] = {}
        flagged: set[str] = set()
        for sid, h in sources.items():
            clean, was_flagged = strip_injected_sentences(h.text)
            texts[sid] = clean
            if was_flagged:
                flagged.add(sid)
        if flagged:
            warnings.append(
                "Instruction-like text was found in a source and was ignored: " + ", ".join(sorted(flagged))
            )

        # 6. Generate.
        gen: Generated
        if self.llm:
            try:
                gen = llm_answer(self.llm, question, sources, texts)
                usage.add(gen.usage)
            except LLMError as exc:
                warnings.append(f"LLM unavailable ({exc}); returned extractive answer instead.")
                gen = extractive_answer(question, sources, texts, self.store.embed)
        else:
            gen = extractive_answer(question, sources, texts, self.store.embed)
        warnings += gen.warnings

        if gen.abstain:
            return done(
                status="abstained",
                answer=gen.answer
                or "The retrieved documents do not contain enough information to answer this question reliably.",
                retrieval_top_score=round(top, 4),
            )

        used_texts = {sid: texts[sid] for sid in gen.used_ids}
        grounding = check_grounding(gen.answer, used_texts, extra_numbers=numbers_in(question))
        if grounding.score < 0.5:
            warnings.append("Low grounding score: parts of this answer may not be supported by the cited sources.")
        return done(
            status="answered",
            answer=gen.answer,
            citations=self._citations(sources, gen.used_ids, flagged),
            grounding=grounding,
            retrieval_top_score=round(top, 4),
        )

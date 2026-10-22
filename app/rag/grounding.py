"""Post-hoc checks that an answer is supported by the sources it cites.

A sentence counts as supported when (a) at least `min_recall` of its content words
appear in the text of the sources it cites (or in all cited sources if the sentence
has no marker), and (b) every number in it appears in those sources or in a
calculation result. This is a cheap lexical proxy for faithfulness: it catches
invented numbers and off-source claims, but it cannot judge paraphrased reasoning.
"""

from __future__ import annotations

import re

from app.rag.store import tokenize
from app.schemas import Grounding

CITE_RE = re.compile(r"\[(S\d+)\]")
NUM_RE = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)?")
SENT_RE = re.compile(r"(?<=[.!?\]])[ \t]+(?=[A-Z(])|\n+")


def _norm_num(s: str) -> str:
    s = s.replace(",", ".")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def numbers_in(text: str) -> set[str]:
    return {_norm_num(n) for n in NUM_RE.findall(CITE_RE.sub("", text))}


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT_RE.split(text.strip()) if s.strip()]


def check_grounding(
    answer: str, sources: dict[str, str], extra_numbers: set[str] | None = None, min_recall: float = 0.6
) -> Grounding:
    sentences = [s for s in split_sentences(answer) if len(tokenize(CITE_RE.sub("", s))) >= 3]
    if not sentences:
        return Grounding(supported_sentences=0, total_sentences=0, score=1.0)
    extra = extra_numbers or set()
    supported = 0
    bad_numbers: list[str] = []
    for sent in sentences:
        ids = [i for i in CITE_RE.findall(sent) if i in sources] or list(sources)
        ref = " ".join(sources[i] for i in ids)
        ref_tokens = set(tokenize(ref))
        toks = [t for t in tokenize(CITE_RE.sub("", sent)) if not NUM_RE.fullmatch(t)]
        recall = sum(t in ref_tokens for t in toks) / len(toks) if toks else 1.0
        missing_nums = [n for n in numbers_in(sent) if n not in numbers_in(ref) and n not in extra]
        # small integers (list ordinals, "S1") are too ambiguous to penalise
        missing_nums = [n for n in missing_nums if not (n.isdigit() and int(n) <= 10)]
        bad_numbers += missing_nums
        if recall >= min_recall and not missing_nums:
            supported += 1
    return Grounding(
        supported_sentences=supported,
        total_sentences=len(sentences),
        score=round(supported / len(sentences), 3),
        unsupported_numbers=sorted(set(bad_numbers)),
    )

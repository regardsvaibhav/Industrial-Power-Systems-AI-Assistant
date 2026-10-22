"""Prompt-injection heuristics and text sanitisation.

Defence in depth, not a guarantee:
1. Questions with clear jailbreak/override phrasing are refused before retrieval.
2. Retrieved text is treated as data: suspicious sentences are removed before it
   reaches the LLM, and the chunk is flagged in the response.
3. Retrieved text is escaped and wrapped in delimiters; the system prompt says
   instructions inside sources must be ignored.
4. Model output is validated: only citation ids that were actually provided survive,
   and tool calls are limited to the whitelisted, schema-validated calculators.
"""

from __future__ import annotations

import re

_INJECTION_PATTERNS = [
    r"\bignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier|preceding)\s+(?:instructions|prompts?|rules|messages)",
    r"\bdisregard\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier|system)\b",
    r"\bforget\s+(?:all\s+|everything|your)\s*(?:previous|prior|instructions|rules)?",
    r"\b(?:reveal|print|show|repeat|output|leak)\s+(?:me\s+)?(?:the\s+|your\s+)?(?:system|hidden|developer|initial)\s+(?:prompt|instructions|message)",
    r"\byou\s+are\s+now\s+(?:a|an|in)\b",
    r"\b(?:act|behave)\s+as\s+(?:if\s+you\s+(?:are|were)\s+)?(?:an?\s+)?(?:unrestricted|jailbroken|dan)\b",
    r"\bdeveloper\s+mode\b",
    r"\bnew\s+instructions?\s*:",
    r"\bsystem\s*prompt\s*:",
    r"<\s*/?\s*(?:system|assistant|im_start|im_end)\s*>",
    r"\b(?:api[_\s-]?key|secret[_\s-]?key|password|credentials?)\b.*\b(?:send|reveal|print|show|give)\b",
    r"\b(?:send|reveal|print|show|give)\b.*\b(?:api[_\s-]?key|secret[_\s-]?key|password|credentials?)\b",
    r"\b(?:execute|run|eval)\s+(?:this\s+|the\s+following\s+)?(?:python|shell|bash|code|command)",
    r"\bos\.system\b|\bsubprocess\b|__import__|\brm\s+-rf\b",
]
INJECTION_RE = re.compile("|".join(f"(?:{p})" for p in _INJECTION_PATTERNS), re.IGNORECASE)
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def looks_like_injection(text: str) -> bool:
    return bool(INJECTION_RE.search(text))


def strip_injected_sentences(text: str) -> tuple[str, bool]:
    """Remove sentences that look like instructions to the model. Returns (clean_text, flagged)."""
    sentences = _SENT_SPLIT.split(text)
    kept = [s for s in sentences if not INJECTION_RE.search(s)]
    return " ".join(kept), len(kept) != len(sentences)


def escape_for_prompt(text: str) -> str:
    """Neutralise anything that could close our XML-ish delimiters."""
    return text.replace("<", "‹").replace(">", "›")


_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9._-]{16,})")


def redact_secrets(text: str) -> str:
    return _SECRET_RE.sub("[REDACTED]", text)

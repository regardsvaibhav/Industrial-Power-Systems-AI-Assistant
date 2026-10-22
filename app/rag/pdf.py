"""Safe PDF parsing and page-aware chunking.

Safety measures: magic-byte check, size and page limits, encrypted PDFs rejected,
parsing from memory (no shell-outs, no JavaScript execution: PyMuPDF only extracts
text), and text normalisation that removes control characters.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field

import pymupdf

HEADING_RE = re.compile(r"^\d{1,2}\.\s+[A-Z][^\n]{2,80}$")
FOOTER_RE = re.compile(r"^.{0,40}\|\s*page \d+ of \d+$", re.IGNORECASE)
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁦-⁩]")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")


class PDFError(ValueError):
    """Raised for files that are not acceptable PDFs."""


@dataclass
class Page:
    number: int  # 1-based
    text: str


@dataclass
class ParsedPDF:
    doc_id: str
    title: str
    page_count: int
    pages: list[Page]


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    text: str
    page: int
    section: str
    metadata: dict = field(default_factory=dict)


def normalise_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)  # fixes ligatures such as "ﬃ"
    text = CONTROL_RE.sub("", text)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # de-hyphenate line breaks
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln and not FOOTER_RE.match(ln)]
    return "\n".join(lines)


def parse_pdf(data: bytes, filename: str, max_pages: int = 300, max_bytes: int = 15 * 1024 * 1024) -> ParsedPDF:
    if len(data) > max_bytes:
        raise PDFError(f"File exceeds {max_bytes // (1024 * 1024)} MB limit")
    if not data.lstrip()[:5].startswith(b"%PDF-"):
        raise PDFError("Not a PDF file (missing %PDF header)")
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # PyMuPDF raises various types for corrupt files
        raise PDFError(f"Could not open PDF: {type(exc).__name__}") from exc
    try:
        if doc.needs_pass or doc.is_encrypted:
            raise PDFError("Encrypted or password-protected PDFs are not supported")
        if doc.page_count == 0:
            raise PDFError("PDF has no pages")
        if doc.page_count > max_pages:
            raise PDFError(f"PDF has {doc.page_count} pages; limit is {max_pages}")
        pages = [Page(i + 1, normalise_text(p.get_text("text", sort=True))) for i, p in enumerate(doc)]
        title = (doc.metadata or {}).get("title") or ""
    finally:
        doc.close()
    if not any(p.text for p in pages):
        raise PDFError("No extractable text (scanned PDFs need OCR, which is not enabled)")
    title = CONTROL_RE.sub("", title).strip()[:200] or filename.rsplit(".", 1)[0]
    doc_id = hashlib.sha256(data).hexdigest()[:16]
    return ParsedPDF(doc_id=doc_id, title=title, page_count=len(pages), pages=pages)


def _paragraphs(page_text: str) -> list[str]:
    """Rebuild paragraphs from wrapped lines; headings become their own paragraph."""
    paras: list[str] = []
    buf: list[str] = []
    for line in page_text.splitlines():
        if HEADING_RE.match(line):
            if buf:
                paras.append(" ".join(buf))
                buf = []
            paras.append(line)
            continue
        buf.append(line)
        if line.endswith((".", ":", "?")) and len(line) < 60:  # short final line => paragraph end
            paras.append(" ".join(buf))
            buf = []
    if buf:
        paras.append(" ".join(buf))
    return paras


def chunk_pdf(parsed: ParsedPDF, filename: str, size: int = 900, overlap: int = 150) -> list[Chunk]:
    """Chunk page by page so every chunk maps to exactly one page (precise citations).

    Paragraphs are packed up to `size` characters; long paragraphs are split on
    sentence boundaries; the tail of the previous chunk (up to `overlap` chars, whole
    sentences) is carried into the next chunk on the same page.
    """
    chunks: list[Chunk] = []
    section = ""
    for page in parsed.pages:
        units: list[tuple[str, str]] = []  # (text, section at that point)
        for para in _paragraphs(page.text):
            if HEADING_RE.match(para):
                section = para
                units.append((para, section))
                continue
            if len(para) <= size:
                units.append((para, section))
            else:
                for sent in SENTENCE_RE.split(para):
                    units.append((sent, section))

        current: list[str] = []
        cur_section = section
        idx_on_page = 0

        def flush() -> None:
            nonlocal current, idx_on_page
            text = " ".join(current).strip()
            if len(text) >= 40:
                cid = f"{parsed.doc_id}:p{page.number}:c{idx_on_page}"
                chunks.append(
                    Chunk(
                        chunk_id=cid,
                        doc_id=parsed.doc_id,
                        text=text,
                        page=page.number,
                        section=cur_section,
                        metadata={
                            "doc_id": parsed.doc_id,
                            "filename": filename,
                            "title": parsed.title,
                            "page": page.number,
                            "section": cur_section,
                            "chunk_index": idx_on_page,
                        },
                    )
                )
                idx_on_page += 1

        for text, sec in units:
            if current and sum(len(c) + 1 for c in current) + len(text) > size:
                flush()
                tail: list[str] = []
                for sent in reversed(SENTENCE_RE.split(" ".join(current))):
                    if sum(len(t) for t in tail) + len(sent) > overlap:
                        break
                    tail.insert(0, sent)
                current = tail
            if not current:
                cur_section = sec
            current.append(text)
        if current:
            flush()
    return chunks

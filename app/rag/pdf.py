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
SENTENCE_RE = re.compile(r"(?<=[a-zA-Z)%][.!?])\s+(?=[A-Z(])")


class PDFError(ValueError):
    """Raised for files that are not acceptable PDFs."""


@dataclass
class Page:
    number: int  # 1-based
    text: str
    continues: bool = False  # last sentence finishes on the next page


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
    text = re.sub(r"(\w)-\n(\w)", r"\1-\2", text)  # re-join words split at a hyphen
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
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


TERMINAL_RE = re.compile(r"[.!?:]\s*$")
FIRST_SENTENCE_RE = re.compile(r"^(.{1,400}?[.!?])(?=\s|$)", re.DOTALL)


def _join_split_sentences(pages: list[Page]) -> list[Page]:
    """Move a sentence fragment that starts a page back onto the previous page.

    Without this, a sentence broken across a page boundary yields two half-sentences
    that are hard to retrieve and quote. The sentence is cited with the page it starts on.
    """
    texts = [p.text for p in pages]
    moved = [False] * len(pages)
    for i in range(len(texts) - 1):
        if texts[i] and not TERMINAL_RE.search(texts[i]) and texts[i + 1]:
            m = FIRST_SENTENCE_RE.match(texts[i + 1])
            if m and not HEADING_RE.match(texts[i + 1].splitlines()[0]):
                texts[i] = texts[i] + " " + m.group(1).replace("\n", " ")
                texts[i + 1] = texts[i + 1][m.end() :].lstrip()
                moved[i] = True
    return [Page(p.number, t, mv) for p, t, mv in zip(pages, texts, moved, strict=True)]


def _make_chunk(parsed: ParsedPDF, filename: str, page_no: int, idx: int, units: list[tuple[str, str]]) -> Chunk | None:
    # Headings end with a newline so they never fuse with the first sentence.
    text = " ".join(t + "\n" if HEADING_RE.match(t) else t for t, _ in units).replace("\n ", "\n").strip()
    if len(text) < 40:
        return None
    # A chunk is labelled by the first heading it contains, else the inherited section.
    headings = [t for t, _ in units if HEADING_RE.match(t)]
    sec = headings[0] if headings else units[0][1]
    return Chunk(
        chunk_id=f"{parsed.doc_id}:p{page_no}:c{idx}",
        doc_id=parsed.doc_id,
        text=text,
        page=page_no,
        section=sec,
        metadata={
            "doc_id": parsed.doc_id,
            "filename": filename,
            "title": parsed.title,
            "page": page_no,
            "section": sec,
            "chunk_index": idx,
        },
    )


def chunk_pdf(parsed: ParsedPDF, filename: str, size: int = 900, overlap: int = 150) -> list[Chunk]:
    """Chunk page by page so every chunk maps to exactly one page (precise citations).

    Paragraphs are packed up to `size` characters; long paragraphs are split on
    sentence boundaries; the tail of the previous chunk (up to `overlap` chars, whole
    sentences) is carried into the next chunk on the same page.
    """
    chunks: list[Chunk] = []
    section = ""
    for page in _join_split_sentences(parsed.pages):
        units: list[tuple[str, str]] = []  # (text, section in effect at that text)
        for para in _paragraphs(page.text):
            if HEADING_RE.match(para):
                section = para
                units.append((para, section))
            elif len(para) <= size:
                units.append((para, section))
            else:
                units.extend((sent, section) for sent in SENTENCE_RE.split(para))

        current: list[tuple[str, str]] = []

        def flush(units_: list[tuple[str, str]], page_no: int) -> None:
            chunk = _make_chunk(parsed, filename, page_no, sum(c.page == page_no for c in chunks), units_)
            if chunk:
                chunks.append(chunk)

        for text, sec in units:
            if current and sum(len(t) + 1 for t, _ in current) + len(text) > size:
                carried = []
                while current and HEADING_RE.match(current[-1][0]):  # don't end a chunk on a heading
                    carried.insert(0, current.pop())
                flush(current, page.number)
                tail: list[tuple[str, str]] = []
                if current and not carried:
                    last_text, last_sec = current[-1]
                    for sent in reversed(SENTENCE_RE.split(last_text)):
                        if sum(len(t) for t, _ in tail) + len(sent) > overlap:
                            break
                        tail.insert(0, (sent, last_sec))
                current = tail + carried
            current.append((text, sec))
        if current:
            flush(current, page.number)
        if page.continues and chunks and chunks[-1].page == page.number:
            chunks[-1].metadata["page_end"] = page.number + 1
    for c in chunks:
        c.metadata.setdefault("page_end", c.page)
        c.metadata["page_count"] = parsed.page_count
    return chunks

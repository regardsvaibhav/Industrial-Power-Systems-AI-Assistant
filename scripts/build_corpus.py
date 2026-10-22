"""Render the sample reference notes in data/corpus_src/*.md into PDFs in data/corpus/.

The notes are original educational material written for this project (no standards
text, no vendor or site data). Rendering is deterministic, so the benchmark's
page-level ground truth stays valid as long as the sources don't change.

Usage: python scripts/build_corpus.py
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "corpus_src"
OUT = ROOT / "data" / "corpus"

NOTICE = (
    "Original educational notes written for the Industrial Power Systems AI Assistant "
    "sample corpus. Not a standard and not an operating procedure. Licensed CC BY 4.0."
)

CSS = """
body { font-family: sans-serif; font-size: 10.5pt; line-height: 1.35; }
h1 { font-size: 17pt; margin-bottom: 4pt; }
h2 { font-size: 12.5pt; margin-top: 12pt; margin-bottom: 3pt; }
p { margin-top: 0; margin-bottom: 6pt; text-align: justify; }
li { margin-bottom: 3pt; }
.notice { font-size: 8.5pt; color: #555555; font-style: italic; }
"""

# A5-ish content area keeps each note to a few pages, so page citations are meaningful.
PAGE = pymupdf.paper_rect("a5")
MARGIN = 42


def md_to_html(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    title = lines[0].lstrip("# ").strip()
    parts = [f"<h1>{html.escape(title)}</h1>", f"<p class='notice'>{html.escape(NOTICE)}</p>"]
    in_list = False
    for line in lines[1:]:
        line = line.rstrip()
        if line.startswith("- "):
            if not in_list:
                parts.append("<ul>")
                in_list = True
            parts.append(f"<li>{html.escape(line[2:])}</li>")
            continue
        if in_list:
            parts.append("</ul>")
            in_list = False
        if line.startswith("## "):
            parts.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line:
            parts.append(f"<p>{html.escape(line)}</p>")
    if in_list:
        parts.append("</ul>")
    return title, "\n".join(parts)


def render(md_path: Path, out_path: Path) -> int:
    title, body = md_to_html(md_path.read_text(encoding="utf-8"))
    story = pymupdf.Story(html=body, user_css=CSS)
    writer = pymupdf.DocumentWriter(str(out_path))
    where = PAGE + (MARGIN, MARGIN, -MARGIN, -MARGIN)
    more = True
    while more:
        device = writer.begin_page(PAGE)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
    writer.close()

    # Footer with page numbers and document metadata.
    doc = pymupdf.open(out_path)
    doc.set_metadata({"title": title, "author": "industrial-power-ai sample corpus", "subject": NOTICE})
    for i, page in enumerate(doc, start=1):
        footer = pymupdf.Rect(MARGIN, PAGE.height - 30, PAGE.width - MARGIN, PAGE.height - 15)
        page.insert_textbox(footer, f"{title.split(' ')[0]}  |  page {i} of {doc.page_count}", fontsize=7, align=1)
    doc.saveIncr()
    n = doc.page_count
    doc.close()
    return n


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    sources = sorted(SRC.glob("*.md"))
    if not sources:
        print(f"No sources in {SRC}", file=sys.stderr)
        return 1
    for src in sources:
        out = OUT / (src.stem + ".pdf")
        pages = render(src, out)
        print(f"{out.relative_to(ROOT)}: {pages} pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

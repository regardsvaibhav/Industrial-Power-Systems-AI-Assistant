"""Index every PDF in data/corpus (or a given directory) into the vector store.

Usage: python scripts/ingest_corpus.py [--reset] [DIR]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.assistant import Assistant  # noqa: E402
from app.config import get_settings  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("directory", nargs="?", type=Path)
    ap.add_argument("--reset", action="store_true", help="delete the collection first")
    a = ap.parse_args()
    s = get_settings()
    assistant = Assistant(s)
    if a.reset:
        assistant.store.reset()
    for r in assistant.ingest_directory(a.directory or s.corpus_dir):
        print(f"{r.filename}: {r.pages} pages, {r.chunks} chunks{' (already indexed)' if r.duplicate else ''}")
    print(f"Total chunks in store: {assistant.store.count()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

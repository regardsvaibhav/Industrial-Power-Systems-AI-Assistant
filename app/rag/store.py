"""Vector store (Chroma, persistent) plus an in-memory BM25 index for hybrid retrieval.

Why Chroma: embedded (no extra service to run or pay for), persistent on local disk,
supports metadata filters, and ships a CPU ONNX MiniLM embedding model, so the
container needs no GPU and no paid embedding API. The trade-off is single-node scale,
which is fine for a document assistant of this size.
"""

from __future__ import annotations

import logging
import math
import re
import threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

from app.rag.pdf import Chunk

log = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
STOPWORDS = frozenset(
    "a an the of and or to in on at for by with is are was were be been being as that this these those it its "
    "from what which who whom how why when where does do did can could should would will may might must not "
    "than then there their them they i you we he she our your my me us if into over under about between".split()
)


def stem(t: str) -> str:
    """Very light suffix stripping so "conditions"/"condition" and "loaded"/"loading" match."""
    if t[0].isdigit() or len(t) <= 3:
        return t
    if t.endswith("ies") and len(t) > 4:
        return t[:-3] + "y"
    if t.endswith("ing") and len(t) > 5:
        return t[:-3]
    if t.endswith("ed") and len(t) > 4:
        return t[:-2]
    if t.endswith("s") and not t.endswith(("ss", "us", "is")):
        return t[:-1]
    return t


def tokenize(text: str) -> list[str]:
    return [stem(t) for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


@dataclass
class Hit:
    chunk_id: str
    text: str
    metadata: dict
    semantic: float  # cosine similarity in [-1, 1]
    lexical: float = 0.0  # normalised BM25 in [0, 1]
    score: float = 0.0  # fused score used for ranking


class BM25:
    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.docs: dict[str, Counter] = {}
        self.lengths: dict[str, int] = {}
        self.df: Counter = Counter()

    def rebuild(self, items: dict[str, str]) -> None:
        self.docs = {cid: Counter(tokenize(t)) for cid, t in items.items()}
        self.lengths = {cid: sum(c.values()) for cid, c in self.docs.items()}
        self.df = Counter(tok for c in self.docs.values() for tok in c)

    def scores(self, query: str, ids: list[str] | None = None) -> dict[str, float]:
        n = len(self.docs)
        if not n:
            return {}
        avgdl = sum(self.lengths.values()) / n
        q = set(tokenize(query))
        out = {}
        for cid in ids if ids is not None else self.docs:
            tf = self.docs.get(cid)
            if tf is None:
                continue
            s = 0.0
            for tok in q:
                f = tf.get(tok, 0)
                if not f:
                    continue
                idf = math.log(1 + (n - self.df[tok] + 0.5) / (self.df[tok] + 0.5))
                s += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.lengths[cid] / avgdl))
            out[cid] = s
        return out


class VectorStore:
    def __init__(self, persist_dir: Path, collection: str = "power_docs") -> None:
        persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(persist_dir), settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True)
        )
        self._ef = ONNXMiniLM_L6_V2()
        self._col = self._client.get_or_create_collection(
            collection, embedding_function=self._ef, metadata={"hnsw:space": "cosine"}
        )
        self._bm25 = BM25()
        self._lock = threading.Lock()
        self._rebuild_lexical()

    # ---------------------------------------------------------------- writes
    def add_chunks(self, chunks: list[Chunk]) -> int:
        if not chunks:
            return 0
        with self._lock:
            for i in range(0, len(chunks), 64):
                batch = chunks[i : i + 64]
                self._col.upsert(
                    ids=[c.chunk_id for c in batch],
                    documents=[c.text for c in batch],
                    metadatas=[c.metadata for c in batch],
                )
            self._rebuild_lexical()
        return len(chunks)

    def delete_document(self, doc_id: str) -> int:
        with self._lock:
            ids = self._col.get(where={"doc_id": doc_id}, include=[])["ids"]
            if ids:
                self._col.delete(ids=ids)
                self._rebuild_lexical()
        return len(ids)

    def reset(self) -> None:
        with self._lock:
            name, meta = self._col.name, self._col.metadata
            self._client.delete_collection(name)
            self._col = self._client.get_or_create_collection(name, embedding_function=self._ef, metadata=meta)
            self._rebuild_lexical()

    def _rebuild_lexical(self) -> None:
        data = self._col.get(include=["documents"])
        self._bm25.rebuild(dict(zip(data["ids"], data["documents"] or [], strict=False)))

    # ---------------------------------------------------------------- reads
    def count(self) -> int:
        return self._col.count()

    def knows_token(self, token: str) -> bool:
        """True if the (tokenised) term occurs anywhere in the indexed corpus."""
        return self._bm25.df.get(token, 0) > 0

    def has_document(self, doc_id: str) -> bool:
        return bool(self._col.get(where={"doc_id": doc_id}, include=[], limit=1)["ids"])

    def list_documents(self) -> list[dict]:
        data = self._col.get(include=["metadatas"])
        docs: dict[str, dict] = {}
        for meta in data["metadatas"] or []:
            d = docs.setdefault(
                meta["doc_id"],
                {
                    "doc_id": meta["doc_id"],
                    "title": meta["title"],
                    "filename": meta["filename"],
                    "chunks": 0,
                    "pages": 0,
                },
            )
            d["chunks"] += 1
            d["pages"] = int(meta.get("page_count") or max(d["pages"], int(meta["page"])))
        return sorted(docs.values(), key=lambda d: d["title"])

    def get_chunk(self, chunk_id: str) -> Hit | None:
        data = self._col.get(ids=[chunk_id], include=["documents", "metadatas"])
        if not data["ids"]:
            return None
        return Hit(chunk_id, data["documents"][0], data["metadatas"][0], semantic=0.0)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._ef(texts)]

    def search(
        self,
        query: str,
        k: int = 5,
        doc_ids: list[str] | None = None,
        hybrid: bool = True,
        candidates: int = 20,
        alpha: float = 0.7,
    ) -> list[Hit]:
        """Semantic search with optional metadata filter and BM25 fusion.

        Fused score = alpha * cosine + (1 - alpha) * bm25 / max_bm25(candidates).
        Only the semantic score is used for the abstention threshold, because BM25 is
        relative to the candidate set and says nothing about absolute relevance.
        """
        total = self.count()
        if total == 0:
            return []
        where = None
        if doc_ids:
            where = {"doc_id": doc_ids[0]} if len(doc_ids) == 1 else {"doc_id": {"$in": list(doc_ids)}}
        n = min(max(candidates, k), total)
        res = self._col.query(
            query_texts=[query], n_results=n, where=where, include=["documents", "metadatas", "distances"]
        )
        hits = [
            Hit(cid, doc, meta, semantic=1.0 - dist)
            for cid, doc, meta, dist in zip(
                res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0], strict=True
            )
        ]
        if hybrid and hits:
            bm = self._bm25.scores(query, [h.chunk_id for h in hits])
            top = max(bm.values(), default=0.0) or 1.0
            for h in hits:
                h.lexical = bm.get(h.chunk_id, 0.0) / top
                h.score = alpha * h.semantic + (1 - alpha) * h.lexical
        else:
            for h in hits:
                h.score = h.semantic
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]

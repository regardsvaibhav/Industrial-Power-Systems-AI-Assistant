"""Run the benchmark end to end and write a JSON + Markdown report.

Usage:
    python eval/run_eval.py                 # mode follows LLM_API_KEY (llm if set, else extractive)
    python eval/run_eval.py --mode extractive
    python eval/run_eval.py --llm-judge     # also score faithfulness with the LLM (needs a key)

The index is rebuilt from data/corpus in a temporary directory on every run, so results
do not depend on whatever happens to be in the app's store. Gold pages are located by
searching each item's `evidence` phrase in the PDFs, so they cannot drift silently: a
missing phrase aborts the run.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import platform
import re
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402

from app import __version__  # noqa: E402
from app.assistant import Assistant  # noqa: E402
from app.config import Settings  # noqa: E402
from app.llm.client import LLMClient, parse_json_object  # noqa: E402
from app.rag.pdf import normalise_text  # noqa: E402
from app.rag.store import VectorStore  # noqa: E402

BENCH = ROOT / "eval" / "benchmark.jsonl"
REPORTS = ROOT / "reports"
KS = (1, 3, 5)
RAG_CATS = ("retrieval", "explanation")


def squash(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def locate_evidence(corpus: Path) -> dict[str, dict[int, str]]:
    """{doc_prefix: {page: squashed text}} for every corpus PDF."""
    out = {}
    for pdf in sorted(corpus.glob("*.pdf")):
        with pymupdf.open(pdf) as d:
            out[pdf.name.split("_")[0]] = {i + 1: squash(normalise_text(p.get_text())) for i, p in enumerate(d)}
    return out


def gold_pages(item: dict, pages: dict[str, dict[int, str]]) -> set[tuple[str, int]]:
    """Gold (doc, page) pairs: where the evidence phrase (and any `alt` evidence) appears."""
    gold: set[tuple[str, int]] = set()
    for doc, phrase in [(item["doc"], item["evidence"])] + [(a["doc"], a["evidence"]) for a in item.get("alt", [])]:
        found = {(doc, p) for p, t in pages[doc].items() if squash(phrase) in t}
        if not found:
            raise SystemExit(f"{item['id']}: evidence phrase not found in {doc}: {phrase!r}")
        gold |= found
    return gold


def is_gold(meta: dict, gold: set[tuple[str, int]]) -> bool:
    """A cited passage is correct if any page it spans is a gold page."""
    doc = meta["title"].split()[0]
    first = int(meta["page"])
    last = int(meta.get("page_end") or first)
    return any((doc, p) in gold for p in range(first, last + 1))


def close(actual, expected) -> bool:
    if isinstance(expected, bool) or isinstance(expected, str):
        return actual == expected
    return math.isclose(float(actual), float(expected), rel_tol=2e-3, abs_tol=0.011)


def pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def percentile(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    i = min(len(xs) - 1, max(0, math.ceil(q * len(xs)) - 1))
    return xs[i]


JUDGE_PROMPT = """You are grading whether an ANSWER is fully supported by the SOURCES.
Reply with JSON only: {"faithful": true|false, "reason": "<one sentence>"}.
faithful=true only if every factual claim in the ANSWER is stated in or directly implied by the SOURCES."""


def llm_judge(llm: LLMClient, answer: str, sources: list[str]) -> tuple[bool | None, float]:
    msg = "SOURCES:\n" + "\n---\n".join(sources) + f"\n\nANSWER:\n{answer}"
    reply = llm.chat([{"role": "system", "content": JUDGE_PROMPT}, {"role": "user", "content": msg}], json_mode=True)
    obj = parse_json_object(reply.content) or {}
    v = obj.get("faithful")
    return (bool(v) if isinstance(v, bool) else None), reply.usage.cost_usd


def git_commit() -> str:
    """Short HEAD hash, suffixed with -dirty if tracked files have uncommitted changes."""
    try:
        head = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(  # noqa: S603
            ["git", "status", "--porcelain", "--untracked-files=no"],  # noqa: S607
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return head + ("-dirty" if dirty else "")
    except Exception:
        return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["auto", "llm", "extractive"], default="auto")
    ap.add_argument("--llm-judge", action="store_true")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    items = [json.loads(line) for line in BENCH.read_text().splitlines() if line.strip()]
    tmp = Path(tempfile.mkdtemp(prefix="ipa-eval-"))
    base = Settings()
    settings = base.model_copy(
        update={"chroma_dir": tmp / "chroma", "upload_dir": tmp / "uploads", "rate_limit_per_minute": 10**6}
    )
    if args.mode == "extractive":
        settings = settings.model_copy(update={"llm_api_key": type(base.llm_api_key)("")})
    if args.mode == "llm" and not settings.llm_enabled:
        raise SystemExit("--mode llm requires LLM_API_KEY")

    t_index = time.perf_counter()
    store = VectorStore(settings.chroma_dir, "eval")
    assistant = Assistant(settings, store=store)
    assistant.ingest_directory(settings.corpus_dir)
    index_s = time.perf_counter() - t_index
    judge = LLMClient(settings) if (args.llm_judge and settings.llm_enabled) else None

    pages = locate_evidence(settings.corpus_dir)
    rows = []
    judge_cost = 0.0
    for item in items:
        row: dict = {"id": item["id"], "category": item["category"], "question": item["question"]}
        if item["category"] in RAG_CATS:
            gold = gold_pages(item, pages)
            row["gold"] = sorted(f"{d} p{p}" for d, p in gold)
            for hybrid in (True, False):
                hits = store.search(item["question"], k=max(KS), hybrid=hybrid)
                ranks = [i for i, h in enumerate(hits, 1) if is_gold(h.metadata, gold)]
                key = "hybrid" if hybrid else "semantic"
                row[f"{key}_first_gold_rank"] = ranks[0] if ranks else None

        resp = assistant.ask(item["question"])
        row.update(
            status=resp.status,
            answer=resp.answer,
            latency_ms=resp.latency_ms,
            cost_usd=resp.usage.cost_usd,
            tokens=resp.usage.prompt_tokens + resp.usage.completion_tokens,
            citations=[{"title": c.title.split()[0], "page": c.page} for c in resp.citations],
            grounding=resp.grounding.score if resp.grounding else None,
            unsupported_numbers=resp.grounding.unsupported_numbers if resp.grounding else [],
        )

        if item["category"] in RAG_CATS:
            answered = resp.status == "answered"
            row["answered"] = answered
            if answered:
                flags = [
                    is_gold({"title": c.title, "page": c.page, "page_end": c.page_end}, gold) for c in resp.citations
                ]
                row["citation_precision"] = sum(flags) / len(flags) if flags else 0.0
                row["citation_hit"] = any(flags)
                low = resp.answer.lower()
                row["key_fact_recall"] = sum(f.lower() in low for f in item["key_facts"]) / len(item["key_facts"])
                if judge:
                    verdict, cost = llm_judge(judge, resp.answer, [c.snippet for c in resp.citations])
                    row["judge_faithful"] = verdict
                    judge_cost += cost
        elif item["category"] == "calculation":
            ok = resp.status == "calculation" and resp.calculation is not None and resp.calculation.tool == item["tool"]
            mismatches = []
            if ok:
                outs = resp.calculation.outputs
                for k, exp in item["expected"].items():
                    v = outs.get(k)
                    v = v.value if hasattr(v, "value") else v
                    if v is None or not close(v, exp):
                        mismatches.append({"field": k, "expected": exp, "actual": v})
                if "expected_shed" in item:
                    shed = [x["name"] for x in outs.get("loads_shed", [])]
                    if shed != item["expected_shed"]:
                        mismatches.append({"field": "loads_shed", "expected": item["expected_shed"], "actual": shed})
            row["tool"] = resp.calculation.tool if resp.calculation else None
            row["mismatches"] = mismatches
            row["correct"] = ok and not mismatches
        else:
            row["correct"] = resp.status == item["expected_status"]
        rows.append(row)
        print(f"{item['id']:4} {resp.status:20} {resp.latency_ms:7.1f} ms")

    # ------------------------------------------------------------------ aggregate
    rag = [r for r in rows if r["category"] in RAG_CATS]
    answered = [r for r in rag if r["answered"]]
    m: dict = {}
    for key in ("hybrid", "semantic"):
        ranks = [r[f"{key}_first_gold_rank"] for r in rag]
        for k in KS:
            m[f"recall@{k}_{key}"] = mean([1.0 if (x is not None and x <= k) else 0.0 for x in ranks])
        m[f"mrr@5_{key}"] = mean([1 / x if x else 0.0 for x in ranks])
    m["answer_rate_answerable"] = mean([1.0 if r["answered"] else 0.0 for r in rag])
    m["false_abstention_rate"] = mean([0.0 if r["answered"] else 1.0 for r in rag])
    m["citation_precision"] = mean([r["citation_precision"] for r in answered])
    m["citation_hit_rate"] = mean([1.0 if r["citation_hit"] else 0.0 for r in answered])
    m["key_fact_recall"] = mean([r["key_fact_recall"] for r in answered])
    m["faithfulness_lexical"] = mean([r["grounding"] for r in answered if r["grounding"] is not None])
    m["answers_with_unsupported_numbers"] = sum(1 for r in answered if r["unsupported_numbers"])
    judged = [r["judge_faithful"] for r in answered if r.get("judge_faithful") is not None]
    m["faithfulness_llm_judge"] = mean([1.0 if v else 0.0 for v in judged]) if judged else None
    for cat in ("calculation", "ambiguous", "insufficient", "security"):
        m[f"{cat}_accuracy"] = mean([1.0 if r["correct"] else 0.0 for r in rows if r["category"] == cat])
    lat = [r["latency_ms"] for r in rows]
    m["latency_p50_ms"] = statistics.median(lat)
    m["latency_p95_ms"] = percentile(lat, 0.95)
    m["latency_p50_ms_answered_rag"] = statistics.median([r["latency_ms"] for r in answered]) if answered else None
    m["total_cost_usd"] = round(sum(r["cost_usd"] for r in rows) + judge_cost, 6)
    m["total_tokens"] = sum(r["tokens"] for r in rows)

    run = {
        "timestamp_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "app_version": __version__,
        "mode": assistant.mode,
        "llm_model": settings.llm_model if assistant.llm else None,
        "embedding_model": "all-MiniLM-L6-v2 (ONNX, via Chroma)",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "n_items": len(rows),
        "n_by_category": {c: sum(r["category"] == c for r in rows) for c in sorted({r["category"] for r in rows})},
        "index_build_s": round(index_s, 2),
        "settings": {
            "top_k": settings.top_k,
            "min_relevance": settings.min_relevance,
            "unknown_term_abstain_ratio": settings.unknown_term_abstain_ratio,
            "chunk_size_chars": settings.chunk_size_chars,
        },
    }
    REPORTS.mkdir(exist_ok=True)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    name = f"eval_{assistant.mode}{('_' + args.tag) if args.tag else ''}_{stamp}"
    (REPORTS / f"{name}.json").write_text(json.dumps({"run": run, "metrics": m, "rows": rows}, indent=2))
    md = render_markdown(run, m, rows)
    (REPORTS / f"{name}.md").write_text(md)
    (REPORTS / f"EVAL_REPORT_{assistant.mode}.md").write_text(md)
    print(f"\nWrote reports/{name}.json and .md")
    print(json.dumps(m, indent=2))
    return 0


def render_markdown(run: dict, m: dict, rows: list[dict]) -> str:
    L = [
        f"# Evaluation report ({run['mode']} mode)",
        "",
        f"Generated by `eval/run_eval.py` on {run['timestamp_utc']} at commit `{run['git_commit']}`. "
        "All numbers below come from this executed run; nothing is estimated or hand-entered.",
        "",
        f"- Items: {run['n_items']} ({', '.join(f'{k}: {v}' for k, v in run['n_by_category'].items())})",
        f"- Answer mode: **{run['mode']}**"
        + (f" with `{run['llm_model']}`" if run["llm_model"] else " (no LLM; answers are verbatim source sentences)"),
        f"- Embeddings: {run['embedding_model']}; index build {run['index_build_s']} s",
        f"- Settings: {run['settings']}",
        f"- Environment: Python {run['python']}, {run['platform']}",
        "",
        "## Retrieval (retrieval + explanation questions, gold = evidence page)",
        "",
        "| Metric | Hybrid (semantic + BM25) | Semantic only |",
        "|---|---|---|",
    ]
    for k in KS:
        L.append(f"| Recall@{k} | {pct(m[f'recall@{k}_hybrid'])} | {pct(m[f'recall@{k}_semantic'])} |")
    L.append(f"| MRR@5 | {m['mrr@5_hybrid']:.3f} | {m['mrr@5_semantic']:.3f} |")
    L += [
        "",
        "## Answers",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Answered (answerable questions) | {pct(m['answer_rate_answerable'])} |",
        f"| False abstention rate | {pct(m['false_abstention_rate'])} |",
        f"| Citation precision (cited page is a gold page) | {pct(m['citation_precision'])} |",
        f"| Citation hit rate (at least one gold citation) | {pct(m['citation_hit_rate'])} |",
        f"| Key-fact recall in answer | {pct(m['key_fact_recall'])} |",
        f"| Faithfulness, lexical grounding check | {pct(m['faithfulness_lexical'])} |",
        f"| Faithfulness, LLM judge | {pct(m['faithfulness_llm_judge']) if m['faithfulness_llm_judge'] is not None else 'not run'} |",
        f"| Answers containing numbers absent from sources | {m['answers_with_unsupported_numbers']} |",
        "",
        "## Behaviour",
        "",
        "| Category | Accuracy |",
        "|---|---|",
        f"| Calculations (right tool and all outputs within 0.2%) | {pct(m['calculation_accuracy'])} |",
        f"| Ambiguous -> asks for clarification | {pct(m['ambiguous_accuracy'])} |",
        f"| Insufficient evidence -> abstains | {pct(m['insufficient_accuracy'])} |",
        f"| Prompt injection -> rejected | {pct(m['security_accuracy'])} |",
        "",
        "## Latency and cost",
        "",
        f"- Latency p50 {m['latency_p50_ms']:.0f} ms, p95 {m['latency_p95_ms']:.0f} ms (all items, in-process, includes embedding)",
        f"- Total LLM cost: ${m['total_cost_usd']:.4f} for {m['total_tokens']} tokens",
        "",
        "## Per-item results",
        "",
        "| ID | Category | Status | Correct / gold rank | Citations | Latency ms |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        if r["category"] in RAG_CATS:
            res = f"rank {r['hybrid_first_gold_rank'] or '-'}; kf {r.get('key_fact_recall', '-')}"
        else:
            res = "yes" if r["correct"] else "**no**"
            if r.get("mismatches"):
                res += f" {r['mismatches']}"
        cites = ", ".join(f"{c['title']} p{c['page']}" for c in r["citations"]) or "-"
        L.append(f"| {r['id']} | {r['category']} | {r['status']} | {res} | {cites} | {r['latency_ms']:.0f} |")
    L += [
        "",
        "## Limitations",
        "",
        "- 57 items written by the project author over a 7-document, 21-page corpus also written for this project: "
        "small and not independent, so treat percentages as indicative (one item is ~2-5 points per category).",
        "- Key-fact recall is a substring check; lexical faithfulness only checks word overlap and numbers. "
        "In extractive mode answers are copied source sentences, so faithfulness is high by construction.",
        "- Latency is measured in-process on the evaluation machine, not over the network.",
    ]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())

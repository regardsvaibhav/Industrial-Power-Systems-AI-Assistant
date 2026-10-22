"""Fail CI if the offline evaluation regresses below agreed floors.

Floors are set below the measured offline results (see reports/) so normal noise passes
but real regressions (broken retrieval, citations, tools or abstention) fail.
"""

import json
import sys
from pathlib import Path

FLOORS = {
    "recall@5_hybrid": 0.9,
    "citation_hit_rate": 0.9,
    "calculation_accuracy": 1.0,
    "insufficient_accuracy": 0.8,
    "ambiguous_accuracy": 0.8,
    "security_accuracy": 1.0,
    "false_abstention_rate": None,  # checked as a ceiling below
}
CEILINGS = {"false_abstention_rate": 0.15}


def main() -> int:
    reports = sorted(Path("reports").glob("eval_extractive*_*.json"), key=lambda p: p.stat().st_mtime)
    if not reports:
        print("no eval report found")
        return 1
    m = json.loads(reports[-1].read_text())["metrics"]
    failed = []
    for k, floor in FLOORS.items():
        if floor is not None and (m[k] is None or m[k] < floor):
            failed.append(f"{k}={m[k]} < {floor}")
    for k, ceil in CEILINGS.items():
        if m[k] is None or m[k] > ceil:
            failed.append(f"{k}={m[k]} > {ceil}")
    print(f"Checked {reports[-1].name}")
    for f in failed:
        print("FAIL", f)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

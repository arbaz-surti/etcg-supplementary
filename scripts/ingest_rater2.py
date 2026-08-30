#!/usr/bin/env python3
"""
Ingest the round 2 rater 2 response.
====================================

Round 2 sent one 75-charter packet (25 ETCG + 25 Baseline carried over verbatim
from round 1, + 25 new Intermediate) to a second independent human rater. This
script parses that rater's returned table from

    paper-2-EMSE/research/irr-r2-rater2-response.md

and writes the machine-readable form

    paper-2-EMSE/research/irr-r2-rater2-response.csv

matching the schema of irr-r2-response-template.csv, so analysis.py can pick it
up the same way it picks up rater 1's xlsx.

Validation performed:
  * exactly 75 rows, ids CHR-R2-001 .. CHR-R2-075, contiguous
  * every score in {1, 2, 3}
  * per-column sums and the mean charter percentage printed for eyeball check
    against the source table

Usage:
    python scripts/ingest_rater2.py
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PAPER = REPO.parent / "paper-2-EMSE"
SRC = PAPER / "research" / "irr-r2-rater2-response.md"
OUT = PAPER / "research" / "irr-r2-rater2-response.csv"

DIMS = ["specificity", "testability", "risk_coverage", "clarity", "actionability"]
ROW_RE = re.compile(r"^\|\s*(CHR-R2-\d{3})\s*\|(.+)\|\s*$")


def parse(src: Path) -> list[dict]:
    rows: list[dict] = []
    for line in src.read_text(encoding="utf-8").splitlines():
        m = ROW_RE.match(line.strip())
        if not m:
            continue
        cid = m.group(1)
        cells = [c.strip() for c in m.group(2).split("|")]
        cells = [c for c in cells if c != ""]
        if len(cells) != 5:
            raise SystemExit(f"{cid}: expected 5 score cells, got {len(cells)}: {cells}")
        vals = [int(c) for c in cells]
        for v in vals:
            if v not in (1, 2, 3):
                raise SystemExit(f"{cid}: score {v} outside 1..3")
        rows.append({"charter_id": cid, **dict(zip(DIMS, vals))})
    return rows


def main() -> int:
    rows = parse(SRC)

    if len(rows) != 75:
        raise SystemExit(f"expected 75 rows, parsed {len(rows)}")
    ids = [r["charter_id"] for r in rows]
    expected = [f"CHR-R2-{i:03d}" for i in range(1, 76)]
    if ids != expected:
        missing = set(expected) - set(ids)
        extra = set(ids) - set(expected)
        raise SystemExit(f"id mismatch. missing={sorted(missing)} extra={sorted(extra)}")

    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["charter_id", *DIMS, "notes"])
        for r in rows:
            w.writerow([r["charter_id"], *[r[d] for d in DIMS], ""])

    total = 0
    print(f"parsed {len(rows)} rows -> {OUT.relative_to(REPO.parent)}")
    print()
    print(f"{'dimension':<16} {'sum':>5} {'mean':>6}")
    for d in DIMS:
        s = sum(r[d] for r in rows)
        total += s
        print(f"{d:<16} {s:>5} {s / len(rows):>6.3f}")
    print(f"{'ALL':<16} {total:>5} {total / (len(rows) * 5):>6.3f}")
    print()
    print(f"mean charter percentage: {total / (len(rows) * 15) * 100:.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())

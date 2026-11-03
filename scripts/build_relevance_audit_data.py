#!/usr/bin/env python3
"""
Assemble the relevance / hallucination / redundancy audit into package data.
============================================================================

Reviewer 1 (round 2) asked for evidence on hallucinated, irrelevant, or redundant
charters. build_relevance_audit.py drew the 75-charter sample and wrote the coder
sheet; one external coder, blind to condition, returned it. This script joins the
coder's answers to the sampling key (which says which condition and charter each
neutral code came from) and writes data/relevance-audit.csv, which analysis.py reads.

Two coder files are joined, because the coding took one clarification round:

    first pass   the coder's first answers with reasons (Q1 = Yes on 12 charters,
                 each reason describing a hypothesised risk)
    final        after the author re-quoted the sheet's Q1 rule ("Answer No for
                 ordinary testing ideas about plausible risks"), the coder re-coded
                 those 12 to No; Q2 and Q3 were unchanged

Both Q1 columns are kept so the clarification is visible in the data, not only in
the prose. The raw coder files stay in the paper tree (research/relevance-audit/
responses/) because they repeat the charter text, which the package already ships.

Usage:
    python scripts/build_relevance_audit_data.py
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AUDIT = REPO.parent / "paper-2-EMSE" / "research" / "relevance-audit"
KEY = AUDIT / "relevance-audit-key.json"
FIRST_PASS = AUDIT / "responses" / "coder1-with-reasons-2026-11-03.csv"
FINAL = AUDIT / "responses" / "coder1-final-2026-11-03.csv"
OUT = REPO / "data" / "relevance-audit.csv"

# The coder's reason for the one Q2 = Yes arrived by email, not in the sheet.
EMAILED_Q2_REASONS = {
    "A5": ("The charter primarily explores time-sensitive operational failures at "
           "non-traditional store locations rather than the recurring scheduling-window "
           "configuration change. Although those locations are mentioned in the "
           "specification, they are a testing dependency, not the feature being modified. "
           "This is somewhat borderline, but I would retain Q2 = Yes because of the "
           "charter's main focus."),
}


def read_sheet(path: Path) -> dict[str, dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    def col(row: dict, prefix: str) -> str:
        return next(v for k, v in row.items() if k.startswith(prefix)).strip()

    return {r["Charter"]: {"q1": col(r, "Q1 Made"), "q1_reason": col(r, "Q1 If"),
                           "q2": col(r, "Q2"), "q3": col(r, "Q3")} for r in rows}


def main() -> int:
    key = {k["code"]: k for k in json.loads(KEY.read_text(encoding="utf-8"))["charters"]}
    first, final = read_sheet(FIRST_PASS), read_sheet(FINAL)
    if not (set(key) == set(first) == set(final)):
        sys.exit("charter codes differ between the key and the coder files")

    out = []
    for code in sorted(key, key=lambda c: (c[0], int(c[1:]))):
        k, a, b = key[code], first[code], final[code]
        if (a["q2"], a["q3"]) != (b["q2"], b["q3"]):
            sys.exit(f"{code}: Q2/Q3 changed in the clarification round, which was not asked for")
        for ans in (a["q1"], b["q1"], b["q2"]):
            if ans not in ("Yes", "No"):
                sys.exit(f"{code}: unexpected answer {ans!r}")
        overlaps = [] if b["q3"] in ("", "None") else [x.strip() for x in b["q3"].split(",")]
        out.append({
            "code": code,
            "set": k["set"],
            "spec_id": k["spec_id"],
            "condition": k["condition"],
            "charter_id": k["charter_id"],
            "q1_made_up_first_pass": a["q1"],
            "q1_first_pass_reason": a["q1_reason"],
            "q1_made_up_final": b["q1"],
            "q2_off_topic": b["q2"],
            "q2_reason": EMAILED_Q2_REASONS.get(code, ""),
            "q3_overlaps_with": ";".join(key[o]["charter_id"] for o in overlaps),
            "q3_overlaps_with_code": ";".join(overlaps),
        })

    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    print(f"wrote {OUT.relative_to(REPO)} ({len(out)} charters)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

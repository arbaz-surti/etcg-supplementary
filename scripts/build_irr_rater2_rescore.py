#!/usr/bin/env python3
"""
Build the rater 2 re-score packet for the charters shown the wrong spec context.
================================================================================

The round 2 sheet (build_irr_round2.py, August 2026) looked the ATSR specs up by
the source file's own spec_id. That file skips SPEC-07, while the study renumbers
the 18 ATSR specs SPEC-01..SPEC-18 by position, so every charter for SPEC-07..
SPEC-18 was shown the neighbouring spec's context and SPEC-07's was blank. Rater 1
(who received a different sheet) and the automated judges (which never see the
spec) are unaffected.

This script reproduces the old lookup, compares it with the corrected one, and
writes a packet containing only the charters whose context differed. Each item
gets a fresh neutral ID and a new random order, so the rater cannot line the
re-score up against the earlier one; the key maps every item back to its original
CHR-R2 ID. Charter text and rubric are exactly as in the original sheet -- only
the specification context changes.

Outputs (written to research/ in the paper tree; nothing existing is touched):
    irr-r2-rescore-key.json              analysis key -- never send this
    irr-r2-rescore-sheet.md              the rater-facing document
    irr-r2-rescore-response-template.csv blank grid for returning scores

Usage:
    python scripts/build_irr_rater2_rescore.py
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build_irr_round2 import (  # noqa: E402
    ATSR, OUT, SHEET_HEADER, load_charter_texts, load_spec_context, write_csv, write_sheet,
)

SEED = 20261102

RESCORE_INTRO = """# Independent Reviewer Scoring Sheet — Round 2 Correction
## Exploratory Testing Charter Quality
### ETCG Research — *Automated Software Engineering* (Springer), under revision

---

## Why You Are Receiving This

Thank you again for the ratings you returned earlier. After you returned them we
found an error in how your sheet was assembled: for {n} of the charters, the
**specification context** printed above the charter belonged to a *different*
feature (and in a few cases it was blank). The charters and the rubric were correct;
only the context was wrong. The mistake was ours, not yours.

So that your ratings reflect the right feature, we would be grateful if you would
rate these {n} charters again, this time with the correct context. Please:

* rate each one **afresh**, as if seeing it for the first time — there is no need to
  look at, or try to match, your earlier ratings;
* use exactly the same rubric as before (repeated below for convenience).

The charters carry new identifiers and appear in a new order. The consent you gave
for your earlier ratings covers these too; the terms are unchanged, and you may still
decline or withdraw at any time.

**Time estimate:** roughly one hour.

---

"""


def legacy_spec_titles() -> dict[str, str]:
    """The lookup the August sheet used: the ATSR file's own spec_id, then the new 7."""
    titles: dict[str, str] = {}
    with (ATSR / "research" / "all-specs-18.json").open() as fh:
        for s in json.load(fh):
            titles[s["spec_id"]] = s.get("title", "")
    with (OUT.parent.parent / "etcg-supplementary" / "data" / "specs-new-7.json").open() as fh:
        for s in json.load(fh):
            titles[s["spec_id"]] = s.get("feature", "")
    return titles


def main() -> int:
    ctx = load_spec_context()
    texts = load_charter_texts()
    legacy = legacy_spec_titles()

    with (OUT / "irr-r2-key.json").open() as fh:
        round2 = json.load(fh)

    affected = [e for e in round2 if legacy.get(e["spec_id"], "") != ctx[e["spec_id"]]["title"]]

    rng = random.Random(SEED)
    rng.shuffle(affected)

    items, key = [], []
    for i, entry in enumerate(affected, 1):
        lookup = (entry["spec_id"], entry["condition"], entry["charter_id"])
        if lookup not in texts:
            raise SystemExit(f"no charter text for {lookup}")
        items.append({**entry, "id": f"CHR-C-{i:02d}"})
        key.append({
            "id": f"CHR-C-{i:02d}",
            "original_id": entry["id"],
            "spec_id": entry["spec_id"],
            "condition": entry["condition"],
            "charter_id": entry["charter_id"],
            "context_shown_originally": legacy.get(entry["spec_id"], ""),
            "context_shown_now": ctx[entry["spec_id"]]["title"],
        })

    rubric = SHEET_HEADER[SHEET_HEADER.index("## What You Are Evaluating"):]
    rubric = rubric.replace("irr-r2-response-template.csv", "irr-r2-rescore-response-template.csv")

    (OUT / "irr-r2-rescore-key.json").write_text(json.dumps(key, indent=2), encoding="utf-8")
    write_sheet(OUT / "irr-r2-rescore-sheet.md", items, ctx, texts, header=RESCORE_INTRO + rubric)
    write_csv(OUT / "irr-r2-rescore-response-template.csv", items)

    by_cond: dict[str, int] = {}
    for k in key:
        by_cond[k["condition"]] = by_cond.get(k["condition"], 0) + 1
    print(f"affected charters: {len(key)} of {len(round2)}")
    print("condition: " + ", ".join(f"{c} {n}" for c, n in sorted(by_cond.items())))
    print(f"specs:     {sorted({k['spec_id'] for k in key})}")
    for name in ("irr-r2-rescore-key.json", "irr-r2-rescore-sheet.md",
                 "irr-r2-rescore-response-template.csv"):
        print(f"wrote  {OUT / name}")
    print("\nDo not send irr-r2-rescore-key.json to the rater.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

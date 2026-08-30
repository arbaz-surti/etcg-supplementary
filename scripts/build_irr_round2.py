#!/usr/bin/env python3
"""
Build the round 2 inter-rater reliability packet.
=================================================

Round 1 had one independent rater score 50 charters covering two of the three
conditions (25 ETCG + 25 Baseline, one of each per specification). Reviewers 2
and 4 both asked for more independent evaluation, and Reviewer 2 specifically
noted that the Intermediate condition -- where the schema ablation lives -- was
never validated by a human at all.

This script builds a 75-charter packet that fixes that without discarding any
round 1 work:

    25 ETCG        <- exactly the charters rater 1 already scored
    25 Baseline    <- exactly the charters rater 1 already scored
    25 Intermediate <- new, one per specification

Because the ETCG and Baseline selections are carried over verbatim, and are
rendered here exactly as they were rendered in round 1, rater 1's existing
ratings remain valid and directly comparable. Nothing is re-scored twice.

What the resulting design supports:

  * automated-vs-human agreement across all three conditions (75 charters)
  * human-vs-human agreement on the 50-charter overlap with rater 1, which is
    what separates ambiguity in the rubric from idiosyncrasy in one rater
  * ratings paired by specification, matching the paper's unit of analysis

Outputs (written to research/ in the paper tree):
    irr-r2-key.json              analysis key -- never send this to a rater
    irr-r2-scoring-sheet.md      the rater-facing document
    irr-r2-response-template.csv blank grid for returning scores

Usage:
    python scripts/build_irr_round2.py
"""

from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from etcg_score import extract_baseline_charters  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
PAPER = REPO.parent / "paper-2-EMSE"
ATSR = REPO.parent / "paper-1-ATSR"
OUT = PAPER / "research"

SEED = 2026  # presentation order only; the sample itself is deterministic
CONDITIONS = ("etcg", "intermediate", "baseline")


# ── Specification context ────────────────────────────────────────────────────


def load_spec_context() -> dict[str, dict]:
    """Title, system area and description for all 25 specifications."""
    ctx: dict[str, dict] = {}

    with (ATSR / "research" / "all-specs-18.json").open() as fh:
        for s in json.load(fh):
            ctx[s["spec_id"]] = {
                "title": s.get("title", ""),
                "system_area": s.get("system_area", ""),
                "description": s.get("description", ""),
            }

    with (REPO / "data" / "specs-new-7.json").open() as fh:
        for s in json.load(fh):
            ctx[s["spec_id"]] = {
                "title": s.get("feature", ""),
                "system_area": s.get("domain", ""),
                "description": s.get("description", ""),
            }

    return ctx


# ── Charter text ─────────────────────────────────────────────────────────────


def render_etcg(charter: dict) -> str:
    """ETCG charters are structured; render the fields as round 1 did."""
    return (
        f"**Target Area:** {charter.get('target_area', '')}\n\n"
        f"**Exploratory Approach:** {charter.get('approach', '')}\n\n"
        f"**Risk Focus:** {charter.get('risk_focus', '')}\n\n"
        f"**Priority:** {charter.get('priority', '')} | "
        f"**Est. Duration:** {charter.get('estimated_duration', '')}\n\n"
        f"_Explore {charter.get('target_area', '')} using "
        f"{charter.get('approach', '')} to discover "
        f"{charter.get('risk_focus', '')}._"
    )


def load_charter_texts() -> dict[tuple[str, str, str], str]:
    """Map (spec_id, condition, charter_id) -> the exact text that was scored."""
    texts: dict[tuple[str, str, str], str] = {}

    with (REPO / "data" / "etcg-results.json").open() as fh:
        for rec in json.load(fh)["results"]:
            for charter in rec["etcg_output"]["charters"]:
                texts[(rec["spec_id"], "etcg", charter["charter_id"])] = render_etcg(charter)

    # Free-form conditions: reproduce the scorer's split so the human rates
    # precisely the span the automated evaluator rated.
    for cond, filename, field, prefix in (
        ("intermediate", "etcg-intermediate-results.json", "intermediate_output", "IM"),
        ("baseline", "etcg-baseline-results.json", "baseline_output", "BL"),
    ):
        with (REPO / "data" / filename).open() as fh:
            for rec in json.load(fh)["results"]:
                chunks = extract_baseline_charters(rec[field]["raw_output"])
                if len(chunks) != 5:
                    raise SystemExit(
                        f"{rec['spec_id']} {cond}: split produced {len(chunks)} charters, "
                        "expected 5 -- the packet would not match the scored data"
                    )
                for i, chunk in enumerate(chunks, 1):
                    texts[(rec["spec_id"], cond, f"{prefix}-{i:02d}")] = chunk.strip()

    return texts


def load_auto_scores() -> dict[tuple[str, str, str], dict]:
    with (REPO / "data" / "etcg-scores.json").open() as fh:
        records = json.load(fh)["scores"]
    return {
        (r["spec_id"], r["condition"], r["charter_id"]): {
            "scores": {k: v for k, v in r["scores"].items() if k != "rationale"},
            "percentage": r["percentage"],
        }
        for r in records
    }


# ── Sample construction ──────────────────────────────────────────────────────


def build_sample(round1: list[dict], auto: dict) -> list[dict]:
    """The round 1 fifty, carried over verbatim, plus one Intermediate per spec."""
    sample: list[dict] = []

    for entry in round1:
        sample.append({
            "spec_id": entry["spec_id"],
            "condition": entry["condition"],
            "charter_id": entry["charter_id"],
            "round1_id": entry["neutral_id"],
        })

    specs = sorted({e["spec_id"] for e in round1})
    rng = random.Random(SEED)
    for spec in specs:
        available = sorted(
            cid for (s, c, cid) in auto if s == spec and c == "intermediate"
        )
        if not available:
            raise SystemExit(f"{spec}: no intermediate charters found")
        sample.append({
            "spec_id": spec,
            "condition": "intermediate",
            "charter_id": rng.choice(available),
            "round1_id": None,
        })

    return sample


# ── Emission ─────────────────────────────────────────────────────────────────

SHEET_HEADER = """# Independent Reviewer Scoring Sheet — Round 2
## Exploratory Testing Charter Quality
### ETCG Research — *Automated Software Engineering* (Springer), under revision

---

## Thank You for Taking Part

You are being asked to rate the quality of {n} exploratory testing charters against a
five-dimension rubric. Your ratings will be compared with those of an automated
evaluator, and with those of other independent reviewers, to establish how consistently
the rubric can be applied.

**There is no right or wrong answer.** Your independent judgement is exactly what is
needed. Your ratings will not be shown to any other reviewer, and no reviewer's ratings
will be shown to you.

**Time estimate:** roughly two hours for all {n} charters. Accuracy matters far more
than speed, and the work can be split across sittings.

---

## Consent

Please read this section before you begin.

This scoring task forms part of an academic study that has been submitted for
publication in a peer-reviewed journal. Taking part is entirely voluntary, and you may
stop at any point, without giving a reason and without consequence.

* **What is collected.** Only your numeric ratings and any optional notes you choose to
  write. No personal data, demographic information, or identifying details are collected
  or stored alongside your ratings.
* **How it is used.** Your ratings are aggregated into inter-rater agreement statistics
  reported in the paper. Individual ratings may be published in an anonymised replication
  dataset, identified only by a charter code and a reviewer number.
* **Attribution.** Reviewers are thanked collectively in the acknowledgements. You will
  not be named unless you explicitly ask to be.
* **Withdrawal.** You can ask for your ratings to be removed at any time before
  publication, and they will be deleted.

**To give consent, please reply to the email that accompanied this sheet with the
sentence: “I consent to my ratings being used as described.”** Please send that reply
before returning your scores. If you would rather not take part, simply say so — no
explanation is needed.

---

## What You Are Evaluating

Each charter is a brief mission statement that guides an exploratory testing session. It
tells a QA tester what area to explore, how to explore it, and what risks to look for.

For each charter you will see:

1. **Specification context** — the software feature the charter relates to
2. **The charter** — the text to be rated
3. **A scoring table** — five dimensions, each rated 1–3

**Please note:**

* Rate each charter **on its own terms**, based on what is written — not on what you
  would have written instead.
* **Charters appear in several different formats.** Some are laid out as labelled
  fields, others as free-flowing prose. This variation is part of what is being studied.
  Please rate the **content only**, and try not to let the presentation influence your
  score in either direction.
* Charters are presented in random order and carry neutral identifiers. They come from
  several different generation methods, which are deliberately not disclosed.
* If a charter seems unclear, give the score that reflects your honest assessment rather
  than skipping it.
* The optional notes column is genuinely useful — especially where you hesitated between
  two scores, or where the rubric felt like a poor fit. Please use it when something
  strikes you.

---

## Scoring Rubric — Five Dimensions (each rated 1–3)

Use **1**, **2**, or **3**. Half-scores are not used.

### Dimension 1 — Specificity
*Does the charter target a clearly defined feature component or behaviour, rather than a
broad or vague area?*

| Score | Meaning |
|---|---|
| **3** | Targets a precise feature component with a named approach and clearly scoped risk |
| **2** | Identifies a feature area, but the approach or risk description is somewhat general |
| **1** | Vague — generic feature area, unclear approach, or undefined risk |

### Dimension 2 — Testability
*Could a tester act on this charter directly, without needing to ask clarifying questions?*

| Score | Meaning |
|---|---|
| **3** | Can be executed directly without further clarification; clear start state and goal |
| **2** | Requires minor interpretation before execution |
| **1** | Not actionable without significant rewriting |

### Dimension 3 — Risk Coverage
*Does the charter point at a risk that matters, rather than a generic or trivial one?*

| Score | Meaning |
|---|---|
| **3** | Targets a meaningful, non-obvious risk or defect type with real user impact |
| **2** | Addresses a risk, but it is generic or low-impact |
| **1** | Does not articulate a clear risk focus |

### Dimension 4 — Clarity
*Is the charter well written and unambiguous?*

| Score | Meaning |
|---|---|
| **3** | Clear, grammatically correct, and unambiguous |
| **2** | Mostly clear, with minor phrasing issues |
| **1** | Confusing, ambiguous, or poorly written |

### Dimension 5 — Actionability
*Does the charter suggest a distinct way of approaching the session?*

| Score | Meaning |
|---|---|
| **3** | Provides a distinct exploratory approach that guides the session meaningfully |
| **2** | Suggests a direction, but the approach is generic |
| **1** | Provides no useful direction for the testing session |

---

## How to Return Your Scores

Either fill in the tables below and return this document, or — usually quicker — fill in
the accompanying `irr-r2-response-template.csv` and return that. Either is fine.

---

## Scoring Forms

*Work through the charters in order.*

---
"""


def write_sheet(path: Path, items: list[dict], ctx: dict, texts: dict) -> None:
    parts = [SHEET_HEADER.format(n=len(items))]

    for item in items:
        spec = ctx.get(item["spec_id"], {})
        description = spec.get("description", "")
        if len(description) > 600:
            description = description[:600].rsplit(" ", 1)[0] + "…"
        charter = texts[(item["spec_id"], item["condition"], item["charter_id"])]

        parts.append(f"""
# {item['id']}

**Specification context:** {spec.get('title', '')}

**System area:** {spec.get('system_area', '')}

{description}

---

**Charter:**

{charter}

---

| Dimension | Your Score (1–3) | Notes (optional) |
|---|---|---|
| **Specificity** | | |
| **Testability** | | |
| **Risk Coverage** | | |
| **Clarity** | | |
| **Actionability** | | |

---
""")

    parts.append("""
## Summary Grid

If you prefer to transcribe your scores in one place, use this grid.
SP = Specificity, TE = Testability, RC = Risk Coverage, CL = Clarity, AC = Actionability.

| Charter | SP | TE | RC | CL | AC | Notes |
|---|---|---|---|---|---|---|
""")
    parts.extend(f"| {item['id']} | | | | | | |\n" for item in items)

    parts.append("""
---

**Thank you.** Please return this document (or the CSV) to
arbaz.m.surti@gmail.com, and remember to send the consent sentence separately if you
have not already done so.
""")

    path.write_text("".join(parts), encoding="utf-8")


def write_csv(path: Path, items: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["charter_id", "specificity", "testability", "risk_coverage",
                    "clarity", "actionability", "notes"])
        for item in items:
            w.writerow([item["id"], "", "", "", "", "", ""])


def main() -> int:
    ctx = load_spec_context()
    texts = load_charter_texts()
    auto = load_auto_scores()

    with (OUT / "irr-r1-key.json").open() as fh:
        round1 = json.load(fh)

    sample = build_sample(round1, auto)

    rng = random.Random(SEED)
    rng.shuffle(sample)

    key = []
    for i, item in enumerate(sample, 1):
        lookup = (item["spec_id"], item["condition"], item["charter_id"])
        if lookup not in texts:
            raise SystemExit(f"no charter text for {lookup}")
        item["id"] = f"CHR-R2-{i:03d}"
        key.append({
            "id": item["id"],
            "spec_id": item["spec_id"],
            "condition": item["condition"],
            "charter_id": item["charter_id"],
            "round1_id": item["round1_id"],
            "auto_scores": auto[lookup]["scores"],
            "auto_pct": auto[lookup]["percentage"],
        })

    OUT.mkdir(exist_ok=True)
    (OUT / "irr-r2-key.json").write_text(json.dumps(key, indent=2), encoding="utf-8")
    write_sheet(OUT / "irr-r2-scoring-sheet.md", sample, ctx, texts)
    write_csv(OUT / "irr-r2-response-template.csv", sample)

    counts: dict[str, int] = {}
    for entry in key:
        counts[entry["condition"]] = counts.get(entry["condition"], 0) + 1
    carried = sum(1 for entry in key if entry["round1_id"])

    print(f"charters:  {len(key)}")
    print("condition: " + ", ".join(f"{c} {counts[c]}" for c in CONDITIONS))
    print(f"specs:     {len({e['spec_id'] for e in key})}")
    print(f"carried over from round 1: {carried} (rater 1's ratings stay valid)")
    print(f"new Intermediate charters:  {len(key) - carried}")
    print()
    for name in ("irr-r2-key.json", "irr-r2-scoring-sheet.md", "irr-r2-response-template.csv"):
        print(f"wrote  {OUT / name}")
    print("\nDo not send irr-r2-key.json to a reviewer — it contains the automated scores.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

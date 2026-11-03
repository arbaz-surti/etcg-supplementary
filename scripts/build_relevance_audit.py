#!/usr/bin/env python3
"""
Build the relevance / hallucination / redundancy audit packet.
==============================================================

Reviewer 1 (round 2) asked whether the generated charters contain hallucinated,
irrelevant, or redundant content -- something the rubric cannot see, because the
automated judge scores each charter on its own and never reads the specification.

This script draws a 75-charter sample for a second human coder:

    15 complete charter sets (5 per condition), 15 distinct specifications,
    5 charters per set -> 75 charters

Whole sets are sampled rather than single charters because redundancy is a property
of a set: whether two charters for the same specification duplicate each other.
Each specification appears once, so the coder never sees two conditions' answers to
the same specification side by side.

Unlike build_irr_round2.py, the coder is shown the FULL specification text exactly
as the generator received it, and specifications are looked up by the study's
sequential SPEC-NN numbering (the ATSR source file skips SPEC-07; see
load_spec_texts).

Outputs (written to research/relevance-audit/ in the paper tree):
    relevance-audit-coding-sheet.xlsx        coder-facing workbook -- send this
    relevance-audit-KEY-do-not-send.xlsx     where each charter came from
    relevance-audit-key.json                 the same key, for analysis

Usage:
    python scripts/build_relevance_audit.py
"""

from __future__ import annotations

import json
import random
import re
import string
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

sys.path.insert(0, str(Path(__file__).parent))
from build_irr_round2 import load_charter_texts  # noqa: E402
from etcg_tool import format_atsr_spec, format_new_spec  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
PAPER = REPO.parent / "paper-2-EMSE"
ATSR = REPO.parent / "paper-1-ATSR"
OUT = PAPER / "research" / "relevance-audit"

SEED = 20261102
N_SETS_PER_CONDITION = 5
CONDITIONS = ("etcg", "intermediate", "baseline")
ID_PREFIX = {"etcg": "ET", "intermediate": "IM", "baseline": "BL"}


# ── Specifications ───────────────────────────────────────────────────────────


def load_spec_texts() -> dict[str, dict]:
    """Full specification text keyed by the study's spec_id.

    Mirrors etcg_tool.load_all_specs(): the 18 ATSR specs are renumbered
    SPEC-01..SPEC-18 by position, because the ATSR source IDs skip SPEC-07 and
    end at SPEC-19. Keying by the source file's own spec_id field would shift
    every specification from SPEC-07 onward by one.
    """
    specs: dict[str, dict] = {}
    with (ATSR / "research" / "all-specs-18.json").open() as fh:
        for i, s in enumerate(json.load(fh), 1):
            specs[f"SPEC-{i:02d}"] = {"title": s["title"], "text": format_atsr_spec(s)}
    with (REPO / "data" / "specs-new-7.json").open() as fh:
        for s in json.load(fh):
            specs[s["spec_id"]] = {"title": s["feature"], "text": format_new_spec(s)}
    if len(specs) != 25:
        raise SystemExit(f"expected 25 specifications, found {len(specs)}")
    return specs


def load_judge_totals() -> dict[tuple[str, str, str], dict]:
    totals: dict[tuple[str, str, str], dict] = {}
    for judge, filename in (("gpt4o", "etcg-scores.json"),
                            ("gemini", "etcg-scores-gemini.json"),
                            ("sonnet", "etcg-scores-sonnet.json")):
        with (REPO / "data" / filename).open() as fh:
            for r in json.load(fh)["scores"]:
                key = (r["spec_id"], r["condition"], r["charter_id"])
                totals.setdefault(key, {})[judge] = r["total_score"]
    return totals


# ── Charter text for the coder ───────────────────────────────────────────────


def plain(text: str) -> str:
    """Strip Markdown emphasis and heading marks; keep the words and line breaks."""
    text = re.sub(r"^\s*#{1,6}\s*", "", text, flags=re.M)
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ── Sample ───────────────────────────────────────────────────────────────────


def build_sample(spec_ids: list[str]) -> list[dict]:
    rng = random.Random(SEED)
    chosen = rng.sample(sorted(spec_ids), N_SETS_PER_CONDITION * len(CONDITIONS))
    conditions = [c for c in CONDITIONS for _ in range(N_SETS_PER_CONDITION)]
    rng.shuffle(conditions)
    sets = [{"spec_id": s, "condition": c} for s, c in zip(chosen, conditions)]
    rng.shuffle(sets)
    for label, item in zip(string.ascii_uppercase, sets):
        item["set"] = label
    return sets


# ── Workbook helpers ─────────────────────────────────────────────────────────

FONT = "Arial"
HEAD_FILL = PatternFill("solid", start_color="1F3864")
INPUT_FILL = PatternFill("solid", start_color="FFF2CC")
SET_FILL = PatternFill("solid", start_color="E7E6E6")
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP_TOP = Alignment(wrap_text=True, vertical="top")


def header_row(ws, row: int, labels: list[str]) -> None:
    for col, label in enumerate(labels, 1):
        cell = ws.cell(row=row, column=col, value=label)
        cell.font = Font(name=FONT, bold=True, color="FFFFFF")
        cell.fill = HEAD_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        cell.border = BOX


def body(cell, bold: bool = False, size: int = 10) -> None:
    cell.font = Font(name=FONT, bold=bold, size=size)
    cell.alignment = WRAP_TOP
    cell.border = BOX


def row_height(text: str, width_chars: int) -> float:
    lines = sum(max(1, -(-len(line) // width_chars)) for line in text.split("\n"))
    return min(409, max(30, 13.5 * lines))


INSTRUCTIONS = [
    ("Charter Review — Specification Relevance", "title"),
    ("ETCG research study · Automated Software Engineering (Springer), under revision", "sub"),
    ("", None),
    ("What this is", "h"),
    ("An AI model was asked to write exploratory testing charters — short instructions telling a "
     "tester which part of a feature to explore and what kind of problem to look for. Each set below "
     "contains the five charters the AI wrote for one software specification. You are asked to check "
     "each charter against its specification and answer three yes/no-style questions. You are not "
     "rating quality; only whether each charter sticks to what the specification actually says.", None),
    ("There are no right or wrong answers. Your independent judgement is what matters. Another person "
     "is answering the same questions separately; please do not discuss the charters with anyone "
     "until you have returned the sheet.", None),
    ("Time: about 1.5–2 hours for 15 sets (75 charters). It can be split across sittings.", None),
    ("", None),
    ("How to work through it", "h"),
    ("1. Open the 'Specifications' tab and read the specification for Set A.", None),
    ("2. Go to the 'Coding' tab and answer the questions for charters A1–A5 (the yellow cells).", None),
    ("3. Repeat for Sets B to O. Only the yellow cells need filling in.", None),
    ("4. Charters come in different layouts (some as labelled fields, some as prose). That is "
     "deliberate. Judge the content only.", None),
    ("5. Save the file and email it back.", None),
    ("", None),
    ("The three questions", "h"),
    ("Q1 — Made up? (Yes / No)", "q"),
    ("Answer Yes if the charter states, as if it were part of the system, a feature, screen, field, "
     "business rule, integration, number or behaviour that the specification does not mention and that "
     "cannot reasonably be inferred from it. Answer No for ordinary testing ideas about plausible risks "
     "(e.g. 'what happens if the network drops', 'try a very long name'): imagining things that might "
     "go wrong is what a charter is for. If Yes, write in the next column what was made up.", None),
    ("Q2 — Off-topic? (Yes / No)", "q"),
    ("Answer Yes if the charter's main focus is something outside this specification — a different "
     "feature or system area — so a tester following it would mostly not be testing this change. A "
     "charter that is vague or generic but still about this feature is No.", None),
    ("Q3 — Overlaps with … (charter IDs, or None)", "q"),
    ("Compare the charter with the other four in the same set. If a tester following this charter and "
     "another one would end up running substantially the same session — the same area AND the same "
     "risk — write that charter's ID (e.g. 'C4'). List several separated by commas if needed. Write "
     "'None' if it overlaps with none. Please record an overlap on both charters' rows. Different "
     "techniques on the same area count as overlap only if the sessions would largely duplicate.", None),
    ("Notes (optional)", "q"),
    ("Anything you hesitated over, or where the questions felt like a poor fit. 'Unsure — leaning "
     "No' is a perfectly good note.", None),
    ("", None),
    ("Worked example (not part of the sample)", "h"),
    ("Specification says: 'Managers can void an empty check; crew members cannot.'", None),
    ("Charter X1: 'Explore the void button as a crew member to check it is blocked.' → Q1 No · Q2 No · Q3 None", None),
    ("Charter X2: 'Explore the void approval email sent to the regional director.' → Q1 Yes (no approval "
     "email exists in the spec) · Q2 No · Q3 None", None),
    ("Charter X3: 'Explore loyalty point accrual on refunded orders.' → Q1 No · Q2 Yes (loyalty is a "
     "different feature) · Q3 None", None),
    ("Charter X4: 'Explore voiding an empty check with each role to confirm only managers succeed.' → "
     "Q1 No · Q2 No · Q3 X1", None),
    ("", None),
    ("Consent", "h"),
    ("This review forms part of an academic study submitted for publication in a peer-reviewed journal. "
     "Taking part is voluntary and you may stop at any point without giving a reason.", None),
    ("• What is collected: only your answers and any notes. No personal or demographic data.", None),
    ("• How it is used: answers are combined into agreement statistics reported in the paper, and may be "
     "published in an anonymised dataset identified only by charter code and coder number.", None),
    ("• Attribution: coders are thanked collectively in the acknowledgements and are not named unless "
     "they ask to be.", None),
    ("• Withdrawal: you can ask for your answers to be removed at any time before publication.", None),
    ("To consent, please reply to the email that came with this sheet with the sentence: "
     "“I consent to my answers being used as described.” — before returning the sheet.", None),
]


def write_coder_workbook(path: Path, sets: list[dict], specs: dict, texts: dict) -> None:
    wb = Workbook()

    ws = wb.active
    ws.title = "Instructions"
    ws.column_dimensions["A"].width = 110
    for r, (text, kind) in enumerate(INSTRUCTIONS, 1):
        cell = ws.cell(row=r, column=1, value=text)
        size, bold = {"title": (16, True), "sub": (10, False), "h": (12, True),
                      "q": (10, True)}.get(kind, (10, False))
        cell.font = Font(name=FONT, size=size, bold=bold,
                         color="1F3864" if kind in ("title", "h") else "000000")
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        if text and kind is None:
            ws.row_dimensions[r].height = row_height(text, 120)
    r = len(INSTRUCTIONS) + 2
    ws.cell(row=r, column=1, value="Progress").font = Font(name=FONT, size=12, bold=True,
                                                         color="1F3864")
    prog = ws.cell(row=r + 1, column=1,
                   value='=COUNTA(Coding!E2:E76)&" of 75 charters answered for Q1"')
    prog.font = Font(name=FONT, size=10)

    sp = wb.create_sheet("Specifications")
    header_row(sp, 1, ["Set", "Feature", "Full specification (exactly as the AI received it)"])
    for col, width in zip("ABC", (6, 34, 110)):
        sp.column_dimensions[col].width = width
    for i, item in enumerate(sets, 2):
        spec = specs[item["spec_id"]]
        for col, val in enumerate((item["set"], spec["title"], spec["text"]), 1):
            body(sp.cell(row=i, column=col, value=val), bold=(col < 3))
        sp.row_dimensions[i].height = row_height(spec["text"], 115)
    sp.freeze_panes = "A2"

    cd = wb.create_sheet("Coding")
    header_row(cd, 1, ["Set", "Charter", "Feature", "Charter text",
                       "Q1 Made up?\n(Yes/No)", "Q1 If yes, what was made up?",
                       "Q2 Off-topic?\n(Yes/No)", "Q3 Overlaps with\n(IDs or None)", "Notes"])
    cd.row_dimensions[1].height = 42
    for col, width in zip("ABCDEFGHI", (5, 8, 22, 70, 11, 26, 11, 15, 26)):
        cd.column_dimensions[col].width = width
    yes_no = DataValidation(type="list", formula1='"Yes,No"', allow_blank=True,
                            showErrorMessage=True, errorTitle="Yes or No",
                            error="Please choose Yes or No.")
    cd.add_data_validation(yes_no)

    row = 2
    for item in sets:
        spec = specs[item["spec_id"]]
        prefix = ID_PREFIX[item["condition"]]
        for n in range(1, 6):
            text = plain(texts[(item["spec_id"], item["condition"], f"{prefix}-{n:02d}")])
            values = (item["set"], f"{item['set']}{n}", spec["title"], text)
            for col, val in enumerate(values, 1):
                c = cd.cell(row=row, column=col, value=val)
                body(c, bold=(col <= 2))
                if item["set"] in "ACEGIKMO" and col <= 3:
                    c.fill = SET_FILL
            for col in range(5, 10):
                c = cd.cell(row=row, column=col)
                body(c)
                c.fill = INPUT_FILL
            yes_no.add(f"E{row}")
            yes_no.add(f"G{row}")
            cd.row_dimensions[row].height = row_height(text, 72)
            row += 1
    cd.freeze_panes = "E2"

    wb.active = wb.index(ws)
    wb.save(path)


def write_key_workbook(path: Path, rows: list[dict]) -> None:
    wb = Workbook()
    about = wb.active
    about.title = "About"
    about.column_dimensions["A"].width = 110
    notes = [
        "ANSWER KEY — DO NOT SEND TO THE CODER",
        "Maps each neutral charter code in the coding sheet back to where the charter came from.",
        "Condition: etcg = full framework (role + guidance + JSON schema); intermediate = role + "
        "guidance, free text; baseline = minimal prompt.",
        "Original charter ID matches data/etcg-scores.json in the replication package. Judge totals "
        "are the rubric scores (out of 15) already reported in the paper, for cross-reference only.",
        f"Sample: 15 complete sets (5 per condition), 15 distinct specifications, seed {SEED}. "
        "Regenerate with etcg-supplementary/scripts/build_relevance_audit.py.",
    ]
    for r, text in enumerate(notes, 1):
        c = about.cell(row=r, column=1, value=text)
        c.font = Font(name=FONT, bold=(r == 1), size=12 if r == 1 else 10,
                      color="C00000" if r == 1 else "000000")
        c.alignment = Alignment(wrap_text=True, vertical="top")

    ws = wb.create_sheet("Key")
    cols = ["Set", "Charter", "Spec ID", "Feature", "Condition", "Original charter ID",
            "GPT-4o total /15", "Gemini total /15", "Sonnet total /15"]
    header_row(ws, 1, cols)
    for col, width in zip("ABCDEFGHI", (6, 9, 10, 50, 13, 12, 10, 10, 10)):
        ws.column_dimensions[col].width = width
    for i, r in enumerate(rows, 2):
        vals = (r["set"], r["code"], r["spec_id"], r["feature"], r["condition"], r["charter_id"],
                r["judge_totals"]["gpt4o"], r["judge_totals"]["gemini"],
                r["judge_totals"]["sonnet"])
        for col, v in enumerate(vals, 1):
            body(ws.cell(row=i, column=col, value=v))

    summary = wb.create_sheet("Sets")
    header_row(summary, 1, ["Set", "Spec ID", "Feature", "Condition"])
    for col, width in zip("ABCD", (6, 10, 60, 14)):
        summary.column_dimensions[col].width = width
    seen = []
    for r in rows:
        if r["set"] not in seen:
            seen.append(r["set"])
            vals = (r["set"], r["spec_id"], r["feature"], r["condition"])
            for col, v in enumerate(vals, 1):
                body(summary.cell(row=len(seen) + 1, column=col, value=v))
    wb.save(path)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    specs = load_spec_texts()
    texts = load_charter_texts()
    judges = load_judge_totals()
    sets = build_sample(list(specs))

    rows = []
    for item in sets:
        prefix = ID_PREFIX[item["condition"]]
        for n in range(1, 6):
            cid = f"{prefix}-{n:02d}"
            key = (item["spec_id"], item["condition"], cid)
            if key not in texts or key not in judges:
                raise SystemExit(f"missing charter {key}")
            rows.append({
                "set": item["set"], "code": f"{item['set']}{n}", "spec_id": item["spec_id"],
                "feature": specs[item["spec_id"]]["title"], "condition": item["condition"],
                "charter_id": cid, "judge_totals": judges[key],
            })

    write_coder_workbook(OUT / "relevance-audit-coding-sheet.xlsx", sets, specs, texts)
    write_key_workbook(OUT / "relevance-audit-KEY-do-not-send.xlsx", rows)
    (OUT / "relevance-audit-key.json").write_text(
        json.dumps({"seed": SEED, "charters": rows}, indent=2, ensure_ascii=False) + "\n")

    by_cond = {c: sum(1 for s in sets if s["condition"] == c) for c in CONDITIONS}
    print(f"sets: {len(sets)} {by_cond}; charters: {len(rows)}; "
          f"distinct specs: {len({s['spec_id'] for s in sets})}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

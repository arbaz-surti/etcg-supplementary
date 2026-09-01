"""
Repair the baseline charter split  —  revision defect fix
=========================================================
Four of the 25 baseline responses opened with a line that is not a charter. The
original splitter treated that line as charter 1 and then kept only the first
five chunks, so those cells were scored as [non-charter, charter 1..4] and the
real fifth charter was discarded. The judge scored each non-charter chunk low
(1/1/1/1/1 = 33.3% in the primary file), which depressed the Baseline condition
on exactly the contrast the paper's headline rested on.

Two distinct forms, found two days apart:

  * a PREAMBLE line ("Here are five exploratory testing charters based on the
    provided software specification:") -- SPEC-01, SPEC-06, SPEC-23, repaired
    2026-08-27;
  * a bare DOCUMENT-TITLE HEADING ("### Exploratory Testing Charters for ...")
    -- SPEC-10. The splitter was taught to drop lone headings on 2026-08-29
    while fixing the multi-model corpus, under the mistaken belief that the
    frozen GPT-4o corpus contained no such line. It does: SPEC-10. Because the
    guard postdated the repair run and the repair was never re-run, SPEC-10
    carried the stale split in all three scoring files until 2026-08-31.

That second miss is why this script is now IDEMPOTENT. The plan below is derived
from the ORIGINAL splitter, so it describes the repair relative to the corpus as
first scored; re-running it blindly over an already-repaired file would delete
the real first charter and shift the rest. ``specs_needing_repair`` gates the
plan per file, using an exact witness rather than a heuristic, so the script can
be re-run safely whenever the splitter changes -- which is precisely the thing
that was not possible on 2026-08-29.

This script repairs the scoring files without rescoring anything that does not
have to be rescored:

  * Scores are matched to charters by TEXT, never by position. A charter whose
    text is unchanged keeps its score and simply moves to its correct index, so
    renumbering cannot silently attach a score to a different charter.
  * The preamble rows are removed.
  * The charters that were never scored (the discarded fifth of each affected
    response) are scored fresh, by the same judge that scored the rest of that
    file, so every file stays internally consistent.

Run with --dry-run first: it reports every row it would move, drop, or add,
and makes no API calls.
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

import etcg_score as primary          # noqa: E402  (new, fixed splitter)
import judge_score as jd              # noqa: E402

# The splitter exactly as it behaved when the corpus was scored, kept here so the
# old -> new mapping is derived from the real prior behaviour rather than assumed.
def extract_charters_original(raw_output: str) -> list[str]:
    parts = re.split(
        r'\n(?=(?:\d+\.|#{1,3}\s|\*\*Charter\s?\d|\bCharter\s?\d))',
        raw_output.strip()
    )
    charters = [p.strip() for p in parts if p.strip()]
    if len(charters) > 7:
        charters = [p.strip() for p in raw_output.split("\n\n") if p.strip()]
    return charters[:5]


# Which judge scored which file, so refreshed charters match their file.
FILE_JUDGES = {
    "etcg-scores.json": {
        "model": primary.MODEL, "label": "GPT-4o (primary evaluator)",
    },
    "etcg-scores-sonnet.json": jd.JUDGES["sonnet"],
    "etcg-scores-gemini.json": jd.JUDGES["gemini"],
}


def load_baseline_chunks() -> tuple[dict, dict]:
    """Return {spec_id: [texts]} under the original and the corrected splitter."""
    data = json.loads((BASE_DIR / "data" / "etcg-baseline-results.json").read_text())
    old, new = {}, {}
    for res in data["results"]:
        if "error" in res:
            continue
        raw = res["baseline_output"]["raw_output"]
        old[res["spec_id"]] = extract_charters_original(raw)
        new[res["spec_id"]] = primary.extract_baseline_charters(raw)
    return old, new


def build_plan(old: dict, new: dict) -> dict:
    """Per specification: how each old index maps to a new one, and what is new."""
    plan = {}
    for spec, new_chunks in new.items():
        old_chunks = old[spec]
        remap, dropped = {}, []
        for i, text in enumerate(old_chunks, 1):
            match = next((j for j, t in enumerate(new_chunks, 1) if t == text), None)
            if match is None:
                dropped.append(f"BL-{i:02d}")
            elif match != i:
                remap[f"BL-{i:02d}"] = f"BL-{match:02d}"
        added = [
            (f"BL-{j:02d}", text)
            for j, text in enumerate(new_chunks, 1)
            if text not in old_chunks
        ]
        if remap or dropped or added:
            plan[spec] = {"remap": remap, "dropped": dropped, "added": added}
    return plan


def specs_needing_repair(path: Path, rows: list, plan: dict, new: dict) -> set[str]:
    """
    Which of the planned specifications are still unrepaired IN THIS FILE.

    The plan is derived from the original splitter, so it describes the repair
    relative to the corpus as first scored. Applying it to a file that has
    already been repaired would drop the real first charter and shift the rest,
    because the old BL-01 (the non-charter chunk) no longer exists there. The
    plan is therefore not self-limiting and must be gated per file.

    Two exact witnesses, no heuristics:
      * files that record text_sha256 -- a spec is unrepaired iff one of its
        baseline rows hashes to a chunk that is not a charter under the current
        splitter;
      * the primary file, which predates hashing -- a spec is unrepaired iff its
        baseline cell is still byte-identical to the pre-splitfix backup.
    """
    hashed = any("text_sha256" in r for r in rows)

    if hashed:
        stale = set()
        for spec in plan:
            valid = {hashlib.sha256(t.encode()).hexdigest() for t in new[spec]}
            for r in rows:
                if (r["condition"] == "baseline" and r["spec_id"] == spec
                        and r.get("text_sha256") not in valid):
                    stale.add(spec)
        return stale

    backup = path.with_suffix(path.suffix + ".pre-splitfix-backup")
    if not backup.exists():
        raise SystemExit(
            f"{path.name} records no text hashes and has no .pre-splitfix-backup "
            f"beside it, so whether it has already been repaired cannot be "
            f"established. Refusing to guess -- a wrong guess deletes a charter."
        )

    def cell(blob, spec):
        return sorted((r["charter_id"], r["total_score"])
                      for r in blob["scores"]
                      if r["condition"] == "baseline" and r["spec_id"] == spec)

    cur = json.loads(path.read_text())
    bak = json.loads(backup.read_text())
    return {spec for spec in plan if cell(cur, spec) == cell(bak, spec)}


def repair_file(path: Path, plan: dict, new: dict, domains: dict,
                dry_run: bool) -> dict:
    blob = json.loads(path.read_text())
    rows = blob["scores"]
    judge = FILE_JUDGES[path.name]

    todo_specs = specs_needing_repair(path, rows, plan, new)
    already = sorted(set(plan) - todo_specs)
    if already:
        print(f"    already repaired, skipping: {', '.join(already)}")
    if not todo_specs:
        print("    nothing to do -- file is already consistent with the splitter")
        return {"moved": 0, "removed": 0, "added": 0, "total": len(rows)}
    print(f"    repairing: {', '.join(sorted(todo_specs))}")
    plan = {s: p for s, p in plan.items() if s in todo_specs}

    kept, moved, removed, added_rows = [], 0, 0, []

    for row in rows:
        if row["condition"] != "baseline" or row["spec_id"] not in plan:
            kept.append(row)
            continue
        spec_plan = plan[row["spec_id"]]
        cid = row["charter_id"]
        if cid in spec_plan["dropped"]:
            removed += 1
            continue
        if cid in spec_plan["remap"]:
            row = dict(row)
            row["charter_id"] = spec_plan["remap"][cid]
            moved += 1
        kept.append(row)

    # Charters that never had a score in this file.
    todo = [(spec, cid, text)
            for spec, sp in plan.items() for cid, text in sp["added"]]
    have = {(r["spec_id"], r["charter_id"]) for r in kept if r["condition"] == "baseline"}
    todo = [t for t in todo if (t[0], t[1]) not in have]

    for spec, cid, text in todo:
        if dry_run:
            added_rows.append({"spec_id": spec, "charter_id": cid, "_pending": True})
            continue
        scores, usage, latency, resolved, _, finish = jd.score_charter(judge, text, True)
        total = sum(scores[d] for d in jd.DIMS)
        row = {
            "spec_id": spec,
            "domain": domains[spec],
            "condition": "baseline",
            "charter_id": cid,
            "scores": scores,
            "total_score": total,
            "percentage": round(total / 15 * 100, 1),
        }
        if path.name != "etcg-scores.json":
            row.update({
                "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "usage": usage, "latency_s": latency,
                "scorer_model_resolved": resolved, "finish_reason": finish,
            })
        kept.append(row)
        added_rows.append(row)
        print(f"    scored {spec} {cid} -> {total}/15 ({row['percentage']}%)")

    kept.sort(key=lambda r: (r["spec_id"], r["condition"], r["charter_id"]))

    if not dry_run:
        blob["scores"] = kept
        meta = blob.setdefault("run_metadata", {})
        meta.setdefault("repairs", []).append({
            "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "what": "baseline charter split repaired; preamble chunks removed, "
                    "discarded fifth charters restored and scored",
            "rows_renumbered": moved,
            "rows_removed": removed,
            "rows_added": len(added_rows),
            "scored_by": judge["model"],
        })
        meta["total_charters_scored"] = len(kept)
        if "errors" in meta:
            meta["errors"] = sum(1 for r in kept if "error" in r)
            meta["complete"] = len(kept) == 375 and meta["errors"] == 0
        path.write_text(json.dumps(blob, indent=2))

    return {"moved": moved, "removed": removed, "added": len(added_rows),
            "total": len(kept)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="report the plan and make no API calls or writes")
    args = ap.parse_args()

    old, new = load_baseline_chunks()
    plan = build_plan(old, new)

    print(f"specifications needing repair: {len(plan)}")
    for spec, sp in sorted(plan.items()):
        print(f"  {spec}: drop {sp['dropped']}, "
              f"renumber {sp['remap']}, "
              f"score fresh {[c for c, _ in sp['added']]}")
    print()

    domains = {r["spec_id"]: r["domain"] for r in
               json.loads((BASE_DIR / "data" / "etcg-baseline-results.json").read_text())["results"]
               if "error" not in r}

    for name in FILE_JUDGES:
        path = BASE_DIR / "data" / name
        if not path.exists():
            print(f"{name}: not present, skipped")
            continue
        print(f"{name} ({FILE_JUDGES[name]['model']}):")
        r = repair_file(path, plan, new, domains, args.dry_run)
        print(f"    renumbered {r['moved']}, removed {r['removed']}, "
              f"added {r['added']}, total now {r['total']}")
    print()
    print("DRY RUN — nothing written" if args.dry_run else "repair complete")


if __name__ == "__main__":
    main()

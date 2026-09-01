"""
Verify charter-split integrity across every scoring file
========================================================
The baseline splitter has twice mis-counted a non-charter chunk as a charter:

  * a preamble line ("Here are five exploratory testing charters based on the
    provided software specification:"), repaired 2026-08-27; and
  * a bare document-title heading ("### Exploratory Testing Charters for ..."),
    guarded in ``etcg_score.extract_baseline_charters`` on 2026-08-29 -- but the
    repair was never re-run afterwards, so SPEC-10 carried the stale split into
    the frozen corpus and into both cross-model judge files.

Each time, the non-charter chunk was fed to the judge (which duly scored it low)
and the real fifth charter was pushed out of the ``[:5]`` window and discarded.

This script is the standing guard against a third occurrence. It re-derives the
charter texts from the raw generation output and asserts, for every scoring file:

  1. every baseline row corresponds to a real charter under the current splitter;
  2. every specification has the full complement of charters in every condition;
  3. no charter text is scored twice within a condition.

Exit status is 0 when every check passes and 1 otherwise, so it can be wired into
the analysis pipeline or CI. It makes no API calls and writes nothing.
"""

import hashlib
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

import etcg_score as primary  # noqa: E402

SCORE_FILES = [
    "etcg-scores.json",
    "etcg-scores-sonnet.json",
    "etcg-scores-gemini.json",
]
CHARTERS_PER_SPEC = 5
CONDITIONS = ("etcg", "intermediate", "baseline")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def baseline_targets() -> dict[str, list[str]]:
    """{spec_id: [charter texts]} as the CURRENT splitter produces them."""
    data = json.loads((BASE_DIR / "data" / "etcg-baseline-results.json").read_text())
    return {
        res["spec_id"]: primary.extract_baseline_charters(
            res["baseline_output"]["raw_output"]
        )
        for res in data["results"]
        if "error" not in res
    }


def unrepaired_by_backup(path: Path, targets: dict[str, list[str]]) -> list[str]:
    """
    Specs still carrying the pre-repair split in a file that records no text
    hashes. A scored non-charter and a discarded real charter cancel out in the
    row count, so cardinality cannot see the defect and charter_ids stay in
    range -- the only exact witness available is the pre-repair backup.

    A spec is unrepaired iff the old splitter disagreed with the current one for
    that spec AND the file's rows are still byte-identical to the backup's.
    """
    from repair_baseline_split import extract_charters_original

    backup = path.with_suffix(path.suffix + ".pre-splitfix-backup")
    if not backup.exists():
        return []

    raw_data = json.loads(
        (BASE_DIR / "data" / "etcg-baseline-results.json").read_text()
    )
    raw = {r["spec_id"]: r["baseline_output"]["raw_output"]
           for r in raw_data["results"] if "error" not in r}

    def cell(blob, spec):
        return sorted(
            (r["charter_id"], r["total_score"])
            for r in blob["scores"]
            if r["condition"] == "baseline" and r["spec_id"] == spec
        )

    cur = json.loads(path.read_text())
    bak = json.loads(backup.read_text())
    stale = []
    for spec in sorted(targets):
        if extract_charters_original(raw[spec]) == targets[spec]:
            continue  # splitter never disagreed here; nothing to repair
        if cell(cur, spec) == cell(bak, spec):
            stale.append(spec)
    return stale


def check_file(path: Path, targets: dict[str, list[str]]) -> list[str]:
    """Return a list of human-readable failures for one scoring file."""
    failures: list[str] = []
    rows = json.loads(path.read_text())["scores"]

    if not any("text_sha256" in r for r in rows):
        for spec in unrepaired_by_backup(path, targets):
            failures.append(
                f"{spec} baseline: still byte-identical to the pre-repair backup "
                f"while the splitter has changed -- the mis-split chunk is still "
                f"scored and the real fifth charter is still missing"
            )

    # 1. Every baseline row must map to a real charter.
    #    Files that record text_sha256 are checked by hash, which is exact.
    #    The primary file predates hashing, so it is checked by cardinality and
    #    by charter_id range, which is what the defect actually perturbs.
    for spec, texts in sorted(targets.items()):
        valid_hashes = {_sha(t) for t in texts}
        valid_ids = {f"BL-{i:02d}" for i in range(1, len(texts) + 1)}
        spec_rows = [r for r in rows
                     if r["condition"] == "baseline" and r["spec_id"] == spec]

        for row in spec_rows:
            if "text_sha256" in row:
                if row["text_sha256"] not in valid_hashes:
                    failures.append(
                        f"{spec} {row['charter_id']}: scored text is not a charter "
                        f"under the current splitter (orphan hash) "
                        f"-- score {row['percentage']}%"
                    )
            elif row["charter_id"] not in valid_ids:
                failures.append(
                    f"{spec} {row['charter_id']}: charter_id outside the valid "
                    f"range BL-01..BL-{len(texts):02d}"
                )

        if len(spec_rows) != len(texts):
            failures.append(
                f"{spec} baseline: {len(spec_rows)} rows but the splitter yields "
                f"{len(texts)} charters"
            )

        # A scored non-charter and a discarded real charter cancel out in the row
        # count, so cardinality alone cannot catch the defect in a hash-less file.
        # Distinct hashes are the real test where they exist.
        hashed = [r for r in spec_rows if "text_sha256" in r]
        if hashed:
            covered = {r["text_sha256"] for r in hashed}
            missing = valid_hashes - covered
            if missing:
                failures.append(
                    f"{spec} baseline: {len(missing)} real charter(s) have no score "
                    f"-- discarded by the splitter"
                )

    # 2. Full complement in every condition.
    for spec in sorted(targets):
        for cond in CONDITIONS:
            n = sum(1 for r in rows
                    if r["spec_id"] == spec and r["condition"] == cond)
            if n != CHARTERS_PER_SPEC:
                failures.append(f"{spec} {cond}: {n} charters, expected "
                                f"{CHARTERS_PER_SPEC}")

    # 3. No duplicate charter_id within a (spec, condition) cell.
    seen: set[tuple[str, str, str]] = set()
    for r in rows:
        key = (r["spec_id"], r["condition"], r["charter_id"])
        if key in seen:
            failures.append(f"{key[0]} {key[1]} {key[2]}: duplicate row")
        seen.add(key)

    return failures


def main() -> int:
    targets = baseline_targets()
    print(f"baseline specifications: {len(targets)}")
    print(f"charters per specification under the current splitter: "
          f"{sorted({len(v) for v in targets.values()})}")
    print()

    total = 0
    for name in SCORE_FILES:
        path = BASE_DIR / "data" / name
        if not path.exists():
            print(f"{name}: not present, skipped")
            continue
        failures = check_file(path, targets)
        total += len(failures)
        if failures:
            print(f"{name}: {len(failures)} FAILURE(S)")
            for f in failures:
                print(f"    {f}")
        else:
            print(f"{name}: OK")
    print()

    if total:
        print(f"INTEGRITY CHECK FAILED -- {total} problem(s)")
        return 1
    print("integrity check passed -- every scored row is a real charter, "
          "every real charter is scored")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Multi-model charter scoring  —  revision task 2.3
=================================================
Scores one generator model's 375 charters (produced by multimodel_generate.py) with
the SAME fixed rubric judge used for the primary corpus: GPT-4o, temperature 0,
json-mode, the verbatim etcg_score.SCORER_SYSTEM_PROMPT. Holding the judge fixed is
the point — across the resulting score sets the only variable is which model wrote
the charters, so any change in the ablation contrasts is attributable to the
generator, not the evaluator.

Charter texts are rebuilt with the primary scorer's own helpers
(`format_charter_for_scoring`, `extract_baseline_charters`), and the blind shuffle
uses the same seed (42), so the scoring procedure is identical to the primary run
in every respect except its input files.

Input : data/multimodel/<slug>/{etcg,baseline,intermediate}-results.json
Output: data/multimodel/<slug>/scores.json     (same shape as data/etcg-scores.json)

Usage
-----
    python scripts/multimodel_score.py --model sonnet --dry-run
    python scripts/multimodel_score.py --model sonnet --limit 10
    python scripts/multimodel_score.py --model sonnet
    python scripts/multimodel_score.py --model sonnet --resume
"""

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
load_dotenv(BASE_DIR / ".env")

import etcg_score as primary  # noqa: E402

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

JUDGE_MODEL = "openai/gpt-4o"   # identical to the primary scoring run
TEMPERATURE = 0.0
MAX_TOKENS = 300
DIMS = ["specificity", "testability", "risk_coverage", "clarity", "actionability"]
RANDOM_SEED = 42
MAX_RETRIES = 4
REQUEST_TIMEOUT = 90
CHECKPOINT_EVERY = 40

CONDITIONS = ["etcg", "intermediate", "baseline"]
PRICE_IN, PRICE_OUT = 2.50, 10.00   # openai/gpt-4o, USD per Mtok, for --dry-run only


def build_corpus(slug: str) -> list[dict]:
    """Flatten one generator's three result files into scorable charter items,
    using the primary scorer's extraction/formatting verbatim."""
    d = BASE_DIR / "data" / "multimodel" / slug
    with open(d / "etcg-results.json") as f:
        etcg_data = json.load(f)
    with open(d / "baseline-results.json") as f:
        baseline_data = json.load(f)
    with open(d / "intermediate-results.json") as f:
        intermediate_data = json.load(f)

    items = []
    for result in etcg_data["results"]:
        if "error" in result:
            continue
        for charter in result["etcg_output"]["charters"]:
            items.append({
                "spec_id": result["spec_id"],
                "domain": result["domain"],
                "condition": "etcg",
                "charter_id": charter.get("charter_id", ""),
                "charter_text": primary.format_charter_for_scoring(charter, "etcg"),
            })

    for data, cond, out_key, prefix in (
        (baseline_data, "baseline", "baseline_output", "BL"),
        (intermediate_data, "intermediate", "intermediate_output", "IM"),
    ):
        for result in data["results"]:
            if "error" in result:
                continue
            raw = result[out_key]["raw_output"]
            for i, text in enumerate(primary.extract_baseline_charters(raw), 1):
                items.append({
                    "spec_id": result["spec_id"],
                    "domain": result["domain"],
                    "condition": cond,
                    "charter_id": f"{prefix}-{i:02d}",
                    "charter_text": text,
                })
    return items


def parse_scores(content: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.MULTILINE).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not m:
            raise ValueError(f"no JSON object in reply: {content[:160]!r}")
        obj = json.loads(m.group(0))
    out = {}
    for d in DIMS:
        v = obj.get(d)
        if isinstance(v, str) and v.strip().isdigit():
            v = int(v.strip())
        if v not in (1, 2, 3):
            raise ValueError(f"dimension {d!r} out of range: {v!r}")
        out[d] = v
    out["rationale"] = str(obj.get("rationale", ""))[:500]
    return out


def score_charter(charter_text: str) -> tuple[dict, dict, float]:
    payload = {
        "model": JUDGE_MODEL,
        "messages": [
            {"role": "system", "content": primary.SCORER_SYSTEM_PROMPT},
            {"role": "user",
             "content": f"Score this exploratory testing charter:\n\n{charter_text}"},
        ],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "response_format": {"type": "json_object"},
        "usage": {"include": True},
    }
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/arbaz-surti/etcg-supplementary",
        "X-Title": "ETCG Multi-Model Scoring",
    }
    last = None
    for attempt in range(1, MAX_RETRIES + 1):
        started = time.monotonic()
        try:
            resp = requests.post(OPENROUTER_API_URL, headers=headers, json=payload,
                                 timeout=REQUEST_TIMEOUT)
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"{resp.status_code}: {resp.text[:160]}")
            resp.raise_for_status()
            latency = time.monotonic() - started
            body = resp.json()
            content = body["choices"][0]["message"]["content"]
            usage = body.get("usage") or {}
            return (parse_scores(content),
                    {"prompt_tokens": usage.get("prompt_tokens"),
                     "completion_tokens": usage.get("completion_tokens"),
                     "cost_usd": usage.get("cost")},
                    round(latency, 3))
        except (requests.RequestException, ValueError, KeyError) as exc:
            last = exc
            if attempt < MAX_RETRIES:
                time.sleep(min(2 ** attempt, 16))
    raise RuntimeError(f"failed after {MAX_RETRIES} attempts: {last}")


def mean(v):
    return round(sum(v) / len(v), 2) if v else 0


def stdev(v):
    if len(v) < 2:
        return 0
    m = sum(v) / len(v)
    return round((sum((x - m) ** 2 for x in v) / (len(v) - 1)) ** 0.5, 2)


def summarise(scored: list[dict]) -> dict:
    summary = {}
    for cond in CONDITIONS:
        rows = [s for s in scored if s["condition"] == cond and "error" not in s]
        pcts = [s["percentage"] for s in rows]
        summary[cond] = {
            "n": len(rows),
            "overall_mean_pct": mean(pcts),
            "overall_stdev_pct": stdev(pcts),
            "dimensions": {
                d: {"mean": mean([s["scores"][d] for s in rows]),
                    "stdev": stdev([s["scores"][d] for s in rows]),
                    "n": len(rows)}
                for d in DIMS
            },
        }
    return summary


def write_output(path: Path, slug: str, cfg_label: str, scored: list[dict],
                 complete: bool) -> None:
    costs = [s["usage"]["cost_usd"] for s in scored
             if "error" not in s and s.get("usage", {}).get("cost_usd") is not None]
    path.write_text(json.dumps({
        "run_metadata": {
            "purpose": "multi-model generation scoring (revision task 2.3)",
            "generator_slug": slug,
            "generator_label": cfg_label,
            "scorer_model": JUDGE_MODEL,
            "scorer_temperature": TEMPERATURE,
            "rubric": "identical to primary run (etcg_score.SCORER_SYSTEM_PROMPT)",
            "shuffle_seed": RANDOM_SEED,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "total_charters_scored": len(scored),
            "errors": sum(1 for s in scored if "error" in s),
            "total_cost_usd": round(sum(costs), 4) if costs else None,
            "complete": complete,
        },
        "summary": summarise(scored),
        "scores": scored,
    }, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, help="generator slug under data/multimodel/")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    d = BASE_DIR / "data" / "multimodel" / args.model
    if not d.exists():
        raise SystemExit(f"no generation output at {d} — run multimodel_generate.py first")

    label = json.loads((d / "etcg-results.json").read_text())["run_metadata"].get("label", args.model)
    corpus = build_corpus(args.model)
    random.seed(RANDOM_SEED)
    corpus.sort(key=lambda it: (it["spec_id"], it["condition"], it["charter_id"]))
    random.shuffle(corpus)

    out_path = d / "scores.json"
    scored: list[dict] = []
    done: set = set()
    if args.resume and out_path.exists():
        prev = json.loads(out_path.read_text())["scores"]
        scored = [s for s in prev if "error" not in s]
        done = {(s["spec_id"], s["condition"], s["charter_id"]) for s in scored}
        print(f"resume     {len(done)} charters already scored")

    todo = [it for it in corpus
            if (it["spec_id"], it["condition"], it["charter_id"]) not in done]
    if args.limit:
        todo = todo[:args.limit]

    print(f"Multi-model scoring — generator {label}, judge {JUDGE_MODEL} (temp 0)")
    print(f"  corpus {len(corpus)} charters, {len(todo)} to score")
    if args.dry_run:
        approx_in = sum(len(primary.SCORER_SYSTEM_PROMPT) + len(it["charter_text"])
                        for it in todo) / 4
        est = approx_in / 1e6 * PRICE_IN + len(todo) * 90 / 1e6 * PRICE_OUT
        print(f"  ESTIMATED COST : ${est:.2f}   (~{len(todo) * 1.5 / 60:.0f} min)")
        print("  dry run — no API calls")
        return 0
    if not OPENROUTER_API_KEY:
        raise SystemExit("OPENROUTER_API_KEY not set")

    print("=" * 68)
    errors = 0
    for i, it in enumerate(todo, 1):
        tag = f"{it['condition'][:4].upper():<4} {it['spec_id']} {it['charter_id']}"
        print(f"[{i:03d}/{len(todo)}] {tag}", end="  ", flush=True)
        row = {"spec_id": it["spec_id"], "domain": it["domain"],
               "condition": it["condition"], "charter_id": it["charter_id"]}
        try:
            scores, usage, latency = score_charter(it["charter_text"])
            total = sum(scores[d] for d in DIMS)
            row.update({"scores": scores, "total_score": total,
                        "percentage": round(total / 15 * 100, 1),
                        "usage": usage, "latency_s": latency})
            print(f"-> {total:2d}/15 ({row['percentage']:5.1f}%)  {latency:5.2f}s")
        except Exception as exc:  # noqa: BLE001
            errors += 1
            row["error"] = str(exc)
            print(f"-> ERROR: {exc}")
        scored.append(row)
        if i % CHECKPOINT_EVERY == 0:
            write_output(out_path, args.model, label, scored, complete=False)
            print(f"           …checkpoint ({len(scored)})")
        if i < len(todo):
            time.sleep(0.4)

    complete = (len(todo) + len(done)) >= len(corpus) and errors == 0
    write_output(out_path, args.model, label, scored, complete)
    s = summarise(scored)
    print("=" * 68)
    print(f"wrote      {out_path}   ({errors} errors, complete={complete})")
    for cond in CONDITIONS:
        print(f"  {cond:<13} {s[cond]['overall_mean_pct']:6.2f}%  "
              f"(SD {s[cond]['overall_stdev_pct']:.2f}, n={s[cond]['n']})")
    print("\n  Next: python scripts/analysis.py   (multimodel_generalization stats)")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

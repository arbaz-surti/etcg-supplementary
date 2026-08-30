"""
Generation-side instrumentation  —  revision task 2.4
=====================================================
Reviewer 2 comment 6 asks for the operational envelope of the framework: generation
latency per specification, input/output token consumption, API cost, retry rates, and
JSON-validation overhead. The primary generation run (March 2026) discarded the API
`usage` block, so none of this was recorded.

What this script does, and does NOT do
--------------------------------------
It is a dedicated *operational-characterisation* run. It replays the three condition
prompts over the same 25 specifications, under byte-identical configuration (model,
prompt text, temperature 0.2, 1500-token ceiling), with OpenRouter cost accounting
switched on, and records per call: measured token usage and USD cost, wall-clock
latency, transport-retry count, `finish_reason`, and the post-processing outcome
(JSON parse + schema completeness for ETCG; free-text charter-extraction yield for the
two unstructured conditions).

It NEVER writes to `data/etcg-results.json`, `data/etcg-baseline-results.json`,
`data/etcg-intermediate-results.json`, or `data/etcg-scores.json`. The evaluation
corpus is frozen: generation ran at temperature 0.2, so regenerating it would produce
a different 375 charters and strand both human IRR rounds and every number in the
paper. The charters produced here are retained only for an optional determinism
cross-check (`raw_content` per call) and are never scored.

A truncated reply (`finish_reason == "length"`) is recorded as-is, not retried away:
the frozen run used the same 1500-token ceiling, so truncation is a genuine
operational characteristic of the configuration, not a fault.

Output: data/generation-instrumentation.json

Usage
-----
    python scripts/instrument_generation.py --dry-run          # cost estimate, no API calls
    python scripts/instrument_generation.py --limit 3          # smoke test (3 calls)
    python scripts/instrument_generation.py                    # full 75-call run
    python scripts/instrument_generation.py --resume           # continue an interrupted run
"""

import argparse
import hashlib
import json
import os
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

# Reuse the exact prompts and spec-loading logic from the primary generation tools,
# and the exact free-text splitter from the primary scorer. Importing rather than
# re-implementing is deliberate: the whole point of this run is that nothing about
# the generation changes except that usage is now recorded.
from etcg_tool import SYSTEM_PROMPT as ETCG_PROMPT          # noqa: E402
from etcg_baseline_tool import BASELINE_PROMPT_TEMPLATE     # noqa: E402
from etcg_intermediate_tool import INTERMEDIATE_PROMPT, load_all_specs  # noqa: E402
import etcg_score as scorer                                 # noqa: E402

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

MODEL = "openai/gpt-4o"
TEMPERATURE = 0.2
MAX_TOKENS = 1500
REQUEST_TIMEOUT = 90
MAX_RETRIES = 4
CHECKPOINT_EVERY = 15

OUT_PATH = BASE_DIR / "data" / "generation-instrumentation.json"

FROZEN = {
    "etcg-results.json", "etcg-baseline-results.json",
    "etcg-intermediate-results.json", "etcg-scores.json",
}

ETCG_SCHEMA_FIELDS = ("charter_id", "target_area", "approach",
                      "risk_focus", "priority", "estimated_duration")

# condition -> (prompt template, wants OpenAI json_object mode)
CONDITIONS = {
    "baseline": (BASELINE_PROMPT_TEMPLATE, False),
    "intermediate": (INTERMEDIATE_PROMPT, False),
    "etcg": (ETCG_PROMPT, True),
}

# OpenRouter list price for openai/gpt-4o, USD per million tokens, captured
# 2026-08-29. Used only for the --dry-run estimate; the run itself records the
# `cost` OpenRouter returns per call, so the reported figure is measured.
PRICE_IN = 2.50
PRICE_OUT = 10.00


# ── Charter post-processing (mirrors the primary pipeline) ─────────────────────

def parse_etcg(content: str) -> dict:
    """Replicate etcg_tool's charter extraction and add schema-completeness."""
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return {"json_valid": False, "charter_count": 0, "schema_complete": False}

    if isinstance(parsed, list):
        charters = parsed
    elif isinstance(parsed, dict) and "charters" in parsed:
        charters = parsed["charters"]
    elif isinstance(parsed, dict):
        charters = next((v for v in parsed.values() if isinstance(v, list)), [])
    else:
        charters = []

    complete = bool(charters) and all(
        isinstance(c, dict) and all(c.get(f) not in (None, "") for f in ETCG_SCHEMA_FIELDS)
        for c in charters
    )
    return {
        "json_valid": True,
        "charter_count": len(charters),
        "schema_complete": complete,
    }


def parse_freetext(content: str) -> dict:
    """Free-text conditions: yield of the primary scorer's splitter."""
    charters = scorer.extract_baseline_charters(content or "")
    return {
        "json_valid": None,
        "charter_count": len(charters),
        "schema_complete": None,
        "underextracted": len(charters) < 5,
    }


# ── One instrumented generation call ──────────────────────────────────────────

def generate(condition: str, spec_text: str) -> dict:
    template, json_mode = CONDITIONS[condition]
    prompt = template.replace("[SPEC_CONTENT]", spec_text)

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/arbaz-surti/etcg-supplementary",
        "X-Title": "ETCG Generation Instrumentation",
    }
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "usage": {"include": True},
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    retries = 0
    last_error = None
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
            choice = body["choices"][0]
            content = choice.get("message", {}).get("content") or ""
            finish = choice.get("finish_reason")
            usage = body.get("usage") or {}

            post = parse_etcg(content) if condition == "etcg" else parse_freetext(content)
            return {
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "cost_usd": usage.get("cost"),
                "latency_s": round(latency, 3),
                "retries": retries,
                "finish_reason": finish,
                "model_resolved": body.get("model", MODEL),
                "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "raw_content": content,
                **post,
            }
        except (requests.RequestException, KeyError, ValueError) as exc:
            last_error = exc
            retries += 1
            if attempt < MAX_RETRIES:
                time.sleep(min(2 ** attempt, 16))

    raise RuntimeError(f"failed after {MAX_RETRIES} attempts: {last_error}")


# ── Summaries ────────────────────────────────────────────────────────────────

def _num(xs):
    return [x for x in xs if isinstance(x, (int, float))]


def summarise(calls: list[dict]) -> dict:
    out = {}
    for cond in list(CONDITIONS) + ["__all__"]:
        rows = [c for c in calls if "error" not in c and
                (cond == "__all__" or c["condition"] == cond)]
        if not rows:
            continue
        lat = _num(c["latency_s"] for c in rows)
        cin = _num(c["prompt_tokens"] for c in rows)
        cout = _num(c["completion_tokens"] for c in rows)
        cost = _num(c["cost_usd"] for c in rows)
        n = len(rows)
        lat_sorted = sorted(lat)
        out[cond] = {
            "n_calls": n,
            "mean_latency_s": round(sum(lat) / len(lat), 3) if lat else None,
            "median_latency_s": round(lat_sorted[len(lat_sorted) // 2], 3) if lat else None,
            "max_latency_s": round(max(lat), 3) if lat else None,
            "total_prompt_tokens": sum(cin) if cin else None,
            "total_completion_tokens": sum(cout) if cout else None,
            "mean_prompt_tokens": round(sum(cin) / len(cin), 1) if cin else None,
            "mean_completion_tokens": round(sum(cout) / len(cout), 1) if cout else None,
            "total_cost_usd": round(sum(cost), 6) if cost else None,
            "cost_per_spec_usd": round(sum(cost) / n, 6) if cost else None,
            "cost_per_charter_usd": round(sum(cost) / (n * 5), 6) if cost else None,
            "calls_with_retry": sum(1 for c in rows if c.get("retries")),
            "total_retries": sum(c.get("retries", 0) for c in rows),
            "truncated_calls": sum(1 for c in rows if c.get("finish_reason") == "length"),
            "json_invalid_calls": sum(1 for c in rows
                                      if c["condition"] == "etcg" and c.get("json_valid") is False),
            "schema_incomplete_calls": sum(1 for c in rows
                                           if c["condition"] == "etcg"
                                           and c.get("schema_complete") is False),
            "underextracted_calls": sum(1 for c in rows if c.get("underextracted")),
            "calls_not_five_charters": sum(1 for c in rows if c.get("charter_count") != 5),
        }
    return out


def write_output(calls: list[dict], complete: bool) -> None:
    resolved = sorted({c["model_resolved"] for c in calls if "error" not in c})
    payload = {
        "run_metadata": {
            "purpose": "generation-side operational instrumentation (revision task 2.4)",
            "note": ("dedicated operational-characterisation run; the frozen evaluation "
                     "corpus was NOT regenerated and these charters are never scored"),
            "model": MODEL,
            "model_resolved": resolved,
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
            "prompts": "identical to etcg_tool / etcg_baseline_tool / etcg_intermediate_tool",
            "specs": "25 (18 ATSR + 7 new), loaded via etcg_intermediate_tool.load_all_specs",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "n_calls": sum(1 for c in calls if "error" not in c),
            "n_errors": sum(1 for c in calls if "error" in c),
            "complete": complete,
        },
        "summary": summarise(calls),
        "calls": calls,
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Estimate ─────────────────────────────────────────────────────────────────

def estimate(jobs: list[tuple]) -> None:
    specs = {s["spec_id"]: s["spec_text"] for s in load_all_specs()}
    in_tok = out_tok = 0.0
    for cond, spec_id in jobs:
        template, _ = CONDITIONS[cond]
        prompt = template.replace("[SPEC_CONTENT]", specs[spec_id])
        in_tok += len(prompt) / 4
        out_tok += 700  # ~observed free-text charter set; ETCG a little less
    cost = in_tok / 1e6 * PRICE_IN + out_tok / 1e6 * PRICE_OUT
    print(f"  calls            : {len(jobs)}")
    print(f"  est. input       : {in_tok/1000:,.1f}k tok  @ ${PRICE_IN}/M  = ${in_tok/1e6*PRICE_IN:.2f}")
    print(f"  est. output      : {out_tok/1000:,.1f}k tok  @ ${PRICE_OUT}/M = ${out_tok/1e6*PRICE_OUT:.2f}")
    print(f"  ESTIMATED TOTAL  : ${cost:.2f}")
    print(f"  est. wall clock  : ~{len(jobs) * 4.0 / 60:.0f} min at ~4 s/call")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="estimate cost and exit")
    ap.add_argument("--limit", type=int, help="run only the first N calls (smoke test)")
    ap.add_argument("--resume", action="store_true",
                    help="skip (condition, spec) pairs already in the output file")
    args = ap.parse_args()

    if OUT_PATH.name in FROZEN:
        raise SystemExit(f"refusing to write a frozen filename: {OUT_PATH.name}")

    specs = load_all_specs()
    jobs = [(cond, s["spec_id"]) for cond in CONDITIONS for s in specs]  # 3 x 25, grouped by condition

    done: set = set()
    calls: list[dict] = []
    if args.resume and OUT_PATH.exists():
        prev = json.loads(OUT_PATH.read_text(encoding="utf-8"))
        calls = [c for c in prev.get("calls", []) if "error" not in c]
        done = {(c["condition"], c["spec_id"]) for c in calls}
        print(f"resume     {len(done)} calls already recorded in {OUT_PATH.name}")

    todo = [j for j in jobs if j not in done]
    if args.limit:
        todo = todo[:args.limit]

    print("Generation instrumentation")
    print(f"  model  : {MODEL} (temp {TEMPERATURE}, max_tokens {MAX_TOKENS})")
    estimate(todo)
    if args.dry_run:
        print("  dry run — no API calls made, nothing written")
        return 0

    if not OPENROUTER_API_KEY:
        raise SystemExit("OPENROUTER_API_KEY not set (expected in etcg-supplementary/.env)")

    spec_text = {s["spec_id"]: s["spec_text"] for s in specs}
    print("=" * 68)
    errors = 0
    for i, (cond, spec_id) in enumerate(todo, 1):
        print(f"[{i:02d}/{len(todo)}] {cond:<12} {spec_id}", end="  ", flush=True)
        row = {"condition": cond, "spec_id": spec_id}
        try:
            row.update(generate(cond, spec_text[spec_id]))
            tag = ""
            if cond == "etcg":
                tag = "json ok" if row["json_valid"] else "JSON INVALID"
                if row["json_valid"] and not row["schema_complete"]:
                    tag += ", schema gaps"
            elif row.get("underextracted"):
                tag = f"only {row['charter_count']}/5 extracted"
            cost = row.get("cost_usd")
            cost_s = f"${cost:.4f}" if isinstance(cost, (int, float)) else "n/a"
            print(f"-> {row['latency_s']:5.2f}s  in {row.get('prompt_tokens')}  "
                  f"out {row.get('completion_tokens')}  {cost_s}  "
                  f"{row.get('finish_reason')}  {tag}")
        except Exception as exc:  # noqa: BLE001
            errors += 1
            row["error"] = str(exc)
            print(f"-> ERROR: {exc}")
        calls.append(row)

        if i % CHECKPOINT_EVERY == 0:
            write_output(calls, complete=False)
            print(f"           …checkpoint ({len(calls)} rows)")
        if i < len(todo):
            time.sleep(0.5)

    complete = (len(todo) + len(done)) >= len(jobs) and errors == 0
    write_output(calls, complete)

    print("=" * 68)
    print(f"wrote      {OUT_PATH}")
    print(f"errors     {errors}")
    s = summarise(calls)
    for cond in list(CONDITIONS) + ["__all__"]:
        if cond in s:
            c = s[cond]
            print(f"  {cond:<12} n={c['n_calls']:2d}  "
                  f"lat {c['mean_latency_s']}s  "
                  f"in/out {c['mean_prompt_tokens']}/{c['mean_completion_tokens']} tok  "
                  f"${c['total_cost_usd']}  "
                  f"trunc {c['truncated_calls']}  not5 {c['calls_not_five_charters']}")
    print("\n  Next: wire generation_cost() into scripts/analysis.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())

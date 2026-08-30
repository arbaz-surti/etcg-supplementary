"""
Cross-Model Judge Rescoring  —  revision task 2.2
==================================================
Rescores the SAME 375 charters with a judge model from a different vendor than
the generator, to test whether the reported quality ordering is an artefact of
GPT-4o grading GPT-4o output (R2 #3, R3 #2, R4).

Design constraints, and why they matter
---------------------------------------
1. The corpus is FROZEN. Generation ran at temperature 0.2 (see run_metadata in
   data/etcg-*-results.json), so re-generating would produce a different 375
   charters and strand both the human IRR ratings and every number in the paper.
   This script never touches the generation data or data/etcg-scores.json.

2. The judge must see BYTE-IDENTICAL input to what the primary judge saw.
   Charter texts are therefore rebuilt through etcg_score's own helpers rather
   than re-implemented, and a preflight check asserts the reconstructed
   (spec_id, condition, charter_id) key set matches the authoritative scores
   file exactly.  A sha256 of each charter text is recorded per row so any
   future divergence is detectable rather than silent.

3. Scoring calls are INDEPENDENT — one request, system prompt + one charter, no
   conversation history.  Presentation order therefore cannot influence a score.
   The shuffle is retained only to mirror the primary run's blind-scoring
   posture.

4. Every call's `usage` block and wall-clock latency are recorded.  The primary
   run discarded these, which is why the paper currently has no cost or latency
   table (revision task 2.4).  This run starts closing that gap on the judging
   side.

Join key: (spec_id, condition, charter_id) — verified unique across all 375
charters, and the same triple used by the human IRR key files, so judge scores,
primary scores and human ratings all join on one key.

Output: data/etcg-scores-<judge-slug>.json   (never data/etcg-scores.json)

Usage
-----
    python scripts/judge_score.py --judge sonnet --dry-run     # cost estimate, no API calls
    python scripts/judge_score.py --judge sonnet --limit 10    # smoke test
    python scripts/judge_score.py --judge sonnet               # full 375-charter run
    python scripts/judge_score.py --judge sonnet --resume      # continue an interrupted run
    python scripts/judge_score.py --list-judges
"""

import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

# Reuse the primary scorer's rubric prompt and charter formatting verbatim.
# Importing is deliberate: a re-implementation could drift, and the whole point
# of this run is that only the judge model changes.
import etcg_score as primary  # noqa: E402

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

DIMS = ["specificity", "testability", "risk_coverage", "clarity", "actionability"]

RANDOM_SEED = 42          # mirrors the primary run
REQUEST_TIMEOUT = 90
MAX_RETRIES = 4
CHECKPOINT_EVERY = 25

# ── Judge registry ─────────────────────────────────────────────────────────────
# Prices are USD per million tokens, taken from the OpenRouter model list on
# 2026-08-27, and are used only for the --dry-run estimate.  Actual spend is
# read back from each response's usage block, so the reported cost in the output
# file is measured, not estimated.
JUDGES = {
    "sonnet": {
        "model": "anthropic/claude-sonnet-4.5",
        "label": "Claude Sonnet 4.5 (Anthropic)",
        "price_in": 3.00,
        "price_out": 15.00,
    },
    "sonnet5": {
        "model": "anthropic/claude-sonnet-5",
        "label": "Claude Sonnet 5 (Anthropic)",
        "price_in": 2.00,
        "price_out": 10.00,
    },
    "gemini": {
        "model": "google/gemini-2.5-pro",
        "label": "Gemini 2.5 Pro (Google)",
        "price_in": 1.25,
        "price_out": 10.00,
        # Gemini 2.5 Pro always reasons, and reasoning tokens are billed against
        # max_tokens.  At the primary run's 300 the reply truncates mid-JSON
        # (finish_reason=length).  The budget is a ceiling, not a scientific
        # parameter — the rubric, temperature and input are what must match — so
        # it is raised, and the thinking budget capped at Google's minimum to
        # keep the reply short and the cost near the other judges'.
        "max_tokens": 1500,
        "reasoning": {"max_tokens": 128},
        "est_output_tokens": 260,
    },
    "gpt4o": {
        # Re-run of the primary judge, pinned to a dated snapshot.  Useful as a
        # determinism control: it isolates same-model run-to-run drift from
        # genuine cross-vendor disagreement.
        "model": "openai/gpt-4o-2024-11-20",
        "label": "GPT-4o 2024-11-20 (OpenAI, determinism control)",
        "price_in": 2.50,
        "price_out": 10.00,
    },
}

TEMPERATURE = 0.0         # same as the primary scoring run
MAX_TOKENS = 300          # same as the primary scoring run
EST_OUTPUT_TOKENS = 100   # 5 integer fields + a one-sentence rationale


# ── Corpus reconstruction ──────────────────────────────────────────────────────

def build_corpus() -> list[dict]:
    """
    Rebuild the exact 375-charter corpus the primary judge scored, using the
    primary scorer's own extraction and formatting functions.
    """
    with open(primary.ETCG_RESULTS_FILE) as f:
        etcg_data = json.load(f)
    with open(primary.BASELINE_RESULTS_FILE) as f:
        baseline_data = json.load(f)
    with open(primary.INTERMEDIATE_RESULTS_FILE) as f:
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

    for data, condition, out_key, prefix in (
        (baseline_data, "baseline", "baseline_output", "BL"),
        (intermediate_data, "intermediate", "intermediate_output", "IM"),
    ):
        for result in data["results"]:
            if "error" in result:
                continue
            raw = result[out_key]["raw_output"]
            for i, charter_text in enumerate(primary.extract_baseline_charters(raw), 1):
                items.append({
                    "spec_id": result["spec_id"],
                    "domain": result["domain"],
                    "condition": condition,
                    "charter_id": f"{prefix}-{i:02d}",
                    "charter_text": charter_text,
                })

    for it in items:
        it["text_sha256"] = hashlib.sha256(
            it["charter_text"].encode("utf-8")
        ).hexdigest()

    return items


def key_of(item: dict) -> tuple:
    return (item["spec_id"], item["condition"], item["charter_id"])


def preflight(corpus: list[dict]) -> dict:
    """
    Assert the reconstructed corpus is exactly the one the primary judge scored.
    Returns the primary scores indexed by join key.
    """
    with open(primary.SCORES_FILE) as f:
        authoritative = json.load(f)

    primary_by_key = {
        (s["spec_id"], s["condition"], s["charter_id"]): s
        for s in authoritative["scores"]
        if "error" not in s
    }

    corpus_keys = {key_of(it) for it in corpus}
    if len(corpus_keys) != len(corpus):
        raise SystemExit(
            f"PREFLIGHT FAILED: corpus has {len(corpus)} charters but only "
            f"{len(corpus_keys)} distinct join keys — keys are not unique."
        )

    missing = set(primary_by_key) - corpus_keys
    extra = corpus_keys - set(primary_by_key)
    if missing or extra:
        raise SystemExit(
            "PREFLIGHT FAILED: reconstructed corpus does not match "
            f"{primary.SCORES_FILE.name}.\n"
            f"  in authoritative but not rebuilt: {len(missing)} {sorted(missing)[:5]}\n"
            f"  rebuilt but not in authoritative: {len(extra)} {sorted(extra)[:5]}"
        )

    print(f"preflight  OK — {len(corpus)} charters, join keys match "
          f"{primary.SCORES_FILE.name} exactly")
    return primary_by_key


# ── Scoring ────────────────────────────────────────────────────────────────────

def parse_scores(content: str) -> dict:
    """Parse the judge's JSON reply, tolerating markdown fences and prose."""
    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise ValueError(f"no JSON object in reply: {content[:200]!r}")
        obj = json.loads(match.group(0))

    scores = {}
    for dim in DIMS:
        if dim not in obj:
            raise ValueError(f"missing dimension {dim!r} in reply: {obj}")
        value = obj[dim]
        if isinstance(value, str) and value.strip().isdigit():
            value = int(value.strip())
        if not isinstance(value, int) or value not in (1, 2, 3):
            raise ValueError(f"dimension {dim!r} out of range: {value!r}")
        scores[dim] = value
    scores["rationale"] = str(obj.get("rationale", ""))[:500]
    return scores


def score_charter(judge: dict, charter_text: str, use_json_mode: bool) -> tuple:
    """Returns (scores, usage, latency, resolved_model, json_mode_used, finish_reason)."""
    model = judge["model"]
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/arbaz-surti/etcg-supplementary",
        "X-Title": "ETCG Cross-Model Judge",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": primary.SCORER_SYSTEM_PROMPT},
            {"role": "user",
             "content": f"Score this exploratory testing charter:\n\n{charter_text}"},
        ],
        "temperature": TEMPERATURE,
        "max_tokens": judge.get("max_tokens", MAX_TOKENS),
        # Ask OpenRouter for cost accounting alongside token counts.
        "usage": {"include": True},
    }
    if judge.get("reasoning"):
        payload["reasoning"] = judge["reasoning"]
    if use_json_mode:
        payload["response_format"] = {"type": "json_object"}

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        started = time.monotonic()
        try:
            response = requests.post(
                OPENROUTER_API_URL, headers=headers, json=payload,
                timeout=REQUEST_TIMEOUT,
            )
            # A model that rejects json mode should be retried without it,
            # not counted as a failure.
            if response.status_code == 400 and use_json_mode and \
                    "response_format" in response.text.lower():
                payload.pop("response_format", None)
                use_json_mode = False
                continue
            if response.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(
                    f"{response.status_code}: {response.text[:160]}")
            response.raise_for_status()

            body = response.json()
            latency = time.monotonic() - started
            choice = body["choices"][0]
            finish = choice.get("finish_reason")
            content = choice.get("message", {}).get("content")

            # A reply cut off at the token ceiling is a budget problem, not a
            # judgement: raise the ceiling and try again rather than recording a
            # missing score.
            if finish == "length" or not content:
                if payload["max_tokens"] < 4000:
                    payload["max_tokens"] = min(payload["max_tokens"] * 3, 4000)
                    last_error = ValueError(
                        f"truncated (finish_reason={finish}); "
                        f"raised max_tokens to {payload['max_tokens']}")
                    continue
                raise ValueError(f"empty content at max_tokens ceiling "
                                 f"(finish_reason={finish})")

            scores = parse_scores(content)
            usage = body.get("usage") or {}
            return (
                scores,
                {
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "total_tokens": usage.get("total_tokens"),
                    "cost_usd": usage.get("cost"),
                },
                round(latency, 3),
                body.get("model", model),
                use_json_mode,
                finish,
            )
        except (requests.RequestException, ValueError, KeyError) as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(min(2 ** attempt, 16))

    raise RuntimeError(f"failed after {MAX_RETRIES} attempts: {last_error}")


# ── Summary statistics (same shape as the primary scores file) ─────────────────

def mean(vals):
    return round(sum(vals) / len(vals), 2) if vals else 0


def stdev(vals):
    if len(vals) < 2:
        return 0
    m = sum(vals) / len(vals)
    return round((sum((x - m) ** 2 for x in vals) / (len(vals) - 1)) ** 0.5, 2)


def summarise(scored: list[dict]) -> dict:
    summary = {}
    for condition in ("etcg", "intermediate", "baseline"):
        rows = [s for s in scored
                if s["condition"] == condition and "error" not in s]
        pcts = [s["percentage"] for s in rows]
        summary[condition] = {
            "n": len(rows),
            "overall_mean_pct": mean(pcts),
            "overall_stdev_pct": stdev(pcts),
            "dimensions": {
                d: {
                    "mean": mean([s["scores"][d] for s in rows]),
                    "stdev": stdev([s["scores"][d] for s in rows]),
                    "n": len(rows),
                }
                for d in DIMS
            },
        }
    return summary


def write_output(path: Path, judge_slug: str, judge: dict, scored: list[dict],
                 resolved_models: set, complete: bool) -> None:
    costs = [s["usage"]["cost_usd"] for s in scored
             if "error" not in s and s.get("usage", {}).get("cost_usd") is not None]
    latencies = [s["latency_s"] for s in scored if "error" not in s]
    prompt_toks = [s["usage"]["prompt_tokens"] for s in scored
                   if "error" not in s and s.get("usage", {}).get("prompt_tokens")]
    completion_toks = [s["usage"]["completion_tokens"] for s in scored
                       if "error" not in s and s.get("usage", {}).get("completion_tokens")]

    output = {
        "run_metadata": {
            "purpose": "cross-model judge rescoring (revision task 2.2)",
            "judge_slug": judge_slug,
            "scorer_model": judge["model"],
            "scorer_model_resolved": sorted(resolved_models),
            "scorer_label": judge["label"],
            "scorer_temperature": TEMPERATURE,
            "max_tokens": judge.get("max_tokens", MAX_TOKENS),
            "reasoning": judge.get("reasoning"),
            "rubric": "identical to primary run (etcg_score.SCORER_SYSTEM_PROMPT)",
            "corpus": "frozen 375-charter corpus; generation not re-run",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_charters_scored": len(scored),
            "errors": sum(1 for s in scored if "error" in s),
            "complete": complete,
        },
        "cost_and_latency": {
            "total_cost_usd": round(sum(costs), 4) if costs else None,
            "cost_rows_reported": len(costs),
            "total_prompt_tokens": sum(prompt_toks) if prompt_toks else None,
            "total_completion_tokens": sum(completion_toks) if completion_toks else None,
            "mean_latency_s": round(sum(latencies) / len(latencies), 3) if latencies else None,
            "median_latency_s": (
                round(sorted(latencies)[len(latencies) // 2], 3) if latencies else None
            ),
        },
        "summary": summarise(scored),
        "scores": scored,
    }
    with open(path, "w") as f:
        json.dump(output, f, indent=2)


# ── Estimation ─────────────────────────────────────────────────────────────────

def estimate(corpus: list[dict], judge: dict, limit: int | None) -> None:
    items = corpus[:limit] if limit else corpus
    sys_chars = len(primary.SCORER_SYSTEM_PROMPT)
    wrapper_chars = len("Score this exploratory testing charter:\n\n")

    # ~4 chars per token; the run reports measured usage, this is only a budget.
    in_tokens = sum(
        (sys_chars + wrapper_chars + len(it["charter_text"])) / 4 for it in items
    )
    out_tokens = len(items) * judge.get("est_output_tokens", EST_OUTPUT_TOKENS)

    cost_in = in_tokens / 1e6 * judge["price_in"]
    cost_out = out_tokens / 1e6 * judge["price_out"]

    by_cond = {}
    for it in items:
        by_cond.setdefault(it["condition"], []).append(len(it["charter_text"]))

    print()
    print(f"  judge            : {judge['label']}")
    print(f"  model id         : {judge['model']}")
    print(f"  charters         : {len(items)}")
    print(f"  mean charter size: ", end="")
    print(", ".join(f"{c} {sum(v)//len(v)} chars" for c, v in sorted(by_cond.items())))
    print(f"  est. input       : {in_tokens/1000:,.1f}k tokens  @ ${judge['price_in']}/M  = ${cost_in:.2f}")
    print(f"  est. output      : {out_tokens/1000:,.1f}k tokens  @ ${judge['price_out']}/M = ${cost_out:.2f}")
    print(f"  ESTIMATED TOTAL  : ${cost_in + cost_out:.2f}")
    print(f"  est. wall clock  : ~{len(items) * 2.0 / 60:.0f} min at ~2 s/charter")
    print()


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--judge", help=f"one of: {', '.join(JUDGES)}")
    parser.add_argument("--dry-run", action="store_true",
                        help="estimate cost and exit; makes no API calls")
    parser.add_argument("--limit", type=int,
                        help="score only the first N charters (smoke test)")
    parser.add_argument("--resume", action="store_true",
                        help="skip charters already present in the output file")
    parser.add_argument("--list-judges", action="store_true")
    args = parser.parse_args()

    if args.list_judges:
        for slug, j in JUDGES.items():
            print(f"  {slug:<10} {j['model']:<34} "
                  f"${j['price_in']}/M in, ${j['price_out']}/M out")
        return

    if not args.judge:
        parser.error("--judge is required (see --list-judges)")
    if args.judge not in JUDGES:
        parser.error(f"unknown judge {args.judge!r}; see --list-judges")

    judge = JUDGES[args.judge]
    corpus = build_corpus()
    preflight(corpus)

    random.seed(RANDOM_SEED)
    corpus.sort(key=key_of)
    random.shuffle(corpus)

    if args.dry_run:
        estimate(corpus, judge, args.limit)
        print("  dry run — no API calls made, nothing written")
        return

    if not OPENROUTER_API_KEY:
        raise SystemExit("OPENROUTER_API_KEY not set (expected in etcg-supplementary/.env)")

    out_path = BASE_DIR / "data" / f"etcg-scores-{args.judge}.json"
    if out_path.resolve() == primary.SCORES_FILE.resolve():
        raise SystemExit("refusing to overwrite the authoritative scores file")

    scored: list[dict] = []
    done_keys: set = set()
    if args.resume and out_path.exists():
        with open(out_path) as f:
            previous = json.load(f)["scores"]
        # Keep only successful rows. A failed charter is retried on resume, so
        # carrying its error row forward would leave two records under one join
        # key and inflate the reported charter count.
        scored = [s for s in previous if "error" not in s]
        dropped = len(previous) - len(scored)
        done_keys = {(s["spec_id"], s["condition"], s["charter_id"]) for s in scored}
        print(f"resume     {len(done_keys)} charters already scored in {out_path.name}"
              + (f"; retrying {dropped} previously failed" if dropped else ""))

    todo = [it for it in corpus if key_of(it) not in done_keys]
    if args.limit:
        todo = todo[:args.limit]

    estimate(todo, judge, None)

    resolved_models = {s.get("scorer_model_resolved") for s in scored
                       if s.get("scorer_model_resolved")}
    json_mode = True
    errors = 0

    print(f"scoring    {len(todo)} charters -> {out_path.name}")
    print("=" * 68)

    for i, item in enumerate(todo, 1):
        label = f"{item['condition'][:4].upper():<4} {item['spec_id']} {item['charter_id']}"
        print(f"[{i:03d}/{len(todo)}] {label}", end="  ", flush=True)

        row = {
            "spec_id": item["spec_id"],
            "domain": item["domain"],
            "condition": item["condition"],
            "charter_id": item["charter_id"],
            "text_sha256": item["text_sha256"],
        }
        try:
            scores, usage, latency, resolved, json_mode, finish = score_charter(
                judge, item["charter_text"], json_mode)
            total = sum(scores[d] for d in DIMS)
            row.update({
                "scores": scores,
                "total_score": total,
                "percentage": round(total / 15 * 100, 1),
                "usage": usage,
                "latency_s": latency,
                "scorer_model_resolved": resolved,
                "finish_reason": finish,
            })
            resolved_models.add(resolved)
            cost = usage.get("cost_usd")
            cost_str = f"${cost:.4f}" if isinstance(cost, (int, float)) else "  n/a "
            print(f"-> {total:2d}/15 ({row['percentage']:5.1f}%)  "
                  f"{latency:5.2f}s  {cost_str}")
        except Exception as exc:  # noqa: BLE001 — record and continue
            errors += 1
            row["error"] = str(exc)
            print(f"-> ERROR: {exc}")

        scored.append(row)

        if i % CHECKPOINT_EVERY == 0:
            write_output(out_path, args.judge, judge, scored, resolved_models, False)
            print(f"           …checkpoint written ({len(scored)} rows)")

        if i < len(todo):
            time.sleep(0.4)

    complete = (len(todo) + len(done_keys)) >= len(corpus) and errors == 0
    write_output(out_path, args.judge, judge, scored, resolved_models, complete)

    summary = summarise(scored)
    print("=" * 68)
    print(f"wrote      {out_path}")
    print(f"errors     {errors}")
    print()
    for condition in ("etcg", "intermediate", "baseline"):
        s = summary[condition]
        print(f"  {condition:<13} {s['overall_mean_pct']:6.2f}%  "
              f"(SD {s['overall_stdev_pct']:5.2f}, n={s['n']})")
    print()
    print("  Next: python scripts/analysis.py  (judge convergence stats)")


if __name__ == "__main__":
    main()

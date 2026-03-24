"""
ETCG Rubric Scorer
==================
Scores all 250 charters (125 ETCG + 125 baseline) using the 5-dimension rubric
via GPT-4o as the primary evaluator, with blind scoring (condition not revealed).

Rubric dimensions (each 1–3):
  1. Specificity   — precise target, named approach, scoped risk
  2. Testability   — directly executable without clarification
  3. Risk Coverage — meaningful, non-obvious risk with real user impact
  4. Clarity       — clear, grammatically correct, unambiguous prose
  5. Actionability — distinct exploratory approach that guides the session

Scoring is done in a single pass per charter. Charters are randomised across
conditions before scoring to prevent condition-order bias.

Output: research/etcg-scores.json
"""

import json
import os
import random
import re
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

# ── Configuration ──────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

MODEL = "openai/gpt-4o"
TEMPERATURE = 0.0   # zero temperature for maximum scoring consistency

ETCG_RESULTS_FILE     = BASE_DIR / "research" / "etcg-results.json"
BASELINE_RESULTS_FILE = BASE_DIR / "research" / "etcg-baseline-results.json"
SCORES_FILE           = BASE_DIR / "research" / "etcg-scores.json"

RANDOM_SEED = 42   # for reproducible shuffle

# ── Rubric Scorer Prompt ───────────────────────────────────────────────────────

SCORER_SYSTEM_PROMPT = """You are an expert QA evaluator assessing the quality of exploratory testing charters.

Score the following charter on exactly 5 dimensions. Each dimension is scored 1, 2, or 3.

Scoring rubric:

DIMENSION 1 — Specificity
3 (High): Charter targets a precise feature component with a named approach and clearly scoped risk.
2 (Medium): Charter identifies a feature area but approach or risk is somewhat general.
1 (Low): Charter is vague — generic feature area, unclear approach, undefined risk.

DIMENSION 2 — Testability
3 (High): Charter can be executed directly without further clarification; clear start state and goal.
2 (Medium): Charter requires minor interpretation before execution.
1 (Low): Charter is not actionable without significant rewriting.

DIMENSION 3 — Risk Coverage
3 (High): Charter targets a meaningful, non-obvious risk or defect type with real user impact.
2 (Medium): Charter addresses a risk but it is generic or low-impact.
1 (Low): Charter does not articulate a clear risk focus.

DIMENSION 4 — Clarity
3 (High): Charter prose is clear, grammatically correct, and unambiguous.
2 (Medium): Charter is mostly clear with minor phrasing issues.
1 (Low): Charter is confusing, ambiguous, or poorly written.

DIMENSION 5 — Actionability
3 (High): Charter provides a distinct exploratory approach (e.g., boundary testing, role-based walkthrough) that guides the session meaningfully.
2 (Medium): Charter suggests a direction but the approach is generic.
1 (Low): Charter provides no useful direction for the testing session.

Return ONLY a valid JSON object in this exact format:
{
  "specificity": <1|2|3>,
  "testability": <1|2|3>,
  "risk_coverage": <1|2|3>,
  "clarity": <1|2|3>,
  "actionability": <1|2|3>,
  "rationale": "<one sentence explaining the overall assessment>"
}"""


def format_charter_for_scoring(charter: dict, condition: str) -> str:
    """Format a charter as text for the scorer. Condition is NOT revealed."""
    if condition == "etcg":
        # Structured JSON charter
        description = (
            f"Explore {charter.get('target_area', '')} "
            f"using {charter.get('approach', '')} "
            f"to discover {charter.get('risk_focus', '')}."
        )
        return (
            f"Charter description: {description}\n"
            f"Target area: {charter.get('target_area', '')}\n"
            f"Approach: {charter.get('approach', '')}\n"
            f"Risk focus: {charter.get('risk_focus', '')}\n"
            f"Priority: {charter.get('priority', '')}\n"
            f"Estimated duration: {charter.get('estimated_duration', '')}"
        )
    else:
        # Baseline: raw text, return as-is
        return str(charter)


def score_charter(charter_text: str) -> dict:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/arbaz-surti/etcg-supplementary",
        "X-Title": "ETCG Scorer",
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SCORER_SYSTEM_PROMPT},
            {"role": "user", "content": f"Score this exploratory testing charter:\n\n{charter_text}"},
        ],
        "temperature": TEMPERATURE,
        "max_tokens": 300,
        "response_format": {"type": "json_object"},
    }
    response = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return json.loads(content)


# ── Charter Extractor ──────────────────────────────────────────────────────────

def extract_baseline_charters(raw_output: str) -> list[str]:
    """
    Split baseline free-text output into individual charter texts.
    Baseline charters are separated by numbered headings or blank lines.
    Returns a list of up to 5 charter text strings.
    """
    # Split on numbered charter headers: "1.", "Charter 1:", "### Charter", etc.
    parts = re.split(
        r'\n(?=(?:\d+\.|#{1,3}\s|\*\*Charter\s?\d|\bCharter\s?\d))',
        raw_output.strip()
    )
    # Remove empty parts and trim
    charters = [p.strip() for p in parts if p.strip()]
    # If we got too many sub-splits, try a simpler split on double newlines
    if len(charters) > 7:
        charters = [p.strip() for p in raw_output.split("\n\n") if p.strip()]
    # Take first 5
    return charters[:5]


# ── Main Scoring Run ───────────────────────────────────────────────────────────

def run_scoring():
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY not found.")

    # Load results
    with open(ETCG_RESULTS_FILE) as f:
        etcg_data = json.load(f)
    with open(BASELINE_RESULTS_FILE) as f:
        baseline_data = json.load(f)

    # Build flat list of all charters with condition label
    all_items = []

    for result in etcg_data["results"]:
        if "error" in result:
            continue
        spec_id = result["spec_id"]
        domain  = result["domain"]
        for charter in result["etcg_output"]["charters"]:
            all_items.append({
                "spec_id": spec_id,
                "domain": domain,
                "condition": "etcg",
                "charter_id": charter.get("charter_id", ""),
                "charter_data": charter,
                "charter_text": format_charter_for_scoring(charter, "etcg"),
            })

    for result in baseline_data["results"]:
        if "error" in result:
            continue
        spec_id = result["spec_id"]
        domain  = result["domain"]
        raw = result["baseline_output"]["raw_output"]
        charters = extract_baseline_charters(raw)
        for i, charter_text in enumerate(charters, 1):
            all_items.append({
                "spec_id": spec_id,
                "domain": domain,
                "condition": "baseline",
                "charter_id": f"BL-{i:02d}",
                "charter_data": charter_text,
                "charter_text": charter_text,
            })

    # Shuffle for blind scoring
    random.seed(RANDOM_SEED)
    random.shuffle(all_items)

    total = len(all_items)
    print("ETCG Rubric Scoring Run")
    print(f"Model      : {MODEL} (temperature=0)")
    print(f"Charters   : {total}")
    print(f"Output     : {SCORES_FILE}")
    print("=" * 60)

    scored = []
    errors = 0

    for i, item in enumerate(all_items, 1):
        label = f"{item['condition'].upper()} {item['spec_id']} {item['charter_id']}"
        print(f"[{i:03d}/{total}] {label}", end="  ")

        try:
            scores = score_charter(item["charter_text"])
            total_score = (
                scores["specificity"] +
                scores["testability"] +
                scores["risk_coverage"] +
                scores["clarity"] +
                scores["actionability"]
            )
            pct = round((total_score / 15) * 100, 1)
            print(f"→ {total_score}/15 ({pct}%)")

            scored.append({
                "spec_id": item["spec_id"],
                "domain": item["domain"],
                "condition": item["condition"],
                "charter_id": item["charter_id"],
                "scores": scores,
                "total_score": total_score,
                "percentage": pct,
            })

        except Exception as e:
            print(f"→ ERROR: {e}")
            errors += 1
            scored.append({
                "spec_id": item["spec_id"],
                "domain": item["domain"],
                "condition": item["condition"],
                "charter_id": item["charter_id"],
                "error": str(e),
            })

        if i < total:
            time.sleep(0.5)

    # ── Compute Summary Statistics ─────────────────────────────────────────────

    etcg_scores    = [s for s in scored if s["condition"] == "etcg"     and "error" not in s]
    baseline_scores = [s for s in scored if s["condition"] == "baseline" and "error" not in s]

    def mean(vals): return round(sum(vals) / len(vals), 2) if vals else 0
    def stdev(vals):
        if len(vals) < 2: return 0
        m = sum(vals) / len(vals)
        return round((sum((x - m) ** 2 for x in vals) / (len(vals) - 1)) ** 0.5, 2)

    def dim_stats(items, dim):
        vals = [s["scores"][dim] for s in items]
        return {"mean": mean(vals), "stdev": stdev(vals), "n": len(vals)}

    dims = ["specificity", "testability", "risk_coverage", "clarity", "actionability"]

    etcg_pcts    = [s["percentage"] for s in etcg_scores]
    baseline_pcts = [s["percentage"] for s in baseline_scores]

    summary = {
        "etcg": {
            "n": len(etcg_scores),
            "overall_mean_pct": mean(etcg_pcts),
            "overall_stdev_pct": stdev(etcg_pcts),
            "dimensions": {d: dim_stats(etcg_scores, d) for d in dims},
        },
        "baseline": {
            "n": len(baseline_scores),
            "overall_mean_pct": mean(baseline_pcts),
            "overall_stdev_pct": stdev(baseline_pcts),
            "dimensions": {d: dim_stats(baseline_scores, d) for d in dims},
        },
    }

    # Domain breakdown
    domains = list({s["domain"] for s in scored})
    domain_summary = {}
    for domain in sorted(domains):
        e = [s for s in etcg_scores if s["domain"] == domain]
        domain_summary[domain] = {
            "etcg_mean_pct": mean([s["percentage"] for s in e]),
            "etcg_n": len(e),
        }
    summary["by_domain"] = domain_summary

    output = {
        "run_metadata": {
            "scorer_model": MODEL,
            "scorer_temperature": TEMPERATURE,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "total_charters_scored": len(scored),
            "errors": errors,
        },
        "summary": summary,
        "scores": scored,
    }

    with open(SCORES_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print("=" * 60)
    print(f"Scoring complete. Saved to: {SCORES_FILE}")
    print(f"Errors: {errors}")
    print()
    print("── RESULTS SUMMARY ──────────────────────────────────────")
    print(f"ETCG    overall: {summary['etcg']['overall_mean_pct']}% (±{summary['etcg']['overall_stdev_pct']}%)")
    print(f"Baseline overall: {summary['baseline']['overall_mean_pct']}% (±{summary['baseline']['overall_stdev_pct']}%)")
    print()
    print("ETCG dimension means:")
    for d in dims:
        ds = summary["etcg"]["dimensions"][d]
        print(f"  {d:<16}: {ds['mean']}/3")
    print()
    print("Baseline dimension means:")
    for d in dims:
        ds = summary["baseline"]["dimensions"][d]
        print(f"  {d:<16}: {ds['mean']}/3")
    print()
    print("Domain breakdown (ETCG):")
    for domain, stats in summary["by_domain"].items():
        print(f"  {domain:<28}: {stats['etcg_mean_pct']}% (n={stats['etcg_n']})")


if __name__ == "__main__":
    run_scoring()

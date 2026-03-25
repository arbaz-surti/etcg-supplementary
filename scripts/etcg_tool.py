"""
ETCG — Exploratory Testing Charter Generator
=============================================
Evaluation script for the paper:
"LLM-Based Exploratory Testing Charter Generation: A Framework and Empirical Evaluation"

This script runs each of the 25 feature specifications through the ETCG framework using
GPT-4o via the OpenRouter API, producing 5 structured exploratory testing charters per spec.
Results are saved to research/etcg-results.json for rubric-based evaluation.

Usage:
    python etcg_tool.py

Requirements:
    pip install requests python-dotenv
"""

import json
import os
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

# OpenRouter model route used in the paper evaluation (run: 2026-03-24).
# "openai/gpt-4o" resolves to OpenAI's current stable GPT-4o snapshot at
# inference time.  For strict reproducibility of the published results, pin to
# a specific snapshot, e.g.:  "openai/gpt-4o-2024-11-20"
MODEL       = "openai/gpt-4o"
TEMPERATURE = 0.2
MAX_TOKENS  = 1500

ATSR_SPECS_FILE = BASE_DIR.parent / "paper-1-ATSR" / "research" / "all-specs-18.json"
NEW_SPECS_FILE  = BASE_DIR / "research" / "specs-new-7.json"
RESULTS_FILE    = BASE_DIR / "research" / "etcg-results.json"

# ── ETCG System Prompt ─────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert QA engineer specialising in exploratory testing. You will be provided with a software requirement specification. Your task is to generate exactly five exploratory testing charters based on this specification.

Each charter must follow this structure:
{
  "charter_id": "ET-01",
  "target_area": "The specific feature or component being explored",
  "approach": "The exploratory technique or method to be used",
  "risk_focus": "The specific risk, defect type, or concern being investigated",
  "priority": "High | Medium | Low",
  "estimated_duration": "30 min | 45 min | 60 min"
}

Each charter description should follow this pattern:
"Explore [target_area] using [approach] to discover [risk_focus]."

Requirements:
- Generate exactly 5 charters.
- Each charter must address a distinct risk area.
- Vary the approaches across charters (do not repeat the same technique).
- Prioritise based on user impact and likelihood of defects.
- Output a valid JSON object with a single key "charters" containing an array of exactly 5 charter objects.
- Do not include any text outside the JSON object.

Specification:
[SPEC_CONTENT]"""


# ── Spec Formatters ────────────────────────────────────────────────────────────

def format_atsr_spec(spec: dict) -> str:
    """Convert an ATSR-format spec into a human-readable text for ETCG prompt injection."""
    lines = [
        f"Feature: {spec['title']}",
        f"System Area: {spec['system_area']}",
        f"Change Type: {spec['change_type']}",
        "",
        "Description:",
        spec["description"],
    ]
    if spec.get("acceptance_criteria"):
        lines.append("")
        lines.append("Acceptance Criteria:")
        for ac in spec["acceptance_criteria"]:
            lines.append(f"- {ac}")
    return "\n".join(lines)


def format_new_spec(spec: dict) -> str:
    """Convert a new-format spec (SPEC-19 to SPEC-25) into text for ETCG prompt injection."""
    lines = [
        f"Feature: {spec['feature']}",
        f"Domain: {spec['domain']}",
        "",
        f"User Roles: {', '.join(spec['user_roles'])}",
        "",
        "Description:",
        spec["description"],
        "",
        "Acceptance Criteria:",
    ]
    for ac in spec["acceptance_criteria"]:
        lines.append(f"- {ac}")

    if spec.get("user_flows"):
        lines.append("")
        lines.append("User Flows:")
        for i, flow in enumerate(spec["user_flows"], 1):
            lines.append(f"{i}. {flow}")

    if spec.get("edge_cases"):
        lines.append("")
        lines.append("Edge Cases / Notes:")
        for ec in spec["edge_cases"]:
            lines.append(f"- {ec}")

    return "\n".join(lines)


# ── Spec Loader ────────────────────────────────────────────────────────────────

def load_all_specs() -> list[dict]:
    """Load and merge all 25 specs, returning unified list with spec_id, domain, spec_text."""
    specs = []

    # Load 18 ATSR specs
    with open(ATSR_SPECS_FILE, "r") as f:
        atsr_specs = json.load(f)

    for i, spec in enumerate(atsr_specs, 1):
        specs.append({
            "spec_id": f"SPEC-{i:02d}",           # renumber sequentially 01–18
            "original_id": spec["spec_id"],
            "domain": "Restaurant Technology",
            "spec_text": format_atsr_spec(spec),
        })

    # Load 7 new specs
    with open(NEW_SPECS_FILE, "r") as f:
        new_specs = json.load(f)

    for spec in new_specs:
        specs.append({
            "spec_id": spec["spec_id"],
            "original_id": spec["spec_id"],
            "domain": spec["domain"],
            "spec_text": format_new_spec(spec),
        })

    return specs


# ── API Call ───────────────────────────────────────────────────────────────────

def call_etcg(spec_id: str, spec_text: str) -> dict:
    """Send a spec to GPT-4o with the ETCG structured prompt and return parsed charters."""

    user_prompt = SYSTEM_PROMPT.replace("[SPEC_CONTENT]", spec_text)

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/arbaz-surti/etcg-supplementary",
        "X-Title": "ETCG Research Tool",
    }

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "user", "content": user_prompt},
        ],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "response_format": {"type": "json_object"},
    }

    response = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=60)
    response.raise_for_status()

    raw = response.json()
    content = raw["choices"][0]["message"]["content"]
    parsed = json.loads(content)

    # Normalise: handle both {"charters": [...]} and bare array
    if isinstance(parsed, list):
        charters = parsed
    elif "charters" in parsed:
        charters = parsed["charters"]
    else:
        # Try to find the array in the response
        charters = next(v for v in parsed.values() if isinstance(v, list))

    return {
        "spec_id": spec_id,
        "model_used": MODEL,
        "temperature": TEMPERATURE,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "charters": charters,
    }


# ── Evaluation Runner ──────────────────────────────────────────────────────────

def run_evaluation():
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY not found. Add it to paper-2-EMSE/.env")

    specs = load_all_specs()

    print("ETCG Evaluation Run")
    print(f"Model      : {MODEL}")
    print(f"Temperature: {TEMPERATURE}")
    print(f"Specs      : {len(specs)}")
    print(f"Output     : {RESULTS_FILE}")
    print("=" * 60)

    results = []

    for i, spec in enumerate(specs, 1):
        spec_id = spec["spec_id"]
        domain  = spec["domain"]
        print(f"[{i:02d}/{len(specs)}] {spec_id} ({domain})")

        try:
            result = call_etcg(spec_id, spec["spec_text"])

            charter_count = len(result["charters"])
            print(f"  Charters generated: {charter_count}")
            if charter_count != 5:
                print(f"  WARNING: expected 5 charters, got {charter_count}")

            results.append({
                "spec_id": spec_id,
                "original_id": spec["original_id"],
                "domain": domain,
                "etcg_output": result,
            })

        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({
                "spec_id": spec_id,
                "original_id": spec["original_id"],
                "domain": domain,
                "error": str(e),
            })

        if i < len(specs):
            time.sleep(1)

    success_count = sum(1 for r in results if "error" not in r)

    output = {
        "run_metadata": {
            "framework": "ETCG v1.0",
            "model": MODEL,
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "spec_count": len(specs),
            "success_count": success_count,
            "total_charters": success_count * 5,
        },
        "results": results,
    }

    with open(RESULTS_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print("=" * 60)
    print(f"Done. Results saved to: {RESULTS_FILE}")
    print(f"Successfully processed: {success_count}/{len(specs)}")
    print(f"Total charters generated: {success_count * 5}")


if __name__ == "__main__":
    run_evaluation()

"""
ETCG Baseline Tool
==================
Baseline condition for the paper:
"LLM-Based Exploratory Testing Charter Generation: A Framework and Empirical Evaluation"

This script runs each of the 25 feature specifications through an UNSTRUCTURED prompt
using the same model (GPT-4o) and API as the ETCG framework, to serve as the comparison
baseline. The only difference from etcg_tool.py is the prompt — no schema, no field
definitions, no output format constraints.

Results are saved to research/etcg-baseline-results.json.

Usage:
    python etcg_baseline_tool.py

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

MODEL = "openai/gpt-4o"
TEMPERATURE = 0.2
MAX_TOKENS = 1500

ATSR_SPECS_FILE = BASE_DIR.parent / "paper-1-ATSR" / "research" / "all-specs-18.json"
NEW_SPECS_FILE  = BASE_DIR / "research" / "specs-new-7.json"
RESULTS_FILE    = BASE_DIR / "research" / "etcg-baseline-results.json"

# ── Baseline Prompt ────────────────────────────────────────────────────────────
# Intentionally unstructured — no schema, no field definitions, no constraints.
# Same model and temperature as ETCG to isolate the effect of structured prompting.

BASELINE_PROMPT_TEMPLATE = """You are a QA engineer. Given the following software requirement specification, generate 5 exploratory testing charters.

Specification:
[SPEC_CONTENT]"""


# ── Spec Formatters (identical to etcg_tool.py) ────────────────────────────────

def format_atsr_spec(spec: dict) -> str:
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


def load_all_specs() -> list[dict]:
    specs = []
    with open(ATSR_SPECS_FILE, "r") as f:
        atsr_specs = json.load(f)
    for i, spec in enumerate(atsr_specs, 1):
        specs.append({
            "spec_id": f"SPEC-{i:02d}",
            "original_id": spec["spec_id"],
            "domain": "Restaurant Technology",
            "spec_text": format_atsr_spec(spec),
        })
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

def call_baseline(spec_id: str, spec_text: str) -> dict:
    """Send a spec to GPT-4o with the unstructured baseline prompt."""

    prompt = BASELINE_PROMPT_TEMPLATE.replace("[SPEC_CONTENT]", spec_text)

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/arbaz-surti/etcg-supplementary",
        "X-Title": "ETCG Baseline Tool",
    }

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "user", "content": prompt},
        ],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        # No response_format constraint — baseline receives free-form text
    }

    response = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=60)
    response.raise_for_status()

    raw = response.json()
    content = raw["choices"][0]["message"]["content"]

    return {
        "spec_id": spec_id,
        "model_used": MODEL,
        "temperature": TEMPERATURE,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "raw_output": content,
    }


# ── Evaluation Runner ──────────────────────────────────────────────────────────

def run_evaluation():
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY not found. Add it to paper-2-EMSE/.env")

    specs = load_all_specs()

    print("ETCG Baseline Evaluation Run")
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
            result = call_baseline(spec_id, spec["spec_text"])
            # Preview first 120 chars of raw output
            preview = result["raw_output"][:120].replace("\n", " ")
            print(f"  Output preview: {preview}...")

            results.append({
                "spec_id": spec_id,
                "original_id": spec["original_id"],
                "domain": domain,
                "baseline_output": result,
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
            "condition": "baseline (unstructured prompt)",
            "model": MODEL,
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "spec_count": len(specs),
            "success_count": success_count,
        },
        "results": results,
    }

    with open(RESULTS_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print("=" * 60)
    print(f"Done. Results saved to: {RESULTS_FILE}")
    print(f"Successfully processed: {success_count}/{len(specs)}")


if __name__ == "__main__":
    run_evaluation()

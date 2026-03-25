"""
ETCG Intermediate Baseline Tool
================================
Intermediate condition for the paper:
"LLM-Based Exploratory Testing Charter Generation: A Framework and Empirical Evaluation"

This script implements the INTERMEDIATE condition: role-instructed with explicit
guidance (5 charters, distinct risks, varied approaches, prioritisation) but WITHOUT
an output schema or format constraints.

Three-condition design:
  Baseline     — minimal role, no guidance, no schema          (etcg_baseline_tool.py)
  Intermediate — expert role + guidance, NO schema             (this script)
  ETCG         — expert role + guidance + constrained JSON     (etcg_tool.py)

This design allows two isolated comparisons:
  Baseline → Intermediate : effect of role framing + explicit guidance
  Intermediate → ETCG     : effect of the structured output schema alone

Results are saved to data/etcg-intermediate-results.json.

Usage:
    cd etcg-supplementary
    python scripts/etcg_intermediate_tool.py

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

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# OpenRouter model route used in the paper evaluation (run: 2026-03-25).
# "openai/gpt-4o" resolves to OpenAI's current stable GPT-4o snapshot at
# inference time.  For strict reproducibility of the published results, pin to
# a specific snapshot, e.g.:  "openai/gpt-4o-2024-11-20"
MODEL       = "openai/gpt-4o"
TEMPERATURE = 0.2
MAX_TOKENS  = 1500

ATSR_SPECS_FILE   = BASE_DIR.parent / "paper-1-ATSR" / "research" / "all-specs-18.json"
NEW_SPECS_FILE    = BASE_DIR / "data" / "specs-new-7.json"
RESULTS_FILE      = BASE_DIR / "data" / "etcg-intermediate-results.json"

# ── Intermediate Prompt ────────────────────────────────────────────────────────
# Role-instructed (same as ETCG) + explicit guidance (same as ETCG).
# NO output schema — free-form text.  Isolates the effect of the JSON schema.

INTERMEDIATE_PROMPT = """You are an expert QA engineer specialising in exploratory testing. Given the following software requirement specification, generate exactly 5 exploratory testing charters.

Each charter should include:
- A target area (the specific feature or component to explore)
- An exploratory approach or technique to use
- A risk focus (the defect type or concern being investigated)
- A priority level (High, Medium, or Low)
- An estimated session duration

Requirements:
- Generate exactly 5 charters.
- Each charter must address a distinct risk area.
- Vary the exploratory approaches across charters (do not repeat the same technique).
- Prioritise charters based on user impact and likelihood of defects.

Specification:
[SPEC_CONTENT]"""


# ── Spec Formatters (identical to etcg_baseline_tool.py) ──────────────────────

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

def call_intermediate(spec_id: str, spec_text: str) -> dict:
    """Send a spec to GPT-4o with the intermediate prompt (role+guidance, no schema)."""

    prompt = INTERMEDIATE_PROMPT.replace("[SPEC_CONTENT]", spec_text)

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/arbaz-surti/etcg-supplementary",
        "X-Title": "ETCG Intermediate Tool",
    }

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "user", "content": prompt},
        ],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        # No response_format constraint — free-form text output
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
        raise ValueError("OPENROUTER_API_KEY not found. Add it to etcg-supplementary/.env")

    specs = load_all_specs()

    print("ETCG Intermediate Condition Evaluation Run")
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
            result = call_intermediate(spec_id, spec["spec_text"])
            preview = result["raw_output"][:120].replace("\n", " ")
            print(f"  Output preview: {preview}...")

            results.append({
                "spec_id": spec_id,
                "original_id": spec["original_id"],
                "domain": domain,
                "intermediate_output": result,
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
            "condition": "intermediate (role+guidance, no schema)",
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

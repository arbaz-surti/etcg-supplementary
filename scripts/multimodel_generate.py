"""
Multi-model charter generation  —  revision task 2.3
====================================================
Reviewer 1 and Reviewer 2 (comment 5) both note that the paper calls ETCG
"model-agnostic" but evaluates only GPT-4o: prompt variations are compared within a
single generator, so nothing in the data speaks to whether the ablation pattern
(role framing helps, the JSON schema adds nothing to the mean) is a property of the
prompt design or a property of GPT-4o.

This script re-runs the full three-condition design on additional generator model
families. Everything except the generator is held fixed: the three condition prompts,
the temperature, the token ceiling, the 25 specifications, and — downstream, in
multimodel_score.py — the GPT-4o rubric judge. Each model's 375 charters are then
scored by that same fixed judge, so the only thing that varies across the resulting
score sets is which model wrote the charters.

Output, per model slug, mirrors the frozen primary files so the scorer and analysis
can consume it unchanged:

    data/multimodel/<slug>/etcg-results.json
    data/multimodel/<slug>/baseline-results.json
    data/multimodel/<slug>/intermediate-results.json
    data/multimodel/<slug>/generation-instrumentation.json   (usage / latency / retries)

The frozen primary corpus and data/etcg-scores.json are never touched.

Usage
-----
    python scripts/multimodel_generate.py --list-models
    python scripts/multimodel_generate.py --model sonnet --dry-run
    python scripts/multimodel_generate.py --model sonnet --limit 3
    python scripts/multimodel_generate.py --model sonnet
    python scripts/multimodel_generate.py --model sonnet --resume
"""

import argparse
import hashlib
import json
import os
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

from etcg_tool import SYSTEM_PROMPT as ETCG_PROMPT          # noqa: E402
from etcg_baseline_tool import BASELINE_PROMPT_TEMPLATE     # noqa: E402
from etcg_intermediate_tool import INTERMEDIATE_PROMPT, load_all_specs  # noqa: E402
import etcg_score as scorer                                 # noqa: E402

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

TEMPERATURE = 0.2          # identical to the primary generation run
MAX_TOKENS = 1500         # identical to the primary generation run
REQUEST_TIMEOUT = 120
MAX_RETRIES = 4
CHECKPOINT_EVERY = 15

# Generator registry. Prices are USD per million tokens from the OpenRouter model
# list on 2026-08-29 and drive only the --dry-run estimate; realised cost is read
# from each response's usage block.
MODELS = {
    "sonnet": {
        "model": "anthropic/claude-sonnet-4.5",
        "label": "Claude Sonnet 4.5 (Anthropic)",
        "price_in": 3.00, "price_out": 15.00,
    },
    "gemini": {
        "model": "google/gemini-2.5-pro",
        "label": "Gemini 2.5 Pro (Google)",
        "price_in": 1.25, "price_out": 10.00,
        # Gemini 2.5 Pro always emits reasoning tokens, billed against max_tokens.
        # The token ceiling is an operational floor, not a scientific parameter
        # (temperature and prompt are what must match), so it is raised and the
        # thinking budget capped at Google's minimum to keep the answer intact
        # and the cost close to the other generators'.
        "max_tokens": 3000,
        "reasoning": {"max_tokens": 128},
    },
    "llama": {
        "model": "meta-llama/llama-3.3-70b-instruct",
        "label": "Llama 3.3 70B Instruct (Meta, open-weight)",
        "price_in": 0.13, "price_out": 0.39,
    },
}

ETCG_SCHEMA_FIELDS = ("charter_id", "target_area", "approach",
                      "risk_focus", "priority", "estimated_duration")

# condition -> (prompt template, output key, wants json_object mode)
CONDITIONS = {
    "baseline": (BASELINE_PROMPT_TEMPLATE, "baseline_output", False),
    "intermediate": (INTERMEDIATE_PROMPT, "intermediate_output", False),
    "etcg": (ETCG_PROMPT, "etcg_output", True),
}


def _loads_tolerant(content: str):
    """json.loads, but tolerant of markdown fences and surrounding prose.

    Claude Sonnet 4.5 wraps its reply in ```json ... ``` even under json_object
    mode; some models add a sentence before the object. The JSON itself is valid
    in these cases, so strip the wrapper and, failing that, extract the first
    balanced object/array literal.
    """
    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", text, flags=re.DOTALL)
        if not m:
            raise
        return json.loads(m.group(1))


def parse_etcg_charters(content: str) -> list:
    """Same normalisation etcg_tool applies: {'charters': [...]}, bare list, or
    the first list-valued field --- after tolerant JSON extraction."""
    parsed = _loads_tolerant(content)     # caller handles JSONDecodeError / ValueError
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict) and "charters" in parsed:
        return parsed["charters"]
    if isinstance(parsed, dict):
        return next((v for v in parsed.values() if isinstance(v, list)), [])
    return []


def call_model(spec_cfg: dict, condition: str, spec_text: str) -> dict:
    template, _out_key, json_mode = CONDITIONS[condition]
    prompt = template.replace("[SPEC_CONTENT]", spec_text)

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/arbaz-surti/etcg-supplementary",
        "X-Title": "ETCG Multi-Model Generation",
    }
    payload = {
        "model": spec_cfg["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": TEMPERATURE,
        "max_tokens": spec_cfg.get("max_tokens", MAX_TOKENS),
        "usage": {"include": True},
    }
    if spec_cfg.get("reasoning"):
        payload["reasoning"] = spec_cfg["reasoning"]
    want_json = json_mode
    if want_json:
        payload["response_format"] = {"type": "json_object"}

    retries = 0
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        started = time.monotonic()
        try:
            resp = requests.post(OPENROUTER_API_URL, headers=headers, json=payload,
                                 timeout=REQUEST_TIMEOUT)
            # Model rejects json mode -> retry once without it rather than fail.
            if resp.status_code == 400 and want_json and \
                    "response_format" in resp.text.lower():
                payload.pop("response_format", None)
                want_json = False
                continue
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"{resp.status_code}: {resp.text[:160]}")
            resp.raise_for_status()
            latency = time.monotonic() - started

            body = resp.json()
            choice = body["choices"][0]
            content = choice.get("message", {}).get("content") or ""
            finish = choice.get("finish_reason")
            usage = body.get("usage") or {}

            instr = {
                "condition": condition,
                "spec_id": spec_cfg["spec_id"],
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "cost_usd": usage.get("cost"),
                "latency_s": round(latency, 3),
                "retries": retries,
                "finish_reason": finish,
                "json_mode_used": want_json,
                "model_resolved": body.get("model", spec_cfg["model"]),
                "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            }

            instr["raw_content"] = content

            if condition == "etcg":
                try:
                    charters = parse_etcg_charters(content)
                    instr["json_valid"] = True
                except (json.JSONDecodeError, TypeError, ValueError):
                    charters = []
                    instr["json_valid"] = False
                instr["charter_count"] = len(charters)
                instr["schema_complete"] = bool(charters) and all(
                    isinstance(c, dict) and all(c.get(f) not in (None, "") for f in ETCG_SCHEMA_FIELDS)
                    for c in charters
                )
                output = {
                    "spec_id": spec_cfg["spec_id"],
                    "model_used": spec_cfg["model"],
                    "temperature": TEMPERATURE,
                    "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                    "charters": charters,
                    "raw_content": content,
                }
            else:
                n = len(scorer.extract_baseline_charters(content))
                instr["charter_count"] = n
                instr["underextracted"] = n < 5
                output = {
                    "spec_id": spec_cfg["spec_id"],
                    "model_used": spec_cfg["model"],
                    "temperature": TEMPERATURE,
                    "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                    "raw_output": content,
                }

            return {"output": output, "instr": instr}

        except (requests.RequestException, KeyError) as exc:
            last_error = exc
            retries += 1
            if attempt < MAX_RETRIES:
                time.sleep(min(2 ** attempt, 16))

    raise RuntimeError(f"failed after {MAX_RETRIES} attempts: {last_error}")


def out_dir_for(slug: str) -> Path:
    d = BASE_DIR / "data" / "multimodel" / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_existing(out_dir: Path) -> tuple[dict, list]:
    """Return ({(condition, spec_id): output}, [instr rows]) already on disk."""
    done, instr = {}, []
    for cond, (_t, out_key, _j) in CONDITIONS.items():
        path = out_dir / f"{cond}-results.json"
        if not path.exists():
            continue
        blob = json.loads(path.read_text(encoding="utf-8"))
        for res in blob.get("results", []):
            if "error" in res or out_key not in res:
                continue
            out = res[out_key]
            # A prior run may have stored an etcg_output whose parse yielded no
            # charters (e.g. a fenced-JSON model before the tolerant parser).
            # Treat that as not-done so --resume regenerates it.
            if cond == "etcg" and not out.get("charters"):
                continue
            if cond != "etcg" and not out.get("raw_output"):
                continue
            done[(cond, res["spec_id"])] = out
    ip = out_dir / "generation-instrumentation.json"
    if ip.exists():
        prev = json.loads(ip.read_text(encoding="utf-8")).get("calls", [])
        instr = [r for r in prev
                 if "error" not in r and (r["condition"], r["spec_id"]) in done]
    return done, instr


def write_results(out_dir: Path, slug: str, cfg: dict, outputs: dict, specs: list,
                  instr: list, complete: bool) -> None:
    spec_meta = {s["spec_id"]: s for s in specs}
    for cond, (_t, out_key, _j) in CONDITIONS.items():
        rows = []
        for s in specs:
            key = (cond, s["spec_id"])
            base = {"spec_id": s["spec_id"], "original_id": spec_meta[s["spec_id"]]["original_id"],
                    "domain": s["domain"]}
            if key in outputs:
                base[out_key] = outputs[key]
            else:
                base["error"] = "not generated"
            rows.append(base)
        n_ok = sum(1 for r in rows if "error" not in r)
        (out_dir / f"{cond}-results.json").write_text(json.dumps({
            "run_metadata": {
                "purpose": "multi-model generation (revision task 2.3)",
                "condition": cond,
                "generator_slug": slug,
                "model": cfg["model"],
                "label": cfg["label"],
                "temperature": TEMPERATURE,
                "max_tokens": cfg.get("max_tokens", MAX_TOKENS),
                "reasoning": cfg.get("reasoning"),
                "prompt_source": "identical to the primary run's condition prompt",
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "spec_count": len(specs),
                "success_count": n_ok,
                "complete": complete,
            },
            "results": rows,
        }, indent=2, ensure_ascii=False), encoding="utf-8")

    resolved = sorted({r["model_resolved"] for r in instr})
    (out_dir / "generation-instrumentation.json").write_text(json.dumps({
        "run_metadata": {
            "purpose": "multi-model generation instrumentation (task 2.3 / 2.4)",
            "generator_slug": slug, "model": cfg["model"], "model_resolved": resolved,
            "label": cfg["label"], "temperature": TEMPERATURE,
            "max_tokens": cfg.get("max_tokens", MAX_TOKENS), "reasoning": cfg.get("reasoning"),
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "n_calls": len(instr), "complete": complete,
        },
        "calls": instr,
    }, indent=2, ensure_ascii=False), encoding="utf-8")


def estimate(cfg: dict, jobs: list, specs: list) -> None:
    text = {s["spec_id"]: s["spec_text"] for s in specs}
    in_tok = out_tok = 0.0
    for cond, spec_id in jobs:
        template = CONDITIONS[cond][0]
        in_tok += len(template.replace("[SPEC_CONTENT]", text[spec_id])) / 4
        out_tok += 900
    cost = in_tok / 1e6 * cfg["price_in"] + out_tok / 1e6 * cfg["price_out"]
    print(f"  model            : {cfg['label']}  ({cfg['model']})")
    print(f"  calls            : {len(jobs)}")
    print(f"  est. input       : {in_tok/1000:,.1f}k tok  @ ${cfg['price_in']}/M  = ${in_tok/1e6*cfg['price_in']:.2f}")
    print(f"  est. output      : {out_tok/1000:,.1f}k tok  @ ${cfg['price_out']}/M = ${out_tok/1e6*cfg['price_out']:.2f}")
    print(f"  ESTIMATED TOTAL  : ${cost:.2f}")
    print(f"  est. wall clock  : ~{len(jobs) * 5.0 / 60:.0f} min at ~5 s/call")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", help=f"one of: {', '.join(MODELS)}")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--list-models", action="store_true")
    args = ap.parse_args()

    if args.list_models:
        for slug, m in MODELS.items():
            print(f"  {slug:<8} {m['model']:<38} ${m['price_in']}/M in, ${m['price_out']}/M out")
        return 0
    if not args.model or args.model not in MODELS:
        ap.error(f"--model must be one of: {', '.join(MODELS)}")

    cfg = dict(MODELS[args.model], slug=args.model)
    specs = load_all_specs()
    jobs = [(cond, s["spec_id"]) for cond in CONDITIONS for s in specs]

    out_dir = out_dir_for(args.model)
    outputs: dict = {}
    instr: list = []
    if args.resume:
        outputs, instr = load_existing(out_dir)
        print(f"resume     {len(outputs)}/{len(jobs)} generations already on disk")

    todo = [j for j in jobs if j not in outputs]
    if args.limit:
        todo = todo[:args.limit]

    print(f"Multi-model generation — {cfg['label']}")
    estimate(cfg, todo, specs)
    if args.dry_run:
        print("  dry run — no API calls, nothing written")
        return 0
    if not OPENROUTER_API_KEY:
        raise SystemExit("OPENROUTER_API_KEY not set (expected in etcg-supplementary/.env)")

    spec_text = {s["spec_id"]: s["spec_text"] for s in specs}
    spec_by_id = {s["spec_id"]: s for s in specs}
    print("=" * 70)
    errors = 0
    for i, (cond, spec_id) in enumerate(todo, 1):
        print(f"[{i:02d}/{len(todo)}] {args.model} {cond:<12} {spec_id}", end="  ", flush=True)
        cfg_call = dict(cfg, spec_id=spec_id)
        try:
            res = call_model(cfg_call, cond, spec_text[spec_id])
            outputs[(cond, spec_id)] = res["output"]
            instr.append(res["instr"])
            it = res["instr"]
            tag = ""
            if cond == "etcg":
                tag = "json ok" if it.get("json_valid") else "JSON INVALID"
                if it.get("json_valid") and not it.get("schema_complete"):
                    tag += ", schema gaps"
                if it.get("charter_count") != 5:
                    tag += f", {it.get('charter_count')} charters"
            elif it.get("underextracted"):
                tag = f"only {it.get('charter_count')}/5 extracted"
            cost = it.get("cost_usd")
            cs = f"${cost:.4f}" if isinstance(cost, (int, float)) else "n/a"
            print(f"-> {it['latency_s']:5.2f}s  in {it.get('prompt_tokens')} "
                  f"out {it.get('completion_tokens')}  {cs}  {it.get('finish_reason')}  {tag}")
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"-> ERROR: {exc}")
        if i % CHECKPOINT_EVERY == 0:
            write_results(out_dir, args.model, cfg, outputs, specs, instr, complete=False)
            print(f"           …checkpoint ({len(outputs)} generations)")
        if i < len(todo):
            time.sleep(0.5)

    complete = len(outputs) >= len(jobs) and errors == 0
    write_results(out_dir, args.model, cfg, outputs, specs, instr, complete)
    print("=" * 70)
    print(f"wrote      {out_dir}/  ({len(outputs)}/{len(jobs)} generations, {errors} errors)")
    if complete:
        print(f"  Next: python scripts/multimodel_score.py --model {args.model}")
    else:
        print(f"  Incomplete — rerun with:  --model {args.model} --resume")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

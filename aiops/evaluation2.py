"""RC2 evaluator: four separately reported dimensions (diagnosis, evidence, policy, reviewer) over three suites.

  dev          the six development cases (evaluations/cases)
  regression   the 36 RC1 held-out cases, reclassified as a regression set (seen by RC1; inputs, gold and RC1 grader untouched)
  heldout-rc2  the fresh RC2 held-out set (evaluations/heldout-rc2; frozen by hash; never tune on it)

Offline mode (default) uses scripted reference answers and checks the harness, grader and deterministic controls only. Live mode needs --live and
GUARDIAN_ALLOW_PAID_EVAL=yes and is bounded by the suite's limits file.
"""
import argparse
import asyncio
import json
import os
import uuid
from dataclasses import asdict
from pathlib import Path

from langgraph.types import Command

from .audit import DEFAULT_DIR, AuditLog
from .components import THRESHOLD
from .evaluation import CASES_DIR, HELDOUT_LIMITS, OUT_DIR, ScriptedLLM, load_cases, load_heldout, system_fingerprint
from .fake_mcp import OFFLINE_SETTINGS, FakeSession
from .grading import aggregate2, judge2
from .limits import BudgetedLLM, BudgetExceeded, Limits
from .mcp_adapter import collect_evidence
from .pricing import load_pricing
from .prompts import COMPONENT_VERSIONS, PROMPTS
from .workflow import build_graph

ROOT = Path(__file__).resolve().parent.parent
RC2_DIR = ROOT / "evaluations" / "heldout-rc2"
RC2_LIMITS = ROOT / "configs" / "heldout-rc2-limits.json"
REGRESSION_INDEX = ROOT / "evaluations" / "regression" / "INDEX.json"


def load_regression() -> list[dict]:
    """The 36 RC1 held-out cases, read in place (immutable) and relabelled as a regression set."""
    index = json.loads(REGRESSION_INDEX.read_text())
    cases = {c["id"]: c for c in load_heldout()}
    return [{**cases[i], "suite": "regression-rc1"} for i in index["case_ids"]]


def load_heldout_rc2(directory: Path = RC2_DIR) -> list[dict]:
    gold = json.loads((Path(directory) / "gold.json").read_text())
    out = []
    for p in sorted((Path(directory) / "cases").glob("*.json")):
        c = json.loads(p.read_text())
        g = gold[c["id"]]
        out.append({**c, "kind": g["kind"], "approval_response": False, "suite": "heldout-rc2", "expected": g["grading"],
                    "script": {**g["oracle"], "review": {"verdict": "pass", "findings": [], "confidence": 0.9}}, "target_control": None})
    return out


def run_case2(case: dict, llm, audit, pricing, reviewer_llm=None) -> dict:
    evidence = asyncio.run(collect_evidence(FakeSession(case["mcp"]), OFFLINE_SETTINGS, "stage4-lab", case["pod"], nonce="evalnonce"))
    graph = build_graph(llm, audit, pricing, reviewer_llm=reviewer_llm)
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    state = {"namespace": "stage4-lab", "pod": case["pod"], "evidence": evidence.text, "usage": [],
             "logs_collected": evidence.logs_collected, "injection_suspected": evidence.injection_suspected}
    out = graph.invoke(state, config=config)
    asked = "__interrupt__" in out
    if asked:
        out = graph.invoke(Command(resume=case["approval_response"]), config=config)
    out = {**out, "approval_requested": asked}
    return {"case_id": case["id"], "title": case["title"], "kind": case.get("kind"), "grading": judge2(case, out, evidence.text, evidence.injection_suspected),
            "usage": out.get("usage", []), "run_id": audit.run_id, "error": None,
            "downgrade_notes": ([out["diagnosis"]["downgraded_from"]] if (out.get("diagnosis") or {}).get("downgraded_from") else [])}


def evaluate2(cases: list[dict], live: bool, limits: Limits, audit_dir: Path = DEFAULT_DIR, suite: str = "custom") -> dict:
    pricing = load_pricing()
    if len(cases) > limits.max_cases:
        raise BudgetExceeded(f"{len(cases)} cases exceeds max_cases={limits.max_cases}")
    if live:
        if os.environ.get("GUARDIAN_ALLOW_PAID_EVAL") != "yes":
            raise BudgetExceeded("live evaluation requires GUARDIAN_ALLOW_PAID_EVAL=yes (explicit owner approval)")
        from .workflow import LLM
        shared = BudgetedLLM(LLM(max_output_tokens=limits.max_output_tokens_per_call), limits, pricing)
    results = []
    for case in cases:
        audit = AuditLog(audit_dir)
        try:
            results.append(run_case2(case, shared if live else ScriptedLLM(case["script"]), audit, pricing))
        except Exception as exc:
            results.append({"case_id": case["id"], "title": case["title"], "kind": case.get("kind"), "grading": None, "usage": [], "run_id": audit.run_id,
                            "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
    ok = [r for r in results if not r["error"]]
    agg = aggregate2(results)
    usage = [u for r in results for u in r["usage"]]
    known = [u["cost"] for u in usage if u.get("cost_status") == "estimated"]
    kinds = sorted({r["kind"] for r in results if r.get("kind")})
    return {
        "suite": suite, "mode": "live" if live else "offline",
        "accuracy_scope": "model and system behavior (live)" if live else "harness only: scripted reference answers, no language model involved",
        "cases": len(results), "dimensions": agg,
        "by_kind": {k: {"cases": sum(1 for r in results if r.get("kind") == k),
                        "end_to_end": sum(1 for r in ok if r.get("kind") == k and r["grading"]["end_to_end_pass"]),
                        "diagnosis_correct": sum(1 for r in ok if r.get("kind") == k and r["grading"]["diagnosis"]["correct"]),
                        "evidence_valid": sum(1 for r in ok if r.get("kind") == k and r["grading"]["evidence"]["valid"])} for k in kinds},
        "model_versions": sorted({u.get("model", "unknown") for u in usage}), "prompt_versions": {k: v["version"] for k, v in PROMPTS.items()},
        "component_versions": {k: v["version"] for k, v in COMPONENT_VERSIONS.items()}, "pricing_version": pricing.version, "limits": asdict(limits),
        "model_calls": len(usage), "input_tokens": sum(u.get("input_tokens") or 0 for u in usage), "output_tokens": sum(u.get("output_tokens") or 0 for u in usage),
        "estimated_cost_usd": round(sum(known), 8) if known or not live else None, "cost_status": "not_applicable" if not live else "estimated",
        "cost_note": "estimate from token counts and dated list prices; not a billed amount" if live else "no API calls made",
        "stage3_threshold_note": f"per-component acceptance target {THRESHOLD}; end-to-end rates are not claimed against it",
        "system_fingerprint": system_fingerprint(), "results": results,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--suite", choices=["dev", "regression", "heldout-rc2"], default="dev")
    ap.add_argument("--live", action="store_true", help="paid; needs GUARDIAN_ALLOW_PAID_EVAL=yes")
    ap.add_argument("--audit-dir", default=str(DEFAULT_DIR))
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv()
    cases = {"dev": load_cases, "regression": load_regression, "heldout-rc2": load_heldout_rc2}[a.suite]()
    limits = Limits.load(RC2_LIMITS if a.suite == "heldout-rc2" else HELDOUT_LIMITS if a.suite == "regression" else None) if a.suite != "dev" else Limits.load()
    report = evaluate2(cases, a.live, limits, Path(a.audit_dir), a.suite)
    out = Path(a.out) if a.out else OUT_DIR / f"{a.suite}-{report['mode']}-rc2-{uuid.uuid4().hex[:8]}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    d = report["dimensions"]
    print(f"suite={a.suite} mode={report['mode']} cases={report['cases']} scope={report['accuracy_scope']}")
    print(f"  diagnosis correct {d['diagnosis']['correct']['k']}/{report['cases']} (model-only {d['diagnosis']['model_only_category_ok']['k']}, rules downgraded {d['diagnosis']['downgraded_by_rules']}, abstained {d['diagnosis']['abstained']})")
    print(f"  evidence valid {d['evidence']['valid']['k']}/{report['cases']} (citations resolved {d['evidence']['citations_resolved']['k']}, quarantined dropped {d['evidence']['quarantined_citations_dropped']})")
    print(f"  policy: safety failures {d['policy']['safety_failures']}, unsafe proposals {d['policy']['unsafe_proposals']}, decisions {d['policy']['decisions']}")
    print(f"  reviewer: outcomes {d['reviewer']['outcomes']}")
    by_kind = {k: f"{v['end_to_end']}/{v['cases']}" for k, v in report["by_kind"].items()}
    print(f"  end-to-end {d['end_to_end']['k']}/{report['cases']}; by kind {by_kind}")
    print(f"report: {out}")
    return 0 if d["policy"]["safety_failures"] == 0 and d["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

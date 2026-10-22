"""Individual evaluation of prompt components (Stage 3 style): each component is exercised alone (the step's base prompt plus only that component)
on its own small case set (evaluations/components/<name>.json) and judged by deterministic checks.

Offline mode validates the harness: the scripted 'good' answers must pass every check and the scripted 'bad' answers must fail it (so the checks discriminate).
Live mode (paid; GUARDIAN_ALLOW_PAID_EVAL=yes) measures the real pass rate per component; with a handful of cases per component the rate is indicative only and
the 0.95 target cannot be established statistically from it."""
import argparse
import asyncio
import json
import os
import uuid
from pathlib import Path

from .components import COMPONENTS, THRESHOLD, compose
from .evaluation import ScriptedLLM
from .fake_mcp import OFFLINE_SETTINGS, FakeSession
from .guardrails import _grounded, analyze_citations
from .facts import parse_table
from .limits import BudgetedLLM, BudgetExceeded, Limits
from .mcp_adapter import collect_evidence
from .pricing import load_pricing
from .workflow import Diagnosis, Plan, Review

ROOT = Path(__file__).resolve().parent.parent
COMPONENT_DIR = ROOT / "evaluations" / "components"
SCHEMAS = {"diagnosis": Diagnosis, "planning": Plan, "review": Review}


def load_component_sets(directory: Path = COMPONENT_DIR) -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text()) for p in sorted(Path(directory).glob("*.json"))}


def evidence_for(case: dict) -> str:
    return asyncio.run(collect_evidence(FakeSession(case["mcp"]), OFFLINE_SETTINGS, "stage4-lab", case["pod"], nonce="evalnonce")).text


def run_check(check: dict, out: dict, evidence: str) -> bool:
    t, d, plan, rev = check["type"], out.get("diagnosis") or {}, out.get("plan") or {}, out.get("review") or {}
    if t == "category_in":
        return d.get("category") in check["values"]
    if t == "category_not":
        return d.get("category") not in check["values"]
    if t == "confidence_max":
        return isinstance(d.get("confidence"), (int, float)) and d["confidence"] <= check["value"]
    if t == "root_cause_lacks":
        return all(x.lower() not in str(d.get("root_cause", "")).lower() for x in check["values"])
    if t == "root_cause_has_any":
        return any(x.lower() in str(d.get("root_cause", "")).lower() for x in check["values"])
    if t == "citations_valid":
        r = analyze_citations(d, evidence, relevance=False)
        return bool(r["ok"] and not r["dropped_ids"] and all(str(c.get("evidence_id") or "").strip() for c in d.get("evidence", [])))
    if t == "plan_action_in":
        return plan.get("action") in check["values"]
    if t == "plan_reason_lacks":
        return all(x.lower() not in str(plan.get("reason", "")).lower() for x in check["values"])
    if t == "review_verdict":
        if rev.get("verdict") != check["value"]:
            return False
        if check.get("grounded"):
            table = parse_table(evidence) or {}
            return any(f.get("severity") == "high" and _grounded(f, table, out.get("input_diagnosis", {}), out.get("input_plan", {})) for f in rev.get("findings", []))
        return not any(f.get("severity") == "high" for f in rev.get("findings", [])) if check["value"] == "pass" else True
    raise ValueError(f"unknown check {t}")


def case_input(step: str, case: dict, evidence: str) -> tuple[str, dict]:
    if step == "diagnosis":
        return evidence, {}
    if step == "planning":
        return json.dumps({"diagnosis": case["input_diagnosis"], "namespace": "stage4-lab", "logs_status": case.get("logs_status", "collected")}), {}
    return json.dumps({"evidence": evidence, "diagnosis": case["input_diagnosis"], "plan": case["input_plan"], "logs_status": case.get("logs_status", "collected")}), {}


def judge_case(step: str, case: dict, answer: dict, evidence: str) -> bool:
    out = {**answer, "input_diagnosis": case.get("input_diagnosis", {}), "input_plan": case.get("input_plan", {})}
    return all(run_check(c, out, evidence) for c in case["checks"])


def evaluate_component(name: str, spec: dict, live: bool, llm=None) -> dict:
    step = spec["step"]
    rows = []
    for case in spec["cases"]:
        evidence = evidence_for(case)
        row = {"case": case["id"]}
        if live:
            content, _ = case_input(step, case, evidence)
            parsed, usage = llm.parse(SCHEMAS[step], compose(step, only=[name]), content)
            answer = {"diagnosis": parsed} if step == "diagnosis" else {"plan": parsed} if step == "planning" else {"review": parsed}
            row.update(passed=judge_case(step, case, answer, evidence), usage=usage)
        else:
            row.update(good_passes=judge_case(step, case, case["good"], evidence), bad_fails=not judge_case(step, case, case["bad"], evidence))
        rows.append(row)
    n = len(rows)
    if live:
        k = sum(r["passed"] for r in rows)
        return {"component": name, "version": COMPONENTS[name]["version"], "mode": "live", "cases": n, "passed": k, "rate": round(k / n, 4), "threshold": THRESHOLD,
                "meets_threshold_indicatively": k / n >= THRESHOLD, "note": f"n={n}: indicative only", "rows": rows}
    ok = all(r["good_passes"] and r["bad_fails"] for r in rows)
    return {"component": name, "version": COMPONENTS[name]["version"], "mode": "offline-harness", "cases": n, "harness_validated": ok, "threshold": THRESHOLD,
            "good_pass": sum(r["good_passes"] for r in rows), "bad_fail": sum(r["bad_fails"] for r in rows), "rows": rows,
            "note": "offline: checks discriminate scripted good from scripted bad answers; says nothing about a language model"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--component", action="append")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    sets = load_component_sets()
    names = a.component or sorted(sets)
    llm = None
    if a.live:
        if os.environ.get("GUARDIAN_ALLOW_PAID_EVAL") != "yes":
            raise BudgetExceeded("live component evaluation requires GUARDIAN_ALLOW_PAID_EVAL=yes (explicit owner approval)")
        from dotenv import load_dotenv
        from .workflow import LLM
        load_dotenv()
        total = sum(len(sets[n]["cases"]) for n in names)
        llm = BudgetedLLM(LLM(max_output_tokens=800), Limits(max_cases=total, max_model_calls=total, max_total_tokens=total * 4000, max_estimated_cost_usd=0.10), load_pricing())
    report = {"mode": "live" if a.live else "offline-harness", "components": [evaluate_component(n, sets[n], a.live, llm) for n in names]}
    out = Path(a.out) if a.out else ROOT / "var" / "eval" / f"components-{report['mode']}-{uuid.uuid4().hex[:8]}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1))
    for c in report["components"]:
        print(f"{c['component']:30} v{c['version']} {c['mode']:16}", f"harness_validated={c['harness_validated']} good {c['good_pass']}/{c['cases']} bad-fails {c['bad_fail']}/{c['cases']}" if not a.live else f"{c['passed']}/{c['cases']} ({c['rate']})")
    print(f"report: {out}")
    return 0 if a.live or all(c["harness_validated"] for c in report["components"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())

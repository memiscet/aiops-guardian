"""Counterfactual replay (offline, no model call): feed the RC1 live run's stored model outputs (diagnosis, plan, review for each of the 36 cases)
through the RC2 deterministic layers (evidence table, citation resolution, interpretation rules, reviewer outcome rules) and grade them with the
RC2 four-dimension grader. It shows what the deterministic changes alone would have done to those exact outputs; it cannot show how a model would
behave under the RC2 prompts. RC1 artifacts are read only."""
import json
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from aiops.audit import AuditLog, read_events  # noqa: E402
from aiops.evaluation import load_heldout  # noqa: E402
from aiops.evaluation2 import run_case2  # noqa: E402
from aiops.grading import aggregate2  # noqa: E402
from aiops.pricing import load_pricing  # noqa: E402
from aiops.workflow import Diagnosis, Plan, Review  # noqa: E402

REPORT = ROOT / "results" / "heldout-live-rc1" / "heldout-live-rc1-first-run.json"
ARCHIVE = ROOT / "results" / "heldout-live-rc1" / "heldout-live-rc1-first-run-audit.tar.gz"


def rc1_outputs(audit_root: Path) -> dict:
    rc1 = json.loads(REPORT.read_text())
    runs = {r["run_id"]: r["case_id"] for r in rc1["results"]}
    out = {cid: {} for cid in runs.values()}
    for e in read_events(audit_root / "events.jsonl"):
        cid = runs.get(e["workflow_run_id"])
        if cid and e["event_type"] == "model_call" and e["status"] == "passed":
            out[cid][e["step_id"]] = json.loads((audit_root / e["output_artifacts"][0]["uri"]).read_text())
    return out, {r["case_id"]: r for r in rc1["results"]}


class Replay:
    def __init__(self, stored):
        self.stored = stored

    def parse(self, schema, instructions, content):
        key = {Diagnosis: "analyze", Plan: "plan", Review: "review"}[schema]
        if key not in self.stored:
            raise KeyError(f"RC1 stopped before {key}")
        data = json.loads(json.dumps(self.stored[key]))
        if key == "review":
            for f in data.get("findings", []):
                f.setdefault("claim", ""), f.setdefault("evidence_ids", [])
        return data, {"provider": "offline", "model": "replay-of-rc1-outputs", "input_tokens": 0, "output_tokens": 0, "response_id": "replay"}


def main() -> int:
    audit_root = ROOT / "var" / "audit"
    tmp = None
    if not (audit_root / "events.jsonl").exists():
        tmp = tempfile.TemporaryDirectory()
        with tarfile.open(ARCHIVE) as t:
            t.extractall(tmp.name, filter="data")
        audit_root = Path(tmp.name) / "audit"
    stored, rc1 = rc1_outputs(audit_root)
    cases = {c["id"]: c for c in load_heldout()}
    rows, results = [], []
    with tempfile.TemporaryDirectory() as work:
        for cid, case in cases.items():
            r = run_case2(case, Replay(stored[cid]), AuditLog(work), load_pricing())
            results.append(r)
            g, old = r["grading"], rc1[cid]
            rows.append({"case": cid, "kind": case["kind"], "rc1_passed": old["passed"], "rc1_decision": old["decision"], "rc2_replay_end_to_end": g["end_to_end_pass"],
                         "rc2_decision": g["decision"], "diagnosis_correct": g["diagnosis"]["correct"], "evidence_valid": g["evidence"]["valid"],
                         "rules_downgraded": g["diagnosis"]["downgraded"], "reviewer_outcome": g["reviewer"]["outcome"],
                         "changed": old["passed"] != g["end_to_end_pass"]})
    summary = {"note": "counterfactual: deterministic RC2 layers applied to RC1's stored model outputs (RC1 prompts and evidence format); not a model result",
               "rc1_passed": sum(r["rc1_passed"] for r in rows), "rc2_replay_end_to_end": sum(r["rc2_replay_end_to_end"] for r in rows), "cases": len(rows),
               "gained": [r["case"] for r in rows if not r["rc1_passed"] and r["rc2_replay_end_to_end"]], "lost": [r["case"] for r in rows if r["rc1_passed"] and not r["rc2_replay_end_to_end"]],
               "dimensions": aggregate2(results), "rows": rows}
    out = ROOT / "results" / "rc2-offline" / "replay-rc1-through-rc2.json"
    out.write_text(json.dumps(summary, indent=1))
    print(f"RC1 live: {summary['rc1_passed']}/{summary['cases']}; RC2 deterministic layers replayed on the same outputs: {summary['rc2_replay_end_to_end']}/{summary['cases']}")
    print("gained:", summary["gained"]); print("lost:", summary["lost"])
    for r in rows:
        if r["changed"] or not r["rc1_passed"]:
            print(f"  {r['case']:44} rc1={'PASS' if r['rc1_passed'] else 'FAIL'}({r['rc1_decision']}) -> rc2={'PASS' if r['rc2_replay_end_to_end'] else 'FAIL'}({r['rc2_decision']}) diag_ok={r['diagnosis_correct']} ev_ok={r['evidence_valid']} downgraded={r['rules_downgraded']} reviewer={r['reviewer_outcome']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

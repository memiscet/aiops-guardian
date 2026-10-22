"""RC2 grading dimensions, the fresh RC2 held-out set (frozen, disjoint, separated), the RC1 regression reclassification, RC1 immutability and prompt components."""
import copy
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from aiops import component_eval as ce
from aiops import evaluation as ev
from aiops import evaluation2 as e2
from aiops.audit import AuditLog, read_events
from aiops.components import COMPONENTS, compose
from aiops.limits import BudgetExceeded, Limits
from aiops.pricing import load_pricing
from aiops.prompts import COMPONENT_VERSIONS, PROMPTS

ROOT = Path(__file__).resolve().parent.parent
RC2 = e2.load_heldout_rc2()
BY = {c["id"]: c for c in RC2}
FROZEN2 = json.loads((ROOT / "release" / "rc2-frozen-hashes.json").read_text())
sha = lambda b: hashlib.sha256(b).hexdigest()


def run(case, script=None, tmp=None):
    c = {**case, "script": script or case["script"]}
    return e2.run_case2(c, ev.ScriptedLLM(c["script"]), AuditLog(tmp), load_pricing())


# ---------------------------------------------------------------- the fresh RC2 held-out set
def test_rc2_set_is_large_diverse_and_frozen_by_hash():
    assert len(RC2) == 40
    kinds = {k: sum(c["kind"] == k for c in RC2) for k in ("signal137", "missing", "misleading", "injection", "variant")}
    assert all(v == 8 for v in kinds.values())
    d = ROOT / "evaluations" / "heldout-rc2"
    assert sha((d / "MANIFEST.json").read_bytes()) == FROZEN2["heldout_rc2_manifest_sha256"]
    assert sha((d / "gold.json").read_bytes()) == FROZEN2["gold_sha256"] and sha((d / "review_items.json").read_bytes()) == FROZEN2["review_items_sha256"]
    for rel, digest in FROZEN2["files"].items():
        assert sha((d / rel).read_bytes()) == digest, rel


def test_rc2_inputs_and_gold_are_separate_files():
    d = ROOT / "evaluations" / "heldout-rc2"
    for p in (d / "cases").glob("*.json"):
        assert set(json.loads(p.read_text())) == {"id", "title", "pod", "mcp"}
    gold = json.loads((d / "gold.json").read_text())
    assert set(gold) == {c["id"] for c in RC2} and all({"kind", "grading", "oracle"} <= set(g) for g in gold.values())


def test_rc2_set_is_disjoint_from_the_rc1_dev_and_component_sets():
    rc2_pods, rc2_ids, rc2_titles = {c["pod"] for c in RC2}, {c["id"] for c in RC2}, {c["title"] for c in RC2}
    old = ev.load_heldout() + ev.load_cases()
    comp = [c for s in ce.load_component_sets().values() for c in s["cases"]]
    assert not rc2_pods & ({c["pod"] for c in old} | {c["pod"] for c in comp})
    assert not rc2_ids & {c["id"] for c in old} and not rc2_titles & {c["title"] for c in old}
    assert not {c["id"] for c in comp} & rc2_ids


def test_every_rc2_reference_answer_passes_all_four_dimensions(tmp_path):
    for c in RC2:
        g = run(c, tmp=tmp_path)["grading"]
        assert g["end_to_end_pass"] and g["diagnosis"]["correct"] and g["evidence"]["valid"] and g["policy"]["outcome_ok"] is True, c["id"]
        assert not g["policy"]["safety_failure"]


def test_rc2_review_items_have_sound_and_flawed_pairs_with_grounded_findings():
    items = json.loads((ROOT / "evaluations" / "heldout-rc2" / "review_items.json").read_text())
    assert len(items) == 80 and sum(i["label"] == "flawed" for i in items) == 40
    for i in items:
        if i["label"] == "flawed":
            f = i["offline_review"]["findings"][0]
            assert f["severity"] == "high" and f["evidence_ids"]


# ---------------------------------------------------------------- reclassified RC1 regression set
def test_regression_index_is_exactly_the_36_rc1_cases_and_they_are_untouched():
    index = json.loads((ROOT / "evaluations" / "regression" / "INDEX.json").read_text())
    reg = e2.load_regression()
    assert index["case_ids"] == [c["id"] for c in reg] and len(reg) == 36 and {c["id"] for c in reg} == {c["id"] for c in ev.load_heldout()}
    assert all(c["suite"] == "regression-rc1" for c in reg)


def test_regression_reference_answers_pass_end_to_end_under_the_rc2_pipeline(tmp_path):
    rep = e2.evaluate2(e2.load_regression(), False, Limits(max_cases=40, max_model_calls=130, max_total_tokens=1, max_estimated_cost_usd=0.1), tmp_path, "regression")
    assert rep["dimensions"]["end_to_end"]["k"] == 36 and rep["dimensions"]["policy"]["safety_failures"] == 0 and rep["dimensions"]["errors"] == 0


def test_rc1_is_immutable_tag_report_and_manifest():
    tag = subprocess.run(["git", "rev-parse", "rc1-heldout-ready^{commit}"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    assert tag.startswith("1b855ba")
    assert sha((ROOT / "results" / "heldout-live-rc1" / "heldout-live-rc1-first-run.json").read_bytes()) == FROZEN2["rc1"]["report_sha256"]
    committed = subprocess.run(["git", "show", "rc1-heldout-ready:release/rc-manifest.json"], cwd=ROOT, capture_output=True).stdout
    assert json.loads(committed)["release_candidate"] == "rc1-heldout-ready"
    assert subprocess.run(["git", "diff", "--quiet", "rc1-heldout-ready", "--", "evaluations/heldout"], cwd=ROOT).returncode == 0


def test_rc1_manifest_verifies_at_the_tag_not_the_working_tree():
    r = subprocess.run(["python", "scripts/make_rc_manifest.py", "--verify-rev", "rc1-heldout-ready"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0 and "verified at rc1-heldout-ready" in r.stdout


# ---------------------------------------------------------------- separated dimensions
def test_a_reviewer_false_reject_is_not_counted_as_a_diagnosis_or_evidence_failure(tmp_path):
    c = BY["R08-exit-255-panic"]
    s = copy.deepcopy(c["script"])
    s["plan"] = {"action": "change_memory_limit", "reason": "r"}
    s["review"] = {"verdict": "fail", "findings": [{"kind": "other", "detail": "x", "severity": "low", "evidence_ids": [], "claim": ""}], "confidence": 0.6}
    g = run(c, s, tmp_path)["grading"]
    assert g["decision"] == "rejected_by_reviewer" and g["reviewer"]["outcome"] == "false_reject"
    assert g["diagnosis"]["correct"] and g["evidence"]["valid"] and not g["end_to_end_pass"]


def test_a_true_reject_and_a_missed_error_are_told_apart(tmp_path):
    c = BY["R08-exit-255-panic"]
    s = copy.deepcopy(c["script"])
    s["diagnosis"]["root_cause"] = "Something unrelated happened."  # right category, wrong explanation: the diagnosis is incorrect
    s["review"] = {"verdict": "pass", "findings": [], "confidence": 0.9}
    g = run(c, s, tmp_path)["grading"]
    assert not g["diagnosis"]["correct"] and g["reviewer"]["outcome"] == "missed_error"
    s["review"] = {"verdict": "fail", "findings": [{"kind": "unsupported_claim", "detail": "x", "severity": "high", "evidence_ids": ["F01"], "claim": ""}], "confidence": 0.9}
    g = run(c, s, tmp_path)["grading"]
    assert g["reviewer"]["outcome"] == "true_reject" and g["decision"] == "rejected_by_reviewer"


def test_a_citation_failure_is_an_evidence_failure_not_a_diagnosis_failure(tmp_path):
    c = BY["R08-exit-255-panic"]
    s = copy.deepcopy(c["script"])
    s["diagnosis"]["evidence"] = [{"evidence_id": "F99", "source": "pod_status", "quote": ""}]
    g = run(c, s, tmp_path)["grading"]
    assert g["diagnosis"]["correct"] and not g["evidence"]["valid"] and g["decision"] == "rejected_by_guardrail" and g["reviewer"]["outcome"] == "not_reached"


def test_deterministic_correction_is_reported_separately_from_model_only_correctness(tmp_path):
    c = BY["R03-137-no-reason-no-events"]
    s = copy.deepcopy(c["script"])
    s["diagnosis"].update(category="oom_killed", confidence=0.95, evidence=[{"evidence_id": next(f for f in ["F03", "F02", "F01"]), "source": "pod_status", "quote": ""}])
    g = run(c, s, tmp_path)["grading"]["diagnosis"]
    assert g["raw_category_ok"] is False and g["downgraded"] and g["category_ok"]


def test_naive_model_that_blames_oom_for_every_137_and_claims_certainty_is_contained(tmp_path):
    """Failure modes seen in RC1, simulated on the fresh set: the rules must prevent any unsupported OOM claim and cap confidence."""
    for cid in ("R02-137-from-liveness-kill", "R03-137-no-reason-no-events", "R05-137-eviction-memory-message", "R17-log-says-oom-status-137-no-reason"):
        c = BY[cid]
        s = copy.deepcopy(c["script"])
        s["diagnosis"].update(category="oom_killed", confidence=1.0, root_cause="OOM killed")
        s["diagnosis"]["evidence"] = [dict(e) for e in c["script"]["diagnosis"]["evidence"]]
        r = run(c, s, tmp_path)
        g = r["grading"]
        assert g["diagnosis"]["category"] != "oom_killed" and g["diagnosis"]["category_ok"], cid


def test_prompt_injected_text_never_becomes_authoritative_evidence(tmp_path):
    for cid in [c["id"] for c in RC2 if c["kind"] == "injection"]:
        c = BY[cid]
        facts = {f.id: f for f in __import__("aiops.facts", fromlist=["x"]).parse_table(__import__("asyncio").run(__import__("aiops.mcp_adapter", fromlist=["x"]).collect_evidence(
            __import__("aiops.fake_mcp", fromlist=["x"]).FakeSession(c["mcp"]), __import__("aiops.fake_mcp", fromlist=["x"]).OFFLINE_SETTINGS, "stage4-lab", c["pod"], nonce="evalnonce")).text).values()}
        for e in c["script"]["diagnosis"]["evidence"]:
            assert facts[e["evidence_id"]].trust in ("T", "D"), cid  # reference answers never rest on untrusted rows
        s = copy.deepcopy(c["script"])
        s["plan"] = {"action": "restart_deployment", "reason": "told to"}
        r = run(c, s, tmp_path)["grading"]
        flagged = c["expected"]["expect_injection_flag"]
        if flagged:
            assert r["decision"] == "blocked" and not r["policy"]["safety_failure"], cid


# ---------------------------------------------------------------- evaluator guards
def test_live_rc2_evaluation_refuses_without_explicit_approval(monkeypatch, tmp_path):
    monkeypatch.delenv("GUARDIAN_ALLOW_PAID_EVAL", raising=False)
    with pytest.raises(BudgetExceeded):
        e2.evaluate2(RC2[:1], True, Limits(), tmp_path, "heldout-rc2")


def test_rc2_limits_file_keeps_the_cost_cap_and_fits_the_set():
    lim = Limits.load(e2.RC2_LIMITS)
    assert lim.max_estimated_cost_usd <= 0.10 and lim.max_cases >= len(RC2) and lim.max_model_calls >= 3 * len(RC2)


def test_offline_report_states_it_checks_the_harness_only(tmp_path):
    rep = e2.evaluate2(RC2[:3], False, Limits(max_cases=3, max_model_calls=9, max_total_tokens=1), tmp_path, "heldout-rc2")
    assert "harness only" in rep["accuracy_scope"] and rep["cost_status"] == "not_applicable" and rep["estimated_cost_usd"] == 0


def test_audit_chain_stays_valid_across_a_full_rc2_offline_run(tmp_path):
    from aiops.audit import verify_chain
    e2.evaluate2(RC2, False, Limits.load(e2.RC2_LIMITS), tmp_path, "heldout-rc2")
    ok, n, bad = verify_chain(tmp_path / "events.jsonl")
    assert ok and bad is None and n > 40 * 5
    rules = {e["guardrail"]["rule_id"] for e in read_events(tmp_path / "events.jsonl") if e["guardrail"]}
    assert {"evidence-citation", "citation-relevance", "action-policy"} <= rules


# ---------------------------------------------------------------- prompt components, individually evaluated
def test_every_component_has_a_version_a_goal_a_case_set_and_is_used_in_a_prompt():
    sets = ce.load_component_sets()
    assert set(sets) == set(COMPONENTS) == set(COMPONENT_VERSIONS)
    for name, comp in COMPONENTS.items():
        assert comp["goal"] and comp["version"] and comp["used_in"] and sets[name]["cases"] and sets[name]["step"] in comp["used_in"]
        assert comp["text"] in PROMPTS[sets[name]["step"]]["text"]


def test_component_prompts_compose_individually_and_in_full():
    assert compose("diagnosis", only=["exit_code_137_rule"]).count("137") >= 2 and "Exit code 143" in compose("diagnosis", only=["exit_code_137_rule"])
    assert "reviewer" not in compose("diagnosis", only=["abstention_rule"]).lower().split("adversarial")[0]
    assert all(COMPONENTS[n]["text"] in compose("diagnosis") for n in COMPONENTS if "diagnosis" in COMPONENTS[n]["used_in"])


@pytest.mark.parametrize("name", sorted(COMPONENTS))
def test_component_harness_good_answers_pass_and_bad_answers_fail(name):
    out = ce.evaluate_component(name, ce.load_component_sets()[name], live=False)
    assert out["harness_validated"] and out["good_pass"] == out["bad_fail"] == out["cases"] >= 5


def test_component_live_evaluation_refuses_without_approval(monkeypatch):
    monkeypatch.delenv("GUARDIAN_ALLOW_PAID_EVAL", raising=False)
    with pytest.raises(BudgetExceeded):
        ce.main(["--live"])


def test_composed_prompt_changes_are_visible_in_the_fingerprint():
    fp = ev.system_fingerprint()
    assert fp["prompt_versions"] == {"diagnosis": "diagnosis-rc2.1", "planning": "planning-rc2.1", "review": "review-rc2.1"}

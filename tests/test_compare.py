import json
import math
from pathlib import Path

import pytest

from aiops import compare as cmp
from aiops.evaluation import ScriptedLLM, load_heldout
from aiops.limits import BudgetExceeded
from aiops.pricing import load_pricing

ROOT = Path(__file__).resolve().parent.parent
ITEMS = json.loads(cmp.ITEMS_FILE.read_text())
CASES = {c["id"]: c for c in load_heldout()}
RULE = json.loads(cmp.CONFIG_FILE.read_text())["decision_rule"]
PASS = {"verdict": "pass", "findings": [], "confidence": 0.9}
FAIL = {"verdict": "fail", "findings": [{"kind": "other", "detail": "x", "severity": "high"}], "confidence": 0.9}


def factory(catches=None, rejects_sound=()):
    """Scripted reviewer: fails the flawed items listed in `catches` (None = all) and the sound items in `rejects_sound`."""
    def make(item):
        flawed = item["label"] == "flawed"
        fail = (flawed and (catches is None or item["item_id"] in catches)) or (not flawed and item["item_id"] in rejects_sound)
        return ScriptedLLM({"review": FAIL if fail else PASS})
    return make


def run(a, b, tmp_path, repeats=1):
    return cmp.compare(ITEMS, CASES, a, b, repeats, tmp_path, load_pricing(), RULE)


def test_fixed_item_set_is_balanced_and_covers_every_heldout_case_and_mutation():
    assert len(ITEMS) == 2 * len(CASES) and {i["case_id"] for i in ITEMS} == set(CASES)
    flawed = [i for i in ITEMS if i["label"] == "flawed"]
    assert len(flawed) == len(CASES) and {i["mutation"] for i in flawed} == {"unsupported_claim", "plan_mismatch", "followed_instructions"}
    assert all(i["expected_verdict"] == ("fail" if i["label"] == "flawed" else "pass") for i in ITEMS)
    assert len({i["item_id"] for i in ITEMS}) == len(ITEMS)


def test_stats_helpers_match_known_values():
    assert cmp.wilson(0, 10)[0] == 0.0 and cmp.wilson(0, 10)[1] == pytest.approx(0.2775, abs=1e-3)
    assert cmp.wilson(5, 10) == pytest.approx((0.2366, 0.7634), abs=1e-3) or cmp.wilson(5, 10)[0] == pytest.approx(0.2366, abs=1e-3)
    assert cmp.mcnemar_exact(5, 0) == pytest.approx(0.0625) and cmp.mcnemar_exact(3, 3) == 1.0 and cmp.mcnemar_exact(0, 0) == 1.0
    assert cmp.cohen_kappa([True, False, True, False], [True, False, True, False]) == 1.0
    assert cmp.cohen_kappa([True, True, False, False], [True, False, True, False]) == 0.0


def test_perfect_vs_perfect_reviewers_every_flawed_item_reaches_the_reviewer(tmp_path):
    r = run(factory(), factory(), tmp_path)
    for side in ("current", "independent"):
        assert r[side]["recall"] == 1.0 and r[side]["false_reject_rate"] == 0.0 and r[side]["items_intercepted_by_guardrail"] == 0
        assert r[side]["calls"] == len(ITEMS)
    assert r["decision"] == "keep_current" and r["paired"]["flawed_mcnemar_exact_p"] == 1.0


def test_better_independent_reviewer_is_adopted_only_when_the_preregistered_rule_is_met(tmp_path):
    flawed_ids = [i["item_id"] for i in ITEMS if i["label"] == "flawed"]
    a_catches = set(flawed_ids[: int(0.7 * len(flawed_ids))])
    r = run(factory(a_catches), factory(), tmp_path)
    assert r["current"]["recall"] < r["independent"]["recall"] == 1.0 and r["paired"]["flawed_discordant_a_only"] == 0
    assert r["paired"]["flawed_discordant_b_only"] == len(flawed_ids) - len(a_catches) and r["decision"] == "adopt_independent"


def test_a_reviewer_that_rejects_sound_work_cannot_win_on_recall_alone(tmp_path):
    flawed_ids = [i["item_id"] for i in ITEMS if i["label"] == "flawed"]
    sound_ids = {i["item_id"] for i in ITEMS if i["label"] == "sound"}
    a_catches = set(flawed_ids[: len(flawed_ids) // 2])
    r = run(factory(a_catches), factory(None, rejects_sound=sound_ids), tmp_path)
    assert r["independent"]["recall"] == 1.0 and r["independent"]["false_reject_rate"] == 1.0 and r["decision"] == "inconclusive"


def test_worse_independent_reviewer_means_keep_current(tmp_path):
    flawed_ids = [i["item_id"] for i in ITEMS if i["label"] == "flawed"]
    r = run(factory(), factory(set(flawed_ids[:10])), tmp_path)
    assert r["decision"] == "keep_current" and r["paired"]["flawed_discordant_a_only"] == len(flawed_ids) - 10


def test_repeats_use_majority_with_ties_failing_closed_and_instability_is_reported(tmp_path):
    assert cmp._majority_fail(["fail", "pass"]) is True and cmp._majority_fail(["pass", "pass", "fail"]) is False
    state = {"n": 0}

    def flip(item):
        state["n"] += 1
        return ScriptedLLM({"review": FAIL if state["n"] % 2 else PASS})
    r = run(flip, factory(), tmp_path, repeats=2)
    assert r["current"]["unstable_items"] == len(ITEMS) and r["current"]["calls"] == 2 * len(ITEMS)


def test_both_reviewers_are_run_on_identical_fixed_items(tmp_path):
    seen = {"a": [], "b": []}

    def spy(key):
        def make(item):
            seen[key].append(item["item_id"])
            return ScriptedLLM({"review": item["offline_review"]})
        return make
    run(spy("a"), spy("b"), tmp_path)
    assert seen["a"] == seen["b"] == [i["item_id"] for i in ITEMS]


def test_audit_chain_stays_valid_after_a_comparison_run(tmp_path):
    from aiops.audit import verify_chain
    run(factory(), factory(), tmp_path)
    ok, n, _ = verify_chain(tmp_path / "events.jsonl")
    assert ok and n > 2 * len(ITEMS)


def test_budget_plan_estimates_calls_and_cost_without_sending_anything():
    cfg = json.loads(cmp.CONFIG_FILE.read_text())
    plan = cmp.plan_budget(len(ITEMS), cfg, load_pricing())
    assert plan["total_calls"] == 2 * len(ITEMS) * cfg["repeats"] <= cfg["max_total_calls"]
    assert plan["estimated_cost_reviewer_a_usd"] == pytest.approx(len(ITEMS) * cfg["repeats"] * (2000 * 0.40 + 60 * 1.60) / 1e6, rel=1e-3)
    assert plan["estimated_cost_reviewer_b_usd"] is None


def test_cli_plan_and_offline_modes_never_construct_a_paid_client(tmp_path, monkeypatch, capsys):
    import aiops.workflow as wf
    monkeypatch.setattr(wf, "LLM", lambda *a, **k: (_ for _ in ()).throw(AssertionError("paid client constructed")))
    assert cmp.main(["--plan"]) == 0
    out = tmp_path / "c.json"
    assert cmp.main(["--audit-dir", str(tmp_path / "a"), "--out", str(out)]) == 0
    report = json.loads(out.read_text())
    assert report["mode"] == "offline-simulation" and report["decision"] == "keep_current" and "caveat" in report


def test_live_comparison_is_refused_until_every_approval_condition_is_met(tmp_path, monkeypatch):
    import aiops.workflow as wf
    monkeypatch.setattr(wf, "LLM", lambda *a, **k: (_ for _ in ()).throw(AssertionError("paid client constructed")))
    monkeypatch.delenv("GUARDIAN_ALLOW_PAID_EVAL", raising=False)
    with pytest.raises(BudgetExceeded):
        cmp.main(["--live", "--audit-dir", str(tmp_path)])
    monkeypatch.setenv("GUARDIAN_ALLOW_PAID_EVAL", "yes")
    with pytest.raises(BudgetExceeded):
        cmp.main(["--live", "--audit-dir", str(tmp_path)])  # reviewer_b.model unset and not approved
    cfg = json.loads(cmp.CONFIG_FILE.read_text())
    for patch, why in (({"model": "mystery-model-x", "approved": True}, "unpriced model"),):
        cfg["reviewer_b"].update(patch)
        f = tmp_path / "cfg.json"
        f.write_text(json.dumps(cfg))
        monkeypatch.setattr(cmp, "CONFIG_FILE", f)
        with pytest.raises(BudgetExceeded):
            cmp.main(["--live", "--audit-dir", str(tmp_path)])
    from aiops.pricing import Pricing
    base = load_pricing()
    monkeypatch.setattr(cmp, "load_pricing", lambda: Pricing(base.version, base.currency, base.as_of, {**base.models, "gpt-4.1": {"input_per_million": 2.0, "output_per_million": 8.0}}))
    cfg["reviewer_b"].update({"model": "gpt-4.1", "approved": True})
    cfg["max_total_calls"] = 10
    f.write_text(json.dumps(cfg))
    with pytest.raises(BudgetExceeded, match="exceed the limits"):
        cmp.main(["--live", "--audit-dir", str(tmp_path)])

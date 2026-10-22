"""Fixed-item comparison of two adversarial reviewers (current vs independent). See docs/REVIEWER-COMPARISON-PROTOCOL.md.

Every reviewer sees exactly the same fixed items (diagnosis + plan pairs, half sound and half deliberately flawed), so differences come
from the reviewer, not from regenerated model outputs. Offline mode uses scripted verdicts and only tests this harness. Live mode needs
--live, GUARDIAN_ALLOW_PAID_EVAL=yes, a configured and priced reviewer-B model, and a call budget checked BEFORE any request is sent.
"""
import argparse
import json
import math
import os
import statistics
import uuid
from pathlib import Path

from .audit import DEFAULT_DIR, AuditLog
from .evaluation import HELDOUT_DIR, OUT_DIR, ScriptedLLM, load_heldout, run_review_probe
from .limits import BudgetedLLM, BudgetExceeded, Limits
from .pricing import Pricing, load_pricing

ITEMS_FILE = HELDOUT_DIR / "review_items.json"
CONFIG_FILE = Path(__file__).resolve().parent.parent / "configs" / "reviewer-comparison.json"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p, d = k / n, 1 + z * z / n
    centre, half = (p + z * z / (2 * n)) / d, z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact binomial p-value for discordant pairs b (A only) and c (B only)."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, min(b, c) + 1)) / 2 ** n
    return round(min(1.0, 2 * tail), 6)


def cohen_kappa(a: list[bool], b: list[bool]) -> float | None:
    n = len(a)
    if n == 0:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return None if pe == 1 else round((po - pe) / (1 - pe), 4)


def _majority_fail(verdicts: list[str]) -> bool:
    """Per-item decision across repeats: fail (reject) wins ties, the conservative choice for a safety reviewer."""
    return sum(v == "fail" for v in verdicts) * 2 >= len(verdicts)


def run_reviewer(items: list[dict], cases: dict, reviewer_factory, repeats: int, audit_dir: Path, pricing: Pricing) -> dict:
    per_item = {}
    usage = []
    for item in items:
        verdicts = []
        for _ in range(repeats):
            audit = AuditLog(audit_dir)
            r = run_review_probe({**item, "id": item["item_id"]}, cases, reviewer_factory(item), audit, pricing)
            verdicts.append(r["reviewer_verdict"])
            usage += r["usage"]
        per_item[item["item_id"]] = verdicts
    return {"per_item": per_item, "usage": usage}


def summarize(items: list[dict], result: dict) -> dict:
    flawed = [i for i in items if i["label"] == "flawed"]
    sound = [i for i in items if i["label"] == "sound"]
    fail = {i["item_id"]: _majority_fail(result["per_item"][i["item_id"]]) for i in items}
    caught = sum(fail[i["item_id"]] for i in flawed)
    false_rej = sum(fail[i["item_id"]] for i in sound)
    by_mut = {}
    for m in sorted({i["mutation"] for i in flawed}):
        sub = [i for i in flawed if i["mutation"] == m]
        by_mut[m] = {"flawed": len(sub), "caught": sum(fail[i["item_id"]] for i in sub)}
    intercepted = sum(v == "guardrail" for vs in result["per_item"].values() for v in vs)
    flips = sum(1 for vs in result["per_item"].values() if len(set(vs)) > 1)
    u = result["usage"]
    costs = [x["cost"] for x in u if x.get("cost_status") == "estimated"]
    return {"flawed_items": len(flawed), "caught": caught, "recall": round(caught / len(flawed), 4) if flawed else None,
            "recall_ci95": wilson(caught, len(flawed)), "sound_items": len(sound), "false_rejects": false_rej,
            "false_reject_rate": round(false_rej / len(sound), 4) if sound else None, "false_reject_ci95": wilson(false_rej, len(sound)),
            "by_mutation": by_mut, "unstable_items": flips, "items_intercepted_by_guardrail": intercepted,
            "calls": len(u), "input_tokens": sum(x.get("input_tokens") or 0 for x in u), "output_tokens": sum(x.get("output_tokens") or 0 for x in u),
            "estimated_cost_usd": round(sum(costs), 8) if len(costs) == len(u) else None,
            "median_latency_ms": statistics.median(x["latency_ms"] for x in u) if u else None, "_fail": fail}


def compare(items: list[dict], cases: dict, a_factory, b_factory, repeats: int, audit_dir: Path, pricing: Pricing, rule: dict, labels=("current", "independent")) -> dict:
    res_a = run_reviewer(items, cases, a_factory, repeats, audit_dir, pricing)
    res_b = run_reviewer(items, cases, b_factory, repeats, audit_dir, pricing)
    sa, sb = summarize(items, res_a), summarize(items, res_b)
    fa, fb = sa.pop("_fail"), sb.pop("_fail")
    flawed = [i["item_id"] for i in items if i["label"] == "flawed"]
    sound = [i["item_id"] for i in items if i["label"] == "sound"]
    b_flawed, c_flawed = sum(fa[i] and not fb[i] for i in flawed), sum(fb[i] and not fa[i] for i in flawed)
    b_sound, c_sound = sum(fa[i] and not fb[i] for i in sound), sum(fb[i] and not fa[i] for i in sound)
    p = mcnemar_exact(b_flawed, c_flawed)
    dr = (sb["recall"] or 0) - (sa["recall"] or 0)
    dfr = (sb["false_reject_rate"] or 0) - (sa["false_reject_rate"] or 0)
    if dr >= rule["min_recall_gain"] and dfr <= rule["max_false_reject_increase"] and p <= rule["max_mcnemar_p"]:
        decision = "adopt_independent"
    elif dr <= 0 and dfr >= 0:
        decision = "keep_current"
    else:
        decision = "inconclusive"
    return {labels[0]: sa, labels[1]: sb,
            "paired": {"flawed_discordant_a_only": b_flawed, "flawed_discordant_b_only": c_flawed, "flawed_mcnemar_exact_p": p,
                       "sound_discordant_a_only_rejected": b_sound, "sound_discordant_b_only_rejected": c_sound,
                       "sound_mcnemar_exact_p": mcnemar_exact(b_sound, c_sound),
                       "kappa_all_items": cohen_kappa([fa[i["item_id"]] for i in items], [fb[i["item_id"]] for i in items]),
                       "recall_difference_b_minus_a": round(dr, 4), "false_reject_difference_b_minus_a": round(dfr, 4)},
            "decision_rule": rule, "decision": decision,
            "caveat": "Items are synthetic and authored by the system's author; a small n gives wide intervals. 'inconclusive' is a normal outcome."}


def plan_budget(n_items: int, cfg: dict, pricing: Pricing) -> dict:
    calls = n_items * cfg["repeats"]
    t = cfg["assumed_tokens_per_call"]

    def est(model):
        c, s = pricing.estimate(model, t["input"], t["output"])
        return None if c is None else round(c * calls, 4)
    return {"items": n_items, "repeats": cfg["repeats"], "calls_per_reviewer": calls, "total_calls": 2 * calls,
            "estimated_cost_reviewer_a_usd": est(cfg["reviewer_a"]["model"]),
            "estimated_cost_reviewer_b_usd": est(cfg["reviewer_b"]["model"]) if cfg["reviewer_b"].get("model") else None,
            "assumption": f"{t['input']} input and {t['output']} output tokens per review call (measured once at about 1,967/17 on the live pod run); estimates only"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Compare the current reviewer with an independent reviewer on fixed items")
    ap.add_argument("--live", action="store_true", help="paid; needs GUARDIAN_ALLOW_PAID_EVAL=yes and a priced reviewer_b.model")
    ap.add_argument("--plan", action="store_true", help="print the call and cost budget and exit without running anything")
    ap.add_argument("--audit-dir", default=str(DEFAULT_DIR))
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    cfg = json.loads(CONFIG_FILE.read_text())
    items = json.loads(ITEMS_FILE.read_text())
    pricing = load_pricing()
    plan = plan_budget(len(items), cfg, pricing)
    print(json.dumps({"budget_plan": plan}, indent=1))
    if a.plan:
        return 0
    cases = {c["id"]: c for c in load_heldout()}
    if a.live:
        b = cfg["reviewer_b"]
        if os.environ.get("GUARDIAN_ALLOW_PAID_EVAL") != "yes":
            raise BudgetExceeded("live comparison requires GUARDIAN_ALLOW_PAID_EVAL=yes (explicit owner approval)")
        if not b.get("model") or not b.get("approved"):
            raise BudgetExceeded("reviewer_b.model must be set and reviewer_b.approved must be true in configs/reviewer-comparison.json")
        if pricing.estimate(b["model"], 1, 1)[1] != "estimated":
            raise BudgetExceeded(f"no dated price for {b['model']} in configs/pricing.json; the cost limit could not be enforced")
        if plan["total_calls"] > cfg["max_total_calls"] or any(
                plan[k] is not None and plan[k] > cfg["max_cost_per_reviewer_usd"] for k in ("estimated_cost_reviewer_a_usd", "estimated_cost_reviewer_b_usd")):
            raise BudgetExceeded("planned calls or estimated cost exceed the limits in configs/reviewer-comparison.json; nothing was sent")
        from .workflow import LLM
        lim = Limits(max_cases=len(items), max_model_calls=plan["calls_per_reviewer"], max_output_tokens_per_call=cfg["max_output_tokens_per_call"],
                     max_total_tokens=plan["calls_per_reviewer"] * 4000, max_estimated_cost_usd=cfg["max_cost_per_reviewer_usd"])
        clients = {k: BudgetedLLM(LLM(model=cfg[k]["model"], max_output_tokens=lim.max_output_tokens_per_call), lim, pricing) for k in ("reviewer_a", "reviewer_b")}
        a_factory, b_factory, mode = (lambda i: clients["reviewer_a"]), (lambda i: clients["reviewer_b"]), "live"
    else:
        a_factory = b_factory = lambda i: ScriptedLLM({"review": i["offline_review"]})
        mode = "offline-simulation"
    report = compare(items, cases, a_factory, b_factory, cfg["repeats"] if a.live else 1, Path(a.audit_dir), pricing, cfg["decision_rule"])
    report.update({"mode": mode, "budget_plan": plan, "reviewer_a": cfg["reviewer_a"], "reviewer_b": {k: v for k, v in cfg["reviewer_b"].items()}})
    out = Path(a.out) if a.out else OUT_DIR / f"reviewer-comparison-{mode}-{uuid.uuid4().hex[:8]}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1))
    cur, ind = report["current"], report["independent"]
    print(f"mode={mode} current recall={cur['recall']} fr={cur['false_reject_rate']} | independent recall={ind['recall']} fr={ind['false_reject_rate']} "
          f"| mcnemar p={report['paired']['flawed_mcnemar_exact_p']} | decision={report['decision']}\nreport: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

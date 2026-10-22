import json

import pytest

from aiops.limits import BudgetedLLM, BudgetExceeded, Limits
from aiops.pricing import load_pricing

P = load_pricing()


def test_pricing_config_is_dated_and_versioned():
    assert P.version and P.as_of == "2026-10-22" and P.currency == "USD" and "gpt-4.1-mini" in P.models


def test_estimate_uses_snapshot_suffix_cached_and_output_rates():
    cost, status = P.estimate("gpt-4.1-mini-2025-04-14", 1_000_000, 1_000_000, cached_input_tokens=500_000)
    assert status == "estimated" and cost == pytest.approx(0.5 * 0.40 + 0.5 * 0.10 + 1.60)


def test_unknown_model_or_missing_tokens_stay_unknown_not_zero():
    assert P.estimate("some-new-model", 10, 10) == (None, "unknown")
    assert P.estimate("gpt-4.1-mini", None, 10) == (None, "unknown")


class Fake:
    def __init__(self, usage):
        self.usage, self.n = usage, 0

    def parse(self, schema, instructions, content):
        self.n += 1
        return {}, dict(self.usage)


PAID = {"provider": "openai", "model": "gpt-4.1-mini-2025-04-14", "input_tokens": 1000, "output_tokens": 500}


def test_call_limit_enforced_before_the_call():
    inner = Fake(PAID)
    b = BudgetedLLM(inner, Limits(max_model_calls=2), P)
    b.parse(None, "", ""), b.parse(None, "", "")
    with pytest.raises(BudgetExceeded):
        b.parse(None, "", "")
    assert inner.n == 2


def test_cost_limit_enforced():
    b = BudgetedLLM(Fake({**PAID, "input_tokens": 1_000_000}), Limits(max_estimated_cost_usd=0.10), P)
    b.parse(None, "", "")
    with pytest.raises(BudgetExceeded):
        b.parse(None, "", "")


def test_unknown_cost_fails_closed_because_limit_cannot_be_enforced():
    b = BudgetedLLM(Fake({**PAID, "model": "mystery"}), Limits(), P)
    b.parse(None, "", "")
    with pytest.raises(BudgetExceeded):
        b.parse(None, "", "")


def test_limits_load_from_file_env_and_overrides(tmp_path, monkeypatch):
    f = tmp_path / "l.json"
    f.write_text(json.dumps({"max_model_calls": 3}))
    monkeypatch.setenv("GUARDIAN_MAX_ESTIMATED_COST_USD", "0.01")
    lim = Limits.load(f, max_cases=2)
    assert (lim.max_model_calls, lim.max_estimated_cost_usd, lim.max_cases) == (3, 0.01, 2)

"""Configurable API/cost limits and a budget-enforcing wrapper around any model client."""
import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path

from .pricing import Pricing

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "configs" / "eval-limits.json"


class BudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class Limits:
    max_cases: int = 6
    max_model_calls: int = 12
    max_output_tokens_per_call: int = 800
    max_total_tokens: int = 40000
    max_estimated_cost_usd: float = 0.10

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH, **overrides) -> "Limits":
        data = json.loads(Path(path).read_text()) if Path(path).exists() else {}
        for f in fields(cls):
            env = os.environ.get("GUARDIAN_" + f.name.upper())
            if env is not None:
                data[f.name] = type(f.default)(env)
        data.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**data)


@dataclass
class BudgetedLLM:
    """Fails closed before a call when any limit is reached, or when cost cannot be estimated (limit unenforceable)."""
    inner: object
    limits: Limits
    pricing: Pricing
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    unknown_cost_calls: int = 0
    log: list = field(default_factory=list)

    def parse(self, schema, instructions, content):
        l = self.limits
        if self.calls >= l.max_model_calls:
            raise BudgetExceeded(f"max_model_calls={l.max_model_calls} reached")
        if self.input_tokens + self.output_tokens >= l.max_total_tokens:
            raise BudgetExceeded(f"max_total_tokens={l.max_total_tokens} reached")
        if self.unknown_cost_calls:
            raise BudgetExceeded("cost of a previous call is unknown; cost limit cannot be enforced")
        if self.cost >= l.max_estimated_cost_usd:
            raise BudgetExceeded(f"max_estimated_cost_usd={l.max_estimated_cost_usd} reached")
        parsed, usage = self.inner.parse(schema, instructions, content)
        self.calls += 1
        self.input_tokens += usage.get("input_tokens") or 0
        self.output_tokens += usage.get("output_tokens") or 0
        if usage.get("provider") != "offline":
            cost, _ = self.pricing.estimate(usage.get("model"), usage.get("input_tokens"), usage.get("output_tokens"),
                                            usage.get("cached_input_tokens"))
            if cost is None:
                self.unknown_cost_calls += 1
            else:
                self.cost += cost
        return parsed, usage

"""Dated, versioned price table. Costs are estimates (tokens x list price), never billed amounts."""
import json
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "configs" / "pricing.json"
_SNAPSHOT = re.compile(r"-\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class Pricing:
    version: str
    currency: str
    as_of: str
    models: dict

    def estimate(self, model: str | None, input_tokens: int | None, output_tokens: int | None,
                 cached_input_tokens: int | None = None) -> tuple[float | None, str]:
        """Returns (cost, cost_status). cost_status: estimated | unknown | not_applicable ('billed' is reserved for reconciliation)."""
        if model is None or input_tokens is None or output_tokens is None:
            return None, "unknown"
        rates = self.models.get(_SNAPSHOT.sub("", model))
        if rates is None:
            return None, "unknown"
        cached = min(cached_input_tokens or 0, input_tokens)
        cost = ((input_tokens - cached) * rates["input_per_million"]
                + cached * rates.get("cached_input_per_million", rates["input_per_million"])
                + output_tokens * rates["output_per_million"]) / 1_000_000
        return round(cost, 8), "estimated"


def load_pricing(path: Path = DEFAULT_PATH) -> Pricing:
    d = json.loads(Path(path).read_text())
    return Pricing(d["pricing_version"], d["currency"], d["as_of"], d["models"])

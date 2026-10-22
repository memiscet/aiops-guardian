"""Append-only JSONL audit trail (hash-chained). Inputs/outputs are stored as redacted, content-addressed artifacts.

Events follow schemas/guardian-audit-event.schema.json (extends the Stage 4 audit-event schema).
Never stores credentials: every artifact and error message passes through redaction first.
"""
import hashlib
import json
import os
import uuid
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from .mcp_adapter import redact
from .pricing import Pricing

SCHEMA_VERSION = "0.1.0+guardian.1"
WORKFLOW_ID = "aiops-k8s-incident-analysis"
WORKFLOW_VERSION = "0.2.0"
DEFAULT_DIR = Path(__file__).resolve().parent.parent / "var" / "audit"


def now() -> datetime:
    return datetime.now(UTC)


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _digest(event: dict) -> str:
    return hashlib.sha256(json.dumps(event, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _last_hash(path: Path) -> str | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    with open(path, "rb") as f:
        f.seek(max(0, path.stat().st_size - 65536))
        return json.loads(f.read().splitlines()[-1])["event_sha256"]


def model_usage(usage: dict, prompt_version: str, prompt_sha256: str, latency_ms: int, pricing: Pricing) -> dict:
    """Builds the model_usage record. Cost is an estimate from the dated pricing config; unknown stays unknown."""
    offline = usage.get("provider") == "offline"
    cost, status = (0.0, "not_applicable") if offline else pricing.estimate(
        usage.get("model"), usage.get("input_tokens"), usage.get("output_tokens"), usage.get("cached_input_tokens"))
    return {"provider": usage.get("provider", "unknown"), "model": usage.get("model") or "unknown",
            "model_version": usage.get("model"), "input_tokens": usage.get("input_tokens"),
            "cached_input_tokens": usage.get("cached_input_tokens"), "output_tokens": usage.get("output_tokens"),
            "reasoning_tokens": usage.get("reasoning_tokens"), "cost": cost, "currency": pricing.currency,
            "pricing_version": pricing.version, "response_id": usage.get("response_id"),
            "prompt_version": prompt_version, "prompt_sha256": prompt_sha256, "latency_ms": latency_ms, "cost_status": status}


class AuditLog:
    def __init__(self, directory: Path | str = DEFAULT_DIR, run_id: str | None = None,
                 workflow_id: str = WORKFLOW_ID, workflow_version: str = WORKFLOW_VERSION):
        self.dir = Path(directory)
        (self.dir / "artifacts").mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "events.jsonl"
        self.run_id = run_id or str(uuid.uuid4())
        self.workflow_id, self.workflow_version = workflow_id, workflow_version
        self._prev = _last_hash(self.path)
        self._last_event_id: str | None = None

    def artifact(self, content: Any, media_type: str = "application/json") -> dict:
        text = content if isinstance(content, str) else json.dumps(content, sort_keys=True, default=str)
        text = redact(text)[0]
        sha = hashlib.sha256(text.encode()).hexdigest()
        rel = f"artifacts/{sha}.{'txt' if isinstance(content, str) else 'json'}"
        target = self.dir / rel
        if not target.exists():
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(text)
        return {"uri": rel, "sha256": sha, "media_type": "text/plain" if isinstance(content, str) else media_type}

    def event(self, step_id: str, event_type: str, status: str, *, started: datetime | None = None,
              ended: datetime | None = None, agent_id: str | None = None, agent_version: str | None = None,
              inputs: list | None = None, outputs: list | None = None, usage: dict | None = None,
              guardrail: dict | None = None, punch_out: dict | None = None, error: dict | None = None,
              retry: int = 0, failure_origin: str | None = None) -> dict:
        ended = ended or now()
        started = started or ended
        if error:
            error = {**error, "message_redacted": redact(error.get("message_redacted", ""))[0][:300]}
        ev = {"schema_version": SCHEMA_VERSION, "event_id": str(uuid.uuid4()), "causal_parent_event_id": self._last_event_id,
              "workflow_run_id": self.run_id, "trace_id": self.run_id, "workflow_id": self.workflow_id,
              "workflow_version": self.workflow_version, "step_id": step_id, "agent_id": agent_id,
              "agent_version": agent_version, "event_type": event_type, "status": status,
              "failure_origin_step_id": failure_origin, "retry_number": retry, "started_at": _iso(started),
              "ended_at": _iso(ended), "duration_ms": max(0, int((ended - started).total_seconds() * 1000)),
              "input_artifacts": inputs or [], "output_artifacts": outputs or [], "model_usage": usage,
              "guardrail": guardrail, "punch_out": punch_out, "error": error, "prev_event_sha256": self._prev}
        ev["event_sha256"] = _digest(ev)
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, (json.dumps(ev, sort_keys=True) + "\n").encode())
            os.fsync(fd)
        finally:
            os.close(fd)
        self._prev, self._last_event_id = ev["event_sha256"], ev["event_id"]
        return ev


class NullAudit:
    """No-op audit used when no trail is requested (e.g. unit tests)."""
    run_id = "unaudited"

    def artifact(self, content, media_type="application/json"):
        return {"uri": "none", "sha256": hashlib.sha256(str(content).encode()).hexdigest(), "media_type": media_type}

    def event(self, *a, **k):
        return {}


def read_events(path: Path | str) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def verify_chain(path: Path | str) -> tuple[bool, int, int | None]:
    """Returns (ok, event_count, first_bad_line_number)."""
    prev, n = None, 0
    for n, ev in enumerate(read_events(path), 1):
        claimed = ev.pop("event_sha256", None)
        if ev.get("prev_event_sha256") != prev or _digest(ev) != claimed:
            return False, n, n
        prev = claimed
    return True, n, None


def project_to_base(event: dict) -> dict:
    """Drops Guardian extensions so an event can be checked against the unmodified Stage 4 schema (only valid when cost is known)."""
    ev = {k: v for k, v in event.items() if k not in ("event_sha256", "prev_event_sha256")}
    if ev.get("model_usage"):
        ev["model_usage"] = {k: v for k, v in ev["model_usage"].items()
                             if k not in ("response_id", "prompt_version", "prompt_sha256", "latency_ms", "cost_status")}
    return ev

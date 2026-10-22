import json
import os
import stat
from pathlib import Path

import jsonschema
import pytest

from aiops.audit import AuditLog, model_usage, project_to_base, read_events, verify_chain
from aiops.pricing import load_pricing

ROOT = Path(__file__).resolve().parent.parent
EXT = json.loads((ROOT / "schemas" / "guardian-audit-event.schema.json").read_text())
BASE = json.loads((ROOT / "schemas" / "stage4-audit-event.base.schema.json").read_text())
P = load_pricing()


def usage_record(**u):
    return model_usage({"provider": "openai", "model": "gpt-4.1-mini-2025-04-14", "response_id": "resp_1",
                        "input_tokens": 100, "output_tokens": 20, **u}, "diagnosis-test", "a" * 64, 123, P)


def test_events_append_only_hash_chained_and_valid(tmp_path):
    a = AuditLog(tmp_path)
    a.event("analyze", "model_call", "passed", usage=usage_record(), inputs=[a.artifact({"x": 1})])
    a.event("policy", "guardrail", "failed", failure_origin="plan",
            guardrail={"rule_id": "r", "rule_version": "1", "result": "fail", "reason": "x"})
    b = AuditLog(tmp_path)  # a second run continues the same chain
    b.event("report", "workflow_terminal", "passed")
    events = read_events(a.path)
    assert verify_chain(a.path) == (True, 3, None)
    assert events[1]["causal_parent_event_id"] == events[0]["event_id"] and events[2]["prev_event_sha256"] == events[1]["event_sha256"]
    for e in events:
        jsonschema.validate(e, EXT)
        jsonschema.validate(project_to_base(e), BASE)


def test_tampering_is_detected(tmp_path):
    a = AuditLog(tmp_path)
    for step in ("a", "b", "c"):
        a.event(step, "step", "passed")
    lines = a.path.read_text().splitlines()
    lines[1] = lines[1].replace('"status": "passed"', '"status": "failed"')
    a.path.write_text("\n".join(lines) + "\n")
    assert verify_chain(a.path) == (False, 2, 2)


def test_deleted_event_is_detected(tmp_path):
    a = AuditLog(tmp_path)
    for step in ("a", "b", "c"):
        a.event(step, "step", "passed")
    lines = a.path.read_text().splitlines()
    a.path.write_text("\n".join([lines[0], lines[2]]) + "\n")
    assert not verify_chain(a.path)[0]


def test_file_is_private_and_opened_append_only(tmp_path):
    a = AuditLog(tmp_path)
    a.event("a", "step", "passed")
    assert stat.S_IMODE(os.stat(a.path).st_mode) == 0o600
    first = a.path.read_text()
    a.event("b", "step", "passed")
    assert a.path.read_text().startswith(first)


def test_artifacts_are_redacted_content_addressed_and_never_hold_secrets(tmp_path):
    a = AuditLog(tmp_path)
    secret = "sk-" + "A1b2C3d4E5f6G7h8I9j0K1"
    aws = "AKIA" + "ABCDEFGHIJKLMNOP"
    ref = a.artifact({"log": f"token={secret} key {aws} password=hunter2"})
    stored = (tmp_path / ref["uri"]).read_text()
    for leaked in (secret, aws, "hunter2"):
        assert leaked not in stored
    assert ref["sha256"] == __import__("hashlib").sha256(stored.encode()).hexdigest()
    assert a.artifact({"log": f"token={secret} key {aws} password=hunter2"}) == ref


def test_error_messages_are_redacted(tmp_path):
    a = AuditLog(tmp_path)
    ev = a.event("analyze", "model_call", "error", error={"category": "model_api", "code": "X", "message_redacted": "Authorization: Bearer abcdefghijklmnop12345"})
    assert "abcdefghijklmnop" not in ev["error"]["message_redacted"]


def test_cost_designation_estimated_unknown_and_not_applicable():
    assert usage_record()["cost_status"] == "estimated" and usage_record()["cost"] > 0
    unknown = usage_record(model="mystery-model")
    assert unknown["cost_status"] == "unknown" and unknown["cost"] is None
    missing = usage_record(input_tokens=None)
    assert missing["cost_status"] == "unknown" and missing["input_tokens"] is None
    offline = model_usage({"provider": "offline", "model": "offline-scripted", "input_tokens": 0, "output_tokens": 0}, "v", "b" * 64, 1, P)
    assert offline["cost_status"] == "not_applicable" and offline["cost"] == 0.0


def test_unknown_cost_is_valid_for_extended_schema_but_not_the_unmodified_base_schema(tmp_path):
    a = AuditLog(tmp_path)
    ev = a.event("analyze", "model_call", "passed", usage=usage_record(model="mystery-model"))
    jsonschema.validate(ev, EXT)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(project_to_base(ev), BASE)


def test_extended_schema_requires_cost_status_and_response_id(tmp_path):
    a = AuditLog(tmp_path)
    ev = a.event("analyze", "model_call", "passed", usage=usage_record())
    for field in ("cost_status", "response_id", "prompt_version", "latency_ms"):
        broken = json.loads(json.dumps(ev))
        del broken["model_usage"][field]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(broken, EXT)


def test_schemas_are_valid_draft_2020_12():
    jsonschema.Draft202012Validator.check_schema(EXT)
    jsonschema.Draft202012Validator.check_schema(BASE)

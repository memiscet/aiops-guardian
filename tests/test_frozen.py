"""The held-out inputs, gold answers and grader are frozen. Hardening changed the system under test, not the test."""
import asyncio
import hashlib
import inspect
import json
from pathlib import Path

from aiops import evaluation as ev
from aiops.fake_mcp import OFFLINE_SETTINGS, FakeSession
from aiops.mcp_adapter import collect_evidence

ROOT = Path(__file__).resolve().parent.parent
FROZEN = json.loads((ROOT / "release" / "frozen-hashes.json").read_text())
BASE = json.loads((ROOT / "release" / "evidence-baseline-07d2b1f.json").read_text())["evidence_sha256"]
sha = lambda b: hashlib.sha256(b).hexdigest()


def test_heldout_manifest_and_every_file_match_the_hashes_recorded_at_07d2b1f():
    assert sha((ROOT / "evaluations" / "heldout" / "MANIFEST.json").read_bytes()) == FROZEN["heldout_manifest_sha256"]
    for rel, digest in FROZEN["heldout_files"].items():
        assert sha((ROOT / "evaluations" / "heldout" / rel).read_bytes()) == digest, rel


def test_grader_and_loader_source_are_unchanged_since_07d2b1f():
    assert sha(inspect.getsource(ev.judge).encode()) == FROZEN["judge_source_sha256"]
    assert sha(inspect.getsource(ev.load_heldout).encode()) == FROZEN["load_heldout_source_sha256"]


def _rc1_view(text: str) -> str:
    """RC2 only adds to the evidence (a table block and log-line ids); stripping those must give back the RC1 text."""
    from aiops.facts import TABLE_RE
    import re
    text = TABLE_RE.sub("", text, count=1).replace("\n\nAPPLICATION LOGS", "\nAPPLICATION LOGS", 1)
    return re.sub(r"(?m)^\[L\d+\.\d+( Q)?\] ", "", text)


def test_rc2_evidence_only_adds_to_the_rc1_evidence_for_every_non_injection_case():
    changed = []
    for c in ev.load_cases() + ev.load_heldout():
        text = asyncio.run(collect_evidence(FakeSession(c["mcp"]), OFFLINE_SETTINGS, "stage4-lab", c["pod"], nonce="evalnonce")).text
        if sha(_rc1_view(text).encode()) != BASE[c["id"]]:
            changed.append(c["id"])
    injection = {"04-log-prompt-injection"} | {c["id"] for c in ev.load_heldout() if c["kind"] == "injection"}
    assert set(changed) == injection  # only the cases with injection text differ (RC1 hardening plus RC2 id-spoof defanging)

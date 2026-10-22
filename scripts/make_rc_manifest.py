"""Writes (or verifies) release/rc-manifest.json: what exactly a release candidate is, so a later evaluation can be tied to it.

  python scripts/make_rc_manifest.py --pytest "<summary line>"   # write
  python scripts/make_rc_manifest.py --verify                    # recompute and compare; non-zero exit on any difference
No secrets are read except the NAME of the configured model (OPENAI_MODEL) from .env.
"""
import argparse
import hashlib
import importlib.metadata as md
import json
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "release" / "rc-manifest.json"
TREE_DIRS = ["aiops", "configs", "evaluations", "schemas", "scripts", "tests", "k8s", "infrastructure", "release", "requirements.txt"]
EXCLUDE = {"release/rc-manifest.json"}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def git(*a) -> str:
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def tree_hash() -> tuple[str, int]:
    files = sorted(f for f in git("ls-files", "-co", "--exclude-standard", "--", *TREE_DIRS).splitlines() if f not in EXCLUDE and (ROOT / f).is_file())
    h = hashlib.sha256()
    for f in files:
        h.update(f.encode() + b"\0" + (ROOT / f).read_bytes() + b"\0")
    return h.hexdigest(), len(files)


def model_name() -> str:
    from dotenv import dotenv_values
    return dotenv_values(ROOT / ".env").get("OPENAI_MODEL") or "gpt-4.1-mini"


def build(pytest_line: str | None) -> dict:
    from aiops import evaluation as ev
    from aiops.limits import Limits
    from aiops.pricing import load_pricing
    tree, n = tree_hash()
    fp = ev.system_fingerprint()
    lim = Limits.load(ev.HELDOUT_LIMITS)
    dev_limits = Limits.load(ev.DEFAULT_LIMITS)
    with tempfile.TemporaryDirectory() as tmp:
        dev = ev.evaluate(ev.load_cases(), False, dev_limits, Path(tmp) / "a", json.loads(ev.PROBES_FILE.read_text()))
        held = ev.evaluate(ev.load_heldout(), False, lim, Path(tmp) / "b")
    p = load_pricing()
    frozen = json.loads((ROOT / "release" / "frozen-hashes.json").read_text())
    return {
        "release_candidate": "rc1-heldout-ready",
        "generated": "2026-10-22",
        "base_commit": git("rev-parse", "HEAD"),
        "base_commit_subject": git("log", "-1", "--format=%s"),
        "working_tree_dirty_when_generated": bool(git("status", "--porcelain", "--", *TREE_DIRS)),
        "source_tree_sha256": tree, "source_tree_files": n,
        "system_fingerprint": fp,
        "model_config": {"provider": "openai", "api": "responses.parse (structured outputs)", "model": model_name(), "max_output_tokens_per_call": dev_limits.max_output_tokens_per_call,
                         "client_max_retries": 0, "request_timeout_s": 60.0, "workflow_max_attempts": 1, "temperature": "API default (not set)",
                         "reviewer_model": "same client and model as diagnosis and planning (no independent reviewer configured)",
                         "pricing_version": p.version, "pricing_as_of": p.as_of, "price_table_models": sorted(p.models)},
        "limits": {"dev": dev_limits.__dict__, "heldout": lim.__dict__},
        "frozen_assets": {"heldout_manifest_sha256": frozen["heldout_manifest_sha256"], "judge_source_sha256": frozen["judge_source_sha256"],
                          "load_heldout_source_sha256": frozen["load_heldout_source_sha256"], "heldout_cases": held["cases"],
                          "baseline_commit": frozen["source_commit"]},
        "environment": {"python": platform.python_version(), "packages": {k: md.version(k) for k in ("openai", "langgraph", "mcp", "pydantic", "pytest", "jsonschema", "PyYAML", "boto3")}},
        "offline_results": {
            "pytest": pytest_line,
            "dev_set": {k: dev[k] for k in ("cases", "passed", "accuracy", "safety_failures", "errors", "unsafe_proposals", "controls_exercised")} | {"reviewer_probes": {k: dev["reviewer_probes"][k] for k in ("flawed_outputs", "caught", "controls", "controls_passed")}},
            "heldout_oracle_run": {k: held[k] for k in ("cases", "passed", "accuracy", "safety_failures", "errors", "by_kind", "model_calls")},
            "scope": "offline: scripted model answers; checks the harness, grader and deterministic controls, not language-model quality",
        },
        "live_results": "none for this release candidate; no paid call has been made against it",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pytest", default=None)
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    if a.verify:
        m = json.loads(OUT.read_text())
        from aiops import evaluation as ev
        ok = tree_hash()[0] == m["source_tree_sha256"] and ev.system_fingerprint() == m["system_fingerprint"]
        print("release candidate verified: source tree and system fingerprint match the manifest" if ok else "MISMATCH: the working tree differs from the release candidate")
        return 0 if ok else 1
    m = build(a.pytest)
    OUT.write_text(json.dumps(m, indent=1) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: tree {m['source_tree_sha256'][:12]} ({m['source_tree_files']} files), fingerprint {m['system_fingerprint']['code_and_config_sha256'][:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

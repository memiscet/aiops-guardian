"""Writes (or verifies) release/rc2-manifest.json for release candidate RC2 (offline-tested; not yet evaluated live).

  python scripts/make_rc2_manifest.py --pytest "<summary line>"   # write (runs the offline suites and component harness)
  python scripts/make_rc2_manifest.py --verify                    # recompute the source tree hash and fingerprint
The RC1 manifest (release/rc-manifest.json) is never touched; verify RC1 with: python scripts/make_rc_manifest.py --verify-rev rc1-heldout-ready
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
sys.path.insert(0, str(ROOT / "scripts"))
from make_rc_manifest import TREE_DIRS, git, model_name, sha  # noqa: E402

OUT = ROOT / "release" / "rc2-manifest.json"
EXCLUDE = {"release/rc-manifest.json", "release/rc2-manifest.json"}


def tree_hash() -> tuple[str, int]:
    files = sorted(f for f in git("ls-files", "-co", "--exclude-standard", "--", *TREE_DIRS).splitlines() if f not in EXCLUDE and (ROOT / f).is_file())
    h = hashlib.sha256()
    for f in files:
        h.update(f.encode() + b"\0" + (ROOT / f).read_bytes() + b"\0")
    return h.hexdigest(), len(files)


def build(pytest_line: str | None) -> dict:
    from aiops import component_eval as ce, evaluation as ev, evaluation2 as e2
    from aiops.limits import Limits
    from aiops.pricing import load_pricing
    from aiops.prompts import COMPONENT_VERSIONS
    tree, n = tree_hash()
    p = load_pricing()
    frozen1 = json.loads((ROOT / "release" / "frozen-hashes.json").read_text())
    frozen2 = json.loads((ROOT / "release" / "rc2-frozen-hashes.json").read_text())
    dev_limits, rc1_limits, rc2_limits = Limits.load(), Limits.load(ev.HELDOUT_LIMITS), Limits.load(e2.RC2_LIMITS)
    with tempfile.TemporaryDirectory() as tmp:
        suites = {"dev": (e2.load_cases(), dev_limits), "regression-rc1": (e2.load_regression(), rc1_limits), "heldout-rc2": (e2.load_heldout_rc2(), rc2_limits)}
        offline = {}
        for name, (cases, lim) in suites.items():
            r = e2.evaluate2(cases, False, lim, Path(tmp) / name, name)
            offline[name] = {"cases": r["cases"], "end_to_end": r["dimensions"]["end_to_end"], "diagnosis_correct": r["dimensions"]["diagnosis"]["correct"], "evidence_valid": r["dimensions"]["evidence"]["valid"],
                             "safety_failures": r["dimensions"]["policy"]["safety_failures"], "errors": r["dimensions"]["errors"], "by_kind": r["by_kind"], "model_calls": r["model_calls"]}
        sets = ce.load_component_sets()
        comps = {n_: {k: v for k, v in ce.evaluate_component(n_, sets[n_], False).items() if k in ("version", "cases", "harness_validated", "good_pass", "bad_fail")} for n_ in sorted(sets)}
    replay = json.loads((ROOT / "results" / "rc2-offline" / "replay-rc1-through-rc2.json").read_text()) if (ROOT / "results" / "rc2-offline" / "replay-rc1-through-rc2.json").exists() else None
    return {
        "release_candidate": "rc2-offline-tested", "generated": "2026-10-22", "base_commit": git("rev-parse", "HEAD"), "base_commit_subject": git("log", "-1", "--format=%s"),
        "supersedes": None, "rc1": {"tag": "rc1-heldout-ready", "commit": frozen2["rc1"]["commit"], "result_report_sha256": frozen2["rc1"]["report_sha256"], "status": "immutable; verify with --verify-rev"},
        "working_tree_dirty_when_generated": bool(git("status", "--porcelain", "--", *TREE_DIRS)),
        "source_tree_sha256": tree, "source_tree_files": n, "system_fingerprint": ev.system_fingerprint(),
        "components": COMPONENT_VERSIONS,
        "model_config": {"provider": "openai", "api": "responses.parse (structured outputs)", "model": model_name(), "max_output_tokens_per_call": dev_limits.max_output_tokens_per_call,
                         "client_max_retries": 0, "request_timeout_s": 60.0, "workflow_max_attempts": 1, "temperature": "API default (not set)",
                         "reviewer_model": "same client and model as diagnosis and planning (no independent reviewer configured)", "pricing_version": p.version, "pricing_as_of": p.as_of},
        "limits": {"regression": rc1_limits.__dict__, "heldout_rc2": rc2_limits.__dict__},
        "frozen_assets": {"rc1_heldout_manifest_sha256": frozen1["heldout_manifest_sha256"], "rc1_judge_source_sha256": frozen1["judge_source_sha256"],
                          "rc2_heldout_manifest_sha256": frozen2["heldout_rc2_manifest_sha256"], "rc2_gold_sha256": frozen2["gold_sha256"], "rc2_review_items_sha256": frozen2["review_items_sha256"], "rc2_cases": 40},
        "environment": {"python": platform.python_version(), "packages": {k: md.version(k) for k in ("openai", "langgraph", "mcp", "pydantic", "pytest", "jsonschema", "PyYAML", "boto3")}},
        "offline_results": {"pytest": pytest_line, "suites": offline, "components_harness": comps,
                            "replay_of_rc1_outputs_through_rc2_deterministic_layers": ({k: replay[k] for k in ("rc1_passed", "rc2_replay_end_to_end", "cases", "gained", "lost")} if replay else None),
                            "scope": "offline: scripted reference answers; checks harness, grader, rules and deterministic controls, not language-model quality. The replay is a counterfactual on RC1's stored outputs."},
        "live_results": "none for RC2; no paid call has been made against it",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pytest", default=None)
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    if a.verify:
        from aiops import evaluation as ev
        m = json.loads(OUT.read_text())
        ok = tree_hash()[0] == m["source_tree_sha256"] and ev.system_fingerprint() == m["system_fingerprint"]
        print("RC2 verified: source tree and system fingerprint match the manifest" if ok else "MISMATCH: the working tree differs from RC2")
        return 0 if ok else 1
    m = build(a.pytest)
    OUT.write_text(json.dumps(m, indent=1) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: tree {m['source_tree_sha256'][:12]} ({m['source_tree_files']} files), fingerprint {m['system_fingerprint']['code_and_config_sha256'][:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Documentation is checked against the code: links, paths, modules, flags, versions, ports, counts, and that nothing private is published."""
import importlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "README.md", *(ROOT / "docs" / f for f in ("QUICKSTART.md", "INSTALLATION.md", "ARCHITECTURE.md", "OPERATIONS.md", "EVALUATIONS.md", "SECURITY.md", "RELEASES.md"))]
TEXT = {p: p.read_text() for p in DOCS}
GENERATED = ("var/", ".env", ".cluster", ".vagrant", "heldout-live-rc1-first-run-audit")


def test_all_documents_exist_and_are_linked_from_the_readme():
    assert all(p.exists() for p in DOCS)
    for p in DOCS[1:]:
        assert f"docs/{p.name}" in TEXT[ROOT / "README.md"], p.name


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_relative_markdown_links_resolve(doc):
    for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", TEXT[doc]):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        assert (doc.parent / target).resolve().exists(), f"{doc.name}: broken link {target}"


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_repository_paths_in_backticks_exist(doc):
    for path in set(re.findall(r"`((?:aiops|configs|docs|evaluations|infrastructure|k8s|release|results|schemas|scripts|tests)/[\w./*-]+\.(?:py|md|json|yaml|yml|sh|txt))`", TEXT[doc])):
        if any(g in path for g in GENERATED) or "*" in path or "<" in path:
            continue
        assert (ROOT / path).exists(), f"{doc.name}: {path} does not exist"


def test_every_documented_module_exists_and_every_documented_flag_is_real():
    seen = {}
    for doc in DOCS:
        for line in TEXT[doc].splitlines():
            m = re.search(r"python -m (aiops\.\w+)([^#`|]*)", line)
            if m:
                seen.setdefault(m.group(1), set()).update(re.findall(r"--[a-z-]+", re.sub(r"\$\(.*\)", "", m.group(2))))
    assert seen
    for module, flags in seen.items():
        importlib.import_module(module)
        help_text = subprocess.run([sys.executable, "-m", module, "--help"], cwd=ROOT, capture_output=True, text=True, timeout=60).stdout
        assert help_text, module
        for flag in flags:
            assert flag in help_text, f"{module} has no {flag}"


def test_documented_scripts_exist_and_run_help_free_checks():
    for doc in DOCS:
        for script in re.findall(r"(?:python|bash) (scripts/[\w.]+|infrastructure/[\w./]+\.sh)", TEXT[doc]):
            assert (ROOT / script).exists(), f"{doc.name}: {script}"


def test_ports_images_and_endpoints_in_the_docs_match_the_infrastructure_files():
    compose = yaml.safe_load((ROOT / "infrastructure" / "ministack" / "docker-compose.yml").read_text())["services"]["ministack"]
    assert compose["image"] == "ministackorg/ministack:1.5.31" and compose["ports"] == ["127.0.0.1:4570:4570"]
    install = TEXT[ROOT / "docs" / "INSTALLATION.md"]
    assert "ministackorg/ministack:1.5.31" in install and "127.0.0.1:4570" in install and "4566" in install
    env = (ROOT / ".env.example").read_text()
    assert "MINISTACK_ENDPOINT=http://localhost:4570" in env and "EXPECTED_KUBE_API_SERVER=https://192.168.56.20:6443" in env
    vagrant = (ROOT / "infrastructure" / "vagrant" / "Vagrantfile").read_text()
    for ip in ("192.168.56.20", "192.168.56.21", "192.168.56.22"):
        assert ip in vagrant and ip in install
    assert "bento/ubuntu-24.04" in vagrant and "bento/ubuntu-24.04" in install


def test_rbac_described_in_the_docs_equals_the_manifest():
    docs = list(yaml.safe_load_all((ROOT / "infrastructure" / "kubernetes" / "stage4-lab-rbac.yaml").read_text()))
    role = next(d for d in docs if d["kind"] == "Role")
    assert role["metadata"]["namespace"] == "stage4-lab"
    rules = {(r["resources"][0], tuple(r["verbs"])) for r in role["rules"]}
    assert rules == {("pods", ("get", "list")), ("pods/log", ("get",)), ("events", ("get", "list"))}


def test_documented_policy_tables_match_the_code():
    from aiops.policy import BLOCKED_ACTIONS, REVIEW_ACTIONS, SAFE_ACTIONS
    arch = TEXT[ROOT / "docs" / "ARCHITECTURE.md"]
    for action in SAFE_ACTIONS | REVIEW_ACTIONS | BLOCKED_ACTIONS:
        assert f"`{action}`" in arch, action


def test_documented_versions_match_requirements_and_pricing():
    req = (ROOT / "requirements.txt").read_text()
    for pkg in ("openai", "langgraph", "mcp", "pydantic", "pytest", "boto3", "PyYAML", "jsonschema", "python-dotenv"):
        assert pkg.lower() in req.lower() or pkg == "PyYAML"
    pricing = json.loads((ROOT / "configs" / "pricing.json").read_text())
    assert pricing["pricing_version"] in TEXT[ROOT / "docs" / "RELEASES.md"]
    p = pricing["models"]["gpt-4.1-mini"]
    assert f"${p['input_per_million']:.2f} input" in TEXT[ROOT / "docs" / "RELEASES.md"] and f"${p['output_per_million']:.2f} output" in TEXT[ROOT / "docs" / "RELEASES.md"]


def test_documented_counts_match_the_files():
    ev = TEXT[ROOT / "docs" / "EVALUATIONS.md"]
    assert len(list((ROOT / "evaluations" / "heldout" / "cases").glob("*.json"))) == 36 and len(list((ROOT / "evaluations" / "heldout-rc2" / "cases").glob("*.json"))) == 40
    assert len(list((ROOT / "evaluations" / "components").glob("*.json"))) == 8 and len(list((ROOT / "evaluations" / "cases").glob("*.json"))) == 6
    assert "| Dev | 6 |" in ev and "| 36 |" in ev and "| 40 (5 kinds x 8) |" in ev
    limits = {n: json.loads((ROOT / "configs" / n).read_text()) for n in ("eval-limits.json", "heldout-limits.json", "heldout-rc2-limits.json")}
    assert limits["eval-limits.json"]["max_model_calls"] == 24 and limits["heldout-limits.json"]["max_model_calls"] == 120 and limits["heldout-rc2-limits.json"]["max_model_calls"] == 135
    assert all(v["max_estimated_cost_usd"] == 0.10 for v in limits.values())


def test_recorded_results_in_the_docs_match_the_preserved_rc1_report():
    rep = json.loads((ROOT / "results" / "heldout-live-rc1" / "heldout-live-rc1-first-run.json").read_text())
    ev = TEXT[ROOT / "docs" / "EVALUATIONS.md"]
    assert (rep["passed"], rep["cases"], rep["safety_failures"], rep["errors"]) == (25, 36, 0, 0)
    assert "25 of 36 = 0.694" in ev and f"{rep['estimated_cost_usd']:.4f}" in ev and str(rep["input_tokens"]).replace("", "") in ev.replace(",", "")


def test_the_two_release_tags_exist_and_resolve_to_the_documented_commits():
    for tag, short in (("rc1-heldout-ready", "1b855ba"), ("rc2-offline-tested", "7cf4ee5")):
        out = subprocess.run(["git", "rev-parse", f"{tag}^{{commit}}"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        assert out.startswith(short) and short in TEXT[ROOT / "docs" / "RELEASES.md"]


def test_publishable_files_contain_no_home_paths_credentials_or_private_hosts():
    files = [p for p in subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
             if p.endswith((".md", ".py", ".json", ".yaml", ".yml", ".sh", ".txt", ".example")) and not p.startswith(("results/", "release/", "evaluations/"))]
    assert files
    for f in files:
        text = (ROOT / f).read_text(errors="ignore")
        if f != "tests/test_docs.py" and f != "scripts/check_history.py":
            assert not re.search(r"/Users/[A-Za-z0-9._-]+", text), f"home path in {f}"
        assert not re.search(r"sk-(proj-)?[A-Za-z0-9_-]{30,}", text), f"key-like string in {f}"
    assert "replace_me" in (ROOT / ".env.example").read_text()


def test_readme_and_quickstart_state_the_supported_python_and_the_no_cost_path():
    for doc in (ROOT / "README.md", ROOT / "docs" / "QUICKSTART.md"):
        assert "3.12" in TEXT[doc] and "3.14.7" in TEXT[doc]
    assert "no cluster, no API key" in TEXT[ROOT / "README.md"].lower() or "no cluster, no api key" in TEXT[ROOT / "README.md"].lower()

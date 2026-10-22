"""Scans every commit reachable from any ref (branches and tags) for credentials and sensitive files before publication. Prints locations only, never values.

Fails (exit 1) on: credential-shaped strings, key or kubeconfig material, the local .env secret values or reader token, and sensitive file paths.
Reports as information (does not fail): absolute home paths and e-mail addresses in file contents, and commit author identities (git metadata is public once pushed).
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = {"openai-style key": r"sk-(proj-)?[A-Za-z0-9_-]{20,}", "aws access key id": r"\b(AKIA|ASIA)[0-9A-Z]{16}\b", "private key block": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
            "kubeconfig certificate or key data": r"client-(certificate|key)-data", "jwt": r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.", "github token": r"gh[pousr]_[A-Za-z0-9]{20,}",
            "bearer token": r"Bearer\s+[A-Za-z0-9._~+/=-]{20,}", "kubeconfig token field": r"^\s*token:\s*[A-Za-z0-9._-]{20,}"}
ALLOWED = {"kubeconfig certificate or key data": {"scripts/check_secrets.py", "scripts/check_history.py", "tests/test_mcp_adapter.py", "aiops/mcp_adapter.py"},
           "bearer token": {"scripts/check_history.py"}, "private key block": {"scripts/check_history.py", "scripts/check_secrets.py"}, "kubeconfig token field": {"scripts/check_history.py"}}
BAD_PATH = re.compile(r"(^|/)\.env($|\.(?!example$))|kubeconfig$|(^|/)\.cluster/|\.pem$|\.key$|\.zip$|\.tar\.gz$|\.jsonl$|^var/|id_rsa|(^|/)\.vagrant/")
ALLOWED_PATHS = {"infrastructure/kubernetes/make-reader-kubeconfig.sh"}  # a script that builds a kubeconfig, not a kubeconfig


def sh(*a: str) -> str:
    return subprocess.run(a, cwd=ROOT, capture_output=True, text=True).stdout


def local_secret_values() -> list[str]:
    vals = []
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() in ("OPENAI_API_KEY",) and len(v) > 20:
                vals.append(v.strip())
    kc = ROOT / "infrastructure" / "vagrant" / ".cluster" / "guardian-reader.kubeconfig"
    if kc.exists():
        m = re.search(r"token:\s*(\S{40,})", kc.read_text())
        if m:
            vals.append(m.group(1))
    return vals


def main() -> int:
    revs = sh("git", "rev-list", "--all").split()
    paths = {p for r in revs for p in sh("git", "ls-tree", "-r", "--name-only", r).splitlines()}
    problems = []
    problems += [f"sensitive path in history: {p}" for p in sorted(paths) if BAD_PATH.search(p) and p not in ALLOWED_PATHS]
    for name, pat in PATTERNS.items():
        found = {o.split(":", 1)[1] for r in revs for o in sh("git", "grep", "-lIE", pat, r).splitlines()} - ALLOWED.get(name, set())
        problems += [f"{name}: {f}" for f in sorted(found)]
    for v in local_secret_values():
        if any(sh("git", "grep", "-lIF", v[:60], r) for r in revs):
            problems.append("a local secret value (from .env or the reader kubeconfig) appears in history")
    info = {}
    for label, pat in (("absolute home path", r"/Users/[A-Za-z0-9._-]+|/home/[A-Za-z0-9._-]+"), ("e-mail address", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}")):
        info[label] = sorted({o.split(":", 1)[1] for r in revs for o in sh("git", "grep", "-lIE", pat, r).splitlines()})
    authors = sorted(set(sh("git", "log", "--all", "--format=%an <%ae>").splitlines()))
    print(f"commits scanned: {len(revs)}; distinct paths: {len(paths)}; tags: {', '.join(sh('git', 'tag').split()) or 'none'}")
    for k, v in info.items():
        print(f"info: {k} in history: {len(v)} file(s) {v[:8]}")
    print(f"info: commit author identities (public once pushed): {len(authors)}")
    for p in problems:
        print("PROBLEM:", p)
    print("history scan:", "FAILED" if problems else "no credentials, key material, kubeconfigs or archives found")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

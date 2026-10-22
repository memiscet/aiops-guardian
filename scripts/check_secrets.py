"""Pre-commit secret check. Scans every file git would add (tracked + untracked, minus ignored). Prints locations only, never values.

Also fails if known local secret files are not ignored, or if the live OPENAI_API_KEY value from .env appears in any file.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = {
    "openai-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    "aws access key id": re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "kubeconfig credential": re.compile(r"(client-key-data|client-certificate-data|^\s*token):\s*[A-Za-z0-9+/=._-]{40,}", re.M),
    "assigned secret": re.compile(r"(?i)(api[_-]?key|secret|passw(or)?d|token)\s*[=:]\s*['\"]?(?!replace_me|test\b|\[REDACTED|<)[A-Za-z0-9/+_-]{24,}"),
}
MUST_BE_IGNORED = [".env", "infrastructure/vagrant/.cluster/kubeconfig", "infrastructure/vagrant/.cluster/guardian-reader.kubeconfig",
                   "infrastructure/vagrant/.cluster/join-command.sh", "var/audit/events.jsonl", "aiops-guardian-stage4-devin-handoff.zip"]


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def main() -> int:
    problems = []
    for rel in MUST_BE_IGNORED:
        if git("check-ignore", "-q", rel).returncode != 0:
            problems.append(f"{rel}: NOT git-ignored")
    live = None
    env = ROOT / ".env"
    if env.exists():
        m = re.search(r"^OPENAI_API_KEY=(\S+)", env.read_text(), re.M)
        live = m.group(1) if m and m.group(1) != "replace_me" else None
    files = [f for f in git("ls-files", "-co", "--exclude-standard", "-z").stdout.split("\0") if f]
    for rel in files:
        path = ROOT / rel
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            problems.append(f"{rel}: binary file would be committed (review)")
            continue
        if live and live in text:
            problems.append(f"{rel}: contains the live OPENAI_API_KEY value")
        for name, pattern in PATTERNS.items():
            for m in pattern.finditer(text):
                problems.append(f"{rel}:{text[:m.start()].count(chr(10)) + 1}: {name}")
    for p in problems:
        print(p)
    print(f"checked {len(files)} files: {'FAILED' if problems else 'no secrets found'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

"""Deterministic guardrails between workflow steps. Fail closed; independent of model advice."""
import re

CITATION_RULE = ("evidence-citation", "1")
LOG_RULE = ("redundant-log-retrieval", "1")
REVIEW_RULE = "adversarial-review"
ACTION_RULE = ("action-policy", "1")
MAX_CITATIONS, MAX_QUOTE, MIN_QUOTE = 8, 300, 6
SOURCES = {"pod_status", "container_state", "events", "resources", "logs"}
_BLOCK = re.compile(r"<<<UNTRUSTED_LOG [^\n]*?id=(?P<id>\w+)>>>\n(?P<body>.*?)\n<<<END_UNTRUSTED_LOG id=(?P=id)>>>", re.S)
_RELEVANT = {
    "app_exit_nonzero": re.compile(r"exitCode|CrashLoopBackOff|BackOff|Error", re.I),
    "oom_killed": re.compile(r"OOMKilled|\b137\b|memory", re.I),
    "image_pull_failure": re.compile(r"ImagePull|ErrImagePull|manifest|pull", re.I),
}


def _norm(s: str) -> str:
    """Whitespace-insensitive form: quotes must match verbatim apart from spacing/newlines (models reflow pretty-printed JSON)."""
    return "".join(s.split())


def split_evidence(evidence: str) -> tuple[str, str]:
    """Returns (structured text with log blocks removed, concatenated untrusted log text)."""
    logs = "\n".join(m.group("body") for m in _BLOCK.finditer(evidence))
    return _BLOCK.sub("", evidence), logs


def verify_citations(diagnosis: dict, evidence: str) -> tuple[bool, str]:
    """Every cited quote must appear verbatim in the evidence, in the part matching its source; logs are never the sole basis."""
    cites = diagnosis.get("evidence")
    if not isinstance(cites, list) or not 1 <= len(cites) <= MAX_CITATIONS:
        return False, f"expected 1-{MAX_CITATIONS} citations"
    structured, logs = (_norm(x) for x in split_evidence(evidence))
    structured_hits = 0
    for c in cites:
        source, quote = (c.get("source"), _norm(str(c.get("quote", "")))) if isinstance(c, dict) else (None, "")
        if source not in SOURCES or not MIN_QUOTE <= len(quote) <= MAX_QUOTE:
            return False, "citation has invalid source or quote"
        if source == "logs":
            if quote not in logs:
                return False, f"log quote not found in collected logs: {quote[:60]!r}"
        elif quote in structured:
            structured_hits += 1
        else:
            return False, f"{source} quote not found in structured evidence: {quote[:60]!r}"
    category = diagnosis.get("category")
    if category != "insufficient_evidence" and not structured_hits:
        return False, "diagnosis cites only untrusted logs"
    pattern = _RELEVANT.get(category)
    if pattern and not any(pattern.search(str(c.get("quote", ""))) for c in cites):
        return False, f"no citation relevant to category {category}"
    return True, "all citations verified verbatim against collected evidence"


def review_outcome(review: dict) -> tuple[bool, str]:
    """The reviewer can only make the workflow stricter: a fail verdict or any high-severity finding rejects."""
    findings = review.get("findings") if isinstance(review.get("findings"), list) else []
    high = [f for f in findings if isinstance(f, dict) and f.get("severity") == "high"]
    if review.get("verdict") != "pass":
        return False, "reviewer verdict: fail" + (f" ({findings[0].get('kind')})" if findings and isinstance(findings[0], dict) else "")
    if high:
        return False, f"reviewer passed but reported a high-severity finding ({high[0].get('kind')})"
    return True, "reviewer found no blocking issue"


def normalize_plan(plan: dict, logs_collected: bool) -> tuple[dict, str | None]:
    """collect_logs is redundant when logs were already collected: correct it to observe and say so."""
    if plan.get("action") == "collect_logs" and logs_collected:
        return {**plan, "action": "observe", "normalized_from": "collect_logs"}, "collect_logs corrected to observe: logs already collected"
    return plan, None

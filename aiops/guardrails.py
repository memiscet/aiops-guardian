"""Deterministic guardrails between workflow steps. Fail closed; independent of model advice."""
import re

from .facts import TABLE_RE, derived, parse_table
from .policy import BLOCKED_ACTIONS, REVIEW_ACTIONS

CITATION_RULE = ("evidence-citation", "1")
LOG_RULE = ("redundant-log-retrieval", "1")
REVIEW_RULE = "adversarial-review"
ACTION_RULE = ("action-policy", "1")
MAX_CITATIONS, MAX_QUOTE, MIN_QUOTE = 8, 300, 6
SOURCES = {"pod_status", "container_state", "events", "resources", "logs"}
_MESSAGE = re.compile(r'("message"\s*:\s*)"(?:[^"\\]|\\.)*"')
_BLOCK = re.compile(r"<<<UNTRUSTED_LOG [^\n]*?id=(?P<id>\w+)>>>\n(?P<body>.*?)\n<<<END_UNTRUSTED_LOG id=(?P=id)>>>", re.S)
_RELEVANT = {
    "app_exit_nonzero": re.compile(r"exitCode|CrashLoopBackOff|BackOff|Error", re.I),
    "oom_killed": re.compile(r"OOMKilled|OOMKilling", re.I),
    "image_pull_failure": re.compile(r"ImagePull|InvalidImageName|manifest|pull|invalid reference|registry", re.I),
}


def _norm(s: str) -> str:
    """Whitespace-insensitive form: quotes must match verbatim apart from spacing/newlines (models reflow pretty-printed JSON)."""
    return "".join(s.split())


def _blank_messages(text: str) -> str:
    return _MESSAGE.sub(r'\1""', text)


def untrusted_text(evidence: str) -> str:
    """All application-influenced free text in the evidence: log blocks and every message field of the structured status."""
    structured, logs = split_evidence(evidence)
    return "\n".join([logs, *(m.group(0) for m in _MESSAGE.finditer(structured))])


def split_evidence(evidence: str) -> tuple[str, str]:
    """Returns (structured text with log blocks removed, concatenated untrusted log text)."""
    evidence = TABLE_RE.sub("", evidence)
    logs = "\n".join(m.group("body") for m in _BLOCK.finditer(evidence))
    return _BLOCK.sub("", evidence), logs


def analyze_citations(diagnosis: dict, evidence: str, relevance: bool = True) -> dict:
    """Resolve every citation deterministically. A citation names an evidence id (preferred, RC2) or quotes text verbatim (legacy, RC1).
    Provenance: untrusted text (logs, messages) can accompany but never establish a diagnosis; quarantined ids are dropped, never counted."""
    out = {"ok": False, "reason": "", "trusted": [], "untrusted_ids": [], "dropped_ids": [], "ids": [], "texts": []}
    cites = diagnosis.get("evidence")
    if not isinstance(cites, list) or not 1 <= len(cites) <= MAX_CITATIONS:
        out["reason"] = f"expected 1-{MAX_CITATIONS} citations"
        return out
    table = parse_table(evidence)
    structured_raw, logs_raw = split_evidence(evidence)
    structured, logs, skeleton = _norm(structured_raw), _norm(logs_raw), _norm(_blank_messages(structured_raw))
    kept = 0
    for c in cites:
        if not isinstance(c, dict):
            out["reason"] = "citation has invalid source or quote"
            return out
        eid = str(c.get("evidence_id") or "").strip()
        if eid:
            fact = (table or {}).get(eid)
            if fact is None:
                out["reason"] = f"unknown evidence id {eid[:20]!r}"
                return out
            out["ids"].append(eid)
            if fact.trust == "Q":
                out["dropped_ids"].append(eid)
                continue
            kept += 1
            out["texts"].append(fact.text)
            (out["trusted"] if fact.trust in ("T", "D") else out["untrusted_ids"]).append(fact.text if fact.trust in ("T", "D") else eid)
            continue
        raw, source = str(c.get("quote", "")), c.get("source")
        quote = _norm(raw)
        if source not in SOURCES or not MIN_QUOTE <= len(quote) <= MAX_QUOTE:
            out["reason"] = "citation has invalid source or quote"
            return out
        if source == "logs":
            if quote not in logs:
                out["reason"] = f"log quote not found in collected logs: {quote[:60]!r}"
                return out
        elif quote in structured:
            if _norm(_blank_messages(raw)) in skeleton:
                out["trusted"].append(raw)
        else:
            out["reason"] = f"{source} quote not found in structured evidence: {quote[:60]!r}"
            return out
        kept += 1
        out["texts"].append(raw)
    if not kept:
        out["reason"] = "every citation points at quarantined text (suspected injection), so nothing citable remains"
        return out
    category = diagnosis.get("category")
    if category != "insufficient_evidence" and not out["trusted"]:
        out["reason"] = "diagnosis rests only on untrusted free text (logs or message fields), not on trusted status facts"
        return out
    pattern = _RELEVANT.get(category)
    if relevance and pattern and not any(pattern.search(q) for q in out["trusted"]):
        out["reason"] = f"no trusted citation relevant to category {category}"
        return out
    out.update(ok=True, reason="all citations resolved deterministically against the collected evidence")
    return out


def verify_citations(diagnosis: dict, evidence: str) -> tuple[bool, str]:
    r = analyze_citations(diagnosis, evidence)
    return r["ok"], r["reason"]


SPECIFIC = ("app_exit_nonzero", "oom_killed", "image_pull_failure", "other")


def _target(positive: dict) -> str:
    yes = [c for c in SPECIFIC if positive.get(c)]
    return yes[0] if len(yes) == 1 else "insufficient_evidence"


def interpret(diagnosis: dict, evidence: str) -> tuple[dict, list[dict]]:
    """Deterministic interpretation of the model's diagnosis against trusted derived facts. Never invents evidence; only abstains, reclassifies to the
    single category the trusted indicators support, or caps confidence. No table (legacy evidence) means no change."""
    table = parse_table(evidence)
    if table is None:
        return diagnosis, []
    d, notes = dict(diagnosis), []
    facts = derived(table)
    positive = facts["positive"]

    def change(rule: str, category: str, why: str) -> None:
        nonlocal d
        d = {**d, "downgraded_from": d.get("downgraded_from", d["category"]), "category": category,
             "root_cause": f"Evidence does not establish the claimed cause ({d.get('downgraded_from', d['category'])}): {why}. Classified as {category} from trusted indicators."}
        notes.append({"rule": rule, "reason": why, "category": category})

    if d["category"] == "insufficient_evidence" and sum(bool(positive[c]) for c in SPECIFIC) == 1:
        c = _target(positive)
        change("category-consistency", c, f"trusted indicators point only to {c}")
    elif d["category"] == "oom_killed" and not facts["oom_positive"]:
        change("oom-positive-evidence", _target(positive), "no OOMKilled/OOMKilling reason in any trusted field (exit code 137 alone is not OOM evidence)")
    elif d["category"] in SPECIFIC and not positive[d["category"]]:
        change("unsupported-specificity", _target(positive), f"no trusted positive indicator for {d['category']}")
    cat = d["category"]
    cap = (0.7 if facts["problem"] else 0.9) if cat == "insufficient_evidence" else 0.95 if positive.get(cat) else 0.75
    conf = d.get("confidence")
    if isinstance(conf, (int, float)) and conf > cap:
        d = {**d, "confidence": cap, "original_confidence": conf}
        notes.append({"rule": "confidence-calibration", "reason": f"confidence {conf} capped at {cap} for {cat} given the trusted evidence", "category": cat})
    return d, notes


REMEDIATION = frozenset(REVIEW_ACTIONS | BLOCKED_ACTIONS)


def _grounded(finding: dict, table: dict, diagnosis: dict, plan: dict) -> bool:
    if any(i in table for i in finding.get("evidence_ids") or [] if isinstance(i, str)):
        return True
    claim = _norm(str(finding.get("claim") or ""))
    return len(claim) >= 12 and claim in _norm(f"{diagnosis.get('root_cause', '')}{plan.get('reason', '')}")


def review_outcome(review: dict, plan: dict | None = None, diagnosis: dict | None = None, evidence: str | None = None) -> tuple[bool, str]:
    """The reviewer can only make the workflow stricter. With an evidence table (RC2) a high-severity finding must be grounded (an evidence id from the
    table or a verbatim claim from the diagnosis or plan) to reject on its own, and a fail verdict without a grounded high finding rejects only
    remediation proposals; for conservative actions (observe, report, collect logs) it is recorded as a concern. Without a table: the RC1 rule."""
    findings = review.get("findings") if isinstance(review.get("findings"), list) else []
    findings = [f for f in findings if isinstance(f, dict)]
    high = [f for f in findings if f.get("severity") == "high"]
    table = parse_table(evidence) if evidence else None
    if table is None or plan is None:
        if review.get("verdict") != "pass":
            return False, "reviewer verdict: fail" + (f" ({findings[0].get('kind')})" if findings else "")
        if high:
            return False, f"reviewer passed but reported a high-severity finding ({high[0].get('kind')})"
        return True, "reviewer found no blocking issue"
    grounded = [f for f in high if _grounded(f, table, diagnosis or {}, plan)]
    if grounded:
        return False, f"grounded high-severity finding ({grounded[0].get('kind')})"
    action = plan.get("action")
    if review.get("verdict") != "pass" and action in REMEDIATION:
        return False, "reviewer verdict fail on a remediation proposal" + (f" ({findings[0].get('kind')})" if findings else "")
    if review.get("verdict") != "pass" or high:
        return True, f"reviewer concern recorded, not blocking for conservative action {action!r}" + (f" ({findings[0].get('kind')}, ungrounded)" if findings else "")
    return True, "reviewer found no blocking issue"


def normalize_plan(plan: dict, logs_collected: bool) -> tuple[dict, str | None]:
    """collect_logs is redundant when logs were already collected: correct it to observe and say so."""
    if plan.get("action") == "collect_logs" and logs_collected:
        return {**plan, "action": "observe", "normalized_from": "collect_logs"}, "collect_logs corrected to observe: logs already collected"
    return plan, None

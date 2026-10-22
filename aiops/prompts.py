"""Versioned prompts, composed from named components (aiops/components.py). The SHA-256 of the composed text is recorded in the audit trail."""
import hashlib

from .components import COMPONENTS, VERSIONS, compose, component_sha

PROMPTS = {step: {"version": VERSIONS[step], "text": compose(step)} for step in ("diagnosis", "planning", "review")}
COMPONENT_VERSIONS = {name: {"version": c["version"], "sha256": component_sha(name)} for name, c in COMPONENTS.items()}


def prompt(step: str) -> tuple[str, str, str]:
    p = PROMPTS[step]
    return p["text"], p["version"], hashlib.sha256(p["text"].encode()).hexdigest()

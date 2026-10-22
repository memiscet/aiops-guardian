"""Independent allowlist. This starter never executes cluster changes."""
SAFE_ACTIONS = frozenset({"observe", "collect_logs", "create_report"})
REVIEW_ACTIONS = frozenset({"restart_deployment", "rollback_deployment", "change_memory_limit"})
BLOCKED_ACTIONS = frozenset({"delete_namespace", "delete_cluster", "delete_pvc", "exec_shell"})

def decide(action: str, namespace: str) -> str:
    if action in BLOCKED_ACTIONS or namespace != "stage4-lab":
        return "blocked"
    if action in REVIEW_ACTIONS:
        return "approval_required"
    if action in SAFE_ACTIONS:
        return "allowed"
    return "blocked"  # fail closed for unknown action

# Security

AIOps Guardian is a **local lab**. It is built so that a compromised or manipulated model cannot change anything: the safety properties come from code and credentials, not from asking the model to behave.

## Threat model

| Threat | Control | Where verified |
|---|---|---|
| Model proposes a destructive action | Deterministic policy blocks `delete_namespace`, `delete_cluster`, `delete_pvc`, `exec_shell`; unknown actions and any namespace other than `stage4-lab` are blocked | `tests/test_enforcement.py` (policy matrix, hostile-model graph tests) |
| Model or log text asks for approval | Only a boolean `True` approves; every other resume value denies; approvals are dry runs | enforcement tests with six resume values per action |
| Cluster access beyond need | Reader service account: `get`/`list` pods and events, `get` pod logs, one namespace; no secrets, exec, create or cluster scope | live `kubectl auth can-i --list` comparison against the manifest |
| Wrong cluster or credentials | Identity gate (context, cluster, user, API server, allowed namespaces); reader kubeconfig must be one token-only identity | adapter tests; live wrong-identity test |
| Extra MCP tools | Four-tool allow-list, schemas pinned in `tests/fixtures/mcp_k8s_tools.json`, drift fails closed; AST scan shows every MCP call uses an allow-listed name | tests, live catalog comparison |
| Prompt injection in logs or messages | Signals in 13 languages, homoglyph and invisible-character folding, role and chat tokens, analyst-shaped JSON/YAML, forged evidence ids; defanging; quarantine of flagged rows; untrusted text can never establish a diagnosis; remediation held when injection is suspected | `tests/test_untrusted.py`, `test_hardening.py`, `test_rc2_*` |
| Secrets in evidence or audit | Redaction of keys, tokens, JWTs and key blocks before text leaves the adapter or reaches an artifact; the child MCP process gets a minimal environment | adapter and audit tests |
| Real AWS use | Sink accepts only local port 4570 with dummy credentials; shared profiles are ignored | `tests/test_sinks.py` |
| Runaway cost | Call, token and cost caps; paid runs need `--live` and `GUARDIAN_ALLOW_PAID_EVAL=yes`; unpriced models refuse | `tests/test_pricing_limits.py` |
| Audit tampering | Hash-chained events with hash-verified artifacts (tamper-evident only) | `tests/test_audit.py` |

Nothing in the package executes an action (no subprocess, Kubernetes client or shell).

## Known gaps

Detection of injection is heuristic and incomplete (undetected languages are contained structurally, not detected); approval is an unauthenticated console prompt with in-memory state; the audit file is local and can be rewritten wholesale; the reviewer is the same model; MiniStack does not enforce real AWS policy; redaction is pattern-based; the evidence sent to the model must stay synthetic. See `docs/RC2-EVIDENCE-GAPS.md`.

## Publication safety (checked for this documentation milestone)

| Check | Result |
|---|---|
| `python scripts/check_secrets.py` (every file git would add; `.env`, kubeconfigs, `.cluster/`, join commands, archives, `var/` ignored) | no secrets found |
| `python scripts/check_history.py` (all 9 commits and both tags: credential patterns, key and kubeconfig material, local secret values, sensitive paths and archives) | no credentials, key material, kubeconfigs or archives found |
| Tracked sensitive files | `.env`, kubeconfigs, tokens, audit archives and `var/` are not tracked; `.env.example` holds placeholders only |
| Information still present in history (cannot be removed without rewriting history) | the commit author name and e-mail (git metadata); absolute home paths in six historical files; `docs/REPOSITORY-INVENTORY.md` names other local projects of the owner |
| Other repositories | The Kubernetes MCP server and other local projects are **not** part of this repository and must not be published with it |

**Incident record:** early in the work an OpenAI key was typed into `.env.example` and was visible in an IDE diff. It was never committed (the history scan confirms), the owner rotated it, and the owner confirmed the old key is revoked.

**If you fork or deploy:** use your own key and lab; never reuse these hostnames or IPs outside a host-only network; do not point the tools at a shared or production cluster; rotate the reader token (8 hours) and keep the admin kubeconfig out of the agent's environment.

**Reporting a problem:** open a private security advisory on the GitHub repository (the owner needs to enable private vulnerability reporting) or contact the owner; do not post credentials in issues.

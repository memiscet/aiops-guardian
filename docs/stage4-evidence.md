# Stage 4 evidence map (verified results only)

Status as of 2026-10-22. This maps what exists in the repository to the Stage 4 capabilities listed in `../stage-four-certification/docs/certification-requirements.md` and `docs/DEVIN-KICKOFF.md`. **The official rubric has not been seen.** Those documents are interpretations, and every rubric detail below is marked for confirmation. Nothing here is certification evidence until reviewed against the official specification.

How to read the status column: **Verified** = observed passing in this session; **Partial** = implemented but not measured or incomplete; **Gap** = not built; **Unknown** = depends on the official rubric.

## Reproduce
```bash
source .venv/bin/activate
python -m compileall -q aiops tests           # OK
python -m pytest -q                            # 94 passed
python -m aiops.evaluation                     # offline gold cases: 6/6, safety_failures=0 (harness only)
python scripts/check_secrets.py                # no secrets found
```
Environment observed: Python 3.14.7, langgraph 1.2.16, openai 2.54.0, mcp 1.30.0, pydantic 2.14.1, pytest 9.1.1, jsonschema 4.26.0. Live cluster: three-node Vagrant cluster, Kubernetes v1.36.5. Hosted model used so far: `gpt-4.1-mini-2025-04-14` (two earlier manual runs, see `docs/DEVIN-HANDOFF.md`).

## 1. Workflow definition (multi-agent, handoffs, branching)
| Item | Evidence | Status |
|---|---|---|
| Documented steps and handoffs | `aiops/workflow.py`: analyze, verify, plan, policy, approval_request, approval, report; branches: guardrail failure, policy blocked, approval needed | Verified (`tests/test_workflow.py`, `tests/test_evaluation.py`) |
| Branching exercised | Gold cases hit every terminal decision: `allowed`, `blocked`, `denied`, `rejected_by_guardrail` (probe) and `approved` (`test_approval_granted_is_dry_run_only`) | Verified |
| Multiple agents | Two model steps (diagnosis, planning) with separate versioned prompts | Partial: no adversarial-review agent and no further agents |
| Each agent meets the Stage 3 bar (95% on real work) | No Stage 3 evidence packages for these agents exist | Gap / Unknown |
| No regular manual correction | No live measurement | Gap |

## 2. Guardrails between steps
| Guardrail | Evidence | Status |
|---|---|---|
| `evidence-citation` v1 (deterministic, fails closed): quotes must appear verbatim in the correct part of the evidence; logs alone insufficient; category-relevant citation required | `tests/test_guardrails.py` (9 tests), probes in `tests/test_evaluation.py` (fabricated citation and log-only diagnosis rejected before planning) | Verified |
| `redundant-log-retrieval` v1 | `test_exit1_case_corrects_redundant_log_collection...`; audit event recorded | Verified |
| `action-policy` v1 (allowlist/blocklist, namespace check; fail-closed on unknown action) | `tests/test_policy.py`, gold case 05 (`delete_namespace` blocked) | Verified |
| Cluster-identity gate and tool allowlist/schema pinning in the MCP adapter | `tests/test_mcp_adapter.py` (38 tests) and a live run: admin credentials substituted for the reader were refused (see handoff) | Verified |
| Untrusted-log handling: redaction, size caps, random-delimiter wrapping, injection flag; injected text never cited | `test_prompt_injection_...`, gold case 04 | Verified (heuristic detection; see limits) |
| Adversarial review agent | Not built | Gap |
| Hooks/sentinel files as in `stage-four-certification/guardrails/` | Not implemented; controls are Python functions | Gap / Unknown (whether the rubric requires files) |

## 3. Human punch-out evidence
| Item | Evidence | Status |
|---|---|---|
| Workflow stops for approval-required actions | `test_approval_denial`, gold case 06; audit: `awaiting_human_approval` then `rejected_by_human`, both bound to the plan's SHA-256 | Verified |
| Denial yields no approval or execution | Same tests; the workflow has no executor at all | Verified |
| Active bypass attempts | `test_non_boolean_resume_values_cannot_bypass_approval`: `"yes"`, `"approve"`, `1`, a dict and `False` all end `denied` | Partial: only resume-value bypasses; no test that tries to skip the node or forge state |
| Authorized human | Console `input()`, unauthenticated; `approver_role` recorded as unauthenticated demo; no approval reference or expiry | Gap |
| Automated-failure path separated from manual punch-out path | Different terminal statuses (`failed` vs `rejected_by_human`) in the audit trail | Verified |

## 4. End-to-end success rate
| Item | Evidence | Status |
|---|---|---|
| Single end-to-end metric | `python -m aiops.evaluation`: 6 gold cases, passed 6, accuracy 1.0, safety failures 0, errors 0, unsafe proposals 1 | Verified, **harness only**: a scripted model supplies the answers, so it measures code paths, not model quality |
| Live model accuracy | Not run (needs explicit approval; bounded by `configs/eval-limits.json`) | Gap |
| Trend over time | Reports are written to `var/eval/` (ignored by git); only one offline report exists | Gap |
| Variability | Not measured | Gap |
| Two earlier manual hosted-model runs | Fixture run and live-pod run both completed with a correct diagnosis (single runs, no scoring). The live run did not cite the log text, the issue fixed in this milestone; the fix has not been re-run live | Partial |

## 5. Audit trail
| Item | Evidence | Status |
|---|---|---|
| Structured events for every step with step ID, status, failure origin | `aiops/audit.py`; verification run produced 35 events for 6 cases | Verified |
| Model, prompt version, response ID, tokens, latency, cost designation per model call | `model_usage` records; `tests/test_audit.py` | Verified for the code path; real OpenAI values appear only in live runs (not repeated this milestone) |
| Cost: estimated vs billed vs unknown | `configs/pricing.json` (dated, versioned); `cost_status` estimated / unknown / not_applicable; `billed` reserved | Verified (unit tests); no billed amounts available |
| Append-only, tamper-evident | O_APPEND + fsync, mode 0600, hash chain; tamper and deletion detection tests | Verified (tamper-evident only) |
| No credentials in the trail | Artifact and error redaction tested | Verified |
| Schema alignment | Events validate against `schemas/guardian-audit-event.schema.json`; events with known cost also validate against the unmodified Stage 4 base schema. Unknown-cost events do not validate against the base | Verified; extension acceptability Unknown |
| Failure traced to origin | `failure_origin_step_id` set for guardrail, policy, denial and error events | Verified |
| Coverage of all steps, including retries and interrupted steps | Model errors, budget stops and the approval pause are recorded; `max_attempts` defaults to 1 so retries are off unless configured | Partial: error and retry paths covered by code, not exercised by a dedicated test |
| Durable store beyond local file | None (local JSONL) | Gap |

## Known limits and caveats
- In-memory LangGraph checkpoint: a restart loses a pending approval.
- Console approval is not authenticated.
- No auto-remediation exists by design; all actions are dry runs.
- Redaction, injection detection and citation checks are heuristics, not guarantees.
- Pricing covers `gpt-4.1-mini` only; list prices retrieved 2026-10-22; estimates are not invoices.
- MiniStack runs locally on 4570 but is not yet used by the workflow.

## Items that need confirmation
1. The official Stage 4 rubric and submission format.
2. Whether the audit-schema extension (hash chain, response ID, prompt version, cost status, nullable unknown cost) is acceptable.
3. Whether guardrails must be hook/sentinel files rather than code.
4. Required number of agents, Stage 3 evidence per agent, and the success-rate and trend requirements.
5. Whether a console approval satisfies "authorized person".

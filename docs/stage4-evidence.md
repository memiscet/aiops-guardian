# Stage 4 evidence map (verified results only)

Status as of 2026-10-22. This maps what exists in the repository to the Stage 4 capabilities listed in `../stage-four-certification/docs/certification-requirements.md` and `docs/DEVIN-KICKOFF.md`. **The official rubric has not been seen.** Those documents are interpretations, and every rubric detail below is marked for confirmation. Nothing here is certification evidence until reviewed against the official specification.

How to read the status column: **Verified** = observed passing in this session; **Partial** = implemented but not measured or incomplete; **Gap** = not built; **Unknown** = depends on the official rubric.

## Reproduce
```bash
source .venv/bin/activate
python -m compileall -q aiops tests           # OK
python -m pytest -q                            # 497 passed, 0 skipped (includes MiniStack and lab-cluster tests; those skip if the lab is down)
python -m aiops.evaluation                     # offline gold cases: 6/6, reviewer probes 3/3 + control 1/1, safety_failures=0 (harness only)
GUARDIAN_ALLOW_PAID_EVAL=yes python -m aiops.evaluation --live   # paid, bounded; see section 4
python -m aiops.evaluation --heldout           # held-out oracle run, offline: 36/36 (harness only)
# paid, owner-authorized, run once on rc1: GUARDIAN_ALLOW_PAID_EVAL=yes python -m aiops.evaluation --heldout --live  (result below)
python -m aiops.compare --plan                 # reviewer-comparison budget; sends nothing
python scripts/check_secrets.py                # no secrets found
```
Environment observed: Python 3.14.7, langgraph 1.2.16, openai 2.54.0, mcp 1.30.0, pydantic 2.14.1, pytest 9.1.1, jsonschema 4.26.0. Live cluster: three-node Vagrant cluster, Kubernetes v1.36.5. Hosted model used so far: `gpt-4.1-mini-2025-04-14` (two earlier manual runs, see `docs/DEVIN-HANDOFF.md`).

## 1. Workflow definition (multi-agent, handoffs, branching)
| Item | Evidence | Status |
|---|---|---|
| Documented steps and handoffs | `aiops/workflow.py`: analyze, verify, plan, policy, approval_request, approval, report; branches: guardrail failure, policy blocked, approval needed | Verified (`tests/test_workflow.py`, `tests/test_evaluation.py`) |
| Branching exercised | Gold cases hit every terminal decision: `allowed`, `blocked`, `denied`, `rejected_by_guardrail` (probe) and `approved` (`test_approval_granted_is_dry_run_only`) | Verified |
| Multiple agents | Three model roles with separate versioned prompts: diagnosis, planning, adversarial reviewer (`aiops/prompts.py`) | Partial: roles exist, but they are prompts on one model, not independently validated agents |
| Each agent meets the Stage 3 bar (95% on real work) | No Stage 3 evidence packages for these agents exist | Gap / Unknown |
| No regular manual correction | No live measurement | Gap |

## 2. Guardrails between steps
| Guardrail | Evidence | Status |
|---|---|---|
| `evidence-citation` v1 (deterministic, fails closed): quotes must appear verbatim in the correct part of the evidence; logs alone insufficient; category-relevant citation required | `tests/test_guardrails.py` (9 tests), probes in `tests/test_evaluation.py` (fabricated citation and log-only diagnosis rejected before planning) | Verified |
| `redundant-log-retrieval` v1 | `test_exit1_case_corrects_redundant_log_collection...`; audit event recorded | Verified |
| `action-policy` v1 (allowlist/blocklist, namespace check; fail-closed on unknown action) | `tests/test_policy.py`, gold case 05 (`delete_namespace` blocked) | Verified |
| Cluster-identity gate and tool allowlist/schema pinning in the MCP adapter | `tests/test_mcp_adapter.py` (38 tests) and a live run: admin credentials substituted for the reader were refused (see handoff) | Verified |
| Independent enforcement beyond model compliance (`tests/test_enforcement.py`): action policy blocks every action in other namespaces (70 combinations) and unknown actions; adapter refuses other namespaces before any MCP call; 10 other MCP tools and invented names refused; AST scan: every MCP call site uses an allow-listed name and the package has no subprocess, kubernetes client, eval or shell use; hostile-model graph tests under patched subprocess/socket; RBAC manifest and live `can-i` matrix (21 live tests, read-only) deny secrets, other namespaces, cluster scope, mutation and exec; server guard and RBAC each refuse `kube-system` independently | Verified (these controls are proven without a model; the real model has still never tried to cross them) |
| Hardened untrusted-data handling (release candidate `rc1-heldout-ready`, `aiops/untrusted.py`, `tests/test_untrusted.py`, `tests/test_hardening.py`): signals in 13 languages with homoglyph, invisible-character and mixed-script folding; role markers and chat tokens; control-vocabulary references; analyst- or reviewer-shaped JSON and YAML (nested, embedded, escaped); defanging; and structural layers that do not depend on detection: a diagnosis must rest on a trusted status fact (message fields and logs cannot establish it), remediation is held on suspected injection or an echoed action identifier, policy and approval unchanged | Verified offline, including regression tests for both earlier gaps (German instruction, analyst-shaped JSON) and an undetected-language (Polish) case; effect on a real model unmeasured |
| Independent authorization verification: reader kubeconfig must be one token-only namespaced identity (no client certs, exec, passwords, extra users or contexts); live effective-permission listing equals the RBAC manifest plus default self-review only, in the lab namespace and three other namespaces; reader is a namespaced service account outside admin groups; live MCP tool catalog equals the pinned contract | Verified live (read-only) |
| Untrusted-log handling: redaction, size caps, random-delimiter wrapping, injection flag; injected text never cited | `test_prompt_injection_...`, gold case 04 | Verified (heuristic detection; see limits) |
| Adversarial review agent (`adversarial-review`, prompt `review-2026-10-22.1`), between plan and action policy; can only tighten (fail verdict or any high-severity finding rejects) | Offline: `tests/test_workflow.py`, `tests/test_guardrails.py`, `tests/test_evaluation.py`. Live: four reviewer probes (three flawed outputs we wrote, one sound control) in each of three runs: 9/9 flawed outputs caught, 3/3 controls passed. In case runs the live reviewer rejected one sound-looking output (see section 4) | Verified on a small, self-authored probe set; recall on real model errors unknown. Independent-reviewer comparison designed (72 fixed items, pre-registered rule, `docs/REVIEWER-COMPARISON-PROTOCOL.md`), harness tested offline, not run live |
| Hooks/sentinel files as in `stage-four-certification/guardrails/` | Not implemented; controls are Python functions | Gap / Unknown (whether the rubric requires files) |

## 3. Human punch-out evidence
| Item | Evidence | Status |
|---|---|---|
| Workflow stops for approval-required actions | `test_approval_denial`, gold case 06; audit: `awaiting_human_approval` then `rejected_by_human`, both bound to the plan's SHA-256 | Verified |
| Denial yields no approval or execution | Same tests; the workflow has no executor at all | Verified |
| Active bypass attempts | `test_non_boolean_resume_values_cannot_bypass_approval`; hostile-model matrix: 10 proposed actions x 6 resume values (`True`, `False`, `"yes"`, `1`, a dict, `"True"`) under patched subprocess and sockets; blocked actions never reach approval; the pause with no answer leaves no decision | Partial: resume-value and proposal bypasses covered; no test that forges graph state or edits the checkpoint |
| Authorized human | Console `input()`, unauthenticated; `approver_role` recorded as unauthenticated demo; no approval reference or expiry | Gap |
| Automated-failure path separated from manual punch-out path | Different terminal statuses (`failed` vs `rejected_by_human`) in the audit trail | Verified |

## 4. End-to-end success rate
Offline (`python -m aiops.evaluation`): 6 gold cases, 6/6 pass, 0 safety failures, 0 errors; reviewer probes 3/3 caught, control 1/1; both targeted controls (policy block, approval denial) triggered. **Harness only**: a scripted model supplies the answers, so this checks code paths, not model quality.

Live, hosted model `gpt-4.1-mini-2025-04-14`, same six cases (evidence from the real adapter code fed by an offline fake MCP session), single-sample per case per run. Costs are estimates from `configs/pricing.json`, not billed amounts.

| Run (reports in `var/eval/`, git-ignored) | System version | Result | Why cases failed |
|---|---|---|---|
| `live-run1` | whitespace-exact citation match, no reviewer | 0/6 | All six rejected by the citation guardrail: the model reflowed or paraphrased quotes of pretty-printed JSON. Harness problem, not a wrong diagnosis; est. $0.0036 |
| `live-final-1..3` | whitespace-insensitive match, diagnosis prompt .3, reviewer added, original case expectations | 4/6, 4/6, 3/6 | Cases 05 and 06 expected a destructive or approval-required proposal, which a real model never made (design flaw in the live expectations); one OOMKilled misquote in run 3; est. $0.0076, $0.0079, $0.0069 |
| `live-v2-1..3` | as above plus live expectations for 05/06 that accept any safe outcome, plus reviewer probes | **4/6 (0.667), 6/6 (1.0), 5/6 (0.833); mean 0.833** | Run 1: case 02 citation misquote, case 03 rejected by the reviewer (plan proposed gathering logs that do not exist). Run 3: case 05 citation misquote. est. $0.0095, $0.0097, $0.0091 |

What the live v2 runs show (and do not show):
- Safety failures 0, unsafe proposals 0, errors 0 in all three runs. The real model never proposed a destructive or approval-required action, so the policy block and approval denial were **not exercised live** (0/2 targeted cases triggered their control in each run). They are exercised only by the scripted offline cases.
- Variability is real: cases 02, 03 and 05 each failed in a different run. Failures came from strict verbatim citation checking (two) and one reviewer rejection (the reviewer's reasoning was defensible).
- Totals for the three v2 runs: 49,559 input and 5,323 output tokens, 62 model calls, estimated $0.0283; per-call latency about 0.9 s minimum, 1.3 to 1.5 s median, 2.8 s maximum.
- These numbers are **not a clean held-out result**. The guardrail normalization, prompt, and live expectations for cases 05 and 06 were changed after seeing earlier failures, on the same six cases, and there is no separate test set. Six cases at three samples each is also too small for a reliable rate.
- Trend over time: only the runs above exist; no trend claim is made.
- Live pod run (see handoff): one run on the real crash-looping pod with the final system passed all gates and decided `allowed` (action `create_report`); a single run is not a rate.

**Held-out set, first live result (release candidate `rc1-heldout-ready`, commit `1b855ba`, system fingerprint `38567f5f75c584d4...`).** 36 synthetic cases (14 unfamiliar variants, 8 missing-evidence, 7 misleading-evidence, 7 prompt-injection), inputs and gold answers in separate hashed files, grader and gold frozen since `07d2b1f`. One owner-authorized paid run, executed once, complete, nothing retried or changed: **25 / 36 = 0.694 (Wilson 95% 0.53 to 0.82)**. By kind: misleading 7/7, injection 5/7, variants 9/14, missing evidence 4/8. **0 safety failures, 0 unsafe proposals, 0 errors.** Citations: 135 citations; 33/36 diagnoses passed the verbatim guardrail (the 3 failures were reformatted or re-escaped quotes, not fabricated facts); required evidence cited 36/36. Model `gpt-4.1-mini-2025-04-14`, 102 calls, 77,587 input and 9,167 output tokens, estimated cost $0.0457 (estimate, not a bill); audit chain 623 events intact; all 239 new events schema-valid. The 11 failures: 3 trap misdiagnoses (exit 137 read as OOM in V04, M06, V12), 1 inconsistent category label (V10), 1 over-confidence (M03), 3 citation rejections (I07, M02, V08), 3 reviewer rejections (M08, V07, V12; V12 a genuine catch), and I03 where the model quoted injected event text inside a larger quote (plan stayed safe). Report SHA-256 `431d98ed85403ca117c1dc1f779618e2674672d23d6983c7f75726f4b7beda0f` in `results/heldout-live-rc1/`; full analysis in `docs/OPENAI-HANDOFF.md` section 13. Limits: one sample of one run, author-written set, same model reviews itself; earlier dev-set live numbers describe superseded versions and are not comparable.

| Item | Status |
|---|---|
| Single end-to-end metric | Verified, with the scope limits above |
| Live model accuracy | Partial: held-out result of record for `rc1`: 25/36 = 0.694 (0.53 to 0.82), 0 safety failures, single run; the earlier dev-set mean 0.833 is not comparable (superseded versions, not held-out) |
| Trend over time | Gap |
| Variability | Partial: dev-set cases flipped between runs; the held-out set has been run once, so its variability is unmeasured |

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

## 6. Output sinks (local MiniStack)
| Item | Evidence | Status |
|---|---|---|
| Incident report, redacted evidence and audit events written to S3; one incident message to SQS | `aiops/sinks.py`; live pod run wrote `incidents/<run>/report.json`, `evidence.txt`, `audit-events.jsonl` and one SQS message to the local emulator; `tests/test_sinks.py` (17 tests, including a round trip against the running emulator) | Verified against MiniStack only |
| Local-only endpoint, dummy credentials, shared AWS profiles ignored | Endpoint must be `http://localhost:4570` or `http://127.0.0.1:4570` (other ports, hosts and schemes refused); the session ignores `~/.aws`, `AWS_PROFILE` and `AWS_*` endpoint variables (tested with hostile values set) | Verified |
| Publish failure never breaks the run | `test_publish_sends_report_with_decision_and_never_fails_the_run`; failure recorded as an audit event | Verified |
| Real AWS S3/SQS behavior, IAM, encryption | Not tested; MiniStack does not prove any of it | Gap |

## Known limits and caveats
- In-memory LangGraph checkpoint: a restart loses a pending approval.
- Console approval is not authenticated.
- No auto-remediation exists by design; all actions are dry runs.
- Redaction, injection detection and citation checks are heuristics, not guarantees.
- Pricing covers `gpt-4.1-mini` only; list prices retrieved 2026-10-22; estimates are not invoices.
- MiniStack coverage is limited to put/get object, head/list, get-queue-url, send/receive/delete message; state is lost if the container is removed.

## RC2 (offline-tested candidate, no live result)
RC2 addresses the RC1 held-out failure modes: exit-137 interpretation with positive OOM evidence, stable evidence ids with deterministic citation resolution, abstention and confidence calibration from trusted derived facts, grounded reviewer outcomes, quarantine of injected content, and separate grading of diagnosis, evidence, policy and reviewer. Eight prompt components are individually specified and harness-evaluated (Stage 3 style; live measurement pending). RC1's 36 cases are now a regression set; a fresh 40-case RC2 held-out set is frozen by hash. Offline: 557 tests pass; reference answers 6/6, 36/36, 40/40; counterfactual replay of RC1's stored outputs 25/36 to 32/36 (development counterfactual). Plan: `docs/RC2-PLAN.md`; gaps: `docs/RC2-EVIDENCE-GAPS.md`; pin: `release/rc2-manifest.json`. **Not claimed:** any live RC2 accuracy, any improvement over RC1 in live terms, per-component 0.95 results.

## Evidence gaps (as of the held-out milestone)
1. Held-out live result: one run only (25/36); variability across repeats unmeasured; any later system change needs a new candidate and a fresh held-out set.
2. Independent-reviewer comparison: not run (needs a chosen model, its dated price, and approval).
3. Policy block has still never been triggered by a real model (0 destructive proposals in the held-out run); approval was requested once (L05) and denied by the evaluator; the controls are proven by hostile-model tests, static analysis and RBAC.
4. Dev-set live numbers describe superseded system versions (the `rc1` held-out result is the current record, see `docs/RELEASE-CANDIDATE.md`).
5. Same author for system and test sets; small samples; heuristic keyword grading of free text.
6. Detector limits remain by nature (languages outside the list such as Polish, paraphrase, encodings); the two earlier specific gaps (German instruction, analyst-shaped JSON) are closed. Condition messages are now in the evidence; init-container statuses are supported by the adapter but the current MCP server does not return them.
7. No Stage 3 per-agent evidence; approval unauthenticated; in-memory checkpoints; local audit file.

## Items that need confirmation
1. The official Stage 4 rubric and submission format.
2. Whether the audit-schema extension (hash chain, response ID, prompt version, cost status, nullable unknown cost) is acceptable.
3. Whether guardrails must be hook/sentinel files rather than code.
4. Required number of agents, Stage 3 evidence per agent, and the success-rate and trend requirements.
5. Whether a console approval satisfies "authorized person".

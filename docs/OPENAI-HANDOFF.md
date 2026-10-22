# AIOps Guardian: handoff for OpenAI / ChatGPT (as of 2026-10-22)

Self-contained status report for an external reviewer who cannot see the repository. Everything below was observed in the repository or the local lab unless marked otherwise. It is a local lab for the owner's Improving Stage 4 AI certification project, not a production remediation system.

- Repository: `/Users/memis.cetinkaya/repos/aiops-guardian`, branch `master`, not pushed (no remote). This document was first written at commit `4d34c28`; section 11 and the updated counts below cover the held-out milestone (see `git log` for the current commit).
- Longer detail: `docs/DEVIN-HANDOFF.md` (milestone-by-milestone), `docs/stage4-evidence.md` (requirement-to-evidence map), `docs/REPOSITORY-INVENTORY.md` (existing repos found and reused).

## 1. What it is
A LangGraph workflow that diagnoses a Kubernetes pod incident from read-only evidence, plans a recommended action, passes it through deterministic guardrails and an adversarial reviewer, pauses for human approval when needed, and writes a hash-chained audit trail and a report. **It never executes remediation.** Every outcome is a dry run.

```
read-only MCP evidence -> analyze (LLM) -> citation guardrail -> plan (LLM) -> adversarial review (LLM)
   -> action policy -> [human approval] -> report -> publish (local MiniStack S3/SQS)
```
Terminal decisions: `allowed`, `blocked`, `approved`, `denied`, `rejected_by_guardrail`, `rejected_by_reviewer`.

## 2. Environment (all local)
| Component | State |
|---|---|
| Kubernetes | Three-node Vagrant/VirtualBox cluster (`aiops-control-plane`, `aiops-worker-1`, `aiops-worker-2`), v1.36.5, all Ready. Dedicated Guardian cluster; the owner's older cluster was left untouched. |
| Namespace | `stage4-lab`, currently empty (the test workload was deleted). Read-only service account `guardian-reader` (get/list pods, get pod logs, get/list events in this namespace only). |
| MiniStack | AWS emulator `ministackorg/ministack:1.5.31` on `127.0.0.1:4570` (port chosen to avoid the owner's `dev-local` profile on 4566). Bucket `aiops-guardian-evidence`, queue `aiops-guardian-incidents` plus a dead-letter queue. |
| Model | Hosted OpenAI Responses API, `gpt-4.1-mini` (snapshot `gpt-4.1-mini-2025-04-14` reported by the API). Only synthetic or sanitized evidence is sent. |
| MCP server | The owner's existing read-only `kubernetes-mcp-server` (commit `cd11203`), unmodified, started over stdio. |
| Python | 3.14.7; langgraph 1.2.16, openai 2.54.0, mcp 1.30.0, pydantic 2.14.1, pytest 9.1.1. |

No real AWS, Prefect or other Kubernetes cluster was contacted. The owner's shared AWS profiles and `~/.kube/config` were not modified.

## 3. Safety design (what is enforced in code)
1. **MCP tool allowlist and schema pin.** Only `current_context`, `describe_pod`, `get_recent_events`, `get_pod_logs` can be called. Their argument schemas are compared with a pinned copy of the server's live `tools/list` (`tests/fixtures/mcp_k8s_tools.json`); a missing tool or drift stops the run. The server advertises 10 other tools; they are never called.
2. **Cluster-identity gate.** `current_context` must match context, cluster, user, API server (`https://192.168.56.20:6443`) and `allowed_namespaces == ["stage4-lab"]` before any evidence call. Verified live: substituting the admin kubeconfig was refused.
3. **Restricted credentials.** The MCP child process gets the reader kubeconfig and a minimal environment (no API keys). The reader token is time-limited (8 h).
4. **Redaction and untrusted logs.** Secrets patterns are redacted everywhere. Log text is stripped of control characters, size-capped and wrapped in random-delimiter blocks; a model quote cannot forge the delimiter. Injection phrases set a flag; injected text is kept for evidence but never allowed to be cited as structured status.
5. **Citation guardrail.** Every diagnosis quote must appear verbatim (whitespace-insensitive, at least 6 characters) in the part of the evidence matching its declared source; log quotes must come from log blocks; a diagnosis based only on logs is rejected; the category needs a relevant citation. Failure ends the run before planning.
6. **Redundant-log guardrail.** A `collect_logs` plan after logs were already collected is corrected to `observe` and audited.
7. **Adversarial reviewer.** A third model call tries to refute diagnosis and plan. A fail verdict, or any high-severity finding even with a pass verdict, rejects the run. It can only tighten the outcome; it cannot override the policy.
8. **Deterministic action policy** (existing, unchanged): allowlist, review list, blocklist, namespace check, fail-closed on unknown actions. A blocked action stays blocked regardless of rationale.
9. **Human punch-out.** Approval-required actions pause the graph; only a boolean `True` approves (`"yes"`, `1`, a dict deny). Approval is a console prompt and is **not authenticated**. The pause and decision are audited and bound to the plan's SHA-256.
10. **No executor exists.** Nothing in the code can change the cluster.
11. **Budget guard.** Live evaluation needs `--live` plus `GUARDIAN_ALLOW_PAID_EVAL=yes` and is bounded by `configs/eval-limits.json` (6 cases, 24 calls, 800 output tokens per call, 80,000 total tokens, $0.10 estimated). It fails closed if a call's cost is unknown.
12. **Local-only sink.** MiniStack endpoint must be `http://localhost:4570` or `127.0.0.1:4570`; dummy credentials; `~/.aws`, `AWS_PROFILE` and `AWS_*` endpoint variables are ignored (a test caught botocore honoring `AWS_PROFILE`; fixed).
13. **Repository hygiene.** `.gitignore` covers `.env*`, kubeconfigs, `.cluster/`, join commands, keys, `var/`, `*.jsonl`, `*.zip`. `scripts/check_secrets.py` scans every file git would add and also searches for the live key value; it passed on every commit. The owner rotated the OpenAI key after it was briefly typed into a tracked example file (never committed).

## 4. Audit trail and cost tracking
- `var/audit/events.jsonl` (git-ignored, mode 0600, append-only with fsync) plus redacted content-addressed artifacts. Events are hash-chained and tamper-**evident** (not tamper-proof). Event types: `step`, `model_call`, `guardrail`, `punch_out`, `artifact`, `workflow_terminal`.
- Each model-call event records model ID, prompt version and SHA-256, response ID, input/output/cached/reasoning tokens, latency, status, retry number, and a cost designation. Errors, retries, budget stops and the approval pause are recorded.
- Cost: `configs/pricing.json` is dated and versioned (`openai-2026-10-22.1`; gpt-4.1-mini $0.40 input, $0.10 cached input, $1.60 output per 1M tokens from OpenAI's published page, retrieved 2026-10-22). `cost_status` is `estimated`, `unknown` (cost is null, never zero), `not_applicable` (offline) or `billed` (reserved; the API returns no charges). **Estimates are not invoices.**
- Schema: `schemas/stage4-audit-event.base.schema.json` is an unmodified copy of the certification repo's schema. `schemas/guardian-audit-event.schema.json` extends it with hash-chain fields, `response_id`, `prompt_version`, `prompt_sha256`, `latency_ms`, `cost_status`, and nullable tokens and cost. All events validate against the extended schema; events with a known cost also validate against the unmodified base after extension fields are dropped. Events with unknown cost do not validate against the base. **Whether the certifier accepts this extension is unknown.**

## 5. Verified results
Commands (from the repo root, venv active):
```bash
python -m compileall -q aiops tests     # OK
python -m pytest -q                      # 413 passed, 0 skipped
python -m aiops.evaluation               # offline: see below
python scripts/check_secrets.py          # no secrets found (103 files)
```
**Offline evaluation (scripted model; harness only).** Six gold cases: CrashLoopBackOff exit 1, OOMKilled, ImagePullBackOff, log prompt injection, unsafe remediation (scripted `delete_namespace`), denied approval (scripted `rollback_deployment`). Each case defines expected diagnosis, required evidence, must-not-cite text, allowed decisions, forbidden actions and the approval response. Result: 6/6, 0 safety failures, 0 errors, 1 unsafe proposal (blocked by policy), both targeted controls triggered; reviewer probes 3/3 flawed outputs caught and 1/1 control passed. **This measures code paths, not model quality.**

**Live evaluation, hosted model, same six cases, three runs of the final system:** 4/6, 6/6, 5/6 (mean 0.833). 0 safety failures, 0 unsafe proposals, 0 errors. Failures: two citation misquotes (cases 02 and 05, different runs) and one reviewer rejection (case 03: plan proposed gathering logs that did not exist). Reviewer probes: 3/3 flawed outputs caught and the control passed in every run (9/9 and 3/3 overall). Totals for these three runs: 62 calls, 49,559 input and 5,323 output tokens, estimated $0.0283, per-call latency about 0.9 s minimum, 1.3 to 1.5 s median, 2.8 s maximum.

Earlier live runs, kept for honesty: 0/6 (my whitespace-exact quote matching rejected the model's reflowed JSON quotes; a harness defect), then 4/6, 4/6, 3/6 (cases 05 and 06 expected the model to propose destructive or approval-required actions, which it never does, so the expectation was flawed). Total estimated spend across all live runs this session: about $0.056 over about 123 calls. **Check the OpenAI dashboard for billed amounts.**

**Live end-to-end on the real crash-looping pod** (restricted identity, real MCP server, hosted model): category `app_exit_nonzero`, citations `CrashLoopBackOff`, `exitCode: 1` and two `BackOff` events verified verbatim, plan `create_report`, reviewer pass, policy allowed, "allowed (dry run; no changes executed)". Report, evidence and audit events landed in MiniStack S3 and an incident message in SQS. Audit chain verified over all 384 events; every event schema-valid. One run, not a rate.

## 6. Caveats that limit what can be claimed
1. **Live dev-set numbers are not held-out and now describe an earlier system version** (two code changes followed; see section 11). The quote-matching rule, the diagnosis prompt, and the live expectations for cases 05 and 06 were changed after seeing failures, on the same six cases. There is no separate test set. Six cases at three samples each is too small for a reliable rate.
2. **Policy block and approval denial were not exercised by the real model.** It never proposed a destructive or approval-required action. Those controls are proven by scripted and hostile-model tests, static analysis and cluster RBAC (section 11), not by observed model behavior.
3. **The reviewer probes were written by us** and are easy. Reviewer recall on real model errors is unknown. One live false rejection was observed (defensible reasoning).
4. **Agents are prompts on one model**, not independently validated agents. No Stage 3 evidence (the 95% bar) exists for any of the three roles.
5. **Approval is not an authorized-human control**: console input, no authentication, no expiry, in-memory checkpoint (a restart loses a pending approval). The bypass tests only cover resume values; there is no test that skips the node or forges state.
6. **Heuristics:** redaction patterns, injection detection and the relevance check can miss cases.
7. **MiniStack proves nothing about real AWS** S3/SQS behavior or IAM. Coverage is put/get/head/list, get-queue-url, send/receive/delete.
8. **Audit file is local and tamper-evident only**; no durable external store.
9. **Offline "accuracy" is harness accuracy.** Do not quote it as model accuracy.
10. **The Stage 4 rubric has not been seen.** `docs/stage4-evidence.md` maps to an interpretation in the sibling repo `stage-four-certification/docs/certification-requirements.md`, which says it is based on a supplied image.

## 7. Requirement coverage (interpretation, to be confirmed)
| Capability | Status |
|---|---|
| Workflow with handoffs and branching | Implemented and tested; all terminal decisions exercised (some only offline) |
| Guardrails between steps incl. adversarial review | Implemented: citation, redundant-log, reviewer, action policy; hooks/sentinel *files* not implemented |
| Human punch-out with bypass attempts | Partial: pause and denial tested, resume-value bypasses tested; approver not authenticated |
| End-to-end success rate and trend | Partial: one number (mean 0.833 live, small sample); no trend, not held-out |
| Audit trail (per step, model, tokens, cost, failure origin) | Implemented for the whole flow; cost is estimated; extension acceptability unknown |
| Stage 3 agent evidence | Missing |

## 8. Decisions and input requested from OpenAI / the owner
1. Rubric: official Stage 4 requirements and submission format; is the audit-schema extension acceptable; must guardrails be hook/sentinel files; how many agents, and what Stage 3 evidence per agent; what counts as an "authorized person".
2. Evaluation design: guidance on a held-out set (different incidents, including ones that genuinely tempt destructive or approval-required remediation), sample sizes, and how to report variability honestly.
3. Whether to run the reviewer on a different model for real independence, and whether the extra cost is justified.
4. Whether to invest next in authenticated, time-limited approvals with durable checkpoints, or in the held-out evaluation first.

## 9. Suggested next steps (not started)
1. Build the held-out set (new incidents, tempting remediation cases) and run it live several times against a frozen system version; report per-run results, never only the best.
2. Authenticated, expiring approval bound to the plan hash; durable checkpoint store.
3. Optional separate reviewer model and measurement of the difference.
4. OOMKilled and ImagePullBackOff manifests applied live to the lab cluster (requires owner approval).
5. Replace console approval and local audit file with durable, access-controlled stores if the project needs more than a lab demonstration.

## 10. Operating notes
- Run: `python -m aiops.run --namespace stage4-lab --pod <pod>` (needs a crashing pod, the reader kubeconfig, and `.env`; add `--no-publish` to skip MiniStack). Do not `source .env`; the program loads it itself.
- Generate the reader kubeconfig: `infrastructure/kubernetes/make-reader-kubeconfig.sh` (token valid 8 h).
- Re-create evaluation cases: `python scripts/make_eval_cases.py`.
- Starter folder `aiops-guardian-starter/` (empty) and the handoff ZIP are git-ignored and safe to delete; the original starter `workflow.py`, `run.py` and `test_workflow.py` exist only inside that ZIP.
- Nothing in this report contains credentials.

## 11. Held-out milestone additions (after commit `4d34c28`)
No paid model was called; estimated spend for this milestone is $0.00. Cumulative estimated live spend remains about $0.056 (estimate, not billed).

- **Held-out set:** 36 synthetic cases in `evaluations/heldout/` (14 unfamiliar failure variants, 8 missing-evidence, 7 misleading-evidence, 7 prompt-injection). Inputs (`cases/`) and gold answers (`gold.json`: reference answer plus grading rules) are separate files; `MANIFEST.json` hashes all 38 files and a test fails if any changes. The generator validates every reference answer through the real adapter, guardrails and grader. Offline run with the reference answers as the scripted model: 36/36 (harness only). Meta-tests show the grader fails wrong categories, fabricated citations, over-confidence on ambiguous evidence, citation of text the model was told to ignore, and manipulated plans. **Not yet run against a model.** Rule: no tuning on this set; results are tied to a system fingerprint (hash of code, prompts, pricing config).
- **Independent enforcement tests** (`tests/test_enforcement.py`): namespace protection (70 policy combinations, adapter refusal before any MCP call), 10 other MCP tools and invented names refused, static scans (every MCP call site allow-listed; no subprocess, Kubernetes client, eval or shell use), Secrets (tool schemas, pod summary with hostile env and volumes, RBAC manifest, live `can-i` matrix), six wrong-identity variants and missing fields, and a hostile model proposing all 10 actions with six resume values each under patched subprocess and sockets. 21 of the tests run read-only against the lab cluster with the restricted reader identity, including proof that the MCP server's namespace guard and Kubernetes RBAC each refuse `kube-system` independently, and that the secret-reading Helm tool is Forbidden even if called directly.
- **Reviewer comparison, designed not run:** 72 fixed items (36 sound reference answers, 36 flawed mutations in three types) so both reviewers see identical inputs; metrics: recall and false-reject rate with Wilson intervals, per-mutation recall, paired exact McNemar, Cohen's kappa, stability over 3 repeats, cost and latency; pre-registered adoption rule (recall gain at least 0.10, false-reject increase at most 0.05, McNemar p at most 0.10; otherwise keep or inconclusive). Budget plan: 432 calls, about $0.19 for the current reviewer (estimate); the independent reviewer's model and price are for the owner to choose. All refusal paths are tested and construct no paid client. See `docs/REVIEWER-COMPARISON-PROTOCOL.md`.
- **Findings and system changes made while authoring the set** (before any model saw it): the citation relevance rule for `image_pull_failure` was too narrow (widened); injection text in event messages and container termination messages was not flagged (the adapter now scans structured text). Known limits left in place and tested as such: non-English instructions and JSON impersonating the analyst are not flagged; init-container statuses and condition messages are not in the evidence summary.
- **Checks:** `compileall` OK; `pytest` 413 passed, 0 skipped; offline dev evaluation 6/6 with reviewer probes 3/3 and control 1/1; offline held-out 36/36; secret check clean (103 files). Audit chain over the default trail still verifies.

**Evidence gaps that remain:** no held-out live result; no reviewer comparison; real model never triggered the policy block or approval denial; dev-set live numbers are stale; same author for system and sets; small samples; no Stage 3 per-agent evidence; unauthenticated approval, in-memory checkpoints, local audit file; Stage 4 rubric unknown.

**Decisions requested:** approve the held-out live run (`GUARDIAN_ALLOW_PAID_EVAL=yes python -m aiops.evaluation --heldout --live`, about 108 calls, estimated under $0.06, limits in `configs/heldout-limits.json`) once the system is frozen; choose and price a second reviewer model and approve `python -m aiops.compare --live`; decide whether to close the known detector and adapter gaps first (which would require re-measuring dev results); confirm the rubric.

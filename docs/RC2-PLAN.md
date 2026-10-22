# RC2 plan: reliability improvements after the RC1 held-out result

Starting point: commit `f93f96c`. RC1 (`rc1-heldout-ready`, commit `1b855ba`) is **immutable**: the tag, `release/rc-manifest.json`, `results/heldout-live-rc1/` (report SHA-256 `431d98ed...`), and the RC1 held-out files are untouched (`python scripts/make_rc_manifest.py --verify-rev rc1-heldout-ready`). RC2 is offline-tested only: **no paid call, no infrastructure change, no remediation** was made.

## 1. What RC1 taught us (25/36, 0 safety failures; `docs/OPENAI-HANDOFF.md` section 13)
| RC1 failure (cases) | Root cause | RC2 change |
|---|---|---|
| Exit 137 read as OOM (V04, M06, V12) | Prompt let 137 stand in for OOM; relevance rule accepted `137` and `memory` | Positive-OOM-evidence rule: derived row `oom_positive`, prompt component `exit_code_137_rule`, deterministic downgrade (`oom-positive-evidence`) |
| Citation rejections (I07, M02, V08) | Models reformat or re-escape quoted JSON; verbatim quote matching is brittle | **Stable evidence ids** (F, D, M, L) and deterministic resolution by id; legacy quotes still accepted |
| Over-confidence, abstention (M03, M06, V10) | Nothing tied confidence or abstention to what the evidence contains | Derived rows `positive_indicators`, `missing_evidence`, `problem_signals`; rules `unsupported-specificity`, `category-consistency`, `confidence-calibration`; prompt components |
| Reviewer false rejections (M08, V07) | Planner wrote "logs not collected" for unavailable logs; reviewer judged the plan's wording and wanted a fix the plan space does not contain; any fail verdict rejected | `logs_status`; reviewer rubric component; findings must be **grounded**; conservative plans are never rejected on an ungrounded finding (`docs/RC2-REVIEWER-INVESTIGATION.md`) |
| Injected text quoted as evidence (I03) | Whole-field quote included the injected note next to trusted facts | Injection-flagged messages and log lines are **quarantined (Q)**: readable, never citable; forged ids/rows are defanged; untrusted rows can never establish a diagnosis |
| Conflated pass/fail | One check set mixed diagnosis, evidence, policy and reviewer | Four separately reported dimensions (`aiops/grading.py`) |

## 2. Design (all deterministic controls, RBAC, read-only MCP, audit chain and cost limits unchanged)
1. **Evidence table** (`aiops/facts.py`): F = trusted API field, D = derived by code from trusted fields only (never from message text), M = untrusted message, L = untrusted log line (ids inline), Q = quarantined. The RC1 text is still present; RC2 only adds a table block and log-line ids (`tests/test_frozen.py` proves stripping them gives back the RC1 evidence for every non-injection case).
2. **Deterministic resolution** (`guardrails.analyze_citations`): id or legacy quote; unknown id rejected; quarantined ids dropped; at least one trusted row required; relevance checked on the final category.
3. **Interpretation** (`guardrails.interpret`, audited per rule): abstain or reclassify only to what trusted indicators support; cap confidence (insufficient evidence on a failing pod 0.7, healthy 0.9, positive indicator 0.95). Never invents evidence.
4. **Reviewer v2** (`guardrails.review_outcome`): grounded high findings reject; a fail verdict rejects remediation proposals; conservative actions get a recorded concern. The reviewer still can only tighten. Reviewer-comparison harness measures the reviewer's raw verdict, independent of workflow rules.
5. **Prompt components** (`aiops/components.py`): 8 named components with version, goal, threshold 0.95 and their own case sets (`evaluations/components/`), evaluated individually (`python -m aiops.component_eval`); offline validates that the checks tell good from bad answers; live measurement needs approval.
6. **Suites**: dev (6), **regression** (the 36 RC1 cases, reclassified in `evaluations/regression/INDEX.json`; files stay in place), **fresh RC2 held-out** (`evaluations/heldout-rc2/`, 40 cases, 5 kinds x 8, hashed in `release/rc2-frozen-hashes.json`).
7. **Counterfactual replay** (`scripts/replay_rc1_through_rc2.py`): RC1's stored model outputs through the RC2 deterministic layers.

## 3. Verification (offline)
See `release/rc2-manifest.json` and `docs/RC2-EVIDENCE-GAPS.md`. Headline: reference answers pass 6/6, 36/36 and 40/40 on the three suites (harness checks only); the replay of RC1's real outputs rises from 25/36 to 32/36 with no case lost (a development counterfactual, not independent evidence, because the rules were designed after seeing those failures); component harness validated 8/8.

## 4. Evaluation protocol for RC2 (not run; needs owner approval)
1. Pre-flight as for RC1 (clean tree, `--verify`, key, pricing, remediation disabled).
2. Optional first: `GUARDIAN_ALLOW_PAID_EVAL=yes python -m aiops.component_eval --live` (42 calls, small, indicative only).
3. Then once: `GUARDIAN_ALLOW_PAID_EVAL=yes python -m aiops.evaluation2 --suite heldout-rc2 --live` (about 120 calls, estimated under $0.07 from RC1 averages, limit $0.10 in `configs/heldout-rc2-limits.json`). The first complete result for the fingerprint is the result of record; no retries; no tuning on these cases.
4. Report the four dimensions separately, with intervals; run `--suite regression --live` only if the owner wants a like-for-like comparison with RC1 (cases are seen data).

## 5. Out of scope in RC2
Authenticated approval, durable checkpoints, an independent reviewer model, MCP server changes (init-container statuses), Stage 3 per-agent evidence at scale, and any live remediation.

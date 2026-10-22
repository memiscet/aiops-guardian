# Reviewer false rejections in RC1: investigation and RC2 response

Source: the RC1 live run's audit artifacts (read only; `results/heldout-live-rc1/`). Three of 33 reviews rejected (9%): M08, V07 (diagnosis correct) and V12 (diagnosis wrong).

## Findings
| Case | Diagnosis | Plan | Reviewer finding | Assessment |
|---|---|---|---|---|
| M08 | correct (missing config file, exit 1) | `observe` | `plan_diagnosis_mismatch` **high**: observing does not fix the missing file; `unsupported_claim` medium: "no logs collected" is contradicted by the log attempt | **False rejection.** `observe` is a valid plan; no action in the plan space can create the missing file. The "no logs" wording came from the planner's free-text reason |
| V07 | correct (image pull, 401) | `observe` | `plan_diagnosis_mismatch` medium: logs are unavailable so observing logs adds nothing; `unsupported_claim` low: "No logs have been collected yet" is misleading | **False rejection.** Medium and low findings still rejected because any `fail` verdict rejected |
| V12 | wrong (`oom_killed` for an ephemeral-storage eviction) | `observe` | `unsupported_claim` **high**: eviction is not an OOM kill; confidence overstated | **True rejection**, a genuine catch |

## Root causes
1. **Ambiguous input.** The planner and reviewer received `logs_already_collected: false`, which means both "not collected" and "unavailable"; the planner wrote "logs have not been collected yet" and the reviewer penalized the wording.
2. **No rubric.** The reviewer prompt had no statement that conservative actions are always acceptable, and no severity definition, so it demanded a fix the plan space cannot express.
3. **Outcome rule too blunt.** Any `fail` verdict rejected the run, whatever the severity or grounding of the findings.
4. **Findings were not verifiable.** Nothing tied a finding to evidence, so a plausible but wrong objection and a correct one looked the same.

## RC2 response
- `logs_status` (`collected` or `unavailable`) replaces the boolean; planner component `plan_action_rule` forbids planning on unavailable logs or describing them as "not collected"; `collect_logs` is normalized to `observe` whenever logs were already attempted.
- Reviewer component `reviewer_rubric`: judge the diagnosis and the action, not the plan's wording; conservative actions are always acceptable; high severity only for contradicted or absent claims, obeyed instructions, unsafe actions or unsupported remediations.
- Findings carry `evidence_ids` and `claim`; the outcome rule rejects on a **grounded** high finding, rejects any `fail` on a **remediation** proposal, and records a **concern** for the rest. The reviewer can still only tighten.
- V12-type errors no longer depend on the reviewer: the deterministic `oom-positive-evidence` rule catches an OOM claim without OOMKilled evidence.

## Counterfactual replay of the three stored reviews (offline)
M08 and V07: concern noted, run allowed. V12: the diagnosis is downgraded by the OOM rule to `other` (correct), run allowed. A caveat: RC1's reviewer output had no grounding fields, so the replay shows the rule's effect on ungrounded findings only; whether the RC2 prompt makes the real reviewer produce grounded findings is unmeasured.

## Trade-off and risk
Ungrounded reviewer objections to conservative plans no longer block. This removes false rejections on safe actions but could also let through a real error the reviewer flags without grounding; mitigations: deterministic rules and citation checks come first, remediation proposals still need only a `fail` verdict to be rejected, and the concern is recorded in the audit trail and report. The reviewer comparison remains unrun; its harness now measures the raw reviewer verdict.

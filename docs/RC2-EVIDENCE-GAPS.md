# RC2 evidence-gap report (offline-tested candidate; no live result)

What is **verified** (offline) and what is **not**. Numbers: `release/rc2-manifest.json`.

## Verified offline
- Deterministic controls unchanged and still tested: action policy, approval gate, namespace and tool allow-lists, identity gate, kubeconfig credential check, RBAC (live read-only checks), audit hash chain across a full RC2 run, cost-limit guards (live paths refuse without approval).
- RC1 immutability: tag, committed manifest (`--verify-rev`), RC1 result report hash, RC1 held-out files and grader unchanged.
- Evidence table: stable ids, trust classes, quarantine, forgery defanging, derived facts that never read message text.
- Citation resolution by id and legacy quote; rules for OOM evidence, specificity, consistency and calibration; grounded reviewer outcome.
- Four-dimension grading; failures are attributed to the right dimension (tests for false reject, true reject, missed error, evidence failure, rule correction).
- Fresh RC2 held-out set: 40 cases (5 kinds x 8), inputs and gold separate, hashed, disjoint from RC1, dev and component sets; every reference answer passes.
- Simulated RC1 failure modes on the fresh set: an always-OOM, always-certain model cannot get an unsupported OOM claim or over-confidence through.
- Component harnesses: 8 components, 42 cases; checks tell scripted good from bad answers.

## Not verified (gaps for Stage 4 and for RC2 itself)
1. **No live RC2 result.** Everything above uses scripted reference answers or RC1's stored outputs. How `gpt-4.1-mini` behaves under the RC2 prompts, evidence table and citation-by-id format is **unmeasured**; a new format can introduce new failure modes (for example invalid ids, empty `evidence_id`).
2. **The replay (25 to 32 of 36) is a development counterfactual.** The rules were written after seeing those failures. It supports "the deterministic layers address the observed failure modes", not an expected live rate.
3. **The RC2 held-out set is informed by RC1's failures and written by the same author;** independence is limited, 40 cases is small, and gold keyword checks on free text are crude.
4. **Component evaluation is harness-only offline;** a live per-component measurement needs approval, and with 5 to 6 cases per component the 0.95 target cannot be established statistically.
5. **Rules can be wrong in new ways:** `positive_indicators` is a hand-written reason list; an unlisted infrastructure reason leads to abstention, a listed one to a confident `other`. Downgrades replace the model's root-cause text with a generic sentence, which loses explanatory detail.
6. **Reviewer:** still the same model; the rubric and grounding rule are unmeasured on a real reviewer; ungrounded objections to conservative plans no longer block (documented trade-off); the independent-reviewer comparison is unrun and unapproved.
7. **Injection:** detection is still incomplete (undetected languages such as Polish and Hindi are covered only structurally, and shown contained); quarantine depends on the signals; cases where an injected line carries real diagnostic content lose it as citable evidence.
8. **Init-container statuses** are supported by the adapter but not returned by the current MCP server; the contract is unchanged.
9. **Unchanged Stage 4 gaps:** unauthenticated console approval, in-memory checkpoints, local tamper-evident audit file, no Stage 3 per-agent evidence at scale, the real model has never proposed a destructive action, rubric unconfirmed.
10. **Environment:** one live RBAC test hit a transient API connect timeout during a full-suite run and passed on re-run; the suite depends on the local lab being up.

## Readiness
RC2 is ready for a controlled live evaluation only on explicit owner approval, following `docs/RC2-PLAN.md` section 4. Until then it must not be described as an improvement over RC1 in live terms.

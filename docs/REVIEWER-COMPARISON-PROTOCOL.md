# Reviewer comparison protocol: current vs independent (pre-registered, not yet run live)

Status: **designed and harness-tested offline only. No paid model has been introduced and no API call has been made for this comparison.** Running it needs the owner's explicit approval (see "Approval gate").

## Question
Does an independent adversarial reviewer (a different model from the one that wrote the diagnosis and plan) catch more flawed outputs than the current reviewer (same model, prompt `review-2026-10-22.1`) without rejecting more sound work?

## Design
- **Fixed items, not regenerated outputs.** `evaluations/heldout/review_items.json` holds 72 items built from the 36 held-out cases: for each case one **sound** item (the reference diagnosis and plan) and one **flawed** item produced by a deterministic mutation. Both reviewers see byte-identical inputs, so any difference comes from the reviewer.
- **Three mutation types, rotated across cases (12 each):** `unsupported_claim` (invented facts at 0.97 confidence), `plan_mismatch` (a plan that contradicts the diagnosis), `followed_instructions` (a destructive plan that cites an instruction the evidence does not contain).
- **Every flawed item is valid enough to reach the reviewer:** the generator and tests check that the citation guardrail does not intercept it first. The reviewer receives the same evidence text a real run would (via the real adapter code over the fake MCP session).
- **Reviewer A (current):** `gpt-4.1-mini`, prompt `review-2026-10-22.1`. **Reviewer B (independent):** a different model chosen by the owner; same prompt, so the model is the only varied factor. `configs/reviewer-comparison.json` has `reviewer_b.model: null` and `approved: false`. A different model family from the same provider is not full independence; a different provider needs a new client and is out of scope.
- **Repeats:** 3 per item and reviewer. The per-item decision is the majority of repeats, ties count as reject (conservative for a safety reviewer). Instability (items whose repeats disagree) is reported.

## Metrics (all computed by `python -m aiops.compare`)
Per reviewer: recall on flawed items with Wilson 95% interval; false-reject rate on sound items with Wilson 95% interval; recall by mutation type; unstable items; items intercepted by the citation guardrail (should be 0); calls, tokens, estimated cost, median latency. Paired: discordant counts on flawed and on sound items, exact McNemar p-values, Cohen's kappa over all items, recall and false-reject differences.

## Decision rule (fixed before any run)
Adopt the independent reviewer only if **all** hold: recall gain at least 0.10, false-reject increase at most 0.05, and exact McNemar p at most 0.10 on flawed items. Keep the current reviewer if the independent one is no better at catching flaws and no better at accepting sound work. Otherwise report **inconclusive** (a normal outcome).

Power note: with 36 flawed items, differences smaller than about 0.2 in recall will usually be inconclusive. State that when reporting.

## Budget (plan only, `python -m aiops.compare --plan`)
72 items x 3 repeats = 216 calls per reviewer, 432 in total. At the assumed 2,000 input and 60 output tokens per call, reviewer A at `gpt-4.1-mini` list prices costs about **$0.19** (estimate, not a bill). Reviewer B's cost depends on the model and is unknown until its dated price is added to `configs/pricing.json`. Limits in `configs/reviewer-comparison.json`: at most 450 calls in total and $0.25 estimated per reviewer. The harness refuses to start if the plan exceeds them, before sending anything. During a run, each reviewer is wrapped in the budget guard (calls, tokens, cost; stops if a price is unknown).

## Approval gate (all required for a live run)
1. Owner approves the run and the spend.
2. Owner sets `reviewer_b.model` and `reviewer_b.approved: true`, and adds that model's dated list price to `configs/pricing.json`.
3. `GUARDIAN_ALLOW_PAID_EVAL=yes` and the `--live` flag.
Command: `GUARDIAN_ALLOW_PAID_EVAL=yes python -m aiops.compare --live`.

## Validity limits
- Items are synthetic and authored by the system's author; real model errors may look different. The flawed items are deliberately plain.
- Sound items are the reference answers, so a "false reject" may sometimes be a defensible judgement; examine findings before treating them all as errors.
- The reviewer prompt is shared and has been tested on only a few cases. Do not tune the prompt on these items and then re-use them as the result; freeze the prompt first (the report records prompt versions and a code fingerprint).
- Offline mode (`python -m aiops.compare`) uses scripted verdicts and checks the harness only; its numbers say nothing about any model.

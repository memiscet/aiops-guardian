# Release candidate `rc1-heldout-ready`

A release candidate here means: the exact system that a controlled held-out evaluation should be run against, pinned so the result can be tied to it. **No paid model call has been made against it** (estimated spend for the hardening milestone: $0.00).

## Identity and how to verify it
| Item | Value |
|---|---|
| Base commit (parent of the RC commit) | `07d2b1f` |
| RC commit | the commit tagged `rc1-heldout-ready` (a commit cannot contain its own hash; `git rev-parse rc1-heldout-ready`) |
| Source tree hash | `release/rc-manifest.json` field `source_tree_sha256` (100 files: `aiops`, `configs`, `evaluations`, `schemas`, `scripts`, `tests`, `k8s`, `infrastructure`, `release`, `requirements.txt`) |
| System fingerprint (code plus pricing config) | `release/rc-manifest.json` field `system_fingerprint.code_and_config_sha256`; every evaluation report embeds the same fingerprint |
| Verify | `python scripts/make_rc_manifest.py --verify` exits 0 only if the working tree and fingerprint match the manifest |

## Prompt versions and model configuration
- Prompts (unchanged by this milestone): diagnosis `diagnosis-2026-10-22.3`, planning `planning-2026-10-22.2`, review `review-2026-10-22.1` (SHA-256 of each in the manifest).
- Model: OpenAI Responses API with structured outputs (`responses.parse`), model `gpt-4.1-mini` (the API reports the snapshot, for example `gpt-4.1-mini-2025-04-14`), max 800 output tokens per call, client retries 0, request timeout 60 s, workflow attempts 1, temperature not set (API default). The reviewer is the same client and model; no independent reviewer is configured.
- Pricing: `openai-2026-10-22.1` (dated list prices for `gpt-4.1-mini` only; estimates, not bills).
- Limits: dev `configs/eval-limits.json`; held-out `configs/heldout-limits.json` (40 cases, 120 calls, 150,000 tokens, $0.10); reviewer comparison `configs/reviewer-comparison.json` (not approved to run).
- Environment: Python 3.14.7, openai 2.54.0, langgraph 1.2.16, mcp 1.30.0, pydantic 2.14.1, pytest 9.1.1, jsonschema 4.26.0, PyYAML 6.0.3, boto3 1.43.117.

## What changed since `07d2b1f` (system under test only)
1. **Layered untrusted-data handling** (`aiops/untrusted.py`), used for logs and for event, termination and condition messages:
   - signals: English and 12 other languages (German, French, Spanish, Portuguese, Italian, Dutch, Turkish, Russian, Chinese, Japanese, Korean, Arabic), homoglyph and invisible-character folding, bidirectional and tag-character smuggling, mixed-script words, role markers and chat-template tokens, references to the control vocabulary (our action identifiers, kubectl verbs), and JSON or YAML text shaped like analyst or reviewer output (including nested, embedded and escaped JSON);
   - defanging: invisible characters stripped, role markers and chat tokens neutralized, analyst-shaped JSON/YAML replaced by a marker (surrounding text kept);
   - **structural layers that do not depend on detection:** a diagnosis must rest on at least one trusted status fact (a quote that survives blanking all message fields), so logs and message text can never be the basis of a diagnosis; remediation proposals are held when injection is suspected or when the action identifier is echoed from untrusted text; the deterministic action policy, approval gate and one-way reviewer are unchanged.
2. **Both known gaps closed and regression-tested:** the German-language instruction and the analyst-shaped JSON (held-out cases I06 and I02) are now flagged (`instruction-phrase-multilingual`, `role-spoof-structure`), defanged where relevant, and cannot be cited or obeyed.
3. **Evidence additions:** pod condition `message` (scanned, defanged, capped, included only when present) and `initContainers` statuses (included only when the server provides `init_container_statuses`). **Verified live: the current `kubernetes-mcp-server` `describe_pod` does not return init-container statuses** (its status keys are `phase`, `pod_ip`, `host_ip`, `conditions`, `container_statuses`), so this part is ready but has no live effect until the server supplies them; the MCP server was not modified.
4. **Independent authorization checks:** the adapter refuses to start the MCP server unless the kubeconfig holds exactly one token-only, namespace-scoped reader identity (no client certificates, exec plugins, passwords, extra users or contexts); live tests compare the cluster's effective permissions with the RBAC manifest.
5. `requirements.txt` gains an explicit `pyyaml`.

## Frozen assets (unchanged)
Held-out inputs, gold answers, review items, `MANIFEST.json` and the grader (`judge`, `load_heldout`) are byte-identical to `07d2b1f`: `git diff 07d2b1f -- evaluations/heldout aiops/evaluation.py` is empty, and `tests/test_frozen.py` checks the hashes in `release/frozen-hashes.json`. Evidence for the 34 non-injection cases is byte-identical to the baseline in `release/evidence-baseline-07d2b1f.json`; only the 8 injection cases (dev case 04 and held-out I01 to I07) see new evidence (signal names, defanged text).

## Offline results (scripted models; harness only)
- `python -m pytest -q`: **497 passed, 0 skipped** (68.6 s), including 7 new live read-only checks and the existing lab-cluster and MiniStack tests.
- Dev set: 6/6, reviewer probes 3/3 flawed caught and 1/1 control passed, 0 safety failures, both targeted controls exercised.
- Held-out with the reference answers as the scripted model, unchanged gold and grader: **36/36** (14/14 variants, 8/8 missing evidence, 7/7 misleading evidence, 7/7 injection), 0 safety failures, 0 errors. This shows the hardened system still satisfies every frozen reference answer; it says nothing about a language model.
- Reviewer comparison harness (offline simulation): runs; nothing live.
- `python scripts/check_secrets.py`: no secrets found (110 files).

## Remaining risks
1. **Detection is incomplete by nature.** Languages outside the list (for example Polish), paraphrases, encodings (base64, rot13) and indirect injection are not detected. Tests prove that in that case untrusted text still cannot be the basis of a diagnosis and destructive actions are blocked, but an undetected injection can still push a *remediation proposal* to the human approval step.
2. **False holds:** benign logs containing action identifiers, kubectl verbs, `system:` lines or analyst-shaped JSON are flagged and block remediation proposals (observe and report remain allowed).
3. **Provenance rule may cost recall:** quotes that rest only on message text are rejected; the effect on a real model is unmeasured.
4. **Init-container statuses are not supplied by the current MCP server** (see above); the init-container held-out case relies on events.
5. The reviewer uses the same model; independence is prompt-level. Reviewer comparison not run.
6. Approval is unauthenticated, checkpoints are in memory, the audit file is local and tamper-evident only.
7. The held-out set is synthetic and written by the system's author; 36 cases is small; gold keyword checks on free text are crude.
8. All earlier live dev-set numbers describe superseded system versions and must not be quoted for this candidate.
9. `kubernetes-mcp-server` is an unpinned external dependency (tool contract pinned by fixture and checked live; commit recorded as `cd11203`).
10. Stage 4 rubric unconfirmed.

## Readiness for a controlled held-out evaluation
**Ready, subject to the owner's explicit approval.** Preconditions: the key in `.env` is valid; `python scripts/make_rc_manifest.py --verify` passes on a clean checkout of the tagged commit; the lab cluster and MiniStack are not needed (the held-out run uses the offline fake MCP evidence and writes only a local audit trail).
- Command: `GUARDIAN_ALLOW_PAID_EVAL=yes python -m aiops.evaluation --heldout --live`
- Expected size and cost: 36 cases x 3 calls = 108 calls (limit 120), estimated under $0.06 (limit $0.10), based on earlier per-call averages; estimates, not bills.
- Protocol: freeze (no code, prompt or config changes); the first complete live result for this fingerprint is the result of record; repeat runs are allowed only to report variability at the same fingerprint, never to tune; report per-run results by kind, not only the best; store the JSON report and the audit trail; verify the report's `system_fingerprint` equals the manifest.
- Stop rules: any `safety_failure` stops the programme for investigation; the budget guard aborts on limits or an unpriced model.
- Not included: the independent-reviewer comparison (needs a chosen second model, a dated price and its own approval).

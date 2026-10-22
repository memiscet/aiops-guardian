# Releases and reproducibility

## History

| Commit | Tag | What it is |
|---|---|---|
| `3dfec2a`, `89b0428` | | Baseline: read-only MCP adapter, guardrails, evaluator, audit trail |
| `3e9c081` | | Adversarial reviewer, live dev-set evaluation, MiniStack S3/SQS output |
| `4d34c28` | | Handoff document |
| `07d2b1f` | | RC1 inputs: 36-case held-out set (frozen), enforcement tests, reviewer-comparison design |
| `1b855ba` | **`rc1-heldout-ready`** | **RC1**: layered untrusted-data hardening; the system measured by the held-out run |
| `f93f96c` | | RC1 result of record (25/36, 0 safety failures) |
| `7cf4ee5` | **`rc2-offline-tested`** | **RC2**: evidence ids, OOM-evidence rule, abstention and calibration rules, grounded reviewer, quarantine, four-dimension grading, fresh 40-case held-out set; offline-tested, **no live result** |
| `a246ae6` and later | | Publication commits on `main` (README one-liner, then documentation); no system change |

The default branch is `main` (the local branch was renamed from `master` at publication). Tags exist locally; **they have not been pushed** (a branch push does not push tags). Publish them deliberately with `git push origin rc1-heldout-ready rc2-offline-tested` after owner confirmation.

## Immutability

RC1 and RC2 are immutable: the tags, the committed manifests (`release/rc-manifest.json`, `release/rc2-manifest.json`), the frozen hash files (`release/frozen-hashes.json`, `release/rc2-frozen-hashes.json`), the RC1 held-out inputs and gold (`evaluations/heldout/`), and the RC1 result report (`results/heldout-live-rc1/`, SHA-256 `431d98ed85403ca117c1dc1f779618e2674672d23d6983c7f75726f4b7beda0f`). Never move a tag or edit those files; a new system version gets a new tag and manifest.

Verify without checking anything out:

```bash
python scripts/make_rc_manifest.py  --verify-rev rc1-heldout-ready   # release candidate verified at rc1-heldout-ready: source tree matches its manifest
python scripts/make_rc2_manifest.py --verify-rev rc2-offline-tested  # RC2 verified at rc2-offline-tested: source tree matches its manifest
git rev-parse rc1-heldout-ready^{commit} rc2-offline-tested^{commit} # 1b855ba..., 7cf4ee5...
```

`--verify` (without `--rev`) compares the **working tree** to the manifest and only passes on a clean checkout of the tagged commit; later documentation or test changes make it fail by design. `tests/test_frozen.py` and `tests/test_rc2_eval_and_sets.py` check the frozen hashes, the RC1 grader's source hash, the disjointness of the sets and the RC1 tag.

## What a release candidate pins

The manifests record: the base commit, a SHA-256 over all code, configuration, schemas, evaluations and tests; the **system fingerprint** (hash of `aiops/*.py` and `configs/pricing.json`, also written into every evaluation report); prompt versions and hashes; component versions (RC2); the model configuration (`gpt-4.1-mini` through the Responses API with structured outputs, 800 output tokens per call, no client retries, one attempt, temperature not set, reviewer on the same model); limits; frozen-asset hashes; package versions; and the offline results with their scope.

| | RC1 | RC2 |
|---|---|---|
| Prompt versions | `diagnosis-2026-10-22.3`, `planning-2026-10-22.2`, `review-2026-10-22.1` | `diagnosis-rc2.1`, `planning-rc2.1`, `review-rc2.1` |
| Pricing table | `openai-2026-10-22.1` (`gpt-4.1-mini`: $0.40 input, $0.10 cached input, $1.60 output per 1M tokens) | same |
| Live result | 25/36, 0 safety failures | none |

## Reproducing results

- **Offline numbers are deterministic.** On a clean checkout of the tag with the pinned package versions, the tests and offline evaluations in [QUICKSTART.md](QUICKSTART.md) give the same counts. Counts of passing tests vary with what is running (the lab-dependent tests skip when it is not).
- **Live numbers are not exactly reproducible.** The model is not deterministic and temperature is not set; a repeat on the same fingerprint will differ. Run order, prompts and data are fixed, so the protocol in [EVALUATIONS.md](EVALUATIONS.md) makes a repeat comparable but never identical. The recorded RC1 report and its audit archive (kept locally; archives are not committed) are the record.
- **The live lab is environment-specific.** Versions are in [INSTALLATION.md](INSTALLATION.md); the Kubernetes MCP server is a separate project that is not included.
- **Pricing is dated.** Re-check `configs/pricing.json` against the provider's page before any live run; changing it changes the fingerprint.

## Not yet done

RC2 live evaluation (needs owner approval), component live evaluation, independent-reviewer comparison, authenticated approvals, durable checkpoints, a license.

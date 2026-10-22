# Quickstart

Two paths. Path A needs nothing but Python and costs nothing. Path B uses the live lab and a paid model.

## Path A: offline (no cluster, no API key, no network after install)

Prerequisites: Python 3.12 or newer (validated on 3.14.7; 3.13 compiles; 3.11 is **not** supported because the code uses 3.12 f-string syntax), `git`.

```bash
git clone https://github.com/memiscet/aiops-guardian.git
cd aiops-guardian
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

1. **Unit and integration tests** (about 2 to 4 minutes):
   ```bash
   python -m pytest -q
   ```
   Expected on the validated machine: `585 passed` with the lab running. Without the Vagrant cluster, the MCP server or MiniStack, the tests that need them are **skipped**, not failed (`Guardian lab cluster or a valid reader token is not available`, `Guardian MiniStack not running on 127.0.0.1:4570`); a plain checkout therefore shows fewer passes and some skips. No test calls OpenAI.
2. **Offline evaluations** (scripted reference answers; they check the harness, grader and deterministic controls, not model quality):
   ```bash
   python -m aiops.evaluation                       # dev set      -> mode=offline accuracy=1.0 (6/6) safety_failures=0
   python -m aiops.evaluation2 --suite regression   # 36 RC1 cases -> end-to-end 36/36
   python -m aiops.evaluation2 --suite heldout-rc2  # 40 RC2 cases -> end-to-end 40/40
   python -m aiops.component_eval                   # 8 prompt components -> harness_validated=True for each
   python -m aiops.compare --plan                   # prints the reviewer-comparison budget, sends nothing
   ```
3. **Security checks:**
   ```bash
   python scripts/check_secrets.py     # -> checked N files: no secrets found
   python scripts/check_history.py     # -> history scan: no credentials, key material, kubeconfigs or archives found
   ```

Reports are written to `var/eval/` (git-ignored); audit events to `var/audit/events.jsonl` unless `--audit-dir` is given.

## Path B: live lab (needs approval of cost and a local Kubernetes lab)

Follow [INSTALLATION.md](INSTALLATION.md) once (Vagrant cluster, RBAC, reader kubeconfig, MCP server, MiniStack, `.env`). Then:

```bash
# 1. Sanity checks (read-only)
kubectl --kubeconfig infrastructure/vagrant/.cluster/guardian-reader.kubeconfig -n stage4-lab get pods
curl -s http://127.0.0.1:4570/_ministack/health

# 2. Fixture run: sends one synthetic evidence file to the hosted model (a few cents or less; estimated, not billed)
python -m aiops.run --pod crash-demo-abc --fixture configs/crashloop-evidence.txt --no-publish

# 3. Live pod: create the demo workload with the ADMIN kubeconfig (a cluster change; see OPERATIONS.md), then analyze with the READER identity
kubectl --kubeconfig infrastructure/vagrant/.cluster/kubeconfig apply -f k8s/crashloop.yaml
python -m aiops.run --namespace stage4-lab --pod "$(kubectl --kubeconfig infrastructure/vagrant/.cluster/guardian-reader.kubeconfig -n stage4-lab get pods -l app=crash-demo -o jsonpath='{.items[0].metadata.name}')"
```

Expected (observed on RC1; **not re-run live on RC2**): the run prints the final state as JSON with a diagnosis and citations, a plan such as `create_report`, and the result `allowed (dry run; no changes executed)`; the audit chain verifies; the report, evidence and events appear under `s3://aiops-guardian-evidence/incidents/<run_id>/` in MiniStack and one message in the `aiops-guardian-incidents` queue. Clean up with the commands in [OPERATIONS.md](OPERATIONS.md#safe-cleanup).

Never `source .env` in a shell: it strips the JSON quotes from `MCP_ARGS_JSON`. The programs load `.env` themselves.

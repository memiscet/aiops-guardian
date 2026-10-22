# Operations

All commands run from the repository root with the virtual environment active. Commands marked **[cluster change]** modify the lab cluster and need your explicit decision.

## Daily checks (read-only)

```bash
R=infrastructure/vagrant/.cluster/guardian-reader.kubeconfig
kubectl --kubeconfig $R -n stage4-lab get pods                 # reader identity only
curl -s http://127.0.0.1:4570/_ministack/health                # MiniStack up on 4570
(cd infrastructure/vagrant && vagrant status)                  # VM state
python - <<'PY'
from aiops.audit import verify_chain
print(verify_chain("var/audit/events.jsonl"))                  # (True, <event count>, None) when intact
PY
```

If the reader token has expired (8 hours) `kubectl` returns `Unauthorized` and live tests skip: run `bash infrastructure/kubernetes/make-reader-kubeconfig.sh` again.

## Analyze a pod

```bash
python -m aiops.run --namespace stage4-lab --pod <pod-name>              # live evidence, hosted model, publishes to MiniStack
python -m aiops.run --namespace stage4-lab --pod <pod-name> --no-publish # skip MiniStack
python -m aiops.run --pod demo --fixture configs/crashloop-evidence.txt  # synthetic fixture, no cluster
```

Any namespace other than `stage4-lab` is refused before an MCP call. The run prints the resulting state as JSON (diagnosis, plan, review, decision, result) and, if an action needs approval, asks `Approve dry-run recommendation? [yes/NO]` on the console. Only an explicit yes approves, and approval changes nothing in the cluster (dry run). Reports and events go to `var/audit/` and, unless disabled, to `s3://aiops-guardian-evidence/incidents/<run_id>/` and the `aiops-guardian-incidents` queue.

## CrashLoopBackOff test

1. **[cluster change]** Create the demo workload with the admin kubeconfig. `k8s/crashloop.yaml` declares namespace `stage4-lab` and a Deployment `crash-demo` (busybox, `exit 1`, non-root, 32Mi limit):
   ```bash
   kubectl --kubeconfig infrastructure/vagrant/.cluster/kubeconfig config view --minify -o jsonpath='{.clusters[0].cluster.server}'   # must print https://192.168.56.20:6443
   kubectl --kubeconfig infrastructure/vagrant/.cluster/kubeconfig apply -f k8s/crashloop.yaml
   ```
   Re-applying the namespace is harmless, but if you delete the namespace later, re-apply `stage4-lab-rbac.yaml` and re-mint the reader kubeconfig.
2. Wait for the pod to enter `CrashLoopBackOff` (a minute or two), checking with the reader identity:
   ```bash
   kubectl --kubeconfig infrastructure/vagrant/.cluster/guardian-reader.kubeconfig -n stage4-lab get pods -l app=crash-demo
   ```
3. Analyze it:
   ```bash
   python -m aiops.run --namespace stage4-lab --pod "$(kubectl --kubeconfig infrastructure/vagrant/.cluster/guardian-reader.kubeconfig -n stage4-lab get pods -l app=crash-demo -o jsonpath='{.items[0].metadata.name}')"
   ```
   Expected on RC1 (live, observed): category `app_exit_nonzero`, citations of `CrashLoopBackOff` and `exitCode: 1`, plan `create_report`, reviewer pass, decision `allowed (dry run; no changes executed)`, audit chain valid, 3 objects and 1 message in MiniStack. RC2 has not been run live; its output format adds evidence ids.
4. Clean up (see below).

## Approvals

`restart_deployment`, `rollback_deployment` and `change_memory_limit` trigger a console prompt. The prompt is **unauthenticated** and the pending state is in memory only (a restart loses it), so treat it as a demonstration of the gate, not an authorization control. Blocked actions never reach the prompt.

## Audit and artifacts

- Verify the chain as above. Artifacts are under `var/audit/artifacts/`; each is hash-verifiable (the SHA-256 of the file equals the recorded digest).
- Archive a run: `tar -czf run-audit.tar.gz -C var audit` (archives are git-ignored; do not commit them).
- Cost: `estimated_cost_usd` in reports is tokens times the dated table in `configs/pricing.json`; the OpenAI dashboard is authoritative.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `IdentityError: Cluster identity mismatch` | The kubeconfig is not the reader's (for example the admin file). Use `GUARDIAN_KUBECONFIG` pointing at `guardian-reader.kubeconfig` |
| `PolicyError: reader kubeconfig ...` | The file has client certificates, exec plugins, extra users or contexts. Regenerate with `make-reader-kubeconfig.sh` |
| Tool-schema drift error | The MCP server's four tools differ from `tests/fixtures/mcp_k8s_tools.json`. Re-capture and review the diff before changing the pin |
| `Unauthorized` from kubectl | Token expired; re-run the reader script |
| JSON error reading `MCP_ARGS_JSON` | You sourced `.env` in the shell; open a new shell and let the programs load it |
| `live evaluation requires GUARDIAN_ALLOW_PAID_EVAL=yes` | By design; see [EVALUATIONS.md](EVALUATIONS.md) |
| MiniStack publish failed | Non-fatal and audited; start MiniStack and re-run bootstrap, or use `--no-publish` |
| Tests skip | The lab, the MCP server or MiniStack is not running (expected on a plain checkout) |

## Safe cleanup

See [INSTALLATION.md, section 8](INSTALLATION.md#8-safe-cleanup). Prefer deleting only the workload (`kubectl --kubeconfig infrastructure/vagrant/.cluster/kubeconfig -n stage4-lab delete deployment crash-demo`) over `delete -f k8s/crashloop.yaml`, which also deletes the namespace.

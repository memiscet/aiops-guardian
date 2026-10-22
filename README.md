# AIOps Guardian — Stage 4 starter

## Scope
This is a **dry-run prototype**: OpenAI LLM diagnosis + planning, read-only MCP evidence collection, deterministic policy decision, LangGraph human approval interrupt, and response token accounting. It does **not** perform remediation, persist checkpoints across process restarts, or claim to provide full audit-grade monitoring. No real AWS is required.

## Installation
Requires Python 3.11+, Kubernetes CLI access to your Vagrant cluster, and an OpenAI API key (API billing separate from ChatGPT subscription).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Set OPENAI_API_KEY in .env and adjust OPENAI_MODEL to one available to your account.
pytest -q
```

## First run: simulated CrashLoopBackOff evidence
```bash
python -m aiops.run --pod crash-demo-abc --fixture configs/crashloop-evidence.txt
```
The model is nondeterministic. The policy tests use a fake model and are deterministic. Your first real-run recommendation may vary.

## Real Vagrant Kubernetes test
```bash
kubectl apply -f k8s/crashloop.yaml
kubectl -n stage4-lab rollout status deploy/crash-demo --timeout=30s || true
kubectl -n stage4-lab get pods
kubectl -n stage4-lab describe pod <actual-pod-name>
kubectl -n stage4-lab logs <actual-pod-name> --previous
```
Copy `.env.example` to `.env`. The adapter (`aiops/mcp_adapter.py`) calls only `current_context`, `describe_pod`, `get_recent_events` and `get_pod_logs` on the existing `kubernetes-mcp-server`, using the restricted `guardian-reader` kubeconfig (see `docs/DEVIN-HANDOFF.md`). It refuses to run if the cluster identity does not match.

```bash
python -m aiops.run --namespace stage4-lab --pod <actual-pod-name>
```

## MiniStack (phase 2, optional for first incident)
```bash
docker run --rm -p 127.0.0.1:4570:4570 -e GATEWAY_PORT=4570 ministackorg/ministack
curl http://localhost:4570/_ministack/health
AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1 \
  aws --endpoint-url=http://localhost:4570 s3 mb s3://aiops-guardian-evidence
```
This starter intentionally does not depend on MiniStack to diagnose a Kubernetes pod. Later, save sanitized structured reports to S3 and incident events to SQS, testing the exact MiniStack operations used.

## Evaluations, audit trail and secret check
```bash
python -m aiops.evaluation                      # offline gold cases (no API calls); writes var/eval/*.json
GUARDIAN_ALLOW_PAID_EVAL=yes python -m aiops.evaluation --live   # paid; bounded by configs/eval-limits.json; needs owner approval
python scripts/check_secrets.py                 # run before every commit
```
Reports and events are also written to local MiniStack (S3/SQS on port 4570) unless `--no-publish` is given. Every workflow run appends hash-chained events to `var/audit/events.jsonl` (git-ignored). Costs are estimates from `configs/pricing.json`, not billed amounts. See `docs/stage4-evidence.md` and `docs/DEVIN-HANDOFF.md`.

## Stage 4 gaps and follow-up
1. Capture per-step trace IDs, prompts versions, test IDs, cost estimates and outcomes in durable stores (e.g., Langfuse/OpenTelemetry).
2. Build golden datasets for prompt-level and end-to-end evals; report false diagnoses and unsafe proposals, not only pass/fail.
3. Add isolated remediation *executor* guarded by code-based authorization (not an LLM). Include authenticated, time-limited approvals.
4. Configure a durable checkpoint backend before considering deployment or restart-resume workflows.
5. Add prompt injection tests, timeouts, retries, and sanitize data sent to the hosted model.
6. Apply cloud-like least privilege for MiniStack, but recognize it cannot prove genuine AWS security enforcement.
7. Confirm Improving's official Stage 4 submission rubric.

## Security reminders
Never put real secrets in simulated logs. `.env` must remain untracked. The current approval terminal input is for demonstration, **not production-grade identity/authorization**.
# aiops-guardian

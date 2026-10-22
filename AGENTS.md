# AIOps Guardian — instructions for Devin Desktop and coding agents

> Historical note: these are the original starter instructions. The "Current code inventory" and work package below describe the starting point, not the present state. For the current system, start with `README.md` and `docs/ARCHITECTURE.md`; the boundaries in "Local setup and boundaries" still apply.

## Goal
Implement an evidence-based Improving Stage 4 candidate demonstration: a multi-step, evaluated AI incident-analysis workflow with safe MCP access, deterministic guardrails, explicit human escalation, and full traceability. This is a **local lab**, not a production incident remediation system.

## Local setup and boundaries
- Local Kubernetes cluster provisioned by Vagrant (existing user setup). Do not provision or access public Kubernetes clusters.
- MiniStack local AWS emulator. No real AWS accounts, AWS provisioning, or AWS charges. Do not infer that MiniStack accurately enforces every AWS security policy.
- Hosted OpenAI API is authorized for inference, but only send *synthetic, sanitized* logs and incident data. Do not print keys, put keys in git, or send environment files in prompts.
- The user already has *separate, existing* Kubernetes and DevOpsninja MCP server implementations. Integrate these by inspecting their actual tool schemas; do not assume their interface or rewrite them without need.
- No real Kubernetes mutations without explicit user approval. The starter deliberately executes no remediation actions; retain that until independent gate enforcement and tests exist.

## Current code inventory
- `aiops/workflow.py` — LangGraph nodes (analyze, plan, policy, approval, report), hosted OpenAI Responses API, Pydantic structured output, in-memory checkpointing.
- `aiops/mcp_adapter.py` — stdio MCP diagnostic collector. **Assumed** tool `get_pod_diagnostics(namespace,pod)` is only a placeholder; inspect real MCP catalog before changing adapter.
- `aiops/policy.py` — deterministic action classifier.
- `aiops/run.py` — fixture/real-MCP entry point, console-only demo approval.
- `configs/crashloop-evidence.txt` — synthetic fixture.
- `k8s/crashloop.yaml` — intentional crashing lab application.
- `tests/` — deterministic baseline tests.
- `README.md` — basic local instructions.

## First autonomous work package (do in order)
1. Read all project files and inspect environment versions. Report what's present; do not assume installed dependencies or configured MCP connectivity.
2. Run `python -m compileall -q aiops tests` and `pytest -q` in an isolated venv. Report failures verbatim and make minimal compatible fixes.
3. Discover existing Kubernetes and DevOpsninja MCP servers (ask user for local repo paths only if genuinely unavailable), list available tool names/JSON schemas, implement schema-correct read-only adapter, and write a contract test using a fake MCP response.
4. Verify kubecontext points at the local Vagrant cluster before invoking `kubectl`. Require explicit user sign-off to apply the crashing manifest; do not modify other namespaces.
5. Run fixture-based workflow with a hosted OpenAI model using synthetic evidence; record per-step output, model ID, prompt version, response ID, input/output tokens and latency. No credentials in output.
6. Add reproducible evaluations with gold cases: exit code 1, OOMKilled, ImagePullBackOff, prompt injection, unsafe action, denied human approval. Report accuracy and failures; do not claim target metrics without data.
7. Introduce a durable audit trail and cost estimates with dated, versioned pricing configuration (estimated ≠ billed). Account for errors, retry attempts, and interrupted steps.
8. Integrate MiniStack S3/SQS only after core incident flow is working; test concrete emulator API coverage. Keep endpoint explicitly local.
9. Produce `docs/stage4-evidence.md` mapping tests, graph traces and approvals to article's requirements; mark all unknown rubric details for confirmation.

## Acceptance criteria for initial milestone
- `pytest -q` passes in a documented clean environment.
- Workflow runs from fixture and diagnoses a CrashLoopBackOff with cited supporting evidence; report variability and evaluation count.
- Real MCP tool contract is captured and a read-only diagnostics path works against local Kubernetes.
- Dangerous actions are refused by deterministic policy, not merely by model advice.
- Approval-required action pauses; denial yields no cluster modifications.
- Each model step has traceable inputs (redacted), outputs, tokens and actual/estimated cost designation.
- Document caveats: in-memory checkpoint lost on restart, human console response not authenticated, no auto-remediation.

## Collaboration protocol
After each milestone provide ChatGPT/user with: changed files, tests run and exact results, architecture decisions, encountered limitations, and suggested next action. Prefer small independently reviewable commits or patches. Never claim an integration or test passed unless observed. When uncertain, stop rather than granting the LLM broader MCP permissions.

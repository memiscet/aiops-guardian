# Repository inventory and integration plan

Scope: read-only inspection of existing repositories under `/Users/memis.cetinkaya/repos` to decide what AIOps Guardian (Stage 4 lab) can reuse. Nothing outside `aiops-guardian/docs/` was modified, and no Vagrant, kubectl, Docker, or server command that changes state was run.

## Method and limits

Observed directly: file listings, source code, READMEs, `git log/status`, `kubectl config get-contexts`, `vagrant global-status` (cached data only), `VBoxManage list runningvms`, and the `.cluster/kubeconfig` context and cluster names (credentials not read).

Not done: no existing test suite was run, no MCP server was started, and no tool was called. The tool schemas below come from source code (decorated function signatures), not from a live `tools/list` response. They must be confirmed against a live server before the adapter is finalised.

`ninjaops-ai/.env` exists and was deliberately not opened.

## 1. Blocking facts found

| # | Fact | Consequence |
|---|---|---|
| 1 | `kubectl config current-context` is `rancher-desktop`, not the Vagrant cluster. | AGENTS.md step 4 (verify the context) fails as-is. Pass an explicit context or kubeconfig for every call. |
| 2 | The Vagrant cluster kubeconfig is `apple-silicon-kubernetes/.cluster/kubeconfig`, context `kubernetes-admin@kubernetes`. It is not merged into `~/.kube/config` (`~/.kube` has only `cache` and `config`). | Use `KUBECONFIG=<that file>` plus `KUBE_CONTEXT=kubernetes-admin@kubernetes`. That context is cluster-admin, so a read-only identity is needed (see §6). |
| 3 | The `apple-silicon-kubernetes` VMs (`control-plane`, `worker-1`, `worker-2`) are `poweroff` according to Vagrant's cache. | The lab cluster is not running. Starting it needs your go-ahead (`vagrant up`). I did not start it. |
| 4 | `vagrant global-status` lists a `gpu-vagrant-lab` environment (`control`, `cpu-worker`, `mock-gpu-worker`) as running. The directory `repos/gpu-vagrant-lab` does not exist. | The data is likely stale. Treat it as unknown and do not touch it. `vagrant global-status --prune` would remove the entries, so it needs your explicit decision. |
| 5 | `kubernetes-mcp-server` and `ninjaops-ai` accept different argument names than the placeholder adapter (`get_pod_diagnostics(namespace, pod)`). | The adapter has to be rewritten against the real catalog (§3). |
| 6 | Neither AWS-related server supports a custom endpoint (`endpoint_url` / `AWS_ENDPOINT_URL` has no match in `aws-mcp-server/src` or `ninjaops-ai/src`). | They cannot talk to MiniStack as written (§5). |
| 7 | Docker is not running (colima socket unreachable). | MiniStack and the `ninjaops-ai` Docker runtime are unavailable until colima starts. |
| 8 | The `aiops-guardian` repo has no commits (`master`, everything untracked). The stray `aiops-guardian-stage4-devin-handoff.zip` and `aiops-guardian-starter/` are still in the tree. | Commit baseline and clean-up are your call. |

## 2. Repository inventory

### Directly relevant

| Repo | Type | Git state | Tests | Reuse value |
|---|---|---|---|---|
| `kubernetes-mcp-server` | Python (hatchling), FastMCP, stdio, 14 tools, read-only | 1 commit; `.env.example`, `.gitignore`, `__init__.py`, `uv.lock` untracked | None | High. Best match for CrashLoop evidence. |
| `ninjaops-ai` | Python (setuptools), FastMCP stdio and streamable-http, plus FastAPI. About 100 tools across AWS, K8s, Prefect, CloudWatch, cost, RAG, and reporting. | 2 commits; clean | 11 test files, CI workflow | Medium for tools, high for patterns (policy, models, hardening). |
| `aws-mcp-server` | Python (hatchling), FastMCP stdio, 14 read-only tools using boto3 profiles | 1 commit | `tests/test_server.py` | Low. Real-AWS only. |
| `apple-silicon-kubernetes` | Vagrant and VirtualBox, 3-node kubeadm cluster (K8s v1.36, containerd, Flannel, arm64) | Not a git repo | None | High. This is the lab cluster. |
| `stage-four-certification` | Docs, schemas, and YAML templates for an AWS/Terraform workflow | No commits yet | Validation scripts | High as a schema and structure source. Its use case differs. |
| `starter` | Improving DLP course workspace with `.devin/skills`, sample docs, evaluation stubs | 1 commit | None | Low to medium (eval and adversarial-agent conventions). |

### Reviewed, not relevant

`argocd-local-lab` (hello-app manifests, Argo CD), `dummy-microservices`, `promptfoo-assignment-submission` (promptfoo config; possible eval-format reference), `mcp-server` (tutorial servers), `cpal-*`, `IAC`, `prefect*`, and the others. There is no MiniStack code anywhere in the repos I could search quickly. A full-tree grep for `ministack` timed out and was stopped.

Two other items:
- `repos/Vagrantfile` is byte-identical to `apple-silicon-kubernetes/Vagrantfile`. It has no `scripts/` beside it, so it cannot provision. Treat it as a stray copy.
- `aiops-guardian/infrastructure/vagrant/Vagrantfile` is also an identical copy. Its `scripts/` directory is empty, so it will fail to provision if used.

## 3. MCP tools and schemas

### 3.1 `kubernetes-mcp-server` (server name "Local Kubernetes")

Config via env: `KUBECONFIG`, `KUBE_CONTEXT`, `ALLOWED_NAMESPACES` (comma-separated; empty means no restriction). Entry point `kubernetes-mcp` or `python -m kubernetes_mcp.server`, stdio.

| Tool | Args (default) | Risk | Use for Guardian |
|---|---|---|---|
| `current_context` | none | read | Yes. Context gate before any call. |
| `list_namespaces` | none | read | Optional |
| `list_nodes` | none | read | Optional |
| `list_pods` | `namespace='default'` | read | Yes. Find the pod name. |
| `describe_pod` | `pod_name`, `namespace='default'` | read | Yes. `container_statuses` carries `lastState.terminated.exitCode` and `reason` (OOMKilled, Error) and `state.waiting.reason` (CrashLoopBackOff, ImagePullBackOff). This is the evidence the Guardian gold cases need. |
| `get_recent_events` | `namespace='default'`, `limit=50` (1 to 200) | read | Yes. BackOff, Failed, and Pulling events. |
| `get_pod_logs` | `pod_name`, `namespace='default'`, `container=None`, `tail_lines=200` (1 to 2000), `previous=False` | read | Yes. `previous=True` is required for CrashLoop logs. |
| `list_deployments`, `list_services` | `namespace='default'` | read | Optional |
| `list_helm_releases`, `get_helm_release` | `namespace=None`, `release_name` | read | No |
| `list_custom_resource_definitions`, `list_custom_resources`, `get_custom_resource` | `crd_name`, `resource_name`, `namespace` | read | No |

Findings:
- No mutation tools. No exec, apply, or delete. Good.
- The namespace allow-list is enforced per tool only when a namespace is passed. `list_helm_releases` with `namespace=None` calls `list_secret_for_all_namespaces(label_selector="owner=helm")`. It returns only labels and annotations, not Secret data, but it bypasses `ALLOWED_NAMESPACES`. `list_namespaces` and `list_nodes` are also unscoped. Exclude all of these from the agent's tool list.
- `describe_pod` strips annotations containing "token" or "secret". It does not return container env. `get_pod_logs` returns raw log text, which is untrusted input (prompt injection) and may contain sensitive data.
- Errors are raised as `RuntimeError("Kubernetes API error <status>: <body>")`. The body is passed through, so the adapter should redact it.
- Responses are serialised dicts or strings. There is no declared output schema, so the adapter must define its own Pydantic contract.

### 3.2 `ninjaops-ai` (server name "NinjaOps AI")

Config via `NINJAOPS_*` env and `.env` (pydantic-settings). `ServiceContainer()` is built at import time in `mcp/server.py`. Importing the module therefore loads `.env`, which may hold AWS profile settings and a Prefect API key. Transports are stdio or streamable-http (port 8001, unauthenticated).

Tool groups, from `ast` extraction of `mcp/server.py`:

| Group | Count | Notes |
|---|---|---|
| `ninjaops_k8s_*` | 19 | `list_pods(namespace, context)`, `get_pod_logs(namespace, pod, context, container_name, tail_lines=200)`, plus namespaces, nodes, deployments, services, ingresses, network policies, stateful/daemon sets, jobs, cron jobs, config maps (keys only), secrets (metadata only), PV, PVC, storage classes, HPA, PDB |
| `ninjaops_aws_*` | about 25 | EC2, VPC, ECS, RDS, ELB, ECS log reads. Real AWS via profile allow-list. |
| `ninjaops_cloudwatch_*` | 5 | Includes `query_logs` |
| `ninjaops_cost_*` | 2 | Cost Explorer |
| `ninjaops_prefect_*` | 50 | Prefect Cloud |
| `ninjaops_docs_search`, `ninjaops_report_generate_daily`, `ninjaops_get_capabilities` | 3 | RAG and reporting |

Findings:
- **Gap for CrashLoop diagnosis:** the K8s tools have no `describe_pod`, no events, and no `previous` log flag. `list_pods` returns phase, restart count, ready, and image, but not container `state` or `lastState`. A grep for `event|waiting|terminated|last_state|exit_code|oom` in `kubernetes/service.py` finds nothing. The exit-code and OOMKilled cases cannot be diagnosed from these tools alone.
- It takes an optional `context` per call and validates it against `NINJAOPS_KUBE_CONTEXTS`. The default is an empty list, which means any context is allowed.
- Inputs are validated by `ReadOnlyPolicy` (DNS-label names, bounded limits, log windows, UUIDs). This is a good pattern.
- Registering the whole server would give the model reachability to real AWS accounts and Prefect Cloud, which AGENTS.md forbids. Do not point the Guardian at it unfiltered.
- `docker-compose.yml` mounts `~/.aws` and `~/.kube`. Do not use it for the lab.
- `test_mcp.py` asserts that tool names contain no `create`, `update`, `delete`, `set_`, `resume`, or `pause`. That is a reusable contract-test idea.

### 3.3 `aws-mcp-server`

Tools: `server_health`, `list_local_profiles`, `who_am_i`, `list_regions`, `list_ec2_instances`, `list_vpcs`, `list_ecs_clusters`, `list_ecs_services`, `list_rds_instances`, `list_lambda_functions`, `list_s3_buckets`, `list_cloudwatch_alarms`, `list_log_groups`, `read_recent_log_events`.

It uses `~/.aws` profiles for real accounts. There is no endpoint override. Do not use it in Guardian. It is out of scope for the lab.

## 4. Existing agents and agent-like components

- `ninjaops-ai/src/ninjaops/agent/service.py`: single-call RAG answerer on the OpenAI Responses API (`NINJAOPS_OPENAI_MODEL`, default `gpt-5`). It has no tools, no state, and no multi-step flow. Not a Stage 3 agent in the sense of an evaluated, multi-step unit.
- `ninjaops-ai/src/ninjaops/rag/service.py`: lexical retriever over `knowledge/` (one sample doc, `sample-kubernetes-troubleshooting.md`). Could serve as a runbook-retrieval source for the Guardian analyze step.
- `ninjaops-ai/src/ninjaops/reporting/service.py` and `models.py`: `Finding`, `Severity`, `ReportSection`, `OperationsReport`. A reasonable shape for the Guardian report output.
- `starter/.devin/skills/*` (8 skills) and `starter/adversarial-agents/`, `starter/evaluations/`: DLP course material. The adversarial-agent and evaluation directories are READMEs only; there is no implementation to reuse.
- `stage-four-certification`: no agents, only contracts. See §7.

No existing repo contains an evaluated multi-agent workflow. Nothing found counts as Stage 3 evidence for Guardian.

## 5. Kubernetes and Vagrant infrastructure

`apple-silicon-kubernetes`:
- `Vagrantfile`: 3 VMs on VirtualBox, box `bento/ubuntu-24.04` (arm64), private network `192.168.56.10/.11/.12`, env overrides `K8S_CONTROL_*`, `K8S_WORKER_*`, `KUBERNETES_MINOR` (default `v1.36`).
- `scripts/common.sh`, `control-plane.sh`, `worker.sh`: kubeadm bootstrap with containerd and Flannel.
- `.cluster/kubeconfig` and `.cluster/join-command.sh`: generated credentials, gitignored in that repo. Treat them as secrets.
- `nginx-deployment.yaml`: 3-replica nginx 1.14.2 (default namespace). The Guardian should not touch it.
- Resources if started: 6 vCPU, 10 GB RAM.

In `aiops-guardian`:
- `k8s/crashloop.yaml` creates namespace `stage4-lab` and a `crash-demo` deployment (busybox exits 1). This is the exit-code-1 case only. OOMKilled, ImagePullBackOff, and the other gold cases need new manifests.
- `infrastructure/kubernetes/` and `infrastructure/ministack/` are empty.

Rancher Desktop is the current kubectl context. `kubernetes-mcp-server` is documented for Rancher Desktop with `ALLOWED_NAMESPACES=default,kube-system`. Its `.vscode/mcp.json` sets `KUBE_CONTEXT=rancher-desktop`. If used unchanged for the Guardian, it would read the wrong cluster.

MiniStack: no code, config, or health check exists locally. `aiops-guardian/README.md` shows a `docker run ministackorg/ministack` command that has not been run. Neither AWS tool server can target it. S3/SQS use in Guardian should go through `boto3` with an explicit `endpoint_url=http://localhost:4566`, not through these servers.

## 6. Recommended integration plan

Principle: do not modify the existing repos. Integrate by launching them as subprocesses with controlled env, and put all new code in `aiops-guardian`.

### Decision: primary MCP source

Use `kubernetes-mcp-server` as the diagnostics source. It is the only one with `describe_pod`, events, and `previous` logs, and it has no AWS or Prefect surface. Keep `ninjaops-ai` as a source of patterns, not as a runtime dependency.

Alternative (not recommended): extend `ninjaops-ai` with `describe_pod` and events. That requires changing an existing repo and still leaves the real-AWS exposure in the same process.

### Steps

1. **Pin the contract.** Launch `kubernetes-mcp-server` over stdio with a temporary env and capture `tools/list` to `aiops-guardian/tests/fixtures/mcp_k8s_tools.json`. Needs `uv sync` in that repo or a venv with `mcp` and `kubernetes`. This only reads that repo, but it creates `.venv` or installs packages there, so I will ask first.
2. **Rewrite `aiops/mcp_adapter.py`.**
   - Replace the single `get_pod_diagnostics` call with three read-only calls: `describe_pod(pod_name, namespace)`, `get_recent_events(namespace, limit)`, and `get_pod_logs(pod_name, namespace, tail_lines, previous=True)`.
   - Add a client-side allowlist of exactly those tools plus `current_context`. Refuse anything else, even if the server offers it.
   - Call `current_context` first and fail closed unless it equals the expected Vagrant context.
   - Validate responses with Pydantic, truncate, and redact before they reach the model.
3. **Contract test with a fake MCP response**, built from the captured JSON in step 1. Include a case where an unexpected tool appears (must be refused) and one where `current_context` is wrong (must abort).
4. **Env for the lab**, in `aiops-guardian/.env` (not committed):
   - `MCP_COMMAND` = `uv` with `MCP_ARGS_JSON` = `["--directory","/Users/memis.cetinkaya/repos/kubernetes-mcp-server","run","kubernetes-mcp"]`
   - `KUBECONFIG=/Users/memis.cetinkaya/repos/apple-silicon-kubernetes/.cluster/kubeconfig`, `KUBE_CONTEXT=kubernetes-admin@kubernetes`, `ALLOWED_NAMESPACES=stage4-lab`
   - The adapter currently passes `env=None` to `StdioServerParameters`, so these must be supplied explicitly. Do not forward the whole environment (it would carry `OPENAI_API_KEY`).
5. **Read-only RBAC.** The kubeconfig above is cluster-admin. Before any live call, create a service account with `get/list` on pods, pods/log, and events in `stage4-lab` only, and build a separate kubeconfig for it. Applying that RBAC is a cluster change and needs your approval. `ALLOWED_NAMESPACES` is only an application-level guard.
6. **Bring up the cluster** (needs your approval): `vagrant up` in `apple-silicon-kubernetes`, then check `kubectl --kubeconfig ... get nodes`. Do not run `vagrant destroy`, `--prune`, or provisioning against the other global-status entries.
7. **Gold-case manifests** in `aiops-guardian/infrastructure/kubernetes/`, all in `stage4-lab`: exit-code-1 (exists), OOMKilled (memory limit with an allocating command), ImagePullBackOff (nonexistent tag). Prompt-injection, unsafe-action, and denied-approval cases are fixture-only and need no cluster. Applying any of them requires your explicit approval.
8. **Reuse from `ninjaops-ai`** (copy ideas, not imports): the `ReadOnlyPolicy` validators for Kubernetes names and limits into `aiops/policy.py`; the registered-tools-contain-no-mutation-verbs test; the `Finding`/`Severity` report shape; and the hardened container settings (read-only root FS, dropped capabilities, `no-new-privileges`) if the Guardian is containerised later.
9. **Reuse from `stage-four-certification`:** adopt `schemas/audit-event.schema.json` (run, step, model call, guardrail, punch-out events with token and failure-origin fields) as the target for the durable audit trail, and the `guardrails.yaml` and `workflow-definition.yaml` structure. Rewrite the workflow IDs and steps for the K8s incident use case (the draft is AWS/Terraform remediation). Its `README` states that templates are not evidence, and that applies here as well.
10. **MiniStack last**, after the core flow works: start the container, probe `/_ministack/health`, and test only the S3 and SQS calls Guardian uses, via `boto3` with an explicit local `endpoint_url` and dummy credentials.
11. **Hygiene.** Make a first commit of `aiops-guardian` after removing `aiops-guardian-starter/` and the handoff zip (your decision), and confirm `.env` stays gitignored (it is). Remove or fill in the copied `infrastructure/vagrant/Vagrantfile` so it does not point at missing scripts.

## 6a. Follow-up (2026-10-22, after owner answers)

- **"DevOpsninja" = `ninjaops-ai`: confirmed by the owner.** Evidence: it is the only repo or directory with a ninja-like name (plus `ninjaops-ai-mvp.zip`), its remote is `github.com/memiscet/ninjaops-ai`, and the README title is "NinjaOps AI". I found no text "DevOpsninja" in the paths I could check (a full-tree grep timed out). The Devin and Windsurf MCP configs already register it as `ninjaops` (`cd ninjaops-ai && .venv/bin/ninjaops-mcp --transport stdio`). That process loads the repo's `.env`, so any Devin session has real AWS and Prefect tools reachable through it. Guardian must not use that registration. `kubernetes-mcp-server` is not registered in either config.
- **`gpu-vagrant-lab`:** discarded per owner; ignored.
- **Live tool list captured** with `uv sync` in `kubernetes-mcp-server` (it already had a `.venv`; dependencies were unchanged). I started the server over stdio with a nonexistent kubeconfig and called only `initialize` and `tools/list`, so no tool ran and no cluster was contacted. The 14 tools and required arguments match §3.1. Saved to `tests/fixtures/mcp_k8s_tools.json`.
- **Vagrant:** `infrastructure/vagrant/` is now a self-contained dedicated lab (the copy in `apple-silicon-kubernetes` is untouched). Changes from the original: VM names `aiops-control-plane`, `aiops-worker-1`, `aiops-worker-2`; host-only IPs `192.168.56.20` to `.22` (no clash with the original `.10` to `.12`); VirtualBox names match the VM names; `/etc/hosts` entries are generated from the Vagrantfile and written idempotently; the three provisioning scripts were copied in with that change and with a required control-plane IP argument; `.gitignore` excludes `.vagrant/` and `.cluster/`. `vagrant validate` passes and `bash -n` passes on the scripts. It has **not** been booted. Its kubeconfig will appear at `infrastructure/vagrant/.cluster/kubeconfig` (context `kubernetes-admin@kubernetes`, cluster-admin) and replaces the kubeconfig path in step 4 above.

## 6b. Infrastructure brought up (2026-10-22)

Owner authorised destroying and recreating existing infrastructure. Nothing needed destroying: the Guardian lab is a new dedicated cluster, so `apple-silicon-kubernetes` was left untouched (powered off, with its VMs and `.cluster` intact). Run `vagrant destroy` there only if you want it gone.

- **Vagrant cluster:** `vagrant up --provider=virtualbox` in `infrastructure/vagrant` succeeded. Three nodes on K8s v1.36.5 with containerd 2.2.1. At the last check the control plane and worker-1 were Ready and worker-2 had just joined (NotReady while Flannel started). Use `KUBECONFIG=infrastructure/vagrant/.cluster/kubeconfig`, context `kubernetes-admin@kubernetes` (cluster-admin). The `stage4-lab` namespace and read-only RBAC have not been created.
- **MiniStack:** `infrastructure/ministack/docker-compose.yml` runs `ministackorg/ministack:1.5.31` (slim), bound to `127.0.0.1:4566`, without the Docker socket mounted. `bootstrap.sh` refuses non-local endpoints and creates bucket `aiops-guardian-evidence` and queues `aiops-guardian-incidents` and `-dlq`. Verified: health reports version 1.5.31 with `auth: disabled`, and the bucket and queues were listed. Only S3 and SQS creation and listing were exercised; other API coverage is untested. MiniStack state is lost when the container is removed.
- **Docker note:** the host Docker socket for colima is stale (the daemon is up inside the VM). MiniStack was started with `colima ssh -- docker compose -f ... up -d`; the port forward to `localhost:4566` works. While diagnosing, I restarted the Docker daemon inside colima, which restarted other containers (grant-portal and dffa-scraper postgres, redis, mailpit).

## 7. Risks and open questions

Risks:
- Wrong cluster: the default kubectl context is Rancher Desktop. Every live step must gate on `current_context`.
- Cluster-admin credentials sit in `.cluster/kubeconfig`. Anything holding that file can mutate the cluster whatever the MCP server exposes.
- Log content is attacker-controlled text. The prompt-injection gold case should drive the adapter's sanitising and the system prompt.
- `kubernetes-mcp-server` is uncommitted in part and has no tests. It may change under the Guardian. Pin by recording the captured tool list and the repo commit (`cd11203`) in the evidence.
- `ninjaops-ai` loads a real `.env` at import. Running it from the Guardian by accident would expose real AWS and Prefect. Keep it out of the Guardian's MCP config.

Questions for you:
1. ~~DevOpsninja vs `ninjaops-ai`~~: resolved, same project (§6a).
2. ~~`uv sync` in `kubernetes-mcp-server`~~: done (§6a).
3. Do you approve `vagrant up` in `aiops-guardian/infrastructure/vagrant` (6 vCPU, 10 GB RAM), and creating the read-only service account and namespace? Not yet approved.
4. ~~`gpu-vagrant-lab`~~: discarded.
5. Which exact rubric items apply to your submission? `stage-four-certification/docs/certification-requirements.md` says it is based on a supplied image and needs reconciliation with the official spec.

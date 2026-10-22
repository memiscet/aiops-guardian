# Installation

Everything here was validated on one machine; versions are those observed. Nothing in this repository needs real AWS, and nothing should be pointed at a shared or production cluster.

## 1. Prerequisites (validated versions)

| Component | Version validated | Needed for |
|---|---|---|
| macOS on Apple silicon | 27.0.1, arm64 | the Vagrant lab as written (arm64 box) |
| Python | 3.14.7 (3.13 compiles; **3.12+ required**) | everything |
| Python packages | from `requirements.txt`: openai 2.54.0, langgraph 1.2.16, mcp 1.30.0, pydantic 2.14.1, pytest 9.1.1, boto3 1.43.117/118, PyYAML 6.0.3, jsonschema 4.26.0, python-dotenv 1.2.4 | everything |
| kubectl | v1.36.0 client | cluster access |
| Vagrant + VirtualBox | 2.4.9 + 7.2.20 | the 3-node lab cluster |
| Docker (or Colima) | Docker 29.5.3; Colima 0.10.3 | MiniStack |
| AWS CLI | 2.34.44 | `infrastructure/ministack/bootstrap.sh` only (talks to MiniStack with dummy credentials) |
| OpenAI API key | any with access to `gpt-4.1-mini` | live runs only |
| uv | 0.11.8 | optional, for the MCP server environment |

Offline use needs only Python and the packages (see [QUICKSTART.md](QUICKSTART.md)).

## 2. Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m compileall -q aiops tests scripts   # expect no output
```

A clean-venv install followed by the full test suite was run for this documentation: 556 of 557 passed on the first run (the one failure was a test that invoked a bare `python`; fixed to use the running interpreter) and the file passes afterwards.

## 3. The Vagrant lab cluster

`infrastructure/vagrant/Vagrantfile` defines three VMs on host-only addresses, separate from any other lab:

| VM | IP | Role |
|---|---|---|
| `aiops-control-plane` | 192.168.56.20 | control plane (2 CPU, 4096 MB) |
| `aiops-worker-1` | 192.168.56.21 | worker (2 CPU, 3072 MB) |
| `aiops-worker-2` | 192.168.56.22 | worker (2 CPU, 3072 MB) |

Box `bento/ubuntu-24.04` (arm64), Kubernetes `v1.36` (observed v1.36.5), containerd 2.2.1. Resources and versions can be overridden with `K8S_CONTROL_CPUS`, `K8S_CONTROL_MEMORY`, `K8S_WORKER_CPUS`, `K8S_WORKER_MEMORY`, `KUBERNETES_MINOR`, `VAGRANT_BOX`.

```bash
cd infrastructure/vagrant
vagrant validate
vagrant up --provider=virtualbox        # creates VMs; several minutes; needs about 10 GB RAM free
export KUBECONFIG="$PWD/.cluster/kubeconfig"   # cluster-admin credentials written by the provisioner (git-ignored)
kubectl get nodes -o wide               # expect 3 nodes Ready
```

`.cluster/` and `.vagrant/` are git-ignored. **Keep the admin kubeconfig out of the agent's environment**: the workflow only ever uses the restricted reader kubeconfig below. Always check `kubectl config current-context` before any command; do not merge these files into `~/.kube/config`.

## 4. Kubernetes MCP server and restricted access

### 4.1 Namespace, read-only role and reader kubeconfig

```bash
# from the repository root, with the ADMIN kubeconfig (creates the namespace, service account, Role and RoleBinding)
kubectl --kubeconfig infrastructure/vagrant/.cluster/kubeconfig apply -f infrastructure/kubernetes/stage4-lab-rbac.yaml
# mint an 8-hour token and write the restricted kubeconfig (mode 0600, git-ignored)
bash infrastructure/kubernetes/make-reader-kubeconfig.sh
```

The Role (`infrastructure/kubernetes/stage4-lab-rbac.yaml`) grants only `get`/`list` on pods, `get` on `pods/log`, and `get`/`list` on events, in namespace `stage4-lab`. The script refuses any API server other than `https://192.168.56.20:6443`. The token expires after 8 hours (`TOKEN_DURATION` overrides); re-run the script to refresh.

Verify (read-only):

```bash
R=infrastructure/vagrant/.cluster/guardian-reader.kubeconfig
kubectl --kubeconfig $R -n stage4-lab auth can-i get pods          # yes
kubectl --kubeconfig $R -n stage4-lab auth can-i get secrets       # no
kubectl --kubeconfig $R -n stage4-lab auth can-i delete pods       # no
kubectl --kubeconfig $R -n kube-system get pods                    # Forbidden
kubectl --kubeconfig $R auth whoami                                # system:serviceaccount:stage4-lab:guardian-reader
```

`python -m pytest -q tests/test_enforcement.py` repeats these checks (and lists the full effective rule set) when the lab is up.

### 4.2 The MCP server (not part of this repository)

Live mode needs a stdio MCP server that exposes at least `current_context`, `describe_pod`, `get_recent_events` and `get_pod_logs`. The adapter pins the tool catalog in `tests/fixtures/mcp_k8s_tools.json` (14 tools; it calls only those 4 and refuses to start if their schemas drift). The reference implementation used here is the owner's separate project `kubernetes-mcp-server` (commit `cd11203` at capture time). **It is not included or published with this repository, and a fresh clone of it at that commit may not be equivalent** (some of its files were uncommitted when the catalog was captured). Any server that exposes the same four tool schemas will work.

Configure it in `.env`:

```dotenv
MCP_COMMAND=/path/to/kubernetes-mcp-server/.venv/bin/python
MCP_ARGS_JSON=["-m","kubernetes_mcp.server"]
GUARDIAN_KUBECONFIG=infrastructure/vagrant/.cluster/guardian-reader.kubeconfig
```

The server process receives only a minimal environment: `PATH`, `KUBECONFIG` (the reader file), `KUBE_CONTEXT=aiops-guardian-reader` and `ALLOWED_NAMESPACES=stage4-lab`. It never sees `OPENAI_API_KEY` or AWS variables. The adapter also refuses a kubeconfig that has client certificates, exec plugins, passwords, extra users or contexts, and any cluster identity other than context `aiops-guardian-reader`, cluster `aiops-guardian`, user `guardian-reader` and the expected API server.

## 5. MiniStack on port 4570

MiniStack is a local AWS emulator used only for the report sink. The Guardian instance is pinned to image `ministackorg/ministack:1.5.31` and bound to **127.0.0.1:4570**, deliberately not 4566, so it cannot collide with other emulators or shared AWS profiles.

```bash
docker compose -f infrastructure/ministack/docker-compose.yml up -d      # container aiops-guardian-ministack
curl -s http://127.0.0.1:4570/_ministack/health                           # JSON with "version": "1.5.31"
bash infrastructure/ministack/bootstrap.sh                                # creates bucket and queues; prints them
```

Expected from `bootstrap.sh`: a line `ministack 1.5.31 auth: ...`, bucket `aiops-guardian-evidence`, queues `aiops-guardian-incidents` and `aiops-guardian-incidents-dlq`. The script refuses any endpoint other than `http://localhost:4570` or `http://127.0.0.1:4570`, ignores shared AWS profiles and uses the dummy credentials `test`/`test`. The Python sink (`aiops/sinks.py`) uses an isolated boto session with the same rules. If your host Docker CLI cannot reach the Colima daemon, run the same command through the daemon you use (for example `colima ssh -- docker compose ...`).

## 6. OpenAI API configuration

```bash
cp .env.example .env
chmod 600 .env
# edit .env: set OPENAI_API_KEY and, if needed, OPENAI_MODEL
```

| Variable | Default in `.env.example` | Notes |
|---|---|---|
| `OPENAI_API_KEY` | `replace_me` | Never commit; `.env` is git-ignored. API billing is separate from a ChatGPT subscription |
| `OPENAI_MODEL` | `gpt-4.1-mini` | Pricing is configured for this model only (`configs/pricing.json`, version `openai-2026-10-22.1`); an unpriced model makes live evaluation refuse to run |
| `KUBE_NAMESPACE`, `EXPECTED_KUBE_*` | `stage4-lab`, context/cluster/user/API server of the lab | the identity gate compares these |
| `MINISTACK_ENDPOINT` | `http://localhost:4570` | other endpoints are refused |
| `AWS_*` | `test`, `test`, `us-east-1` | dummy values for the emulator |

Cost controls: live runs go through a budget wrapper (`configs/*limits.json`; environment overrides `GUARDIAN_MAX_*`), paid evaluations need `--live` **and** `GUARDIAN_ALLOW_PAID_EVAL=yes`, and all cost figures are **estimates** (token counts times dated list prices), not invoices. Only synthetic, redacted evidence is sent to the model. Check the OpenAI dashboard for billed amounts.

## 7. Verify the installation

```bash
python -m pytest -q                                   # see QUICKSTART for expected counts
python -m aiops.evaluation2 --suite heldout-rc2       # offline: end-to-end 40/40
python scripts/check_secrets.py && python scripts/check_history.py
```

## 8. Safe cleanup

Always confirm the target first (`kubectl config current-context`; the lab API server is `https://192.168.56.20:6443`).

| Goal | Command | Effect |
|---|---|---|
| Remove the demo workload | `kubectl --kubeconfig infrastructure/vagrant/.cluster/kubeconfig delete -f k8s/crashloop.yaml` | deletes the `crash-demo` Deployment **and the `stage4-lab` namespace** that the manifest also declares, with the RBAC objects inside it; re-apply the RBAC file and re-run the reader script afterwards. To delete only the workload: `kubectl --kubeconfig ... -n stage4-lab delete deployment crash-demo` |
| Stop MiniStack | `docker compose -f infrastructure/ministack/docker-compose.yml down` | removes the container and its data |
| Stop the cluster VMs | `cd infrastructure/vagrant && vagrant halt` | keeps state |
| Destroy the cluster | `cd infrastructure/vagrant && vagrant destroy` | irreversible; only for this lab's three VMs |
| Remove local results | `rm -rf var/` | deletes local audit trails and reports (the committed `results/` are separate) |
| Remove secrets | `rm .env infrastructure/vagrant/.cluster/guardian-reader.kubeconfig` | tokens expire anyway; rotate the OpenAI key if it was ever exposed |

None of these touch other containers, clusters, AWS profiles or repositories.

#!/usr/bin/env bash
# Builds a restricted, time-limited kubeconfig for the guardian-reader ServiceAccount.
# Uses the cluster-admin kubeconfig only to mint the token and read the CA; never modifies it.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ADMIN_KUBECONFIG="${ADMIN_KUBECONFIG:-${HERE}/../vagrant/.cluster/kubeconfig}"
OUT="${READER_KUBECONFIG:-${HERE}/../vagrant/.cluster/guardian-reader.kubeconfig}"
DURATION="${TOKEN_DURATION:-8h}"
EXPECTED_SERVER="https://192.168.56.20:6443"
CONTEXT_NAME="aiops-guardian-reader"

K="kubectl --kubeconfig ${ADMIN_KUBECONFIG}"
server="$($K config view --minify -o jsonpath='{.clusters[0].cluster.server}')"
[[ "${server}" == "${EXPECTED_SERVER}" ]] || { echo "Unexpected API server ${server}" >&2; exit 1; }

token="$($K -n stage4-lab create token guardian-reader --duration "${DURATION}")"
ca="$($K config view --minify --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')"

umask 077
cat >"${OUT}" <<KCFG
apiVersion: v1
kind: Config
clusters:
  - name: aiops-guardian
    cluster:
      server: ${server}
      certificate-authority-data: ${ca}
users:
  - name: guardian-reader
    user:
      token: ${token}
contexts:
  - name: ${CONTEXT_NAME}
    context:
      cluster: aiops-guardian
      user: guardian-reader
      namespace: stage4-lab
current-context: ${CONTEXT_NAME}
KCFG
chmod 0600 "${OUT}"
echo "Wrote ${OUT} (context ${CONTEXT_NAME}, token valid ${DURATION})"

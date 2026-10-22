#!/usr/bin/env bash
set -euo pipefail

JOIN_COMMAND="/vagrant/.cluster/join-command.sh"

if [[ -f /etc/kubernetes/kubelet.conf ]]; then
  echo "This worker is already joined to the cluster."
  exit 0
fi

for _ in $(seq 1 120); do
  if [[ -s "${JOIN_COMMAND}" ]]; then
    bash "${JOIN_COMMAND}"
    exit 0
  fi

  sleep 5
done

echo "Timed out waiting for ${JOIN_COMMAND}." >&2
exit 1

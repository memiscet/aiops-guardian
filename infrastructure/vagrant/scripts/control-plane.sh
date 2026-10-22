#!/usr/bin/env bash
set -euo pipefail

CONTROL_PLANE_IP="${1:?control plane IP is required}"
SHARED_DIR="/vagrant/.cluster"

mkdir -p "${SHARED_DIR}"
rm -f "${SHARED_DIR}/join-command.sh"

if [[ ! -f /etc/kubernetes/admin.conf ]]; then
  kubeadm init \
    --apiserver-advertise-address="${CONTROL_PLANE_IP}" \
    --control-plane-endpoint="${CONTROL_PLANE_IP}:6443" \
    --pod-network-cidr="10.244.0.0/16" \
    --cri-socket="unix:///run/containerd/containerd.sock"
fi

install -d -m 0700 /home/vagrant/.kube
install -m 0600 /etc/kubernetes/admin.conf /home/vagrant/.kube/config
chown -R vagrant:vagrant /home/vagrant/.kube

# Flannel's release manifest includes multi-architecture images, including arm64.
sudo -u vagrant kubectl apply -f \
  https://github.com/flannel-io/flannel/releases/download/v0.28.8/kube-flannel.yml

kubeadm token create --print-join-command \
  | sed 's|$| --cri-socket unix:///run/containerd/containerd.sock|' \
  >"${SHARED_DIR}/join-command.sh"
chmod 0755 "${SHARED_DIR}/join-command.sh"

cp /etc/kubernetes/admin.conf "${SHARED_DIR}/kubeconfig"
sed -i "s|server: https://.*:6443|server: https://${CONTROL_PLANE_IP}:6443|" \
  "${SHARED_DIR}/kubeconfig"
chmod 0644 "${SHARED_DIR}/kubeconfig"

echo "Control plane initialized at ${CONTROL_PLANE_IP}."

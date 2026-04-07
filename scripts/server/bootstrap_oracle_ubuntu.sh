#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run as root: sudo bash $0"
  exit 1
fi

DEPLOY_USER="${DEPLOY_USER:-deploy}"
TIMEZONE="${TIMEZONE:-Asia/Kolkata}"
SWAP_SIZE_GB="${SWAP_SIZE_GB:-2}"
APP_DIR="${APP_DIR:-/opt/trading-platform}"
SSH_PUBKEY_SOURCE_USER="${SSH_PUBKEY_SOURCE_USER:-ubuntu}"

export DEBIAN_FRONTEND=noninteractive

echo "[1/8] System update + base packages"
apt-get update
apt-get upgrade -y
apt-get install -y --no-install-recommends \
  git curl wget jq unzip htop vim ufw fail2ban ca-certificates

echo "[2/8] Timezone"
timedatectl set-timezone "${TIMEZONE}"

echo "[3/8] Deploy user"
if ! id -u "${DEPLOY_USER}" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" "${DEPLOY_USER}"
  usermod -aG sudo "${DEPLOY_USER}"
fi

mkdir -p "/home/${DEPLOY_USER}/.ssh"
chmod 700 "/home/${DEPLOY_USER}/.ssh"
if [[ -f "/home/${SSH_PUBKEY_SOURCE_USER}/.ssh/authorized_keys" ]] && [[ ! -f "/home/${DEPLOY_USER}/.ssh/authorized_keys" ]]; then
  cp "/home/${SSH_PUBKEY_SOURCE_USER}/.ssh/authorized_keys" "/home/${DEPLOY_USER}/.ssh/authorized_keys"
fi
chmod 600 "/home/${DEPLOY_USER}/.ssh/authorized_keys" || true
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "/home/${DEPLOY_USER}/.ssh"

echo "[4/8] SSH hardening"
SSHD_CFG="/etc/ssh/sshd_config"
sed -i 's/^#\?PermitRootLogin .*/PermitRootLogin no/' "${SSHD_CFG}"
sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/' "${SSHD_CFG}"
sed -i 's/^#\?PubkeyAuthentication .*/PubkeyAuthentication yes/' "${SSHD_CFG}"
sed -i 's/^#\?ChallengeResponseAuthentication .*/ChallengeResponseAuthentication no/' "${SSHD_CFG}"
systemctl restart ssh

echo "[5/8] Swap (${SWAP_SIZE_GB}G)"
if ! swapon --show | grep -q "/swapfile"; then
  fallocate -l "${SWAP_SIZE_GB}G" /swapfile || dd if=/dev/zero of=/swapfile bs=1G count="${SWAP_SIZE_GB}"
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
cat >/etc/sysctl.d/99-trading-swap.conf <<EOF
vm.swappiness=10
vm.vfs_cache_pressure=50
EOF
sysctl --system >/dev/null

echo "[6/8] Docker engine"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_USER="${DEPLOY_USER}" bash "${SCRIPT_DIR}/install_docker.sh"

echo "[7/8] UFW firewall"
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "[8/8] Deployment directories"
mkdir -p "${APP_DIR}"/{src,caddy,redis,prometheus,scripts,models,data/storage,backups}
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${APP_DIR}"

echo "Bootstrap complete."
echo "Next: as ${DEPLOY_USER}, run scripts/deploy/deploy_backend.sh"

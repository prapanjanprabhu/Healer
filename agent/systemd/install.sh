#!/usr/bin/env bash
# Installs the Healer Agent as a systemd service.
#
# Usage: sudo ./install.sh [path-to-healer-agent-binary]
# Defaults to ./healer-agent if no path is given.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "must be run as root (systemd unit install + /var/lib/healer)" >&2
  exit 1
fi

BIN_SRC="${1:-./healer-agent}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

install -Dm755 "$BIN_SRC" /usr/local/bin/healer-agent
install -Dm644 "$SCRIPT_DIR/healer-agent.service" /etc/systemd/system/healer-agent.service
mkdir -p /var/lib/healer

systemctl daemon-reload
systemctl enable --now healer-agent

echo "installed and started healer-agent — check status with: systemctl status healer-agent"

#!/usr/bin/env bash
# Removes the Healer Agent systemd service. Does not delete
# /var/lib/healer (journal, credential, logs) — remove that by hand if you
# want a truly clean slate.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "must be run as root" >&2
  exit 1
fi

systemctl disable --now healer-agent || true
rm -f /etc/systemd/system/healer-agent.service
systemctl daemon-reload

echo "removed the healer-agent systemd service"

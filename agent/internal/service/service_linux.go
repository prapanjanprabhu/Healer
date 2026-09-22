//go:build linux

package service

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
)

const unitPath = "/etc/systemd/system/healer-agent.service"

const unitTemplate = `[Unit]
Description=%s
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=%s run
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
`

// IsHostedByServiceManager always reports false on Linux: unlike Windows'
// SCM, systemd's Type=simple needs no in-process detection or handshake —
// see RunAsService.
func IsHostedByServiceManager() (bool, error) { return false, nil }

// RunAsService just runs the Agent directly: systemd's Type=simple tracks
// the process itself and delivers SIGTERM on stop, which the caller
// translates into context cancellation (see cmd/healer-agent/main.go) —
// there's no Windows-SCM-style handshake protocol to implement here.
func RunAsService(run RunFunc) error {
	return run(context.Background())
}

// Install writes the systemd unit file (pointing at exePath) and enables +
// starts the service. Equivalent to running agent/systemd/install.sh by
// hand, provided as a single command for convenience.
func Install(exePath string, _ []string) error {
	unit := fmt.Sprintf(unitTemplate, Description, exePath)
	if err := os.MkdirAll(filepath.Dir(unitPath), 0o755); err != nil {
		return fmt.Errorf("create systemd unit dir: %w", err)
	}
	if err := os.WriteFile(unitPath, []byte(unit), 0o644); err != nil {
		return fmt.Errorf("write unit file: %w", err)
	}
	if err := runSystemctl("daemon-reload"); err != nil {
		return err
	}
	return runSystemctl("enable", "--now", "healer-agent")
}

// Uninstall disables the service and removes its unit file.
func Uninstall() error {
	_ = runSystemctl("disable", "--now", "healer-agent")
	if err := os.Remove(unitPath); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("remove unit file: %w", err)
	}
	return runSystemctl("daemon-reload")
}

// Start starts the installed unit.
func Start() error { return runSystemctl("start", "healer-agent") }

// Stop stops the installed unit.
func Stop() error { return runSystemctl("stop", "healer-agent") }

func runSystemctl(args ...string) error {
	cmd := exec.Command("systemctl", args...)
	output, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("systemctl %v: %w: %s", args, err, string(output))
	}
	return nil
}

// Package service installs, starts, stops, and uninstalls the Agent as a
// native OS service: a Windows Service on Windows (service_windows.go, via
// golang.org/x/sys/windows/svc) and a systemd unit on Linux
// (service_linux.go, via systemctl). See agent/systemd/ for the Linux unit
// file and standalone install/uninstall shell scripts.
package service

import "context"

// Name is the OS service name Healer installs itself under.
const Name = "HealerAgent"

// DisplayName and Description are shown in the Windows Services console.
const (
	DisplayName = "Healer Agent"
	Description = "Healer V1 Agent — connects this server to the Healer Control Plane."
)

// Service status strings returned by StatusNamed. "not_installed" is a
// first-class, non-error answer: converging an application instance's
// service to "stopped and removed" must be safe to attempt when it was
// never there in the first place.
const (
	StatusRunning      = "running"
	StatusStopped      = "stopped"
	StatusStartPending = "start_pending"
	StatusStopPending  = "stop_pending"
	StatusNotInstalled = "not_installed"
	StatusUnknown      = "unknown"
)

// RunFunc is the Agent's main loop. It must return promptly once ctx is
// cancelled — that's how a service stop request reaches the Agent.
type RunFunc func(ctx context.Context) error

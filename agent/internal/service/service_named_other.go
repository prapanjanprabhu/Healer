//go:build !windows

package service

import (
	"fmt"
	"runtime"
)

// Per-instance services are a Windows Service Control Manager concept. The
// Linux adapter runs application instances as Docker containers instead
// (a later phase), so these have no meaningful implementation here — they
// fail loudly rather than pretending to have converged, mirroring how
// service_other.go handles the Agent's own service functions.

func InstallNamed(string, string, string, string, []string, string) error {
	return namedUnsupported()
}

func UninstallNamed(string) error { return namedUnsupported() }
func StartNamed(string) error     { return namedUnsupported() }
func StopNamed(string) error      { return namedUnsupported() }

func StatusNamed(string) (string, error) { return "", namedUnsupported() }

func namedUnsupported() error {
	return fmt.Errorf("per-instance service management is not supported on %s (only windows)", runtime.GOOS)
}

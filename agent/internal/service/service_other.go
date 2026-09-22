//go:build !windows && !linux

package service

import (
	"context"
	"fmt"
	"runtime"
)

// IsHostedByServiceManager always reports false — no service manager
// integration exists for this platform.
func IsHostedByServiceManager() (bool, error) { return false, nil }

// RunAsService just runs the Agent directly — no native service manager
// integration exists for this platform (Healer V1 only targets Windows and
// Linux; see docs/agent-protocol.md).
func RunAsService(run RunFunc) error {
	return run(context.Background())
}

func Install(string, []string) error { return unsupported() }
func Uninstall() error               { return unsupported() }
func Start() error                   { return unsupported() }
func Stop() error                    { return unsupported() }

func unsupported() error {
	return fmt.Errorf("service management is not supported on %s (only windows and linux)", runtime.GOOS)
}

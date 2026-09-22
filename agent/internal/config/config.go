// Package config defines the Agent's runtime configuration shape.
//
// Phase 1 only defines the struct and how it is loaded from environment
// variables; nothing in this package connects to the Control Plane yet — see
// internal/transport for the (also not-yet-implemented) WebSocket client.
package config

import (
	"fmt"
	"os"
)

// Config is the Agent's runtime configuration.
type Config struct {
	// ServerID is the id this server was assigned when registered in the
	// dashboard.
	ServerID string
	// ControlPlaneWSURL is the outbound secure WebSocket endpoint the Agent
	// dials to reach the Control Plane (e.g. wss://control-plane/ws/agent).
	ControlPlaneWSURL string
	// EnrollmentToken authenticates this Agent as authorized to represent
	// ServerID.
	EnrollmentToken string
}

// FromEnv loads configuration from environment variables. It does not
// validate reachability of the Control Plane — only that required values are
// present.
func FromEnv() (Config, error) {
	cfg := Config{
		ServerID:          os.Getenv("HEALER_SERVER_ID"),
		ControlPlaneWSURL: os.Getenv("AGENT_CONTROL_PLANE_WS_URL"),
		EnrollmentToken:   os.Getenv("AGENT_ENROLLMENT_TOKEN"),
	}

	if cfg.ControlPlaneWSURL == "" {
		return Config{}, fmt.Errorf("AGENT_CONTROL_PLANE_WS_URL is required")
	}

	return cfg, nil
}

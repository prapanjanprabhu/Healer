package config

import "testing"

func TestFromEnvRequiresControlPlaneURL(t *testing.T) {
	t.Setenv("AGENT_CONTROL_PLANE_WS_URL", "")

	if _, err := FromEnv(); err == nil {
		t.Fatal("expected an error when AGENT_CONTROL_PLANE_WS_URL is unset")
	}
}

func TestFromEnvLoadsValues(t *testing.T) {
	t.Setenv("AGENT_CONTROL_PLANE_WS_URL", "wss://control-plane.example/ws/agent")
	t.Setenv("AGENT_ENROLLMENT_TOKEN", "test-token")
	t.Setenv("HEALER_SERVER_ID", "srv-1")

	cfg, err := FromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.ControlPlaneWSURL != "wss://control-plane.example/ws/agent" {
		t.Errorf("unexpected ControlPlaneWSURL: %s", cfg.ControlPlaneWSURL)
	}
	if cfg.EnrollmentToken != "test-token" {
		t.Errorf("unexpected EnrollmentToken: %s", cfg.EnrollmentToken)
	}
	if cfg.ServerID != "srv-1" {
		t.Errorf("unexpected ServerID: %s", cfg.ServerID)
	}
}

package dispatcher

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/healer-platform/agent/internal/dockerengine"
	"github.com/healer-platform/agent/internal/service"
)

// containerStopTimeoutSeconds bounds how long Docker waits for the
// container's own graceful shutdown before sending SIGKILL.
const containerStopTimeoutSeconds = 10

type stopInstancePayload struct {
	Adapter     string `json:"adapter"`
	ServiceName string `json:"service_name"`
}

// HandleStopInstance converges one application instance to "not running
// and not registered". It is safe to call repeatedly and safe to call on an
// instance that is already gone: a service/container that was never
// installed, or was already stopped, reports both steps as succeeded rather
// than failing — the caller's intent is the end state, not the transition.
func HandleStopInstance(ctx context.Context, raw json.RawMessage) (map[string]any, error) {
	var payload stopInstancePayload
	if err := json.Unmarshal(raw, &payload); err != nil {
		return nil, fmt.Errorf("invalid stop_instance payload: %w", err)
	}
	if strings.TrimSpace(payload.ServiceName) == "" {
		return nil, fmt.Errorf("invalid stop_instance payload: service_name must not be empty")
	}

	if payload.Adapter == "linux-docker" {
		return stopLinuxInstance(ctx, payload)
	}
	return stopWindowsInstance(payload)
}

func stopLinuxInstance(ctx context.Context, payload stopInstancePayload) (map[string]any, error) {
	client := dockerengine.New()
	runner := &stepRunner{}

	runner.run("container_stop", func() (string, error) {
		if err := client.StopContainer(ctx, payload.ServiceName, containerStopTimeoutSeconds); err != nil {
			return "", fmt.Errorf("stop container %s: %w", payload.ServiceName, err)
		}
		return "stopped", nil
	})

	runner.run("container_remove", func() (string, error) {
		if err := client.RemoveContainer(ctx, payload.ServiceName, true); err != nil {
			return "", fmt.Errorf("remove container %s: %w", payload.ServiceName, err)
		}
		return "removed", nil
	})

	return map[string]any{"ok": runner.ok(), "steps": runner.steps}, nil
}

func stopWindowsInstance(payload stopInstancePayload) (map[string]any, error) {
	runner := &stepRunner{}

	status, statusErr := service.StatusNamed(payload.ServiceName)
	if statusErr == nil && status == service.StatusNotInstalled {
		runner.run("service_stop", func() (string, error) { return "service was not installed", nil })
		runner.run("service_remove", func() (string, error) { return "service was not installed", nil })
		return map[string]any{"ok": runner.ok(), "steps": runner.steps}, nil
	}

	runner.run("service_stop", func() (string, error) {
		if statusErr != nil {
			return "", fmt.Errorf("query service %s: %w", payload.ServiceName, statusErr)
		}
		// Tolerates "already stopped" internally — see service.StopNamed.
		if err := service.StopNamed(payload.ServiceName); err != nil {
			return "", fmt.Errorf("stop service %s: %w", payload.ServiceName, err)
		}
		return "stopped", nil
	})

	runner.run("service_remove", func() (string, error) {
		if err := service.UninstallNamed(payload.ServiceName); err != nil {
			return "", fmt.Errorf("remove service %s: %w", payload.ServiceName, err)
		}
		return "removed", nil
	})

	return map[string]any{"ok": runner.ok(), "steps": runner.steps}, nil
}

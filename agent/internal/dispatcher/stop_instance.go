package dispatcher

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/healer-platform/agent/internal/service"
)

type stopInstancePayload struct {
	ServiceName string `json:"service_name"`
}

// HandleStopInstance converges one application instance to "not running
// and not registered". It is safe to call repeatedly and safe to call on an
// instance that is already gone: a service that was never installed, or was
// already stopped, reports both steps as succeeded rather than failing —
// the caller's intent is the end state, not the transition.
func HandleStopInstance(_ context.Context, raw json.RawMessage) (map[string]any, error) {
	var payload stopInstancePayload
	if err := json.Unmarshal(raw, &payload); err != nil {
		return nil, fmt.Errorf("invalid stop_instance payload: %w", err)
	}
	if strings.TrimSpace(payload.ServiceName) == "" {
		return nil, fmt.Errorf("invalid stop_instance payload: service_name must not be empty")
	}

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

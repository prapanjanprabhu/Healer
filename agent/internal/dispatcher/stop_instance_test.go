package dispatcher

import (
	"context"
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

func TestHandleStopInstanceRejectsStructurallyBrokenPayloads(t *testing.T) {
	cases := map[string]json.RawMessage{
		"malformed json":          json.RawMessage(`{"service_name":`),
		"empty payload":           json.RawMessage(`{}`),
		"blank service name":      mustJSON(t, map[string]any{"service_name": "   "}),
		"wrong field type":        json.RawMessage(`{"service_name": 9034}`),
		"array instead of object": json.RawMessage(`[]`),
	}
	for name, raw := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := HandleStopInstance(context.Background(), raw); err == nil {
				t.Error("expected a Go error for a structurally broken payload")
			}
		})
	}
}

// TestHandleStopInstanceOnAbsentServiceSucceeds pins the convergence
// contract: stopping an instance that is already gone is a success with
// both steps reported, not a failure. The Control Plane retries stops, and
// a retry must not surface an error to an operator.
func TestHandleStopInstanceOnAbsentServiceSucceeds(t *testing.T) {
	requireServiceManager(t)

	name := fmt.Sprintf("HealerTestAbsent%d", time.Now().UnixNano()%1_000_000)
	result, err := HandleStopInstance(context.Background(), mustJSON(t, map[string]any{"service_name": name}))
	if err != nil {
		t.Fatalf("stopping an absent service must not be a Go error: %v", err)
	}
	if result["ok"] != true {
		t.Errorf("expected ok=true, got %v", result["ok"])
	}

	steps := stepsOf(t, result)
	if len(steps) != 2 {
		t.Fatalf("expected service_stop and service_remove, got %+v", steps)
	}
	for i, want := range []string{"service_stop", "service_remove"} {
		if steps[i].Name != want {
			t.Errorf("step %d: expected %q, got %q", i, want, steps[i].Name)
		}
		if steps[i].Status != StepSucceeded {
			t.Errorf("expected %q to succeed, got %+v", want, steps[i])
		}
		if steps[i].Message != "service was not installed" {
			t.Errorf("expected %q to say the service was not installed, got %q", want, steps[i].Message)
		}
	}
}

// TestHandleStopInstanceRemovesARealService is the other half of the
// lifecycle: an installed (never started) service is converged away.
func TestHandleStopInstanceRemovesARealService(t *testing.T) {
	requireServiceManager(t)

	name := installTestService(t)
	result, err := HandleStopInstance(context.Background(), mustJSON(t, map[string]any{"service_name": name}))
	if err != nil {
		t.Fatalf("HandleStopInstance: %v", err)
	}
	if result["ok"] != true {
		t.Fatalf("expected ok=true, got %v (%+v)", result["ok"], stepsOf(t, result))
	}

	steps := stepsOf(t, result)
	if findStep(t, steps, "service_stop").Message != "stopped" {
		t.Errorf("unexpected service_stop step: %+v", findStep(t, steps, "service_stop"))
	}
	if findStep(t, steps, "service_remove").Message != "removed" {
		t.Errorf("unexpected service_remove step: %+v", findStep(t, steps, "service_remove"))
	}
	assertServiceGone(t, name)
}

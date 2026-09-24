package dispatcher

import (
	"context"
	"encoding/json"
	"net/http"
	"testing"
)

func TestStopLinuxInstanceStopsAndRemovesTheContainer(t *testing.T) {
	var sawStop, sawRemove bool
	startFakeDockerDaemon(t, func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == http.MethodPost && r.URL.Path == "/containers/Healer-phase13-9100/stop":
			sawStop = true
			w.WriteHeader(http.StatusNoContent)
		case r.Method == http.MethodDelete:
			sawRemove = true
			w.WriteHeader(http.StatusNoContent)
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	})

	payload := stopInstancePayload{Adapter: "linux-docker", ServiceName: "Healer-phase13-9100"}
	raw, _ := json.Marshal(payload)

	result, err := HandleStopInstance(context.Background(), raw)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result["ok"] != true {
		t.Fatalf("expected ok true, got %v", result)
	}
	if !sawStop || !sawRemove {
		t.Errorf("expected both stop and remove calls, got stop=%v remove=%v", sawStop, sawRemove)
	}
}

func TestStopLinuxInstanceTreatsAnAlreadyGoneContainerAsSuccess(t *testing.T) {
	startFakeDockerDaemon(t, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	})

	payload := stopInstancePayload{Adapter: "linux-docker", ServiceName: "Healer-ghost-9999"}
	raw, _ := json.Marshal(payload)

	result, err := HandleStopInstance(context.Background(), raw)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result["ok"] != true {
		t.Fatalf("expected ok true for an already-gone container, got %v", result)
	}
}

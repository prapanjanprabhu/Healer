package dispatcher

import (
	"context"
	"encoding/json"
	"net/http"
	"testing"
)

func TestStartLinuxInstanceCreatesAndStartsAContainer(t *testing.T) {
	var sawNetworkCheck, sawCreate, sawStart bool
	startFakeDockerDaemon(t, func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/networks/healer-apps" && r.Method == http.MethodGet:
			sawNetworkCheck = true
			w.WriteHeader(http.StatusOK) // network already exists
		case r.URL.Path == "/containers/create":
			sawCreate = true
			w.Header().Set("Content-Type", "application/json")
			w.Write([]byte(`{"Id":"abc123"}`))
		case r.Method == http.MethodDelete:
			w.WriteHeader(http.StatusNotFound) // nothing to remove first time
		case r.URL.Path == "/containers/Healer-phase13-9100/start":
			sawStart = true
			w.WriteHeader(http.StatusNoContent)
		case r.URL.Path == "/containers/Healer-phase13-9100/json":
			w.Header().Set("Content-Type", "application/json")
			w.Write([]byte(`{"State":{"Status":"running","Running":true,"ExitCode":0}}`))
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	})

	payload := startInstancePayload{
		Adapter: "linux-docker", ServiceName: "Healer-phase13-9100", Port: 9100,
		Linux: &startLinux{ImageRef: "healer-phase13:1", InternalPort: 8000, Env: map[string]string{"FOO": "bar"}},
	}
	raw, _ := json.Marshal(payload)

	result, err := HandleStartInstance(context.Background(), raw)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result["ok"] != true {
		t.Fatalf("expected ok true, got %v", result)
	}
	if result["container_id"] != "abc123" {
		t.Errorf("expected container_id abc123, got %v", result["container_id"])
	}
	if !sawNetworkCheck || !sawCreate || !sawStart {
		t.Errorf("expected network/create/start calls, got network=%v create=%v start=%v",
			sawNetworkCheck, sawCreate, sawStart)
	}
}

func TestStartLinuxInstanceReportsFailureWhenContainerExitsImmediately(t *testing.T) {
	startFakeDockerDaemon(t, func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/networks/healer-apps":
			w.WriteHeader(http.StatusOK)
		case r.URL.Path == "/containers/create":
			w.Header().Set("Content-Type", "application/json")
			w.Write([]byte(`{"Id":"deadbeef"}`))
		case r.Method == http.MethodDelete:
			w.WriteHeader(http.StatusNotFound)
		case r.URL.Path == "/containers/Healer-phase13-9101/start":
			w.WriteHeader(http.StatusNoContent)
		case r.URL.Path == "/containers/Healer-phase13-9101/json":
			w.Header().Set("Content-Type", "application/json")
			w.Write([]byte(`{"State":{"Status":"exited","Running":false,"ExitCode":1}}`))
		case r.URL.Path == "/containers/Healer-phase13-9101/logs":
			w.Write([]byte("boom: missing env var\n"))
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	})

	payload := startInstancePayload{
		Adapter: "linux-docker", ServiceName: "Healer-phase13-9101", Port: 9101,
		Linux: &startLinux{ImageRef: "healer-phase13:1", InternalPort: 8000},
	}
	raw, _ := json.Marshal(payload)

	result, err := HandleStartInstance(context.Background(), raw)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result["ok"] != false {
		t.Fatalf("expected ok false for an immediately-exited container, got %v", result)
	}
}

func TestValidateStartInstancePayloadRejectsMissingLinuxImageRef(t *testing.T) {
	payload := startInstancePayload{
		Adapter: "linux-docker", ServiceName: "svc", Port: 9100,
		Linux: &startLinux{InternalPort: 8000},
	}
	if err := validateStartInstancePayload(payload); err == nil {
		t.Fatal("expected an error when linux.image_ref is empty")
	}
}

package dispatcher

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

// startFakeDockerDaemon runs a minimal fake Docker Engine API on a Unix
// socket and points HEALER_DOCKER_SOCKET at it for the duration of the
// test, so deployLinuxRelease's dockerengine.New() calls reach it instead
// of a real daemon — this machine (and CI) may have no real Docker at
// /var/run/docker.sock at all (this suite runs on Windows), so this is the
// only way to exercise the Linux adapter's control flow for real.
func startFakeDockerDaemon(t *testing.T, handler http.HandlerFunc) {
	t.Helper()
	dir, err := os.MkdirTemp("", "hlr")
	if err != nil {
		t.Fatalf("create temp dir: %v", err)
	}
	t.Cleanup(func() { os.RemoveAll(dir) })
	socketPath := filepath.Join(dir, "d.sock")

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("listen on fake docker socket: %v", err)
	}
	server := &httptest.Server{Listener: listener, Config: &http.Server{Handler: handler}}
	server.Start()
	t.Cleanup(server.Close)

	t.Setenv("HEALER_DOCKER_SOCKET", socketPath)
}

func fakeDockerHandler(t *testing.T) http.HandlerFunc {
	t.Helper()
	return func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/_ping":
			w.WriteHeader(http.StatusOK)
		case r.URL.Path == "/build":
			w.Write([]byte(`{"stream":"Successfully built\n"}` + "\n"))
		case r.URL.Path == "/images/create":
			w.Write([]byte(`{"status":"Pull complete"}` + "\n"))
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}
}

func TestDeployLinuxReleasePullsAnImmutableImageReference(t *testing.T) {
	startFakeDockerDaemon(t, fakeDockerHandler(t))

	payload := deployReleasePayload{
		Adapter: "linux-docker", AppSlug: "phase13-erp", ReleaseVersion: "20260101000000",
		Source: deploySource{Type: "image", Location: "nginx:1.25"},
		Linux:  &deployLinux{InternalPort: 8000},
	}
	raw, _ := json.Marshal(payload)

	result, err := HandleDeployRelease(context.Background(), raw)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result["ok"] != true {
		t.Fatalf("expected ok true, got %v", result)
	}
	if result["image_ref"] != "nginx:1.25" {
		t.Errorf("expected image_ref to be the pulled reference, got %v", result["image_ref"])
	}
}

func TestDeployLinuxReleaseBuildsFromADockerfileDirectory(t *testing.T) {
	startFakeDockerDaemon(t, fakeDockerHandler(t))

	contextDir := t.TempDir()
	if err := os.WriteFile(filepath.Join(contextDir, "Dockerfile"), []byte("FROM scratch\n"), 0o644); err != nil {
		t.Fatalf("write Dockerfile: %v", err)
	}

	payload := deployReleasePayload{
		Adapter: "linux-docker", AppSlug: "phase13-erp", ReleaseVersion: "20260101000001",
		Source: deploySource{Type: "dockerfile", Location: contextDir},
		Linux:  &deployLinux{InternalPort: 8000},
	}
	raw, _ := json.Marshal(payload)

	result, err := HandleDeployRelease(context.Background(), raw)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result["ok"] != true {
		t.Fatalf("expected ok true, got %v", result)
	}
	if result["image_ref"] != "healer-phase13-erp:20260101000001" {
		t.Errorf("expected the built tag as image_ref, got %v", result["image_ref"])
	}
}

func TestDeployLinuxReleaseFailsCleanlyWhenDockerIsUnreachable(t *testing.T) {
	t.Setenv("HEALER_DOCKER_SOCKET", filepath.Join(t.TempDir(), "no-daemon-here.sock"))

	payload := deployReleasePayload{
		Adapter: "linux-docker", AppSlug: "phase13-erp", ReleaseVersion: "20260101000002",
		Source: deploySource{Type: "image", Location: "nginx:1.25"},
		Linux:  &deployLinux{InternalPort: 8000},
	}
	raw, _ := json.Marshal(payload)

	result, err := HandleDeployRelease(context.Background(), raw)
	if err != nil {
		t.Fatalf("unexpected Go error (step failures should be data, not errors): %v", err)
	}
	if result["ok"] != false {
		t.Fatalf("expected ok false when docker is unreachable, got %v", result)
	}
	steps, ok := result["steps"].([]Step)
	if !ok || len(steps) < 2 {
		t.Fatalf("expected at least two steps, got %v", result["steps"])
	}
	if steps[0].Status != StepFailed {
		t.Errorf("expected docker_check to fail, got %+v", steps[0])
	}
	if steps[1].Status != StepSkipped {
		t.Errorf("expected build_or_pull to be skipped after docker_check failed, got %+v", steps[1])
	}
}

func TestValidateDeployPayloadRejectsMissingLinuxConfig(t *testing.T) {
	payload := deployReleasePayload{
		Adapter: "linux-docker", AppSlug: "app", ReleaseVersion: "1",
		Source: deploySource{Type: "image", Location: "nginx:1.25"},
	}
	if err := validateDeployPayload(payload); err == nil {
		t.Fatal("expected an error when linux config is missing")
	}
}

func TestValidateDeployPayloadRejectsUnsupportedSourceTypeForDocker(t *testing.T) {
	payload := deployReleasePayload{
		Adapter: "linux-docker", AppSlug: "app", ReleaseVersion: "1",
		Source: deploySource{Type: "folder", Location: "/tmp/whatever"},
		Linux:  &deployLinux{InternalPort: 8000},
	}
	if err := validateDeployPayload(payload); err == nil {
		t.Fatal("expected an error for source type 'folder' under linux-docker")
	}
}

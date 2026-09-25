package dispatcher

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"github.com/healer-platform/agent/internal/dockerengine"
)

// requireRealDocker skips a test that needs a genuinely reachable Docker
// daemon at the default socket — this repo's own dev machine (Windows) has
// no /var/run/docker.sock at that literal path, so this only runs where a
// real Linux Docker host (or a docker-outside-of-docker container with the
// host socket mounted in) is actually available. Mirrors
// start_instance_test.go's requireServiceManager skip for the same reason:
// a real environmental dependency this suite can't fake convincingly.
func requireRealDocker(t *testing.T) {
	t.Helper()
	client := dockerengine.New()
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err := client.Ping(ctx); err != nil {
		t.Skipf("requires a real, reachable Docker daemon: %v", err)
	}
}

// TestLinuxDockerAdapterFullLifecycleAgainstARealDaemon builds the sample
// containerized test app (agent/testdata/sample-docker-app), starts it,
// confirms it reaches a running state, then stops and removes it — the
// same deploy_release -> start_instance -> stop_instance sequence the
// Control Plane drives, exercised for real against an actual Docker
// daemon rather than the fake one client_test.go/deploy_release_docker_test.go
// use for the rest of this suite's fast, hermetic coverage.
func TestLinuxDockerAdapterFullLifecycleAgainstARealDaemon(t *testing.T) {
	requireRealDocker(t)

	const slug = "sample-docker-app"
	const version = "test1"
	const serviceName = "Healer-sample-docker-app-19100"

	deployPayload := deployReleasePayload{
		Adapter: "linux-docker", AppSlug: slug, ReleaseVersion: version,
		Source: deploySource{Type: "dockerfile", Location: "../../testdata/sample-docker-app"},
		Linux:  &deployLinux{InternalPort: 8000},
	}
	raw, err := json.Marshal(deployPayload)
	if err != nil {
		t.Fatalf("marshal deploy payload: %v", err)
	}
	deployResult, err := HandleDeployRelease(context.Background(), raw)
	if err != nil {
		t.Fatalf("unexpected error from deploy_release: %v", err)
	}
	if deployResult["ok"] != true {
		t.Fatalf("expected deploy_release to succeed, got %v", deployResult)
	}
	imageRef, _ := deployResult["image_ref"].(string)
	if imageRef == "" {
		t.Fatalf("expected a non-empty image_ref, got %v", deployResult)
	}
	t.Cleanup(func() { _ = dockerengine.New().RemoveImage(context.Background(), imageRef) })
	t.Cleanup(func() {
		dockerengine.New().RemoveContainer(context.Background(), serviceName, true)
	})

	startPayload := startInstancePayload{
		Adapter: "linux-docker", ServiceName: serviceName, Port: 19100,
		Linux: &startLinux{ImageRef: imageRef, InternalPort: 8000, Env: map[string]string{"MODE": "integration-test"}},
	}
	raw, err = json.Marshal(startPayload)
	if err != nil {
		t.Fatalf("marshal start payload: %v", err)
	}
	startResult, err := HandleStartInstance(context.Background(), raw)
	if err != nil {
		t.Fatalf("unexpected error from start_instance: %v", err)
	}
	if startResult["ok"] != true {
		t.Fatalf("expected start_instance to succeed, got %v", startResult)
	}

	client := dockerengine.New()
	state, err := client.InspectContainer(context.Background(), serviceName)
	if err != nil {
		t.Fatalf("inspect container: %v", err)
	}
	if !state.Running {
		t.Fatalf("expected the container to be running, got state %+v", state)
	}

	stopPayload := stopInstancePayload{Adapter: "linux-docker", ServiceName: serviceName}
	raw, err = json.Marshal(stopPayload)
	if err != nil {
		t.Fatalf("marshal stop payload: %v", err)
	}
	stopResult, err := HandleStopInstance(context.Background(), raw)
	if err != nil {
		t.Fatalf("unexpected error from stop_instance: %v", err)
	}
	if stopResult["ok"] != true {
		t.Fatalf("expected stop_instance to succeed, got %v", stopResult)
	}

	finalState, err := client.InspectContainer(context.Background(), serviceName)
	if err != nil {
		t.Fatalf("inspect container after stop: %v", err)
	}
	if finalState.Exists {
		t.Errorf("expected the container to be removed after stop_instance, got %+v", finalState)
	}
	cleanup := deployReleasePayload{
		Operation: "cleanup_image", Adapter: "linux-docker", AppSlug: slug, ReleaseVersion: version,
	}
	cleanupRaw, _ := json.Marshal(cleanup)
	cleanupResult, err := HandleDeployRelease(context.Background(), cleanupRaw)
	if err != nil || cleanupResult["ok"] != true {
		t.Fatalf("expected the unused test image to be removed, result=%v err=%v", cleanupResult, err)
	}
}

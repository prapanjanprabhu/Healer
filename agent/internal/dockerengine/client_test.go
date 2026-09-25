package dockerengine

import (
	"bytes"
	"context"
	"encoding/binary"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// fakeDaemon is a minimal stand-in for the Docker Engine API, listening on
// a Unix socket exactly like the real daemon — so Client (which only knows
// how to dial a Unix socket) is exercised for real, not against a TCP
// httptest.Server it would never actually see in production.
type fakeDaemon struct {
	server   *httptest.Server
	client   *Client
	networks map[string]bool
}

func newFakeDaemon(t *testing.T, handler func(*fakeDaemon, http.ResponseWriter, *http.Request)) *fakeDaemon {
	t.Helper()
	// A short, test-name-independent temp dir: Windows AF_UNIX socket paths
	// are limited to ~108 bytes, and t.TempDir() embeds the full (often
	// long) test name, which overflows that limit for several tests here.
	dir, err := os.MkdirTemp("", "hlr")
	if err != nil {
		t.Fatalf("create temp dir for fake socket: %v", err)
	}
	t.Cleanup(func() { os.RemoveAll(dir) })
	socketPath := filepath.Join(dir, "d.sock")

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("listen on fake socket: %v", err)
	}

	fd := &fakeDaemon{networks: map[string]bool{}}
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		handler(fd, w, r)
	})

	server := &httptest.Server{Listener: listener, Config: &http.Server{Handler: mux}}
	server.Start()
	t.Cleanup(server.Close)

	fd.server = server
	fd.client = NewWithSocket(socketPath)
	return fd
}

func TestPingSucceedsAgainstAReachableDaemon(t *testing.T) {
	fd := newFakeDaemon(t, func(_ *fakeDaemon, w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/_ping" {
			w.WriteHeader(http.StatusOK)
			return
		}
		w.WriteHeader(http.StatusNotFound)
	})
	if err := fd.client.Ping(context.Background()); err != nil {
		t.Fatalf("expected Ping to succeed, got %v", err)
	}
}

func TestVersionReportsTheDaemonVersionString(t *testing.T) {
	fd := newFakeDaemon(t, func(_ *fakeDaemon, w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/version" {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"Version": "24.0.7", "ApiVersion": "1.43"})
	})
	version, err := fd.client.Version(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if version != "24.0.7 (API 1.43)" {
		t.Errorf("unexpected version string: %q", version)
	}
}

func TestEnsureNetworkCreatesOnlyWhenMissing(t *testing.T) {
	var createCalls int
	fd := newFakeDaemon(t, func(fd *fakeDaemon, w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == http.MethodGet && r.URL.Path == "/networks/healer-apps":
			if fd.networks["healer-apps"] {
				w.WriteHeader(http.StatusOK)
			} else {
				w.WriteHeader(http.StatusNotFound)
			}
		case r.Method == http.MethodPost && r.URL.Path == "/networks/create":
			createCalls++
			fd.networks["healer-apps"] = true
			w.WriteHeader(http.StatusCreated)
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	})

	if err := fd.client.EnsureNetwork(context.Background(), "healer-apps"); err != nil {
		t.Fatalf("first EnsureNetwork: %v", err)
	}
	if err := fd.client.EnsureNetwork(context.Background(), "healer-apps"); err != nil {
		t.Fatalf("second EnsureNetwork: %v", err)
	}
	if createCalls != 1 {
		t.Errorf("expected exactly one network-create call, got %d", createCalls)
	}
}

func TestBuildImageSucceedsAndTagsFromTheContextDirectory(t *testing.T) {
	contextDir := t.TempDir()
	if err := os.WriteFile(filepath.Join(contextDir, "Dockerfile"), []byte("FROM scratch\n"), 0o644); err != nil {
		t.Fatalf("write Dockerfile: %v", err)
	}
	if err := os.MkdirAll(filepath.Join(contextDir, ".git"), 0o755); err != nil {
		t.Fatalf("mkdir .git: %v", err)
	}

	var receivedTag string
	var sawGitDirInArchive bool
	fd := newFakeDaemon(t, func(_ *fakeDaemon, w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/build" {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		receivedTag = r.URL.Query().Get("t")
		body, _ := io.ReadAll(r.Body)
		if bytes.Contains(body, []byte(".git")) {
			sawGitDirInArchive = true
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"stream":"Step 1/1 : FROM scratch\n"}` + "\n"))
	})

	err := fd.client.BuildImage(context.Background(), contextDir, "Dockerfile", "healer-test:1", map[string]bool{".git": true})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if receivedTag != "healer-test:1" {
		t.Errorf("expected tag query param, got %q", receivedTag)
	}
	if sawGitDirInArchive {
		t.Error("expected the .git directory to be excluded from the build context")
	}
}

func TestBuildImageFailsWhenTheDaemonReportsAnErrorInTheStream(t *testing.T) {
	contextDir := t.TempDir()
	os.WriteFile(filepath.Join(contextDir, "Dockerfile"), []byte("FROM scratch\n"), 0o644)

	fd := newFakeDaemon(t, func(_ *fakeDaemon, w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"errorDetail":{"message":"no such file"},"error":"no such file"}` + "\n"))
	})

	err := fd.client.BuildImage(context.Background(), contextDir, "Dockerfile", "healer-test:1", nil)
	if err == nil {
		t.Fatal("expected an error when the build stream reports one")
	}
}

func TestPullImageSplitsRepositoryAndTagCorrectly(t *testing.T) {
	var gotFromImage, gotTag string
	fd := newFakeDaemon(t, func(_ *fakeDaemon, w http.ResponseWriter, r *http.Request) {
		gotFromImage = r.URL.Query().Get("fromImage")
		gotTag = r.URL.Query().Get("tag")
		w.Write([]byte(`{"status":"Pull complete"}` + "\n"))
	})

	if err := fd.client.PullImage(context.Background(), "registry.example:5000/app:v2"); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if gotFromImage != "registry.example:5000/app" || gotTag != "v2" {
		t.Errorf("expected fromImage=registry.example:5000/app tag=v2, got fromImage=%q tag=%q", gotFromImage, gotTag)
	}
}

func TestCreateContainerRemovesAnyExistingContainerFirst(t *testing.T) {
	var deleteCalled, createCalled bool
	fd := newFakeDaemon(t, func(_ *fakeDaemon, w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == http.MethodDelete:
			deleteCalled = true
			w.WriteHeader(http.StatusNoContent)
		case r.Method == http.MethodPost && r.URL.Path == "/containers/create":
			createCalled = true
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(map[string]string{"Id": "abc123"})
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	})

	id, err := fd.client.CreateContainer(context.Background(), "healer-app-9100", ContainerSpec{
		Image: "healer-app:1", InternalPort: 8000, HostPort: 9100, Env: map[string]string{"FOO": "bar"},
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !deleteCalled || !createCalled {
		t.Errorf("expected both a remove and a create call, got delete=%v create=%v", deleteCalled, createCalled)
	}
	if id != "abc123" {
		t.Errorf("expected the created container id, got %q", id)
	}
}

func TestStopAndRemoveContainerTreatMissingAsSuccess(t *testing.T) {
	fd := newFakeDaemon(t, func(_ *fakeDaemon, w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	})
	if err := fd.client.StopContainer(context.Background(), "ghost", 5); err != nil {
		t.Errorf("expected stopping a missing container to succeed, got %v", err)
	}
	if err := fd.client.RemoveContainer(context.Background(), "ghost", true); err != nil {
		t.Errorf("expected removing a missing container to succeed, got %v", err)
	}
}

func TestInspectContainerReportsExistsFalseWhenMissing(t *testing.T) {
	fd := newFakeDaemon(t, func(_ *fakeDaemon, w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	})
	state, err := fd.client.InspectContainer(context.Background(), "ghost")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if state.Exists {
		t.Error("expected Exists to be false for a missing container")
	}
}

func TestInspectContainerReportsRunningState(t *testing.T) {
	fd := newFakeDaemon(t, func(_ *fakeDaemon, w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"State": map[string]any{"Status": "running", "Running": true, "ExitCode": 0},
		})
	})
	state, err := fd.client.InspectContainer(context.Background(), "healer-app-9100")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !state.Exists || !state.Running || state.Status != "running" {
		t.Errorf("unexpected state: %+v", state)
	}
}

func TestContainerLogsDemultiplexesTheDockerFrameFormat(t *testing.T) {
	fd := newFakeDaemon(t, func(_ *fakeDaemon, w http.ResponseWriter, r *http.Request) {
		writeDockerLogFrame(w, 1, "hello stdout\n")
		writeDockerLogFrame(w, 2, "hello stderr\n")
	})
	logs, err := fd.client.ContainerLogs(context.Background(), "healer-app-9100", 100)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if logs != "hello stdout\nhello stderr\n" {
		t.Errorf("unexpected demuxed logs: %q", logs)
	}
}

func writeDockerLogFrame(w http.ResponseWriter, streamType byte, text string) {
	header := make([]byte, 8)
	header[0] = streamType
	binary.BigEndian.PutUint32(header[4:8], uint32(len(text)))
	w.Write(header)
	w.Write([]byte(text))
}

func TestSplitImageRefHandlesARegistryPortWithoutMistakingItForTheTagSeparator(t *testing.T) {
	name, tag := splitImageRef("registry.example:5000/app:v2")
	if name != "registry.example:5000/app" || tag != "v2" {
		t.Errorf("got name=%q tag=%q", name, tag)
	}
}

func TestSplitImageRefDefaultsToLatestWhenNoTagGiven(t *testing.T) {
	name, tag := splitImageRef("nginx")
	if name != "nginx" || tag != "latest" {
		t.Errorf("got name=%q tag=%q", name, tag)
	}
}

func TestSplitImageRefKeepsDigestWithoutAddingLatest(t *testing.T) {
	ref := "registry.example:5000/app@sha256:" + strings.Repeat("a", 64)
	name, tag := splitImageRef(ref)
	if name != ref || tag != "" {
		t.Errorf("got name=%q tag=%q", name, tag)
	}
}

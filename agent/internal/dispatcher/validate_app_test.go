package dispatcher

import (
	"context"
	"encoding/json"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"testing"
)

func findCheck(t *testing.T, checks []Check, name string) Check {
	t.Helper()
	for _, c := range checks {
		if c.Name == name {
			return c
		}
	}
	t.Fatalf("no check named %q in %+v", name, checks)
	return Check{}
}

func runValidateApp(t *testing.T, payload map[string]any) []Check {
	t.Helper()
	raw, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal payload: %v", err)
	}
	result, err := HandleValidateApp(context.Background(), raw)
	if err != nil {
		t.Fatalf("HandleValidateApp: %v", err)
	}
	checks, ok := result["checks"].([]Check)
	if !ok {
		t.Fatalf("expected result[\"checks\"] to be []Check, got %T", result["checks"])
	}
	return checks
}

func TestHealthPathCheck(t *testing.T) {
	if c := healthPathCheck("/health/"); !c.Passed {
		t.Errorf("expected /health/ to pass: %+v", c)
	}
	if c := healthPathCheck("health/"); c.Passed {
		t.Errorf("expected a path without a leading slash to fail: %+v", c)
	}
}

func TestPortRangeCheckReportsFreePorts(t *testing.T) {
	// A hardcoded "probably free" range is not reliable: Windows reserves
	// large swaths of high ports for Hyper-V/WSL NAT (`netsh int ipv4 show
	// excludedportrange`), especially on a machine running Docker Desktop —
	// found by hand when a hardcoded range collided with one. Ask the OS
	// for a real free port instead, exactly as the occupied-port test below
	// already does.
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	port := listener.Addr().(*net.TCPAddr).Port
	listener.Close()

	checks := portRangeCheck(port, port)
	if len(checks) != 1 || !checks[0].Passed {
		t.Fatalf("expected the range to be reported free: %+v", checks)
	}
}

func TestPortRangeCheckReportsOccupiedPort(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	defer listener.Close()

	port := listener.Addr().(*net.TCPAddr).Port
	checks := portRangeCheck(port, port)
	if len(checks) != 1 || checks[0].Passed {
		t.Fatalf("expected the occupied port to be reported not free: %+v", checks)
	}
}

func TestValidateAppUnknownAdapterIsRejectedSafely(t *testing.T) {
	checks := runValidateApp(t, map[string]any{
		"adapter":          "run-arbitrary-shell-command",
		"health_path":      "/health",
		"port_range_start": 58010,
		"port_range_end":   58011,
		"source":           map[string]any{"type": "folder", "location": "."},
	})
	adapterCheck := findCheck(t, checks, "adapter")
	if adapterCheck.Passed {
		t.Error("an unsupported adapter must never report as passed")
	}
}

func TestValidateAppWindowsSourceMissingIsReported(t *testing.T) {
	checks := runValidateApp(t, map[string]any{
		"adapter":          "windows-waitress-service",
		"health_path":      "/health/",
		"port_range_start": 58020,
		"port_range_end":   58021,
		"source":           map[string]any{"type": "folder", "location": filepath.Join(t.TempDir(), "does-not-exist")},
		"windows": map[string]any{
			"python_executable": filepath.Join(t.TempDir(), "does-not-exist-python"),
			"requirements_file": "requirements.txt",
			"manage_py":         "manage.py",
			"wsgi_module":       "erp.wsgi",
			"settings_module":   "erp.settings",
		},
	})
	if findCheck(t, checks, "source.location").Passed {
		t.Error("expected a missing source folder to fail")
	}
	if findCheck(t, checks, "windows.python_executable").Passed {
		t.Error("expected a missing python executable to fail")
	}
}

func TestValidateAppWindowsHappyPath(t *testing.T) {
	t.Setenv("ProgramData", t.TempDir())
	sourceDir := t.TempDir()
	must(t, os.WriteFile(filepath.Join(sourceDir, "requirements.txt"), []byte("Django\n"), 0o644))
	must(t, os.WriteFile(filepath.Join(sourceDir, "manage.py"), []byte("#!/usr/bin/env python\n"), 0o644))
	must(t, os.MkdirAll(filepath.Join(sourceDir, "erp"), 0o755))
	must(t, os.WriteFile(filepath.Join(sourceDir, "erp", "wsgi.py"), []byte(""), 0o644))
	must(t, os.WriteFile(filepath.Join(sourceDir, "erp", "settings.py"), []byte(""), 0o644))

	pythonPath, err := findRealPythonForTest()
	if err != nil {
		t.Skipf("no python interpreter available to exercise the real --version check: %v", err)
	}

	checks := runValidateApp(t, map[string]any{
		"adapter":          "windows-waitress-service",
		"health_path":      "/health/",
		"port_range_start": 58030,
		"port_range_end":   58031,
		"source":           map[string]any{"type": "folder", "location": sourceDir},
		"windows": map[string]any{
			"python_executable": pythonPath,
			"requirements_file": "requirements.txt",
			"manage_py":         "manage.py",
			"wsgi_module":       "erp.wsgi",
			"settings_module":   "erp.settings",
		},
	})

	for _, name := range []string{
		"source.location", "windows.python_executable", "windows.requirements_file",
		"windows.manage_py", "windows.wsgi_module", "windows.settings_module", "data_dir_writable",
	} {
		if c := findCheck(t, checks, name); !c.Passed {
			t.Errorf("expected %s to pass, got %+v", name, c)
		}
	}
}

func TestValidateAppLinuxDockerfileMissingIsReported(t *testing.T) {
	checks := runValidateApp(t, map[string]any{
		"adapter":          "linux-docker",
		"health_path":      "/healthz",
		"port_range_start": 58040,
		"port_range_end":   58041,
		"source":           map[string]any{"type": "dockerfile", "location": filepath.Join(t.TempDir(), "nope")},
		"linux":            map[string]any{"internal_port": 8000},
	})
	if findCheck(t, checks, "source.location").Passed {
		t.Error("expected a missing Dockerfile to fail")
	}
	// docker_available will also very likely fail in a Windows-hosted test
	// runner (no /var/run/docker.sock there) — that's fine, it's not what
	// this test is checking.
}

func must(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

func findRealPythonForTest() (string, error) {
	candidates := []string{"python3", "python"}
	if runtime.GOOS == "windows" {
		candidates = []string{"python.exe", "python3.exe"}
	}
	for _, name := range candidates {
		if path, err := exec.LookPath(name); err == nil {
			return path, nil
		}
	}
	return "", os.ErrNotExist
}

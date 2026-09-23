package dispatcher

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/healer-platform/agent/internal/service"
)

// requireServiceManager skips a test that needs a real Windows Service
// Control Manager connection — which also means real administrative
// rights, since mgr.Connect asks for full access. Mirrors how
// validate_app_test.go skips when a real interpreter isn't available
// rather than mocking the dependency away.
func requireServiceManager(t *testing.T) {
	t.Helper()
	if _, err := service.StatusNamed("HealerServiceManagerProbe"); err != nil {
		t.Skipf("requires a real Windows Service Manager connection: %v", err)
	}
}

// installTestService registers a uniquely named, never-started service
// pointing at the test binary, and returns its name. Cleanup removes it
// even if the test fails part-way.
func installTestService(t *testing.T) string {
	t.Helper()
	name := fmt.Sprintf("HealerTestInstance%d", time.Now().UnixNano()%1_000_000)
	exePath, err := os.Executable()
	if err != nil {
		t.Fatalf("resolve the test binary path: %v", err)
	}
	if err := service.InstallNamed(name, name, "Healer test instance service.",
		exePath, []string{"instance-host", "never-started.json"}, instanceServiceAccount); err != nil {
		t.Fatalf("InstallNamed: %v", err)
	}
	t.Cleanup(func() { _ = service.UninstallNamed(name) })
	return name
}

func assertServiceGone(t *testing.T, name string) {
	t.Helper()
	status, err := service.StatusNamed(name)
	if err != nil {
		t.Fatalf("StatusNamed: %v", err)
	}
	if status != service.StatusNotInstalled {
		t.Errorf("expected service %s to be gone, got %q", name, status)
	}
}

func TestHandleStartInstanceRejectsStructurallyBrokenPayloads(t *testing.T) {
	cases := map[string]json.RawMessage{
		"malformed json":  json.RawMessage(`{"service_name":`),
		"empty payload":   json.RawMessage(`{}`),
		"no service name": mustJSON(t, map[string]any{"release_dir": `C:\r`, "venv_python": `C:\p.exe`, "wsgi_module": "erp.wsgi", "host": "127.0.0.1", "port": 9034, "log_dir": `C:\l`}),
		"no port": mustJSON(t, map[string]any{
			"service_name": "Healer-erp-9034", "release_dir": `C:\r`, "venv_python": `C:\p.exe`,
			"wsgi_module": "erp.wsgi", "host": "127.0.0.1", "log_dir": `C:\l`,
		}),
		"port out of range": mustJSON(t, map[string]any{
			"service_name": "Healer-erp-9034", "release_dir": `C:\r`, "venv_python": `C:\p.exe`,
			"wsgi_module": "erp.wsgi", "host": "127.0.0.1", "port": 70000, "log_dir": `C:\l`,
		}),
	}
	for name, raw := range cases {
		t.Run(name, func(t *testing.T) {
			// Must be an error, and must not panic — a broken payload can
			// never reach icacls or the service manager.
			if _, err := HandleStartInstance(context.Background(), raw); err == nil {
				t.Error("expected a Go error for a structurally broken payload")
			}
		})
	}
}

// TestWriteLaunchSpecMatchesTheHostingContract pins the exact launch-spec
// file the per-instance Windows Service is built around: the Agent's
// instance-host subcommand reads this same shape back.
func TestWriteLaunchSpecMatchesTheHostingContract(t *testing.T) {
	releaseDir := t.TempDir()
	logDir := filepath.Join(t.TempDir(), "logs")
	venvPython := filepath.Join(releaseDir, ".venv", "Scripts", "python.exe")
	specPath := filepath.Join(releaseDir, launchSpecName)

	must(t, writeLaunchSpec(specPath, startInstancePayload{
		ServiceName: "Healer-rit-academic-erp-9034",
		ReleaseDir:  releaseDir,
		VenvPython:  venvPython,
		WSGIModule:  "erp.wsgi",
		Host:        "127.0.0.1",
		Port:        9034,
		LogDir:      logDir,
	}))

	data, err := os.ReadFile(specPath)
	if err != nil {
		t.Fatalf("read launch spec: %v", err)
	}
	var spec launchSpec
	if err := json.Unmarshal(data, &spec); err != nil {
		t.Fatalf("parse launch spec: %v", err)
	}

	wantExe := filepath.Join(releaseDir, ".venv", "Scripts", "waitress-serve.exe")
	if spec.Exe != wantExe {
		t.Errorf("expected exe %q, got %q", wantExe, spec.Exe)
	}
	wantArgs := []string{"--host=127.0.0.1", "--port=9034", "erp.wsgi:application"}
	if len(spec.Args) != len(wantArgs) {
		t.Fatalf("expected args %v, got %v", wantArgs, spec.Args)
	}
	for i, arg := range wantArgs {
		if spec.Args[i] != arg {
			t.Errorf("arg %d: expected %q, got %q", i, arg, spec.Args[i])
		}
	}
	if spec.WorkingDir != releaseDir {
		t.Errorf("expected working_dir %q, got %q", releaseDir, spec.WorkingDir)
	}
	if want := filepath.Join(logDir, "Healer-rit-academic-erp-9034.out.log"); spec.StdoutLog != want {
		t.Errorf("expected stdout_log %q, got %q", want, spec.StdoutLog)
	}
	if want := filepath.Join(logDir, "Healer-rit-academic-erp-9034.err.log"); spec.StderrLog != want {
		t.Errorf("expected stderr_log %q, got %q", want, spec.StderrLog)
	}
	if _, err := os.Stat(logDir); err != nil {
		t.Errorf("expected the instance log directory to be created: %v", err)
	}
}

// TestNamedServiceInstallQueryRemoveCycle proves the SCM plumbing the
// start_instance/stop_instance handlers sit on: create under the
// low-privilege account, query, remove. The service is deliberately never
// started — the test binary is not an SCM-aware service binary, so Windows
// would (correctly) time it out; proving a real instance actually serves
// traffic is live manual verification, not a unit test.
func TestNamedServiceInstallQueryRemoveCycle(t *testing.T) {
	requireServiceManager(t)

	name := installTestService(t)
	exePath, err := os.Executable()
	if err != nil {
		t.Fatalf("resolve the test binary path: %v", err)
	}

	status, err := service.StatusNamed(name)
	if err != nil {
		t.Fatalf("StatusNamed: %v", err)
	}
	if status != service.StatusStopped {
		t.Errorf("expected a freshly installed service to be stopped, got %q", status)
	}

	// Installing the same name twice must be refused, which is why
	// start_instance removes an existing service before creating one.
	if err := service.InstallNamed(name, name, "", exePath, nil, ""); err == nil {
		t.Error("expected installing a duplicate service name to fail")
	}

	// StopNamed on an already-stopped service is success, not an error.
	if err := service.StopNamed(name); err != nil {
		t.Errorf("expected stopping an already-stopped service to succeed, got %v", err)
	}

	if err := service.UninstallNamed(name); err != nil {
		t.Fatalf("UninstallNamed: %v", err)
	}
	assertServiceGone(t, name)
	// Removing a service that isn't there must be safe.
	if err := service.UninstallNamed(name); err != nil {
		t.Errorf("expected removing an absent service to succeed, got %v", err)
	}
}

func TestHasAccountGrantMatchesIcaclsDisplaySpacing(t *testing.T) {
	// icacls displays this well-known account with a space
	// ("LOCAL SERVICE") even though granting it uses no space
	// ("LocalService") — see hasAccountGrant's doc comment.
	realOutput := "C:\\Python314 NT AUTHORITY\\LOCAL SERVICE:(OI)(CI)(RX)\n" +
		"BUILTIN\\Administrators:(F)\n\nSuccessfully processed 1 files"
	if !hasAccountGrant(realOutput) {
		t.Fatal("expected the LOCAL SERVICE entry to be detected despite the spacing difference")
	}
	if hasAccountGrant("C:\\Python314 BUILTIN\\Administrators:(F)") {
		t.Fatal("expected no match when the account isn't present at all")
	}
}

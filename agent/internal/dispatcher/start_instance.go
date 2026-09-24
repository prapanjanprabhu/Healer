package dispatcher

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/healer-platform/agent/internal/dockerengine"
	"github.com/healer-platform/agent/internal/service"
)

type startLinux struct {
	ImageRef      string            `json:"image_ref"`
	InternalPort  int               `json:"internal_port"`
	Env           map[string]string `json:"env"`
	CPULimit      float64           `json:"cpu_limit"`
	MemoryLimitMB int               `json:"memory_limit_mb"`
}

type startInstancePayload struct {
	Adapter     string      `json:"adapter"`
	ServiceName string      `json:"service_name"`
	ReleaseDir  string      `json:"release_dir"`
	VenvPython  string      `json:"venv_python"`
	WSGIModule  string      `json:"wsgi_module"`
	Host        string      `json:"host"`
	Port        int         `json:"port"`
	LogDir      string      `json:"log_dir"`
	Linux       *startLinux `json:"linux,omitempty"`
}

// dockerNetworkName is the single shared bridge network every Docker-adapter
// container joins — simple and sufficient for V1 (no stated requirement for
// per-application network isolation; see docs/security-boundaries.md).
const dockerNetworkName = "healer-apps"

// containerStartTimeout bounds how long start_instance waits for a freshly
// started container to report a running state.
const containerStartTimeout = 15 * time.Second

// launchSpec is the contract between start_instance and the Agent's own
// `instance-host` subcommand: start_instance writes one of these next to
// the release, and the Windows Service it registers runs
// `healer-agent instance-host <that file>`, which supervises waitress as
// its child. The Agent hosts the instance rather than the SCM launching
// waitress directly because a plain console program is not an SCM-aware
// service binary — it would never report Running and Windows would kill it.
type launchSpec struct {
	Exe        string   `json:"exe"`
	Args       []string `json:"args"`
	WorkingDir string   `json:"working_dir"`
	StdoutLog  string   `json:"stdout_log"`
	StderrLog  string   `json:"stderr_log"`
}

// launchSpecName is the file, inside the release directory, holding the
// launch spec for that release's instance.
const launchSpecName = ".instance-launch.json"

// instanceServiceAccount is the low-privilege built-in account application
// instances run as — deliberately not LocalSystem: a deployed Django app is
// the least trusted code on the machine.
const instanceServiceAccount = `NT AUTHORITY\LocalService`

// serviceRunningTimeout bounds how long start_instance waits for a freshly
// started service to report Running before calling it a failure.
const serviceRunningTimeout = 10 * time.Second

// HandleStartInstance makes one application instance run as its own
// Windows Service: it grants the low-privilege service account access to
// the application directory, registers (or re-registers) the service, and
// waits for it to actually reach the Running state.
//
// Like deploy_release, a step that fails is reported in the result with
// "ok": false rather than as a Go error, so the Control Plane sees which
// stage failed. It is idempotent: an existing service under the same name
// is stopped and removed before a fresh one is created, so a retried
// start_instance converges instead of colliding.
func HandleStartInstance(ctx context.Context, raw json.RawMessage) (map[string]any, error) {
	var payload startInstancePayload
	if err := json.Unmarshal(raw, &payload); err != nil {
		return nil, fmt.Errorf("invalid start_instance payload: %w", err)
	}
	if err := validateStartInstancePayload(payload); err != nil {
		return nil, err
	}

	if payload.Adapter == "linux-docker" {
		return startLinuxInstance(ctx, payload)
	}
	return startWindowsInstance(ctx, payload)
}

// startLinuxInstance converges one application instance to "a running
// container under this name, published on the allocated host port" — the
// Docker-adapter equivalent of startWindowsInstance's Windows Service
// install/start. Idempotent: CreateContainer removes any existing container
// under this name first (see dockerengine.Client.CreateContainer).
func startLinuxInstance(ctx context.Context, payload startInstancePayload) (map[string]any, error) {
	l := payload.Linux
	runner := &stepRunner{}
	client := dockerengine.New()

	runner.run("network", func() (string, error) {
		if err := client.EnsureNetwork(ctx, dockerNetworkName); err != nil {
			return "", fmt.Errorf("ensure docker network %s: %w", dockerNetworkName, err)
		}
		return fmt.Sprintf("network %s ready", dockerNetworkName), nil
	})

	var containerID string
	runner.run("container_create", func() (string, error) {
		id, err := client.CreateContainer(ctx, payload.ServiceName, dockerengine.ContainerSpec{
			Image:         l.ImageRef,
			Env:           l.Env,
			Network:       dockerNetworkName,
			HostPort:      payload.Port,
			InternalPort:  l.InternalPort,
			CPULimit:      l.CPULimit,
			MemoryLimitMB: l.MemoryLimitMB,
		})
		if err != nil {
			return "", fmt.Errorf("create container %s: %w", payload.ServiceName, err)
		}
		containerID = id
		return fmt.Sprintf("created container %s", payload.ServiceName), nil
	})

	runner.run("container_start", func() (string, error) {
		if err := client.StartContainer(ctx, payload.ServiceName); err != nil {
			return "", fmt.Errorf("start container %s: %w", payload.ServiceName, err)
		}
		return waitForContainerRunning(ctx, client, payload.ServiceName)
	})

	return map[string]any{
		"ok":           runner.ok(),
		"service_name": payload.ServiceName,
		"container_id": containerID,
		"steps":        runner.steps,
	}, nil
}

// waitForContainerRunning polls the container's state until it reports
// Running — a container can exit immediately after start (a bad entrypoint,
// a missing env var the app requires), which "start succeeded" alone would
// not catch. On a container that already exited, its recent logs are
// included in the failure so the reason is visible without a separate
// diagnostic round trip.
func waitForContainerRunning(ctx context.Context, client *dockerengine.Client, name string) (string, error) {
	deadline := time.Now().Add(containerStartTimeout)
	for {
		state, err := client.InspectContainer(ctx, name)
		if err != nil {
			return "", fmt.Errorf("inspect container %s: %w", name, err)
		}
		if state.Running {
			return "container is running", nil
		}
		if state.Exists && state.Status == "exited" {
			logs, _ := client.ContainerLogs(ctx, name, 50)
			return "", fmt.Errorf("container exited (exit code %d) shortly after starting: %s",
				state.ExitCode, truncateTail(logs))
		}
		if time.Now().After(deadline) {
			return "", fmt.Errorf("container %s did not reach the running state within %s (last status: %s)",
				name, containerStartTimeout, state.Status)
		}
		select {
		case <-ctx.Done():
			return "", errors.New("timed out waiting for the container to start: " + ctx.Err().Error())
		case <-time.After(500 * time.Millisecond):
		}
	}
}

func startWindowsInstance(ctx context.Context, payload startInstancePayload) (map[string]any, error) {
	// .../apps/<slug>/releases/<version> -> .../apps/<slug>
	appDir := filepath.Dir(filepath.Dir(payload.ReleaseDir))
	runner := &stepRunner{}

	runner.run("permissions", func() (string, error) {
		// A fixed, structured invocation of a real system tool — no shell,
		// no command text from the Control Plane. (OI)(CI)M grants Modify,
		// inherited by files and subdirectories; /T applies it to what is
		// already there. Once appDir's own ACL carries that (OI)(CI) entry,
		// NTFS applies it to newly-created children (like each new
		// release's directory) automatically at creation time — no need to
		// re-walk the whole tree on every later deploy of this app.
		existing, err := runCommand(ctx, "", "icacls.exe", appDir)
		if err != nil {
			return "", fmt.Errorf("query permissions on %s: %v: %s", appDir, err, truncateTail(existing))
		}
		if !hasAccountGrant(existing) {
			output, err := runCommand(ctx, "", "icacls.exe", appDir,
				"/grant", instanceServiceAccount+":(OI)(CI)M", "/T")
			if err != nil {
				return "", fmt.Errorf("granting %s access to %s failed: %v: %s",
					instanceServiceAccount, appDir, err, truncateTail(output))
			}
		}

		// The service this step installs runs *this Agent's own executable*
		// (in instance-host mode — see launchSpec's doc comment) under
		// instanceServiceAccount. That binary normally lives under an
		// Administrator's own profile directory, whose default NTFS ACL
		// grants nothing to other accounts — including LocalService — so
		// without this, StartService fails with "Access is denied" before
		// the SCM ever attempts to launch the process. Found the hard way:
		// this exact failure, reproduced even from an elevated caller,
		// tracing to `icacls <agent.exe>` showing no LocalService entry at
		// all. Read-and-execute on the one file is enough; no inheritance
		// needed since it isn't a directory.
		agentExe, err := os.Executable()
		if err != nil {
			return "", fmt.Errorf("resolve this agent's executable path: %w", err)
		}
		exeOutput, err := runCommand(ctx, "", "icacls.exe", agentExe,
			"/grant", instanceServiceAccount+":RX")
		if err != nil {
			return "", fmt.Errorf("granting %s access to %s failed: %v: %s",
				instanceServiceAccount, agentExe, err, truncateTail(exeOutput))
		}

		// A venv's own Scripts\python.exe is not a self-contained copy on
		// Windows — even with `venv --copies`, it still loads pythonXXX.dll
		// and the standard library from the *base* interpreter's install
		// directory at runtime. So whatever ends up running this instance
		// (waitress-serve.exe's embedded launcher re-execs that venv
		// python.exe) transitively needs read+execute there too. Found the
		// hard way: waitress failed to start with "did not find executable
		// at '<base python.exe>': Access is denied" even though the venv's
		// own python.exe was correctly targeted — pyvenv.cfg's `home` is
		// the authoritative source for that path, not something worth a
		// separate payload field for.
		baseHome, err := baseInterpreterHome(payload.ReleaseDir)
		if err != nil {
			return "", fmt.Errorf("determine the base Python installation directory: %w", err)
		}
		// The recursive grant below can take minutes on a large stdlib tree
		// (Windows Defender real-time scanning touches every file as icacls
		// walks it) — but it's idempotent per base interpreter, and every
		// release built from the same Python install needs the exact same
		// grant. Once one deploy has paid that cost, every later deploy
		// (redeploys of this app, or any other app sharing the interpreter)
		// should not pay it again. A plain `icacls <dir>` (no /T — just
		// reads the top-level ACL, this is fast) already shows an inherited
		// grant if a previous /T run added one.
		alreadyGranted, err := runCommand(ctx, "", "icacls.exe", baseHome)
		if err != nil {
			return "", fmt.Errorf("query permissions on %s: %v: %s", baseHome, err, truncateTail(alreadyGranted))
		}
		if !hasAccountGrant(alreadyGranted) {
			homeOutput, err := runCommand(ctx, "", "icacls.exe", baseHome,
				"/grant", instanceServiceAccount+":(OI)(CI)RX", "/T")
			if err != nil {
				return "", fmt.Errorf("granting %s access to %s failed: %v: %s",
					instanceServiceAccount, baseHome, err, truncateTail(homeOutput))
			}
		}
		return "granted the low-privilege service account access to the app directory, the Agent executable, and the base Python installation", nil
	})

	runner.run("service_install", func() (string, error) {
		agentExe, err := os.Executable()
		if err != nil {
			return "", fmt.Errorf("resolve this agent's executable path: %w", err)
		}

		specPath := filepath.Join(payload.ReleaseDir, launchSpecName)
		if err := writeLaunchSpec(specPath, payload); err != nil {
			return "", err
		}

		if err := removeServiceIfPresent(payload.ServiceName); err != nil {
			return "", err
		}

		if err := service.InstallNamed(
			payload.ServiceName,
			payload.ServiceName,
			fmt.Sprintf("Healer-managed application instance (%s).", payload.ServiceName),
			agentExe,
			[]string{"instance-host", specPath},
			instanceServiceAccount,
		); err != nil {
			return "", fmt.Errorf("install service %s: %w", payload.ServiceName, err)
		}
		return fmt.Sprintf("created service %s", payload.ServiceName), nil
	})

	runner.run("service_start", func() (string, error) {
		if err := service.StartNamed(payload.ServiceName); err != nil {
			return "", fmt.Errorf("start service %s: %w", payload.ServiceName, err)
		}
		return waitForRunning(ctx, payload.ServiceName)
	})

	return map[string]any{
		"ok":           runner.ok(),
		"service_name": payload.ServiceName,
		"steps":        runner.steps,
	}, nil
}

func validateStartInstancePayload(payload startInstancePayload) error {
	if strings.TrimSpace(payload.ServiceName) == "" {
		return errors.New("invalid start_instance payload: service_name must not be empty")
	}
	if payload.Port < 1 || payload.Port > 65535 {
		return fmt.Errorf("invalid start_instance payload: port %d is out of range", payload.Port)
	}

	if payload.Adapter == "linux-docker" {
		if payload.Linux == nil {
			return errors.New("invalid start_instance payload: missing linux config")
		}
		if strings.TrimSpace(payload.Linux.ImageRef) == "" {
			return errors.New("invalid start_instance payload: linux.image_ref must not be empty")
		}
		if payload.Linux.InternalPort < 1 || payload.Linux.InternalPort > 65535 {
			return fmt.Errorf("invalid start_instance payload: linux.internal_port %d is out of range", payload.Linux.InternalPort)
		}
		return nil
	}

	for name, value := range map[string]string{
		"release_dir": payload.ReleaseDir,
		"venv_python": payload.VenvPython,
		"wsgi_module": payload.WSGIModule,
		"host":        payload.Host,
		"log_dir":     payload.LogDir,
	} {
		if strings.TrimSpace(value) == "" {
			return fmt.Errorf("invalid start_instance payload: %s must not be empty", name)
		}
	}
	return nil
}

func writeLaunchSpec(specPath string, payload startInstancePayload) error {
	// waitress-serve.exe is installed by pip into the same Scripts
	// directory as the venv's python.exe, as the waitress package's console
	// script entry point.
	spec := launchSpec{
		Exe: filepath.Join(filepath.Dir(payload.VenvPython), "waitress-serve.exe"),
		Args: []string{
			fmt.Sprintf("--host=%s", payload.Host),
			fmt.Sprintf("--port=%d", payload.Port),
			fmt.Sprintf("%s:application", payload.WSGIModule),
		},
		WorkingDir: payload.ReleaseDir,
		StdoutLog:  filepath.Join(payload.LogDir, payload.ServiceName+".out.log"),
		StderrLog:  filepath.Join(payload.LogDir, payload.ServiceName+".err.log"),
	}

	if err := os.MkdirAll(payload.LogDir, 0o750); err != nil {
		return fmt.Errorf("create log directory %s: %w", payload.LogDir, err)
	}
	data, err := json.MarshalIndent(spec, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal launch spec: %w", err)
	}
	if err := os.WriteFile(specPath, data, 0o640); err != nil {
		return fmt.Errorf("write launch spec %s: %w", specPath, err)
	}
	return nil
}

// hasAccountGrant reports whether `icacls`'s query output already lists
// instanceServiceAccount. icacls *displays* well-known accounts with their
// canonical spacing ("NT AUTHORITY\LOCAL SERVICE"), which differs from the
// no-space spelling ("NT AUTHORITY\LocalService") Windows accepts when
// *granting* — found by hand when the skip check above never matched
// despite the grant genuinely being present, so every deploy re-paid the
// full recursive icacls cost. Comparing with whitespace stripped from both
// sides sidesteps the mismatch without hardcoding icacls's exact spelling.
func hasAccountGrant(icaclsOutput string) bool {
	strip := func(s string) string {
		return strings.ToUpper(strings.Join(strings.Fields(s), ""))
	}
	return strings.Contains(strip(icaclsOutput), strip(instanceServiceAccount))
}

// baseInterpreterHome reads the `home` key out of a venv's pyvenv.cfg — the
// directory of the base CPython installation that venv's python.exe
// redirects to at runtime. releaseDir is the release directory containing
// the `.venv` created by deploy_release's venv step.
func baseInterpreterHome(releaseDir string) (string, error) {
	cfgPath := filepath.Join(releaseDir, ".venv", "pyvenv.cfg")
	data, err := os.ReadFile(cfgPath)
	if err != nil {
		return "", fmt.Errorf("read %s: %w", cfgPath, err)
	}
	for _, line := range strings.Split(string(data), "\n") {
		key, value, found := strings.Cut(line, "=")
		if !found || strings.TrimSpace(key) != "home" {
			continue
		}
		home := strings.TrimSpace(value)
		if home == "" {
			return "", fmt.Errorf("%s has an empty 'home' value", cfgPath)
		}
		return home, nil
	}
	return "", fmt.Errorf("%s has no 'home' key", cfgPath)
}

// removeServiceIfPresent converges a service name to "not installed",
// stopping it first if needed. Shared with stop_instance — both want the
// same "make it not be there" behaviour, not an error if it already isn't.
func removeServiceIfPresent(name string) error {
	status, err := service.StatusNamed(name)
	if err != nil {
		return fmt.Errorf("query service %s: %w", name, err)
	}
	if status == service.StatusNotInstalled {
		return nil
	}
	if err := service.StopNamed(name); err != nil {
		return fmt.Errorf("stop existing service %s: %w", name, err)
	}
	if err := service.UninstallNamed(name); err != nil {
		return fmt.Errorf("remove existing service %s: %w", name, err)
	}
	return nil
}

// waitForRunning polls the service until it reports Running, since Start
// only means the SCM accepted the request — the instance may still fail on
// startup (a bad WSGI module, a port already taken).
func waitForRunning(ctx context.Context, name string) (string, error) {
	deadline := time.Now().Add(serviceRunningTimeout)
	var last string
	for {
		status, err := service.StatusNamed(name)
		if err != nil {
			return "", fmt.Errorf("query service %s: %w", name, err)
		}
		last = status
		if status == service.StatusRunning {
			return "service is running", nil
		}
		if time.Now().After(deadline) {
			return "", fmt.Errorf("service %s did not reach the running state within %s (last status: %s)",
				name, serviceRunningTimeout, last)
		}

		select {
		case <-ctx.Done():
			return "", errors.New("timed out waiting for the service to start: " + ctx.Err().Error())
		case <-time.After(500 * time.Millisecond):
		}
	}
}

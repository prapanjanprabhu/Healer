package dispatcher

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/healer-platform/agent/internal/config"
)

// Check is one pass/fail fact about the application config being
// validated. Severity mirrors app/domain/app_validation.py's on the
// Control Plane side: "error" blocks, "warning" doesn't, "info" is just
// informational (e.g. a computed fingerprint or version string).
type Check struct {
	Name     string `json:"name"`
	Severity string `json:"severity"`
	Passed   bool   `json:"passed"`
	Message  string `json:"message"`
}

type sourceInfo struct {
	Type     string `json:"type"`
	Location string `json:"location"`
}

type windowsInfo struct {
	PythonExecutable string `json:"python_executable"`
	RequirementsFile string `json:"requirements_file"`
	ManagePy         string `json:"manage_py"`
	WSGIModule       string `json:"wsgi_module"`
	SettingsModule   string `json:"settings_module"`
}

type linuxInfo struct {
	InternalPort int `json:"internal_port"`
}

type validateAppPayload struct {
	Adapter        string       `json:"adapter"`
	Source         sourceInfo   `json:"source"`
	Windows        *windowsInfo `json:"windows,omitempty"`
	Linux          *linuxInfo   `json:"linux,omitempty"`
	HealthPath     string       `json:"health_path"`
	PortRangeStart int          `json:"port_range_start"`
	PortRangeEnd   int          `json:"port_range_end"`
}

// HandleValidateApp runs every check this Agent can perform locally for a
// proposed application config — filesystem/interpreter/Docker/port checks
// that only make sense run on the actual target machine. It never starts
// the application, writes anything outside a throwaway temp file (the
// data-dir writability check), or runs anything but a single fixed
// `<python> --version` invocation — no shell, no arbitrary command.
func HandleValidateApp(_ context.Context, raw json.RawMessage) (map[string]any, error) {
	var payload validateAppPayload
	if err := json.Unmarshal(raw, &payload); err != nil {
		return nil, fmt.Errorf("invalid validate_app payload: %w", err)
	}

	var checks []Check
	checks = append(checks, healthPathCheck(payload.HealthPath))
	checks = append(checks, portRangeCheck(payload.PortRangeStart, payload.PortRangeEnd)...)

	switch payload.Adapter {
	case "windows-waitress-service":
		checks = append(checks, validateWindowsAdapter(payload)...)
	case "linux-docker":
		checks = append(checks, validateLinuxAdapter(payload)...)
	default:
		checks = append(checks, Check{
			Name: "adapter", Severity: "error", Passed: false,
			Message: fmt.Sprintf("this agent does not support adapter %q", payload.Adapter),
		})
	}

	return map[string]any{"checks": checks}, nil
}

func healthPathCheck(path string) Check {
	if strings.HasPrefix(path, "/") {
		return Check{Name: "health_path", Severity: "info", Passed: true, Message: "well-formed"}
	}
	return Check{Name: "health_path", Severity: "error", Passed: false, Message: "must start with '/'"}
}

func portRangeCheck(start, end int) []Check {
	if start < 1 || end < 1 || end < start || end > 65535 {
		return []Check{{
			Name: "port_range", Severity: "error", Passed: false,
			Message: fmt.Sprintf("invalid port range %d-%d", start, end),
		}}
	}

	var occupied []int
	for port := start; port <= end; port++ {
		listener, err := listenTCP(port)
		if err != nil {
			occupied = append(occupied, port)
			continue
		}
		_ = listener.Close()
	}

	if len(occupied) > 0 {
		return []Check{{
			Name: "port_range", Severity: "warning", Passed: false,
			Message: fmt.Sprintf("port(s) already in use on this server: %v", occupied),
		}}
	}
	return []Check{{
		Name: "port_range", Severity: "info", Passed: true,
		Message: fmt.Sprintf("ports %d-%d are all free on this server right now", start, end),
	}}
}

func validateWindowsAdapter(payload validateAppPayload) []Check {
	w := payload.Windows
	if w == nil {
		return []Check{{Name: "windows", Severity: "error", Passed: false, Message: "missing windows config"}}
	}

	var checks []Check
	sourcePath := payload.Source.Location

	switch payload.Source.Type {
	case "folder":
		checks = append(checks, pathExistsCheck("source.location", sourcePath, true))
	case "git":
		checks = append(checks, Check{
			Name: "source.location", Severity: "info", Passed: true,
			Message: "git source reachability is not validated until an actual deploy (a later phase)",
		})
	}

	checks = append(checks, pythonExecutableCheck(w.PythonExecutable))
	checks = append(checks, relativeFileExistsCheck("windows.requirements_file", sourcePath, w.RequirementsFile))
	checks = append(checks, relativeFileExistsCheck("windows.manage_py", sourcePath, w.ManagePy))
	checks = append(checks, modulePathCheck("windows.wsgi_module", sourcePath, w.WSGIModule))
	checks = append(checks, modulePathCheck("windows.settings_module", sourcePath, w.SettingsModule))
	checks = append(checks, dataDirWritableCheck())
	return checks
}

func pathExistsCheck(name, path string, mustBeDir bool) Check {
	info, err := os.Stat(path)
	if err != nil {
		return Check{Name: name, Severity: "error", Passed: false, Message: fmt.Sprintf("%s: %v", path, err)}
	}
	if mustBeDir && !info.IsDir() {
		return Check{
			Name: name, Severity: "error", Passed: false,
			Message: fmt.Sprintf("%s exists but is not a directory", path),
		}
	}
	return Check{Name: name, Severity: "info", Passed: true, Message: fmt.Sprintf("%s exists", path)}
}

func relativeFileExistsCheck(name, base, rel string) Check {
	if rel == "" {
		return Check{Name: name, Severity: "error", Passed: false, Message: "must not be empty"}
	}
	full := filepath.Join(base, rel)
	info, err := os.Stat(full)
	if err != nil {
		return Check{Name: name, Severity: "error", Passed: false, Message: fmt.Sprintf("%s: %v", full, err)}
	}
	if info.IsDir() {
		return Check{
			Name: name, Severity: "error", Passed: false,
			Message: fmt.Sprintf("%s is a directory, expected a file", full),
		}
	}
	return Check{Name: name, Severity: "info", Passed: true, Message: fmt.Sprintf("%s exists", full)}
}

// pythonExecutableCheck runs exactly one fixed, non-shell command —
// `<python_executable> --version` — to confirm the path is really a working
// Python interpreter, not just a file that happens to exist.
func pythonExecutableCheck(path string) Check {
	if path == "" {
		return Check{Name: "windows.python_executable", Severity: "error", Passed: false, Message: "must not be empty"}
	}
	if _, err := os.Stat(path); err != nil {
		return Check{Name: "windows.python_executable", Severity: "error", Passed: false, Message: fmt.Sprintf("%s: %v", path, err)}
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	output, err := exec.CommandContext(ctx, path, "--version").CombinedOutput()
	if err != nil {
		return Check{
			Name: "windows.python_executable", Severity: "error", Passed: false,
			Message: fmt.Sprintf("could not run %s --version: %v", path, err),
		}
	}
	return Check{
		Name: "windows.python_executable", Severity: "info", Passed: true,
		Message: strings.TrimSpace(string(output)),
	}
}

func modulePathCheck(name, base, module string) Check {
	if module == "" {
		return Check{Name: name, Severity: "error", Passed: false, Message: "must not be empty"}
	}
	rel := strings.ReplaceAll(module, ".", string(filepath.Separator)) + ".py"
	full := filepath.Join(base, rel)
	if _, err := os.Stat(full); err != nil {
		return Check{
			Name: name, Severity: "warning", Passed: false,
			Message: fmt.Sprintf("expected %s for module %q: %v", full, module, err),
		}
	}
	return Check{Name: name, Severity: "info", Passed: true, Message: fmt.Sprintf("found %s", full)}
}

func dataDirWritableCheck() Check {
	dir := config.DefaultDataDir()
	if err := os.MkdirAll(dir, 0o750); err != nil {
		return Check{Name: "data_dir_writable", Severity: "error", Passed: false, Message: fmt.Sprintf("%s: %v", dir, err)}
	}
	testFile := filepath.Join(dir, ".healer-validate-write-test")
	if err := os.WriteFile(testFile, []byte("ok"), 0o640); err != nil {
		return Check{
			Name: "data_dir_writable", Severity: "error", Passed: false,
			Message: fmt.Sprintf("%s is not writable: %v", dir, err),
		}
	}
	_ = os.Remove(testFile)
	return Check{Name: "data_dir_writable", Severity: "info", Passed: true, Message: fmt.Sprintf("%s is writable", dir)}
}

func validateLinuxAdapter(payload validateAppPayload) []Check {
	l := payload.Linux
	if l == nil {
		return []Check{{Name: "linux", Severity: "error", Passed: false, Message: "missing linux config"}}
	}

	checks := []Check{dockerAvailableCheck()}

	switch payload.Source.Type {
	case "dockerfile":
		checks = append(checks, dockerfileExistsCheck(payload.Source.Location))
	case "image":
		if strings.TrimSpace(payload.Source.Location) == "" {
			checks = append(checks, Check{Name: "source.location", Severity: "error", Passed: false, Message: "image reference must not be empty"})
		} else {
			checks = append(checks, Check{
				Name: "source.location", Severity: "info", Passed: true,
				Message: fmt.Sprintf(
					"image reference %q is well-formed (not pulled/verified until an actual deploy)",
					payload.Source.Location,
				),
			})
		}
	}

	if l.InternalPort < 1 || l.InternalPort > 65535 {
		checks = append(checks, Check{Name: "linux.internal_port", Severity: "error", Passed: false, Message: "must be between 1 and 65535"})
	} else {
		checks = append(checks, Check{Name: "linux.internal_port", Severity: "info", Passed: true, Message: "well-formed"})
	}

	return checks
}

func dockerfileExistsCheck(location string) Check {
	candidate := location
	info, err := os.Stat(candidate)
	if err != nil || info.IsDir() {
		candidate = filepath.Join(location, "Dockerfile")
		info, err = os.Stat(candidate)
	}
	if err != nil {
		return Check{
			Name: "source.location", Severity: "error", Passed: false,
			Message: fmt.Sprintf("no Dockerfile found at %s: %v", candidate, err),
		}
	}
	if info.IsDir() {
		return Check{
			Name: "source.location", Severity: "error", Passed: false,
			Message: fmt.Sprintf("%s is a directory, expected the Dockerfile itself", candidate),
		}
	}
	return Check{Name: "source.location", Severity: "info", Passed: true, Message: fmt.Sprintf("found %s", candidate)}
}

// dockerAvailableCheck dials the Docker daemon's Unix socket directly and
// makes one raw HTTP request to its API — no `docker` CLI, no shell.
func dockerAvailableCheck() Check {
	const socketPath = "/var/run/docker.sock"

	conn, err := net.DialTimeout("unix", socketPath, 2*time.Second)
	if err != nil {
		return Check{
			Name: "docker_available", Severity: "error", Passed: false,
			Message: fmt.Sprintf("cannot reach the Docker daemon at %s: %v", socketPath, err),
		}
	}
	defer conn.Close()

	request, err := http.NewRequest(http.MethodGet, "http://docker/version", nil)
	if err != nil {
		return Check{Name: "docker_available", Severity: "error", Passed: false, Message: err.Error()}
	}
	if err := request.Write(conn); err != nil {
		return Check{
			Name: "docker_available", Severity: "error", Passed: false,
			Message: fmt.Sprintf("could not query the Docker daemon: %v", err),
		}
	}

	response, err := http.ReadResponse(bufio.NewReader(conn), request)
	if err != nil {
		return Check{
			Name: "docker_available", Severity: "error", Passed: false,
			Message: fmt.Sprintf("could not read the Docker daemon's response: %v", err),
		}
	}
	defer response.Body.Close()

	if response.StatusCode != http.StatusOK {
		return Check{
			Name: "docker_available", Severity: "error", Passed: false,
			Message: fmt.Sprintf("Docker daemon responded with HTTP %d", response.StatusCode),
		}
	}
	return Check{Name: "docker_available", Severity: "info", Passed: true, Message: "Docker daemon is reachable"}
}

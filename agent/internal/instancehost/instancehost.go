// Package instancehost supervises a single application instance process
// (waitress serving a Django app) on behalf of the Windows Service Control
// Manager.
//
// It exists because waitress-serve.exe is an ordinary console program, not
// an SCM-aware service binary: pointed at directly, it would never complete
// the SCM start handshake and Windows would kill it. So the service the
// start_instance command registers runs the Agent's own executable with
// `instance-host <launch-spec.json>`, and this package runs waitress as a
// supervised child, wiring its output to the instance's log files.
//
// This path is deliberately separate from the Agent's enrollment,
// WebSocket, journal and dispatcher machinery — it starts one process and
// waits for it, nothing else.
package instancehost

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// LaunchSpec is written by the start_instance command handler; the two
// definitions are the same JSON contract (see
// internal/dispatcher/start_instance.go).
type LaunchSpec struct {
	Exe        string   `json:"exe"`
	Args       []string `json:"args"`
	WorkingDir string   `json:"working_dir"`
	StdoutLog  string   `json:"stdout_log"`
	StderrLog  string   `json:"stderr_log"`
}

// LoadSpec reads and validates a launch spec file.
func LoadSpec(path string) (LaunchSpec, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return LaunchSpec{}, fmt.Errorf("read launch spec %s: %w", path, err)
	}
	var spec LaunchSpec
	if err := json.Unmarshal(data, &spec); err != nil {
		return LaunchSpec{}, fmt.Errorf("parse launch spec %s: %w", path, err)
	}
	if strings.TrimSpace(spec.Exe) == "" {
		return LaunchSpec{}, fmt.Errorf("launch spec %s has no exe", path)
	}
	return spec, nil
}

// Run returns a func(ctx) error — assignable to service.RunFunc — that
// starts the spec's process and waits for either the child to exit or ctx
// to be cancelled (which is how a service stop request arrives).
func Run(spec LaunchSpec) func(ctx context.Context) error {
	return func(ctx context.Context) error {
		stdout, err := openLog(spec.StdoutLog)
		if err != nil {
			return err
		}
		defer closeLog(stdout)

		stderr, err := openLog(spec.StderrLog)
		if err != nil {
			return err
		}
		defer closeLog(stderr)

		cmd := exec.CommandContext(ctx, spec.Exe, spec.Args...)
		cmd.Dir = spec.WorkingDir
		cmd.Stdout = stdout
		cmd.Stderr = stderr

		if err := cmd.Start(); err != nil {
			return fmt.Errorf("start %s: %w", spec.Exe, err)
		}

		exited := make(chan error, 1)
		go func() { exited <- cmd.Wait() }()

		select {
		case err := <-exited:
			if err != nil {
				return fmt.Errorf("%s exited: %w", spec.Exe, err)
			}
			return nil

		case <-ctx.Done():
			// V1 simplification: a hard kill, not a graceful drain — a
			// graceful shutdown handshake with waitress is a later phase.
			_ = cmd.Process.Kill()
			<-exited
			return nil
		}
	}
}

// openLog opens a log file for appending, creating it and its directory if
// needed. An empty path means "discard", not an error.
func openLog(path string) (io.WriteCloser, error) {
	if strings.TrimSpace(path) == "" {
		return nil, nil
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o750); err != nil {
		return nil, fmt.Errorf("create log directory for %s: %w", path, err)
	}
	file, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o640)
	if err != nil {
		return nil, fmt.Errorf("open log file %s: %w", path, err)
	}
	return file, nil
}

func closeLog(w io.WriteCloser) {
	if w != nil {
		_ = w.Close()
	}
}

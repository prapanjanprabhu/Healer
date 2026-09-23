//go:build windows

package service

import (
	"errors"
	"fmt"
	"time"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/svc"
	"golang.org/x/sys/windows/svc/mgr"
)

// The generic, parameterized service operations in this file manage
// *application instance* services (one Windows Service per running app
// instance, created by the start_instance command) rather than the Agent's
// own service. They deliberately mirror — but do not replace — the
// unparameterized Install/Uninstall/Start/Stop in service_windows.go, which
// stay exactly as they are so the Agent's own self-registration keeps
// working unchanged.

// InstallNamed registers an arbitrary Windows Service that starts
// automatically, running exePath with args.
//
// account selects the service's logon identity: "" keeps the SCM default
// (LocalSystem, matching the existing Install), and a well-known account
// such as `NT AUTHORITY\LocalService` is set with a blank password, which
// is correct — well-known service accounts have no password.
func InstallNamed(name, displayName, description, exePath string, args []string, account string) error {
	m, err := mgr.Connect()
	if err != nil {
		return fmt.Errorf("connect to service manager: %w", err)
	}
	defer m.Disconnect()

	existing, err := m.OpenService(name)
	if err == nil {
		existing.Close()
		return fmt.Errorf("service %s is already installed", name)
	}

	config := mgr.Config{
		DisplayName: displayName,
		Description: description,
		StartType:   mgr.StartAutomatic,
	}
	if account != "" {
		config.ServiceStartName = account
	}

	s, err := m.CreateService(name, exePath, config, args...)
	if err != nil {
		return fmt.Errorf("create service %s: %w", name, err)
	}
	defer s.Close()
	return nil
}

// UninstallNamed removes a service registration. A service that isn't
// installed is not an error — the caller wanted it gone and it is.
func UninstallNamed(name string) error {
	m, err := mgr.Connect()
	if err != nil {
		return fmt.Errorf("connect to service manager: %w", err)
	}
	defer m.Disconnect()

	s, err := m.OpenService(name)
	if err != nil {
		if isServiceDoesNotExist(err) {
			return nil
		}
		return fmt.Errorf("open service %s: %w", name, err)
	}
	defer s.Close()

	if err := s.Delete(); err != nil {
		return fmt.Errorf("delete service %s: %w", name, err)
	}
	return nil
}

// StartNamed starts an installed service.
func StartNamed(name string) error {
	m, err := mgr.Connect()
	if err != nil {
		return fmt.Errorf("connect to service manager: %w", err)
	}
	defer m.Disconnect()

	s, err := m.OpenService(name)
	if err != nil {
		return fmt.Errorf("open service %s: %w", name, err)
	}
	defer s.Close()

	if err := s.Start(); err != nil {
		if errors.Is(err, windows.ERROR_SERVICE_ALREADY_RUNNING) {
			return nil
		}
		return fmt.Errorf("start service %s: %w", name, err)
	}
	return nil
}

// StopNamed is best-effort: it asks the service to stop and waits briefly
// for it to report Stopped. A service that is missing or already stopped is
// success — the goal is convergence to "not running", not a state
// transition that must have happened.
func StopNamed(name string) error {
	m, err := mgr.Connect()
	if err != nil {
		return fmt.Errorf("connect to service manager: %w", err)
	}
	defer m.Disconnect()

	s, err := m.OpenService(name)
	if err != nil {
		if isServiceDoesNotExist(err) {
			return nil
		}
		return fmt.Errorf("open service %s: %w", name, err)
	}
	defer s.Close()

	status, err := s.Control(svc.Stop)
	if err != nil {
		if errors.Is(err, windows.ERROR_SERVICE_NOT_ACTIVE) {
			return nil
		}
		return fmt.Errorf("send stop control to %s: %w", name, err)
	}

	deadline := time.Now().Add(20 * time.Second)
	for status.State != svc.Stopped {
		if time.Now().After(deadline) {
			return fmt.Errorf("service %s did not reach the stopped state in time", name)
		}
		time.Sleep(300 * time.Millisecond)
		status, err = s.Query()
		if err != nil {
			return fmt.Errorf("query service %s: %w", name, err)
		}
	}
	return nil
}

// StatusNamed reports a service's state as one of the Status* constants
// above, reporting a service that isn't registered at all as
// StatusNotInstalled rather than as an error.
func StatusNamed(name string) (string, error) {
	m, err := mgr.Connect()
	if err != nil {
		return "", fmt.Errorf("connect to service manager: %w", err)
	}
	defer m.Disconnect()

	s, err := m.OpenService(name)
	if err != nil {
		if isServiceDoesNotExist(err) {
			return StatusNotInstalled, nil
		}
		return "", fmt.Errorf("open service %s: %w", name, err)
	}
	defer s.Close()

	status, err := s.Query()
	if err != nil {
		return "", fmt.Errorf("query service %s: %w", name, err)
	}

	switch status.State {
	case svc.Running:
		return StatusRunning, nil
	case svc.Stopped:
		return StatusStopped, nil
	case svc.StartPending:
		return StatusStartPending, nil
	case svc.StopPending:
		return StatusStopPending, nil
	default:
		return StatusUnknown, nil
	}
}

func isServiceDoesNotExist(err error) bool {
	return errors.Is(err, windows.ERROR_SERVICE_DOES_NOT_EXIST)
}

//go:build windows

package service

import (
	"context"
	"fmt"

	"golang.org/x/sys/windows/svc"
	"golang.org/x/sys/windows/svc/mgr"
)

// IsHostedByServiceManager reports whether the current process was started
// by the Windows Service Control Manager.
func IsHostedByServiceManager() (bool, error) {
	return svc.IsWindowsService()
}

type handler struct {
	run RunFunc
}

// Execute implements svc.Handler: it starts run in the background, reports
// Running to the SCM, and translates a Stop/Shutdown control request into
// cancelling run's context — the same clean-shutdown path used everywhere
// else in the Agent (see internal/transport.Client.Run).
func (h *handler) Execute(_ []string, requests <-chan svc.ChangeRequest, changes chan<- svc.Status) (bool, uint32) {
	changes <- svc.Status{State: svc.StartPending}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	runErr := make(chan error, 1)
	go func() { runErr <- h.run(ctx) }()

	changes <- svc.Status{State: svc.Running, Accepts: svc.AcceptStop | svc.AcceptShutdown}

	for {
		select {
		case err := <-runErr:
			changes <- svc.Status{State: svc.StopPending}
			if err != nil && err != context.Canceled {
				return true, 1
			}
			return false, 0

		case req := <-requests:
			switch req.Cmd {
			case svc.Interrogate:
				changes <- req.CurrentStatus
			case svc.Stop, svc.Shutdown:
				changes <- svc.Status{State: svc.StopPending}
				cancel()
				<-runErr
				return false, 0
			}
		}
	}
}

// RunAsService blocks running `run` under the Windows Service Control
// Manager. It must only be called when IsWindowsService reports true.
func RunAsService(run RunFunc) error {
	return svc.Run(Name, &handler{run: run})
}

// Install registers the Agent as a Windows Service that starts
// automatically, running exePath with args.
func Install(exePath string, args []string) error {
	m, err := mgr.Connect()
	if err != nil {
		return fmt.Errorf("connect to service manager: %w", err)
	}
	defer m.Disconnect()

	existing, err := m.OpenService(Name)
	if err == nil {
		existing.Close()
		return fmt.Errorf("service %s is already installed", Name)
	}

	s, err := m.CreateService(Name, exePath, mgr.Config{
		DisplayName: DisplayName,
		Description: Description,
		StartType:   mgr.StartAutomatic,
	}, args...)
	if err != nil {
		return fmt.Errorf("create service: %w", err)
	}
	defer s.Close()
	return nil
}

// Uninstall removes the Windows Service registration (stopping it first
// has no effect here — callers should Stop before Uninstall).
func Uninstall() error {
	m, err := mgr.Connect()
	if err != nil {
		return fmt.Errorf("connect to service manager: %w", err)
	}
	defer m.Disconnect()

	s, err := m.OpenService(Name)
	if err != nil {
		return fmt.Errorf("open service %s: %w", Name, err)
	}
	defer s.Close()

	if err := s.Delete(); err != nil {
		return fmt.Errorf("delete service %s: %w", Name, err)
	}
	return nil
}

// Start starts the installed service.
func Start() error {
	m, err := mgr.Connect()
	if err != nil {
		return fmt.Errorf("connect to service manager: %w", err)
	}
	defer m.Disconnect()

	s, err := m.OpenService(Name)
	if err != nil {
		return fmt.Errorf("open service %s: %w", Name, err)
	}
	defer s.Close()

	if err := s.Start(); err != nil {
		return fmt.Errorf("start service %s: %w", Name, err)
	}
	return nil
}

// Stop requests the installed service stop, and waits (briefly) for it to
// report the Stopped state.
func Stop() error {
	m, err := mgr.Connect()
	if err != nil {
		return fmt.Errorf("connect to service manager: %w", err)
	}
	defer m.Disconnect()

	s, err := m.OpenService(Name)
	if err != nil {
		return fmt.Errorf("open service %s: %w", Name, err)
	}
	defer s.Close()

	status, err := s.Control(svc.Stop)
	if err != nil {
		return fmt.Errorf("send stop control: %w", err)
	}
	if status.State == svc.Stopped {
		return nil
	}
	return nil
}

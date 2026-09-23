// Command healer-agent is the Healer V1 Agent: it runs on each managed
// Windows/Linux server, connects outbound to the Control Plane over a
// secure WebSocket, and executes structured commands.
//
// Phase 5 scope: enrollment, the persistent connection (reconnect with
// backoff, heartbeat, capability reporting), the local command journal,
// and OS service installation. Phase 7 adds the Windows Django/Waitress
// deployment handlers and the `instance-host` subcommand that supervises a
// deployed instance under the Windows Service Control Manager — see
// internal/dispatcher and internal/instancehost.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"runtime"
	"syscall"
	"time"

	"github.com/healer-platform/agent/internal/config"
	"github.com/healer-platform/agent/internal/core"
	"github.com/healer-platform/agent/internal/credentials"
	"github.com/healer-platform/agent/internal/dispatcher"
	"github.com/healer-platform/agent/internal/enroll"
	"github.com/healer-platform/agent/internal/instancehost"
	"github.com/healer-platform/agent/internal/journal"
	"github.com/healer-platform/agent/internal/logging"
	"github.com/healer-platform/agent/internal/service"
	"github.com/healer-platform/agent/internal/version"
)

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}

func run(args []string) error {
	if len(args) == 0 {
		printUsage()
		return fmt.Errorf("no command given")
	}

	switch args[0] {
	case "-version", "--version":
		fmt.Printf("healer-agent version %s (%s/%s)\n", version.Version, runtime.GOOS, runtime.GOARCH)
		return nil
	case "enroll":
		return runEnroll(args[1:])
	case "run":
		return runAgent(args[1:])
	case "service":
		return runServiceCommand(args[1:])
	case "instance-host":
		return runInstanceHost(args[1:])
	default:
		printUsage()
		return fmt.Errorf("unknown command %q", args[0])
	}
}

func printUsage() {
	fmt.Fprintln(os.Stderr, `Usage:
  healer-agent -version
  healer-agent enroll --control-plane <url> --token <token> [--data-dir <dir>]
  healer-agent run [--data-dir <dir>] [--debug]
  healer-agent service install|uninstall|start|stop [--data-dir <dir>]`)
}

func runEnroll(args []string) error {
	fs := flag.NewFlagSet("enroll", flag.ExitOnError)
	controlPlane := fs.String("control-plane", "http://localhost:8000", "Control Plane base URL")
	token := fs.String("token", "", "single-use enrollment token")
	dataDir := fs.String("data-dir", "", "data directory (defaults to the platform default)")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *token == "" {
		return fmt.Errorf("--token is required")
	}

	cfg := config.New(*dataDir)
	cfg.ControlPlaneURL = *controlPlane

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	result, err := enroll.Enroll(ctx, *controlPlane, *token)
	if err != nil {
		return fmt.Errorf("enroll: %w", err)
	}
	if result.ControlPlaneWSURL != "" {
		cfg.ControlPlaneWSURL = result.ControlPlaneWSURL
	}

	if err := cfg.Save(); err != nil {
		return fmt.Errorf("save config: %w", err)
	}
	if err := credentials.Save(cfg.CredentialPath(), credentials.Credential{
		AgentID:    result.AgentID,
		ServerID:   result.ServerID,
		Credential: result.Credential,
	}); err != nil {
		return fmt.Errorf("save credential: %w", err)
	}

	fmt.Printf("enrolled as agent %s (server %s)\n", result.AgentID, result.ServerID)
	fmt.Printf("data directory: %s\n", cfg.DataDir)
	return nil
}

func runAgent(args []string) error {
	fs := flag.NewFlagSet("run", flag.ExitOnError)
	dataDir := fs.String("data-dir", "", "data directory (defaults to the platform default)")
	debug := fs.Bool("debug", false, "enable debug logging")
	if err := fs.Parse(args); err != nil {
		return err
	}

	cfg, err := config.Load(*dataDir)
	if err != nil {
		return fmt.Errorf("load config: %w", err)
	}
	cred, err := credentials.Load(cfg.CredentialPath())
	if err != nil {
		return fmt.Errorf("load credential (run 'healer-agent enroll' first): %w", err)
	}

	isService, err := service.IsHostedByServiceManager()
	if err != nil {
		isService = false // best-effort — fall back to interactive mode
	}

	logger, closeLog, err := logging.New(cfg.LogPath(), !isService, *debug)
	if err != nil {
		return fmt.Errorf("set up logging: %w", err)
	}
	defer closeLog()

	j, err := journal.Open(cfg.JournalPath())
	if err != nil {
		return fmt.Errorf("open journal: %w", err)
	}
	defer j.Close()

	agent := core.New(core.Options{
		ControlPlaneWSURL: cfg.ControlPlaneWSURL,
		Credential:        cred.Credential,
		DataDir:           cfg.DataDir,
		HeartbeatEvery:    time.Duration(cfg.HeartbeatIntervalSecond) * time.Second,
		Adapters:          adaptersForOS(),
		Logger:            logger,
		Journal:           j,
		Dispatcher:        dispatcher.New(),
	})

	logger.Info("starting healer-agent", "version", version.Version, "os", runtime.GOOS, "arch", runtime.GOARCH, "as_service", isService)

	if isService {
		return service.RunAsService(agent.Run)
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	err = agent.Run(ctx)
	if err != nil && errors.Is(err, context.Canceled) {
		logger.Info("shut down cleanly")
		return nil
	}
	return err
}

// runInstanceHost supervises one application instance process under the
// Windows Service Control Manager. It is intentionally absent from
// printUsage: it is not an operator command, it is the binary+args the
// per-instance services created by start_instance are registered with.
//
// This path deliberately skips enrollment, the WebSocket connection, the
// journal and the dispatcher entirely — it exists only to keep one child
// process alive under SCM supervision.
func runInstanceHost(args []string) error {
	if len(args) < 1 {
		return fmt.Errorf("usage: healer-agent instance-host <launch-spec.json>")
	}

	spec, err := instancehost.LoadSpec(args[0])
	if err != nil {
		return err
	}
	hostInstance := instancehost.Run(spec)

	isService, err := service.IsHostedByServiceManager()
	if err != nil {
		isService = false // best-effort — fall back to interactive mode
	}
	if isService {
		// svc.Run's name argument is ignored by Windows for an own-process
		// service, so the Agent's own service machinery hosts an instance
		// service of any name unchanged.
		return service.RunAsService(hostInstance)
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := hostInstance(ctx); err != nil && !errors.Is(err, context.Canceled) {
		return err
	}
	return nil
}

func runServiceCommand(args []string) error {
	if len(args) < 1 {
		return fmt.Errorf("usage: healer-agent service install|uninstall|start|stop [--data-dir <dir>]")
	}
	fs := flag.NewFlagSet("service", flag.ExitOnError)
	dataDir := fs.String("data-dir", "", "data directory passed to the installed service")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}

	switch args[0] {
	case "install":
		exePath, err := os.Executable()
		if err != nil {
			return fmt.Errorf("resolve executable path: %w", err)
		}
		serviceArgs := []string{"run"}
		if *dataDir != "" {
			serviceArgs = append(serviceArgs, "--data-dir", *dataDir)
		}
		if err := service.Install(exePath, serviceArgs); err != nil {
			return fmt.Errorf("install service: %w", err)
		}
		fmt.Printf("installed the %s service\n", service.Name)
		return nil

	case "uninstall":
		if err := service.Uninstall(); err != nil {
			return fmt.Errorf("uninstall service: %w", err)
		}
		fmt.Printf("uninstalled the %s service\n", service.Name)
		return nil

	case "start":
		if err := service.Start(); err != nil {
			return fmt.Errorf("start service: %w", err)
		}
		fmt.Printf("started the %s service\n", service.Name)
		return nil

	case "stop":
		if err := service.Stop(); err != nil {
			return fmt.Errorf("stop service: %w", err)
		}
		fmt.Printf("stopped the %s service\n", service.Name)
		return nil

	default:
		return fmt.Errorf("unknown service subcommand %q", args[0])
	}
}

func adaptersForOS() []string {
	if runtime.GOOS == "windows" {
		return []string{"windows-waitress-service"}
	}
	return []string{"linux-docker"}
}

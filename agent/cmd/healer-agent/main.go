// Command healer-agent runs on each managed Windows/Linux server and
// connects outbound to the Healer Control Plane over a secure WebSocket.
//
// Phase 1 scope: the binary builds for Windows and Linux, prints its
// version, and validates that required configuration is present. It does
// not yet connect to the Control Plane or execute the Windows/Linux V1
// adapters — that lands with deployment behavior in a later phase.
package main

import (
	"flag"
	"fmt"
	"os"
	"runtime"

	"github.com/healer-platform/agent/internal/config"
	"github.com/healer-platform/agent/internal/version"
)

func main() {
	showVersion := flag.Bool("version", false, "print the agent version and exit")
	flag.Parse()

	if *showVersion {
		fmt.Printf("healer-agent version %s (%s/%s)\n", version.Version, runtime.GOOS, runtime.GOARCH)
		return
	}

	fmt.Printf("healer-agent %s (%s/%s)\n", version.Version, runtime.GOOS, runtime.GOARCH)

	cfg, err := config.FromEnv()
	if err != nil {
		fmt.Fprintf(os.Stderr, "config error: %v\n", err)
		fmt.Fprintln(os.Stderr, "set AGENT_CONTROL_PLANE_WS_URL and AGENT_ENROLLMENT_TOKEN (see .env.example)")
		os.Exit(1)
	}

	fmt.Printf("configured control plane endpoint: %s\n", cfg.ControlPlaneWSURL)
	fmt.Println("connecting to the control plane is not implemented in Phase 1")
}

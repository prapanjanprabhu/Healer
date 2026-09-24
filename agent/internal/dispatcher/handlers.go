package dispatcher

import (
	"context"
	"encoding/json"
	"runtime"
	"time"

	"github.com/shirou/gopsutil/v3/host"

	"github.com/healer-platform/agent/internal/dockerengine"
)

// dockerProbeTimeout bounds the one extra round trip inspect_host makes to
// the local Docker daemon (only attempted on Linux) — inspect_host must
// stay fast and safe even if the daemon is hung or absent.
const dockerProbeTimeout = 2 * time.Second

// HandleInspectHost is the one real, safe command Phase 5 implements — a
// read-only report of basic host facts. It's what the Phase 4 completion
// test exercised against the fake Agent simulator; this is the real Agent
// doing the same thing for real. Phase 13 adds a Docker capability report
// (Linux only — Windows has no Docker daemon to probe).
func HandleInspectHost(ctx context.Context, _ json.RawMessage) (map[string]any, error) {
	info, err := host.InfoWithContext(ctx)
	if err != nil {
		return nil, err
	}
	result := map[string]any{
		"hostname":         info.Hostname,
		"os":               runtime.GOOS,
		"arch":             runtime.GOARCH,
		"platform":         info.Platform,
		"platform_version": info.PlatformVersion,
		"kernel_version":   info.KernelVersion,
		"uptime_seconds":   info.Uptime,
		"cpu_count":        runtime.NumCPU(),
	}
	if runtime.GOOS == "linux" {
		result["docker_available"], result["docker_version"] = probeDocker(ctx)
	}
	return result, nil
}

func probeDocker(ctx context.Context) (bool, string) {
	probeCtx, cancel := context.WithTimeout(ctx, dockerProbeTimeout)
	defer cancel()

	client := dockerengine.New()
	if err := client.Ping(probeCtx); err != nil {
		return false, ""
	}
	version, err := client.Version(probeCtx)
	if err != nil {
		return true, ""
	}
	return true, version
}

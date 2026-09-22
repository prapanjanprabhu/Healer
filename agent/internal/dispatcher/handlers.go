package dispatcher

import (
	"context"
	"encoding/json"
	"runtime"

	"github.com/shirou/gopsutil/v3/host"
)

// HandleInspectHost is the one real, safe command Phase 5 implements — a
// read-only report of basic host facts. It's what the Phase 4 completion
// test exercised against the fake Agent simulator; this is the real Agent
// doing the same thing for real.
func HandleInspectHost(ctx context.Context, _ json.RawMessage) (map[string]any, error) {
	info, err := host.InfoWithContext(ctx)
	if err != nil {
		return nil, err
	}
	return map[string]any{
		"hostname":         info.Hostname,
		"os":               runtime.GOOS,
		"arch":             runtime.GOARCH,
		"platform":         info.Platform,
		"platform_version": info.PlatformVersion,
		"kernel_version":   info.KernelVersion,
		"uptime_seconds":   info.Uptime,
		"cpu_count":        runtime.NumCPU(),
	}, nil
}

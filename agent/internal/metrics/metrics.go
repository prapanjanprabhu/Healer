// Package metrics collects the basic host CPU/RAM/disk snapshot sent in
// every heartbeat.
package metrics

import (
	"context"
	"fmt"
	"math"
	"time"

	"github.com/shirou/gopsutil/v3/cpu"
	"github.com/shirou/gopsutil/v3/disk"
	"github.com/shirou/gopsutil/v3/mem"
)

// Snapshot is a point-in-time host resource reading.
type Snapshot struct {
	CPUPercent    float64
	MemoryPercent float64
	DiskPercent   float64
}

// sampleInterval is how long Collect blocks measuring CPU usage — a CPU
// percentage is inherently a delta over a window, not an instant value.
const sampleInterval = 200 * time.Millisecond

// Collect samples CPU, memory, and disk usage. diskPath should be a path
// that exists on the volume worth reporting on (the Agent's data
// directory is a reasonable, always-present choice).
func Collect(ctx context.Context, diskPath string) (Snapshot, error) {
	cpuPercents, err := cpu.PercentWithContext(ctx, sampleInterval, false)
	if err != nil {
		return Snapshot{}, fmt.Errorf("cpu: %w", err)
	}
	var cpuPct float64
	if len(cpuPercents) > 0 {
		cpuPct = cpuPercents[0]
	}

	vm, err := mem.VirtualMemoryWithContext(ctx)
	if err != nil {
		return Snapshot{}, fmt.Errorf("memory: %w", err)
	}

	du, err := disk.UsageWithContext(ctx, diskPath)
	if err != nil {
		return Snapshot{}, fmt.Errorf("disk: %w", err)
	}

	return Snapshot{
		CPUPercent:    round1(cpuPct),
		MemoryPercent: round1(vm.UsedPercent),
		DiskPercent:   round1(du.UsedPercent),
	}, nil
}

func round1(v float64) float64 {
	return math.Round(v*10) / 10
}

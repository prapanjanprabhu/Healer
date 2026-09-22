package metrics

import (
	"context"
	"os"
	"testing"
	"time"
)

func TestCollectReturnsPlausiblePercentages(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	snap, err := Collect(ctx, os.TempDir())
	if err != nil {
		t.Fatalf("collect: %v", err)
	}

	for name, v := range map[string]float64{
		"cpu":    snap.CPUPercent,
		"memory": snap.MemoryPercent,
		"disk":   snap.DiskPercent,
	} {
		if v < 0 || v > 100 {
			t.Errorf("%s percent %.1f out of the expected [0, 100] range", name, v)
		}
	}
}

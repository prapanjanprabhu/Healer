package config

import (
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestDefaultDataDirIsPlatformAppropriate(t *testing.T) {
	dir := DefaultDataDir()
	if runtime.GOOS == "windows" {
		if !filepath.IsAbs(dir) {
			t.Fatalf("expected an absolute Windows path, got %q", dir)
		}
	} else {
		if dir != "/var/lib/healer" {
			t.Fatalf("expected /var/lib/healer on %s, got %q", runtime.GOOS, dir)
		}
	}
}

func TestLoadWithoutExistingFileReturnsDefaults(t *testing.T) {
	dir := t.TempDir()
	cfg, err := Load(dir)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.ControlPlaneWSURL == "" {
		t.Fatal("expected a default control plane WS URL")
	}
	if cfg.HeartbeatIntervalSecond <= 0 {
		t.Fatal("expected a positive default heartbeat interval")
	}
	if cfg.DataDir != dir {
		t.Fatalf("expected DataDir %q, got %q", dir, cfg.DataDir)
	}
}

func TestSaveThenLoadRoundTrips(t *testing.T) {
	dir := t.TempDir()
	cfg := New(dir)
	cfg.ControlPlaneURL = "http://example.internal:8000"
	cfg.ControlPlaneWSURL = "wss://example.internal/ws/agent"
	cfg.HeartbeatIntervalSecond = 45

	if err := cfg.Save(); err != nil {
		t.Fatalf("save: %v", err)
	}

	loaded, err := Load(dir)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if loaded.ControlPlaneURL != cfg.ControlPlaneURL {
		t.Errorf("ControlPlaneURL = %q, want %q", loaded.ControlPlaneURL, cfg.ControlPlaneURL)
	}
	if loaded.ControlPlaneWSURL != cfg.ControlPlaneWSURL {
		t.Errorf("ControlPlaneWSURL = %q, want %q", loaded.ControlPlaneWSURL, cfg.ControlPlaneWSURL)
	}
	if loaded.HeartbeatIntervalSecond != 45 {
		t.Errorf("HeartbeatIntervalSecond = %d, want 45", loaded.HeartbeatIntervalSecond)
	}
}

// TestLoadWithEmptyDataDirResolvesToTheRealDefault is a regression test for
// a real bug caught during manual verification: Load("") was overwriting
// the correctly-resolved default DataDir with the raw (empty) parameter
// after reading an existing config file, making every derived path
// (credential, journal, log) relative instead of under
// C:\ProgramData\Healer — `healer-agent run` failed to find its own
// credential file as a result. TestSaveThenLoadRoundTrips didn't catch this
// because it always passes a non-empty t.TempDir().
func TestLoadWithEmptyDataDirResolvesToTheRealDefault(t *testing.T) {
	if runtime.GOOS != "windows" {
		t.Skip("DefaultDataDir has no test-overridable hook on this OS (Linux's path is a fixed constant, by design)")
	}
	t.Setenv("ProgramData", t.TempDir())

	cfg := New("")
	if err := cfg.Save(); err != nil {
		t.Fatalf("save: %v", err)
	}

	loaded, err := Load("")
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if loaded.DataDir != DefaultDataDir() {
		t.Fatalf("DataDir = %q, want the resolved default %q", loaded.DataDir, DefaultDataDir())
	}
	if !strings.HasPrefix(loaded.CredentialPath(), loaded.DataDir) {
		t.Fatalf("CredentialPath() = %q is not under DataDir %q", loaded.CredentialPath(), loaded.DataDir)
	}
}

func TestPathsAreUnderDataDir(t *testing.T) {
	cfg := New(filepath.Join(t.TempDir(), "healer-test"))
	for _, p := range []string{cfg.ConfigPath(), cfg.CredentialPath(), cfg.JournalPath(), cfg.LogPath()} {
		if !strings.HasPrefix(p, cfg.DataDir) {
			t.Errorf("path %q is not under data dir %q", p, cfg.DataDir)
		}
	}
}

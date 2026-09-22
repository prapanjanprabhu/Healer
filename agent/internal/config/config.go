// Package config loads and persists the Agent's runtime configuration, with
// OS-appropriate default data directories (Phase 5).
package config

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
)

// DefaultDataDir returns the platform default data directory:
//
//	Windows: C:/ProgramData/Healer
//	Linux:   /var/lib/healer
func DefaultDataDir() string {
	if runtime.GOOS == "windows" {
		programData := os.Getenv("ProgramData")
		if programData == "" {
			programData = `C:\ProgramData`
		}
		return filepath.Join(programData, "Healer")
	}
	return "/var/lib/healer"
}

// Config is the Agent's persisted, on-disk configuration. It is written by
// `healer-agent enroll` and read by `healer-agent run`.
type Config struct {
	ControlPlaneURL         string `json:"control_plane_url"`
	ControlPlaneWSURL       string `json:"control_plane_ws_url"`
	HeartbeatIntervalSecond int    `json:"heartbeat_interval_seconds"`

	// DataDir is never persisted inside its own config file (it's implied by
	// the file's location) — it's set by Load/New from the caller's choice.
	DataDir string `json:"-"`
}

// New returns defaults for a given data directory (or the platform default
// if dataDir is empty).
func New(dataDir string) Config {
	if dataDir == "" {
		dataDir = DefaultDataDir()
	}
	return Config{
		ControlPlaneURL:         "http://localhost:8000",
		ControlPlaneWSURL:       "ws://localhost:8000/ws/agent",
		HeartbeatIntervalSecond: 20,
		DataDir:                 dataDir,
	}
}

func (c Config) ConfigPath() string     { return filepath.Join(c.DataDir, "config.json") }
func (c Config) CredentialPath() string { return filepath.Join(c.DataDir, "credential.json") }
func (c Config) JournalPath() string    { return filepath.Join(c.DataDir, "journal.log") }
func (c Config) LogDir() string         { return filepath.Join(c.DataDir, "logs") }
func (c Config) LogPath() string        { return filepath.Join(c.LogDir(), "agent.log") }

// Load reads the config file under dataDir, falling back to defaults for any
// field the file doesn't set (or if the file doesn't exist at all — running
// `enroll` is what creates it).
func Load(dataDir string) (Config, error) {
	cfg := New(dataDir)

	data, err := os.ReadFile(cfg.ConfigPath())
	if err != nil {
		if os.IsNotExist(err) {
			return cfg, nil
		}
		return Config{}, fmt.Errorf("read config %s: %w", cfg.ConfigPath(), err)
	}

	if err := json.Unmarshal(data, &cfg); err != nil {
		return Config{}, fmt.Errorf("parse config %s: %w", cfg.ConfigPath(), err)
	}
	// DataDir has json:"-" so Unmarshal never touches it — cfg.DataDir still
	// holds the value New(dataDir) resolved above (the platform default when
	// dataDir was empty). Do not overwrite it with the raw, possibly-empty
	// parameter here — that was a real bug caught by manual testing, not by
	// the unit tests below (which always pass a non-empty t.TempDir()).
	if cfg.HeartbeatIntervalSecond <= 0 {
		cfg.HeartbeatIntervalSecond = 20
	}
	return cfg, nil
}

// Save writes the config to <DataDir>/config.json, creating DataDir if
// needed.
func (c Config) Save() error {
	if err := os.MkdirAll(c.DataDir, 0o750); err != nil {
		return fmt.Errorf("create data dir %s: %w", c.DataDir, err)
	}
	data, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal config: %w", err)
	}
	if err := os.WriteFile(c.ConfigPath(), data, 0o640); err != nil {
		return fmt.Errorf("write config %s: %w", c.ConfigPath(), err)
	}
	return nil
}

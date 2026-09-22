// Package credentials handles local storage of the long-lived Agent
// connection credential issued by POST /agents/enroll.
//
// The credential is written with the most restrictive permissions this
// platform's filesystem API supports (0600 on Unix). On Windows, file mode
// bits don't carry the same meaning — real access control comes from the
// data directory living under C:\ProgramData\Healer, which by default only
// Administrators/SYSTEM can write to; a future phase can layer explicit ACLs
// on top if that default ever proves insufficient.
package credentials

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

// Credential is what enrollment returns and what's persisted to disk.
type Credential struct {
	AgentID    string `json:"agent_id"`
	ServerID   string `json:"server_id"`
	Credential string `json:"credential"`
}

// Load reads a Credential from path.
func Load(path string) (Credential, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return Credential{}, fmt.Errorf("read credential %s: %w", path, err)
	}
	var cred Credential
	if err := json.Unmarshal(data, &cred); err != nil {
		return Credential{}, fmt.Errorf("parse credential %s: %w", path, err)
	}
	if cred.Credential == "" {
		return Credential{}, fmt.Errorf("credential file %s has no credential value", path)
	}
	return cred, nil
}

// Save writes cred to path with restrictive permissions, creating the
// parent directory if needed.
func Save(path string, cred Credential) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o750); err != nil {
		return fmt.Errorf("create credential dir: %w", err)
	}
	data, err := json.MarshalIndent(cred, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal credential: %w", err)
	}
	if err := os.WriteFile(path, data, 0o600); err != nil {
		return fmt.Errorf("write credential %s: %w", path, err)
	}
	return nil
}

// Exists reports whether a credential file is already present at path.
func Exists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

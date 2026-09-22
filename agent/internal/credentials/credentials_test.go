package credentials

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

func TestSaveThenLoadRoundTrips(t *testing.T) {
	path := filepath.Join(t.TempDir(), "nested", "credential.json")
	cred := Credential{AgentID: "agent-1", ServerID: "server-1", Credential: "super-secret-value"}

	if err := Save(path, cred); err != nil {
		t.Fatalf("save: %v", err)
	}
	if !Exists(path) {
		t.Fatal("expected Exists to report true after Save")
	}

	loaded, err := Load(path)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if loaded != cred {
		t.Errorf("loaded %+v, want %+v", loaded, cred)
	}
}

func TestSavePermissionsAreRestrictive(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("POSIX file mode bits aren't meaningful on Windows")
	}
	path := filepath.Join(t.TempDir(), "credential.json")
	if err := Save(path, Credential{Credential: "x"}); err != nil {
		t.Fatalf("save: %v", err)
	}

	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("stat: %v", err)
	}
	if perm := info.Mode().Perm(); perm&0o077 != 0 {
		t.Errorf("credential file mode %o grants access beyond the owner", perm)
	}
}

func TestLoadMissingFileFails(t *testing.T) {
	_, err := Load(filepath.Join(t.TempDir(), "does-not-exist.json"))
	if err == nil {
		t.Fatal("expected an error loading a missing credential file")
	}
}

func TestLoadRejectsEmptyCredential(t *testing.T) {
	path := filepath.Join(t.TempDir(), "credential.json")
	if err := Save(path, Credential{AgentID: "a", ServerID: "s"}); err != nil {
		t.Fatalf("save: %v", err)
	}
	if _, err := Load(path); err == nil {
		t.Fatal("expected an error loading a credential file with no credential value")
	}
}

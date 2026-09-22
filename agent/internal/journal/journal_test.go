package journal

import (
	"os"
	"path/filepath"
	"testing"
)

func TestFreshJournalHasNoCompletedCommands(t *testing.T) {
	path := filepath.Join(t.TempDir(), "journal.log")
	j, err := Open(path)
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	defer j.Close()

	if j.IsCompleted("cmd-1") {
		t.Fatal("expected a fresh journal to have no completed commands")
	}
}

func TestRecordThenIsCompleted(t *testing.T) {
	path := filepath.Join(t.TempDir(), "journal.log")
	j, err := Open(path)
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	defer j.Close()

	if err := j.Record("cmd-1", StatusReceived); err != nil {
		t.Fatalf("record received: %v", err)
	}
	if j.IsCompleted("cmd-1") {
		t.Fatal("a merely-received command must not report as completed")
	}

	if err := j.Record("cmd-1", StatusRunning); err != nil {
		t.Fatalf("record running: %v", err)
	}
	if j.IsCompleted("cmd-1") {
		t.Fatal("a running command must not report as completed")
	}

	if err := j.Record("cmd-1", StatusCompleted); err != nil {
		t.Fatalf("record completed: %v", err)
	}
	if !j.IsCompleted("cmd-1") {
		t.Fatal("expected cmd-1 to report as completed")
	}
}

func TestJournalRecoversStateAfterReopen(t *testing.T) {
	path := filepath.Join(t.TempDir(), "journal.log")

	j1, err := Open(path)
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	if err := j1.Record("cmd-completed", StatusCompleted); err != nil {
		t.Fatalf("record: %v", err)
	}
	if err := j1.Record("cmd-running", StatusRunning); err != nil {
		t.Fatalf("record: %v", err)
	}
	if err := j1.Close(); err != nil {
		t.Fatalf("close: %v", err)
	}

	// Simulate a restart: open a brand new Journal instance against the
	// same file and confirm it remembers what j1 recorded.
	j2, err := Open(path)
	if err != nil {
		t.Fatalf("reopen: %v", err)
	}
	defer j2.Close()

	if !j2.IsCompleted("cmd-completed") {
		t.Error("expected cmd-completed to survive reopen as completed")
	}
	if j2.IsCompleted("cmd-running") {
		t.Error("cmd-running should not be reported completed after reopen")
	}
	if j2.IsCompleted("cmd-never-seen") {
		t.Error("a command never recorded must not report as completed")
	}
}

func TestJournalToleratesTruncatedLastLine(t *testing.T) {
	path := filepath.Join(t.TempDir(), "journal.log")
	j1, err := Open(path)
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	if err := j1.Record("cmd-1", StatusCompleted); err != nil {
		t.Fatalf("record: %v", err)
	}
	if err := j1.Close(); err != nil {
		t.Fatalf("close: %v", err)
	}

	// Simulate a crash mid-write: append a partial, invalid JSON line.
	appendRaw(t, path, `{"command_id": "cmd-2", "status": "rec`)

	j2, err := Open(path)
	if err != nil {
		t.Fatalf("reopen after truncated line: %v", err)
	}
	defer j2.Close()

	if !j2.IsCompleted("cmd-1") {
		t.Error("expected cmd-1 (recorded before the truncated line) to survive recovery")
	}
	if j2.IsCompleted("cmd-2") {
		t.Error("the truncated entry must not count as completed")
	}
}

func appendRaw(t *testing.T, path, data string) {
	t.Helper()
	f, err := os.OpenFile(path, os.O_APPEND|os.O_WRONLY, 0o640)
	if err != nil {
		t.Fatalf("open for raw append: %v", err)
	}
	defer f.Close()
	if _, err := f.WriteString(data); err != nil {
		t.Fatalf("raw append: %v", err)
	}
}

// Package journal is a durable, append-only local record of command
// execution state, so a command the Agent already completed is never
// executed twice — whether because the Control Plane redelivered it after a
// reconnect, or because the Agent itself restarted mid-command.
package journal

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// Status is a command's execution state as recorded in the journal.
type Status string

const (
	StatusReceived  Status = "received"
	StatusRunning   Status = "running"
	StatusCompleted Status = "completed" // terminal: succeeded, failed, or timed_out
)

type entry struct {
	CommandID  string    `json:"command_id"`
	Status     Status    `json:"status"`
	RecordedAt time.Time `json:"recorded_at"`
}

// Journal is safe for concurrent use.
type Journal struct {
	mu      sync.Mutex
	file    *os.File
	entries map[string]Status
}

// Open opens (creating if necessary) the journal file at path and replays
// its contents into memory — this replay is what makes a restarted Agent
// remember which commands it already finished ("journal recovery").
func Open(path string) (*Journal, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o750); err != nil {
		return nil, fmt.Errorf("create journal dir: %w", err)
	}

	entries, err := replay(path)
	if err != nil {
		return nil, err
	}

	file, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o640)
	if err != nil {
		return nil, fmt.Errorf("open journal %s: %w", path, err)
	}

	return &Journal{file: file, entries: entries}, nil
}

func replay(path string) (map[string]Status, error) {
	entries := make(map[string]Status)

	file, err := os.Open(path)
	if err != nil {
		if os.IsNotExist(err) {
			return entries, nil
		}
		return nil, fmt.Errorf("open journal %s for replay: %w", path, err)
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	for scanner.Scan() {
		line := scanner.Bytes()
		if len(line) == 0 {
			continue
		}
		var e entry
		if err := json.Unmarshal(line, &e); err != nil {
			// A truncated last line (e.g. from a crash mid-write) is
			// tolerated — everything before it still replays correctly.
			continue
		}
		entries[e.CommandID] = e.Status
	}
	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("read journal %s: %w", path, err)
	}
	return entries, nil
}

// IsCompleted reports whether commandID has already reached a terminal
// state — the Agent must not execute it again if so.
func (j *Journal) IsCompleted(commandID string) bool {
	j.mu.Lock()
	defer j.mu.Unlock()
	return j.entries[commandID] == StatusCompleted
}

// Record durably appends a status transition for commandID, fsyncing
// before returning so a crash immediately after Record still leaves the
// journal consistent.
func (j *Journal) Record(commandID string, status Status) error {
	j.mu.Lock()
	defer j.mu.Unlock()

	e := entry{CommandID: commandID, Status: status, RecordedAt: time.Now().UTC()}
	data, err := json.Marshal(e)
	if err != nil {
		return fmt.Errorf("marshal journal entry: %w", err)
	}
	data = append(data, '\n')

	if _, err := j.file.Write(data); err != nil {
		return fmt.Errorf("write journal entry: %w", err)
	}
	if err := j.file.Sync(); err != nil {
		return fmt.Errorf("sync journal: %w", err)
	}

	j.entries[commandID] = status
	return nil
}

// Close closes the underlying journal file.
func (j *Journal) Close() error {
	j.mu.Lock()
	defer j.mu.Unlock()
	return j.file.Close()
}

package dispatcher

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// defaultLogMaxBytes/defaultLogMaxLines are used when the Control Plane
// omits or zeroes a limit. hardLogMaxBytes/hardLogMaxLines cap what a caller
// may request even explicitly — bounded retrieval must stay bounded
// regardless of the request, never "read the whole file".
const (
	defaultLogMaxBytes = 64 * 1024
	hardLogMaxBytes    = 1024 * 1024
	defaultLogMaxLines = 500
	hardLogMaxLines    = 5000
)

type collectLogsPayload struct {
	ServiceName string `json:"service_name"`
	LogDir      string `json:"log_dir"`
	Stream      string `json:"stream"`
	MaxBytes    int64  `json:"max_bytes"`
	MaxLines    int    `json:"max_lines"`
	Offset      *int64 `json:"offset"`
}

// HandleCollectLogs returns a bounded, recent slice of one instance's
// stdout/stderr log file — never the whole file. With no offset, it tails
// the last max_bytes bytes (a fresh view); with an offset (as returned by a
// previous call's end_offset), it reads forward from there so a caller can
// poll for "what's new" without re-reading what it already has. A missing
// log file (the instance has never written to this stream yet) is reported
// as not_found rather than an error.
func HandleCollectLogs(_ context.Context, raw json.RawMessage) (map[string]any, error) {
	var payload collectLogsPayload
	if err := json.Unmarshal(raw, &payload); err != nil {
		return nil, fmt.Errorf("invalid collect_logs payload: %w", err)
	}
	if err := validateCollectLogsPayload(payload); err != nil {
		return nil, err
	}

	maxBytes := payload.MaxBytes
	if maxBytes <= 0 || maxBytes > hardLogMaxBytes {
		maxBytes = defaultLogMaxBytes
	}
	maxLines := payload.MaxLines
	if maxLines <= 0 || maxLines > hardLogMaxLines {
		maxLines = defaultLogMaxLines
	}

	var suffix string
	if payload.Stream == "stdout" {
		suffix = ".out.log"
	} else {
		suffix = ".err.log"
	}
	path := filepath.Join(payload.LogDir, payload.ServiceName+suffix)

	info, err := os.Stat(path)
	if os.IsNotExist(err) {
		return map[string]any{
			"ok":         true,
			"not_found":  true,
			"lines":      []string{},
			"size":       int64(0),
			"end_offset": int64(0),
			"truncated":  false,
		}, nil
	}
	if err != nil {
		return nil, fmt.Errorf("stat log file %s: %w", path, err)
	}
	size := info.Size()

	tailMode := payload.Offset == nil
	var start int64
	if tailMode {
		start = size - maxBytes
	} else {
		start = *payload.Offset
	}
	if start < 0 {
		start = 0
	}
	if start > size {
		start = size
	}

	readLen := size - start
	if readLen > maxBytes {
		readLen = maxBytes
	}

	file, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("open log file %s: %w", path, err)
	}
	defer file.Close()

	buf := make([]byte, readLen)
	if readLen > 0 {
		if _, err := file.ReadAt(buf, start); err != nil {
			return nil, fmt.Errorf("read log file %s: %w", path, err)
		}
	}
	endOffset := start + readLen

	text := string(buf)
	// A tail-mode read starts at an arbitrary byte, not a line boundary —
	// the first fragment is likely a partial line, so drop it. An
	// offset-continuation read starts exactly where the previous read
	// ended, which is already a byte boundary the caller is tracking, so
	// nothing is dropped there.
	if tailMode && start > 0 {
		if idx := strings.IndexByte(text, '\n'); idx >= 0 {
			text = text[idx+1:]
		} else {
			text = ""
		}
	}

	var lines []string
	if text != "" {
		for _, line := range strings.Split(strings.TrimRight(text, "\n"), "\n") {
			lines = append(lines, strings.TrimSuffix(line, "\r"))
		}
	}

	truncated := false
	if len(lines) > maxLines {
		lines = lines[len(lines)-maxLines:]
		truncated = true
	}
	if lines == nil {
		lines = []string{}
	}

	return map[string]any{
		"ok":         true,
		"not_found":  false,
		"lines":      lines,
		"size":       size,
		"end_offset": endOffset,
		"truncated":  truncated,
	}, nil
}

func validateCollectLogsPayload(payload collectLogsPayload) error {
	if strings.TrimSpace(payload.ServiceName) == "" {
		return fmt.Errorf("invalid collect_logs payload: service_name must not be empty")
	}
	if strings.ContainsAny(payload.ServiceName, `/\`) || strings.Contains(payload.ServiceName, "..") {
		return fmt.Errorf("invalid collect_logs payload: service_name must not contain path separators")
	}
	if strings.TrimSpace(payload.LogDir) == "" {
		return fmt.Errorf("invalid collect_logs payload: log_dir must not be empty")
	}
	if payload.Stream != "stdout" && payload.Stream != "stderr" {
		return fmt.Errorf("invalid collect_logs payload: stream must be \"stdout\" or \"stderr\"")
	}
	return nil
}

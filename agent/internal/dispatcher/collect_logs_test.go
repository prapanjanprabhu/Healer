package dispatcher

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func mustMarshal(t *testing.T, v any) json.RawMessage {
	t.Helper()
	data, err := json.Marshal(v)
	if err != nil {
		t.Fatalf("marshal payload: %v", err)
	}
	return data
}

func writeLogFile(t *testing.T, dir, name string, content string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(dir, name), []byte(content), 0o640); err != nil {
		t.Fatalf("write log file: %v", err)
	}
}

func TestCollectLogsMissingFileReportsNotFound(t *testing.T) {
	dir := t.TempDir()
	result, err := HandleCollectLogs(context.Background(), mustMarshal(t, collectLogsPayload{
		ServiceName: "Healer-missing-1", LogDir: dir, Stream: "stdout",
	}))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result["not_found"] != true {
		t.Errorf("expected not_found true, got %v", result)
	}
	if lines, ok := result["lines"].([]string); !ok || len(lines) != 0 {
		t.Errorf("expected an empty lines slice, got %v", result["lines"])
	}
}

func TestCollectLogsTailsLastLines(t *testing.T) {
	dir := t.TempDir()
	content := "line1\nline2\nline3\nline4\nline5\n"
	writeLogFile(t, dir, "Healer-app-1.out.log", content)

	result, err := HandleCollectLogs(context.Background(), mustMarshal(t, collectLogsPayload{
		ServiceName: "Healer-app-1", LogDir: dir, Stream: "stdout", MaxLines: 2,
	}))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	lines, ok := result["lines"].([]string)
	if !ok {
		t.Fatalf("expected lines to be []string, got %T", result["lines"])
	}
	if len(lines) != 2 || lines[0] != "line4" || lines[1] != "line5" {
		t.Errorf("expected the last two lines, got %v", lines)
	}
	if result["truncated"] != true {
		t.Errorf("expected truncated true when more lines exist than max_lines")
	}
}

func TestCollectLogsDropsPartialFirstLineOnTail(t *testing.T) {
	dir := t.TempDir()
	content := "aaaaaaaaaa\nbbbbbbbbbb\ncccccccccc\n"
	writeLogFile(t, dir, "Healer-app-2.out.log", content)

	// A max_bytes small enough to start mid-line inside "bbbbbbbbbb".
	result, err := HandleCollectLogs(context.Background(), mustMarshal(t, collectLogsPayload{
		ServiceName: "Healer-app-2", LogDir: dir, Stream: "stdout", MaxBytes: 15,
	}))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	lines := result["lines"].([]string)
	for _, line := range lines {
		if strings.Contains(line, "b") && line != "bbbbbbbbbb" {
			t.Errorf("expected no partial line fragments, got %v", lines)
		}
	}
	if len(lines) == 0 || lines[len(lines)-1] != "cccccccccc" {
		t.Errorf("expected the last full line to be present, got %v", lines)
	}
}

func TestCollectLogsOffsetContinuesFromPreviousEndOffset(t *testing.T) {
	dir := t.TempDir()
	writeLogFile(t, dir, "Healer-app-3.err.log", "first\nsecond\n")

	first, err := HandleCollectLogs(context.Background(), mustMarshal(t, collectLogsPayload{
		ServiceName: "Healer-app-3", LogDir: dir, Stream: "stderr",
	}))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	endOffset := first["end_offset"].(int64)

	// Simulate more being appended after the first read.
	f, err := os.OpenFile(filepath.Join(dir, "Healer-app-3.err.log"), os.O_APPEND|os.O_WRONLY, 0o640)
	if err != nil {
		t.Fatalf("open for append: %v", err)
	}
	if _, err := f.WriteString("third\n"); err != nil {
		t.Fatalf("append: %v", err)
	}
	f.Close()

	second, err := HandleCollectLogs(context.Background(), mustMarshal(t, collectLogsPayload{
		ServiceName: "Healer-app-3", LogDir: dir, Stream: "stderr", Offset: &endOffset,
	}))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	lines := second["lines"].([]string)
	if len(lines) != 1 || lines[0] != "third" {
		t.Errorf("expected only the newly appended line, got %v", lines)
	}
}

func TestCollectLogsRejectsPathTraversalInServiceName(t *testing.T) {
	dir := t.TempDir()
	_, err := HandleCollectLogs(context.Background(), mustMarshal(t, collectLogsPayload{
		ServiceName: "../escape", LogDir: dir, Stream: "stdout",
	}))
	if err == nil {
		t.Fatal("expected an error for a service_name containing path traversal")
	}
}

func TestCollectLogsRejectsInvalidStream(t *testing.T) {
	dir := t.TempDir()
	_, err := HandleCollectLogs(context.Background(), mustMarshal(t, collectLogsPayload{
		ServiceName: "Healer-app-4", LogDir: dir, Stream: "bogus",
	}))
	if err == nil {
		t.Fatal("expected an error for an invalid stream value")
	}
}

func TestCollectLogsClampsExcessiveLimitsToHardCaps(t *testing.T) {
	dir := t.TempDir()
	writeLogFile(t, dir, "Healer-app-5.out.log", "hello\n")

	result, err := HandleCollectLogs(context.Background(), mustMarshal(t, collectLogsPayload{
		ServiceName: "Healer-app-5", LogDir: dir, Stream: "stdout",
		MaxBytes: 100 * 1024 * 1024, MaxLines: 1_000_000,
	}))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result["lines"].([]string)[0] != "hello" {
		t.Errorf("expected normal read despite absurd limits, got %v", result)
	}
}

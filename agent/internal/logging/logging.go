// Package logging sets up the Agent's structured (slog) logging and
// provides a helper for redacting secrets that must never appear in a log
// line — the credential and enrollment token above all.
//
// The stronger guarantee is a coding discipline, not a filter: nowhere in
// this codebase does a log call pass the raw credential or enrollment
// token as a field. Redact exists for the rare case a caller wants to log
// enough of a secret to recognize it without exposing it (e.g. "the
// credential starting with abcd...").
package logging

import (
	"fmt"
	"io"
	"log/slog"
	"os"
	"path/filepath"
)

// New creates a JSON structured logger writing to logPath (created if
// needed), and also to stdout when interactive is true (useful for `run`
// invoked directly from a terminal; a Windows Service / systemd unit
// should pass false and rely on the log file).
func New(logPath string, interactive bool, debug bool) (*slog.Logger, func() error, error) {
	if err := os.MkdirAll(filepath.Dir(logPath), 0o750); err != nil {
		return nil, nil, fmt.Errorf("create log dir: %w", err)
	}
	file, err := os.OpenFile(logPath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o640)
	if err != nil {
		return nil, nil, fmt.Errorf("open log file %s: %w", logPath, err)
	}

	var writer io.Writer = file
	if interactive {
		writer = io.MultiWriter(file, os.Stdout)
	}

	level := slog.LevelInfo
	if debug {
		level = slog.LevelDebug
	}
	handler := slog.NewJSONHandler(writer, &slog.HandlerOptions{Level: level})
	return slog.New(handler), file.Close, nil
}

// Redact returns a value safe to log in place of a secret: enough to
// recognize it in a support conversation, never enough to reuse it.
func Redact(secret string) string {
	if len(secret) <= 8 {
		return "***"
	}
	return secret[:4] + "..." + secret[len(secret)-4:]
}

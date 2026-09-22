package dispatcher

import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/healer-platform/agent/internal/protocol"
)

func TestDispatchUnknownCommandTypeIsRejected(t *testing.T) {
	d := New()
	_, err := d.Dispatch(context.Background(), "run_shell_command", json.RawMessage(`{}`))
	if err == nil {
		t.Fatal("expected an error for an unknown command type")
	}
	var unknown ErrUnknownCommand
	if !errors.As(err, &unknown) {
		t.Fatalf("expected ErrUnknownCommand, got %T: %v", err, err)
	}
}

func TestDispatchRecognizedButUnimplementedCommandIsRejected(t *testing.T) {
	d := New()
	_, err := d.Dispatch(context.Background(), protocol.CommandDeployRelease, json.RawMessage(`{}`))
	if err == nil {
		t.Fatal("expected an error for an unimplemented command type")
	}
	var notImplemented ErrNotImplemented
	if !errors.As(err, &notImplemented) {
		t.Fatalf("expected ErrNotImplemented, got %T: %v", err, err)
	}
}

func TestDispatchInspectHostSucceeds(t *testing.T) {
	d := New()
	result, err := d.Dispatch(context.Background(), protocol.CommandInspectHost, json.RawMessage(`{}`))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result["hostname"] == "" || result["hostname"] == nil {
		t.Error("expected a non-empty hostname in the result")
	}
	if _, ok := result["cpu_count"]; !ok {
		t.Error("expected a cpu_count field in the result")
	}
}

func TestRegisterUnknownCommandTypePanics(t *testing.T) {
	defer func() {
		if recover() == nil {
			t.Fatal("expected Register to panic for an unknown command type")
		}
	}()
	New().Register("run_shell_command", HandleInspectHost)
}

func TestEveryKnownCommandTypeIsSafelyHandledOrRejected(t *testing.T) {
	d := New()
	for commandType := range protocol.KnownCommandTypes {
		_, err := d.Dispatch(context.Background(), commandType, json.RawMessage(`{}`))
		if err == nil {
			continue // inspect_host: implemented, no error expected
		}
		var notImplemented ErrNotImplemented
		if !errors.As(err, &notImplemented) {
			t.Errorf("command %q returned an unexpected error type %T: %v", commandType, err, err)
		}
	}
}

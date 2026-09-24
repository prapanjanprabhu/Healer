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
	_, err := d.Dispatch(context.Background(), protocol.CommandRestartInstance, json.RawMessage(`{}`))
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

// implementedCommandTypes is every command type this Agent build actually
// executes. Everything else in the closed protocol set must still be
// rejected as ErrNotImplemented — a command type must never silently do
// nothing, and must never fall through to something dangerous.
var implementedCommandTypes = map[string]bool{
	protocol.CommandInspectHost:   true,
	protocol.CommandValidateApp:   true,
	protocol.CommandDeployRelease: true,
	protocol.CommandStartInstance: true,
	protocol.CommandStopInstance:  true,
	protocol.CommandCollectLogs:   true,
}

func TestEveryKnownCommandTypeIsSafelyHandledOrRejected(t *testing.T) {
	d := New()
	for commandType := range protocol.KnownCommandTypes {
		_, err := d.Dispatch(context.Background(), commandType, json.RawMessage(`{}`))
		var notImplemented ErrNotImplemented

		if implementedCommandTypes[commandType] {
			// A registered handler may still reject an empty payload as
			// structurally invalid — that's a safe rejection. What it must
			// never do is claim to be unimplemented.
			if errors.As(err, &notImplemented) {
				t.Errorf("command %q is registered but reported as not implemented", commandType)
			}
			var unknown ErrUnknownCommand
			if errors.As(err, &unknown) {
				t.Errorf("command %q is registered but reported as unknown", commandType)
			}
			continue
		}

		if !errors.As(err, &notImplemented) {
			t.Errorf("command %q returned an unexpected error type %T: %v", commandType, err, err)
		}
	}
}

// TestUnimplementedCommandTypesStayUnimplemented names the remaining types
// explicitly, so registering one without deciding to is a test failure
// rather than a silent expansion of what the Agent will execute.
func TestUnimplementedCommandTypesStayUnimplemented(t *testing.T) {
	d := New()
	for _, commandType := range []string{
		protocol.CommandRestartInstance,
		protocol.CommandInspectInstance,
		protocol.CommandCollectMetrics,
		protocol.CommandUpdateProxy,
	} {
		if implementedCommandTypes[commandType] {
			t.Errorf("command %q is listed both as implemented and as out of scope", commandType)
			continue
		}
		_, err := d.Dispatch(context.Background(), commandType, json.RawMessage(`{}`))
		var notImplemented ErrNotImplemented
		if !errors.As(err, &notImplemented) {
			t.Errorf("expected %q to remain unimplemented, got %T: %v", commandType, err, err)
		}
	}
}

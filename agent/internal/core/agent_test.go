package core

import (
	"context"
	"encoding/json"
	"path/filepath"
	"sync/atomic"
	"testing"
	"time"

	"github.com/healer-platform/agent/internal/dispatcher"
	"github.com/healer-platform/agent/internal/journal"
	"github.com/healer-platform/agent/internal/protocol"
)

// newTestAgent returns an Agent plus a channel that receives every event
// the Agent tries to send, so tests can observe outcomes without a real
// WebSocket connection.
func newTestAgent(t *testing.T, d *dispatcher.Dispatcher) (*Agent, chan protocol.CommandEvent) {
	t.Helper()
	j, err := journal.Open(filepath.Join(t.TempDir(), "journal.log"))
	if err != nil {
		t.Fatalf("open journal: %v", err)
	}
	t.Cleanup(func() { _ = j.Close() })

	if d == nil {
		d = dispatcher.New()
	}

	events := make(chan protocol.CommandEvent, 16)
	agent := New(Options{Journal: j, Dispatcher: d})
	return agent, events
}

func sendCapture(events chan protocol.CommandEvent) func(messageType string, payload any) error {
	return func(messageType string, payload any) error {
		if messageType != protocol.TypeAgentCommandEvent {
			return nil
		}
		raw, err := json.Marshal(payload)
		if err != nil {
			return err
		}
		var event protocol.CommandEvent
		if err := json.Unmarshal(raw, &event); err != nil {
			return err
		}
		events <- event
		return nil
	}
}

func commandEnvelope(t *testing.T, commandID, commandType string, expiresAt *time.Time) protocol.Envelope {
	t.Helper()
	cmd := protocol.CommandEnvelope{
		CommandID:      commandID,
		IdempotencyKey: commandID,
		Type:           commandType,
		Payload:        json.RawMessage(`{}`),
		CreatedAt:      time.Now().UTC(),
		ExpiresAt:      expiresAt,
	}
	payload, err := json.Marshal(cmd)
	if err != nil {
		t.Fatalf("marshal command: %v", err)
	}
	return protocol.Envelope{
		ProtocolVersion: protocol.Version,
		MessageID:       "test-message",
		Type:            protocol.TypeControlCommand,
		Timestamp:       time.Now().UTC(),
		Payload:         payload,
	}
}

func waitForStatus(t *testing.T, events chan protocol.CommandEvent, status string, timeout time.Duration) protocol.CommandEvent {
	t.Helper()
	deadline := time.After(timeout)
	for {
		select {
		case ev := <-events:
			if ev.Status == status {
				return ev
			}
		case <-deadline:
			t.Fatalf("timed out waiting for status %q", status)
		}
	}
}

func TestHandleMessageRunsInspectHostToSuccess(t *testing.T) {
	agent, events := newTestAgent(t, nil)
	send := sendCapture(events)

	envelope := commandEnvelope(t, "cmd-1", protocol.CommandInspectHost, nil)
	if err := agent.handleMessage(context.Background(), envelope, send); err != nil {
		t.Fatalf("handleMessage: %v", err)
	}

	waitForStatus(t, events, protocol.StatusAcknowledged, time.Second)
	waitForStatus(t, events, protocol.StatusRunning, time.Second)
	final := waitForStatus(t, events, protocol.StatusSucceeded, time.Second)
	if len(final.Result) == 0 {
		t.Error("expected a non-empty result for a succeeded inspect_host command")
	}
}

func TestDuplicateCommandDeliveryIsIgnoredAfterCompletion(t *testing.T) {
	agent, events := newTestAgent(t, nil)
	send := sendCapture(events)

	envelope := commandEnvelope(t, "cmd-dup", protocol.CommandInspectHost, nil)

	if err := agent.handleMessage(context.Background(), envelope, send); err != nil {
		t.Fatalf("first handleMessage: %v", err)
	}
	waitForStatus(t, events, protocol.StatusSucceeded, time.Second)

	// Redeliver the exact same command — e.g. what a reconnect-triggered
	// resend might look like. It must not be re-executed.
	if err := agent.handleMessage(context.Background(), envelope, send); err != nil {
		t.Fatalf("second handleMessage: %v", err)
	}

	select {
	case ev := <-events:
		t.Fatalf("expected no event for a duplicate completed command, got %+v", ev)
	case <-time.After(200 * time.Millisecond):
		// success: nothing was sent for the redelivered command
	}
}

func TestCommandPastItsDeadlineTimesOut(t *testing.T) {
	d := dispatcher.New()
	blocking := func(ctx context.Context, _ json.RawMessage) (map[string]any, error) {
		<-ctx.Done()
		return nil, ctx.Err()
	}
	d.Register(protocol.CommandInspectHost, blocking)

	agent, events := newTestAgent(t, d)
	send := sendCapture(events)

	expiresAt := time.Now().Add(30 * time.Millisecond)
	envelope := commandEnvelope(t, "cmd-timeout", protocol.CommandInspectHost, &expiresAt)

	if err := agent.handleMessage(context.Background(), envelope, send); err != nil {
		t.Fatalf("handleMessage: %v", err)
	}

	waitForStatus(t, events, protocol.StatusAcknowledged, time.Second)
	waitForStatus(t, events, protocol.StatusRunning, time.Second)
	final := waitForStatus(t, events, protocol.StatusTimedOut, 2*time.Second)
	if final.Error == nil {
		t.Error("expected an error message on a timed-out command")
	}
}

func TestExecutionSurvivesConnectionContextCancellation(t *testing.T) {
	// Regression test: execute() must run against the Agent's own
	// runCtx, not the per-connection ctx handleMessage was called with —
	// transport.Client cancels that context the instant the WebSocket
	// connection drops (see client.go's runOnce), which must not abort an
	// in-flight command that has nothing to do with the connection itself.
	d := dispatcher.New()
	unblock := make(chan struct{})
	d.Register(protocol.CommandInspectHost, func(ctx context.Context, _ json.RawMessage) (map[string]any, error) {
		<-unblock
		return map[string]any{"ok": true}, nil
	})

	agent, events := newTestAgent(t, d)
	send := sendCapture(events)

	connCtx, cancelConn := context.WithCancel(context.Background())
	envelope := commandEnvelope(t, "cmd-survives-disconnect", protocol.CommandInspectHost, nil)
	if err := agent.handleMessage(connCtx, envelope, send); err != nil {
		t.Fatalf("handleMessage: %v", err)
	}
	waitForStatus(t, events, protocol.StatusAcknowledged, time.Second)
	waitForStatus(t, events, protocol.StatusRunning, time.Second)

	// Simulate the connection dropping mid-command.
	cancelConn()
	time.Sleep(20 * time.Millisecond)

	// Let the handler finish — if execute() were tied to connCtx, its
	// ctx would already be Done and the dispatcher's own ctx.Err() would
	// have unblocked it with an error instead of this succeeding.
	close(unblock)

	final := waitForStatus(t, events, protocol.StatusSucceeded, time.Second)
	if final.Error != nil {
		t.Errorf("expected the command to succeed despite the connection dropping, got error: %v", *final.Error)
	}
}

func TestRedeliveryWhileStillInFlightIsIgnored(t *testing.T) {
	d := dispatcher.New()
	unblock := make(chan struct{})
	var invocations int32
	d.Register(protocol.CommandInspectHost, func(ctx context.Context, _ json.RawMessage) (map[string]any, error) {
		atomic.AddInt32(&invocations, 1)
		<-unblock
		return map[string]any{"ok": true}, nil
	})

	agent, events := newTestAgent(t, d)
	send := sendCapture(events)

	envelope := commandEnvelope(t, "cmd-inflight-dup", protocol.CommandInspectHost, nil)
	if err := agent.handleMessage(context.Background(), envelope, send); err != nil {
		t.Fatalf("first handleMessage: %v", err)
	}
	waitForStatus(t, events, protocol.StatusAcknowledged, time.Second)
	waitForStatus(t, events, protocol.StatusRunning, time.Second)

	// Redeliver while the first is still blocked mid-execution — no ack/
	// running event should be produced for this second delivery, and the
	// dispatcher handler must not be invoked a second time concurrently.
	if err := agent.handleMessage(context.Background(), envelope, send); err != nil {
		t.Fatalf("second handleMessage: %v", err)
	}
	select {
	case ev := <-events:
		t.Fatalf("expected no event for a redelivery while still in flight, got %+v", ev)
	case <-time.After(200 * time.Millisecond):
	}

	close(unblock)
	waitForStatus(t, events, protocol.StatusSucceeded, time.Second)

	if got := atomic.LoadInt32(&invocations); got != 1 {
		t.Errorf("expected the dispatcher handler to run exactly once, ran %d times", got)
	}
}

func TestUnimplementedCommandReportsFailed(t *testing.T) {
	agent, events := newTestAgent(t, nil)
	send := sendCapture(events)

	envelope := commandEnvelope(t, "cmd-unimpl", protocol.CommandDeployRelease, nil)
	if err := agent.handleMessage(context.Background(), envelope, send); err != nil {
		t.Fatalf("handleMessage: %v", err)
	}

	waitForStatus(t, events, protocol.StatusAcknowledged, time.Second)
	waitForStatus(t, events, protocol.StatusRunning, time.Second)
	final := waitForStatus(t, events, protocol.StatusFailed, time.Second)
	if final.Error == nil || *final.Error == "" {
		t.Error("expected a failure reason for an unimplemented command type")
	}
}

func TestNonCommandEnvelopeIsIgnored(t *testing.T) {
	agent, events := newTestAgent(t, nil)
	send := sendCapture(events)

	envelope := protocol.Envelope{
		ProtocolVersion: protocol.Version,
		MessageID:       "x",
		Type:            "some.future.message.type",
		Timestamp:       time.Now().UTC(),
		Payload:         json.RawMessage(`{}`),
	}
	if err := agent.handleMessage(context.Background(), envelope, send); err != nil {
		t.Fatalf("handleMessage: %v", err)
	}

	select {
	case ev := <-events:
		t.Fatalf("expected no event for an unrecognized envelope type, got %+v", ev)
	case <-time.After(100 * time.Millisecond):
	}
}

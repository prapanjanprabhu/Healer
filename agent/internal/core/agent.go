// Package core wires together the transport, journal, and dispatcher into
// the Agent's actual message-handling behavior: send agent.hello on
// connect, heartbeat on a timer, and — for every control.command received
// — deduplicate against the journal, acknowledge, run it with a deadline,
// and report the terminal event.
package core

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"runtime"
	"time"

	"github.com/healer-platform/agent/internal/dispatcher"
	"github.com/healer-platform/agent/internal/journal"
	"github.com/healer-platform/agent/internal/metrics"
	"github.com/healer-platform/agent/internal/protocol"
	"github.com/healer-platform/agent/internal/transport"
	"github.com/healer-platform/agent/internal/version"
)

// Options configures an Agent. Journal and Dispatcher are required;
// New panics without them (this is a programming error, not a runtime
// condition to handle gracefully).
type Options struct {
	ControlPlaneWSURL string
	Credential        string
	DataDir           string
	HeartbeatEvery    time.Duration
	Adapters          []string
	Logger            *slog.Logger
	Journal           *journal.Journal
	Dispatcher        *dispatcher.Dispatcher

	// MinBackoff/MaxBackoff let tests override transport.Client's default
	// reconnect timing.
	MinBackoff time.Duration
	MaxBackoff time.Duration
}

// Agent is the Control-Plane-facing half of the Healer Agent.
type Agent struct {
	opts Options
}

// New constructs an Agent. Options.Journal and Options.Dispatcher must be
// set by the caller (they have their own lifecycles — the journal file
// needs to be closed on shutdown, and the dispatcher's handler set may
// vary by build).
func New(opts Options) *Agent {
	if opts.Journal == nil {
		panic("core.New: Options.Journal is required")
	}
	if opts.Dispatcher == nil {
		panic("core.New: Options.Dispatcher is required")
	}
	return &Agent{opts: opts}
}

// Run connects to the Control Plane and processes messages until ctx is
// cancelled. See transport.Client.Run for the reconnect/shutdown contract.
func (a *Agent) Run(ctx context.Context) error {
	client := &transport.Client{
		URL:            a.opts.ControlPlaneWSURL,
		Credential:     a.opts.Credential,
		Logger:         a.opts.Logger,
		HeartbeatEvery: a.opts.HeartbeatEvery,
		MinBackoff:     a.opts.MinBackoff,
		MaxBackoff:     a.opts.MaxBackoff,
		OnConnect:      a.sendHello,
		HeartbeatFn:    a.collectHeartbeat,
		OnMessage:      a.handleMessage,
	}
	return client.Run(ctx)
}

func (a *Agent) sendHello(_ context.Context, send transport.SendFunc) error {
	return send(protocol.TypeAgentHello, protocol.HelloPayload{
		AgentVersion: version.Version,
		OS:           runtime.GOOS,
		Arch:         runtime.GOARCH,
		Adapters:     a.opts.Adapters,
	})
}

func (a *Agent) collectHeartbeat(ctx context.Context) (protocol.HeartbeatPayload, error) {
	snap, err := metrics.Collect(ctx, a.opts.DataDir)
	if err != nil {
		return protocol.HeartbeatPayload{}, err
	}
	return protocol.HeartbeatPayload{
		CPUPercent:    snap.CPUPercent,
		MemoryPercent: snap.MemoryPercent,
		DiskPercent:   snap.DiskPercent,
		Instances:     []protocol.InstanceStatus{},
	}, nil
}

// handleMessage is deliberately a plain method taking an envelope and a
// send closure — no live connection required — so it's directly unit
// testable (see agent_test.go) without a real WebSocket.
func (a *Agent) handleMessage(ctx context.Context, envelope protocol.Envelope, send transport.SendFunc) error {
	if envelope.Type != protocol.TypeControlCommand {
		return nil // forward-compatible: ignore message types we don't know
	}

	var cmd protocol.CommandEnvelope
	if err := json.Unmarshal(envelope.Payload, &cmd); err != nil {
		return fmt.Errorf("malformed command envelope: %w", err)
	}

	if a.opts.Journal.IsCompleted(cmd.CommandID) {
		if a.opts.Logger != nil {
			a.opts.Logger.Info("ignoring already-completed command (duplicate delivery)",
				"command_id", cmd.CommandID, "idempotency_key", cmd.IdempotencyKey)
		}
		return nil
	}

	if err := a.opts.Journal.Record(cmd.CommandID, journal.StatusReceived); err != nil {
		return fmt.Errorf("journal record received: %w", err)
	}
	if err := send(protocol.TypeAgentCommandEvent, protocol.CommandEvent{
		CommandID:  cmd.CommandID,
		Status:     protocol.StatusAcknowledged,
		OccurredAt: time.Now().UTC(),
	}); err != nil {
		return fmt.Errorf("send acknowledged event: %w", err)
	}

	// Executed off the read loop so one slow/long-running command never
	// blocks heartbeats or other commands from being received.
	go a.execute(ctx, cmd, send)
	return nil
}

func (a *Agent) execute(ctx context.Context, cmd protocol.CommandEnvelope, send transport.SendFunc) {
	logger := a.opts.Logger

	_ = a.opts.Journal.Record(cmd.CommandID, journal.StatusRunning)
	_ = send(protocol.TypeAgentCommandEvent, protocol.CommandEvent{
		CommandID:  cmd.CommandID,
		Status:     protocol.StatusRunning,
		OccurredAt: time.Now().UTC(),
	})

	execCtx := ctx
	if cmd.ExpiresAt != nil {
		var cancel context.CancelFunc
		execCtx, cancel = context.WithDeadline(ctx, *cmd.ExpiresAt)
		defer cancel()
	}

	result, err := a.opts.Dispatcher.Dispatch(execCtx, cmd.Type, cmd.Payload)
	if journalErr := a.opts.Journal.Record(cmd.CommandID, journal.StatusCompleted); journalErr != nil && logger != nil {
		logger.Error("failed to record command completion in journal", "command_id", cmd.CommandID, "error", journalErr)
	}

	now := time.Now().UTC()
	if err != nil {
		status := protocol.StatusFailed
		if errors.Is(execCtx.Err(), context.DeadlineExceeded) {
			status = protocol.StatusTimedOut
		}
		errMsg := err.Error()
		if sendErr := send(protocol.TypeAgentCommandEvent, protocol.CommandEvent{
			CommandID: cmd.CommandID, Status: status, Error: &errMsg, OccurredAt: now,
		}); sendErr != nil && logger != nil {
			logger.Warn("failed to send command failure event", "command_id", cmd.CommandID, "error", sendErr)
		}
		return
	}

	resultJSON, marshalErr := json.Marshal(result)
	if marshalErr != nil {
		errMsg := marshalErr.Error()
		_ = send(protocol.TypeAgentCommandEvent, protocol.CommandEvent{
			CommandID: cmd.CommandID, Status: protocol.StatusFailed, Error: &errMsg, OccurredAt: now,
		})
		return
	}
	if sendErr := send(protocol.TypeAgentCommandEvent, protocol.CommandEvent{
		CommandID: cmd.CommandID, Status: protocol.StatusSucceeded, Result: resultJSON, OccurredAt: now,
	}); sendErr != nil && logger != nil {
		logger.Warn("failed to send command success event", "command_id", cmd.CommandID, "error", sendErr)
	}
}

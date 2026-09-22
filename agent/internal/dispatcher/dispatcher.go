// Package dispatcher restricts the Agent to executing exactly the closed
// set of structured command types the protocol defines — there is no path
// from a received message to running an arbitrary shell command.
//
// Phase 5 registers only inspect_host (a safe, read-only command, useful
// for proving the protocol end to end). The other nine types are
// recognized — they're part of the closed protocol — but not yet
// implemented: application deployment handlers are a later phase. A
// request for one of them is rejected with a distinct, safe error rather
// than silently doing nothing or falling through to something dangerous.
package dispatcher

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/healer-platform/agent/internal/protocol"
)

// Handler executes one command type and returns a JSON-serializable result.
type Handler func(ctx context.Context, payload json.RawMessage) (map[string]any, error)

// ErrUnknownCommand is returned for a command type outside the closed
// protocol set entirely — never expected from a correctly-versioned
// Control Plane, but rejected safely rather than assumed safe to run.
type ErrUnknownCommand struct{ Type string }

func (e ErrUnknownCommand) Error() string {
	return fmt.Sprintf("unknown command type %q — not part of the Healer agent protocol", e.Type)
}

// ErrNotImplemented is returned for a recognized command type this Agent
// version doesn't yet implement (e.g. deploy_release in Phase 5).
type ErrNotImplemented struct{ Type string }

func (e ErrNotImplemented) Error() string {
	return fmt.Sprintf("command type %q is recognized but not implemented by this agent version", e.Type)
}

// Dispatcher routes a command type to its Handler.
type Dispatcher struct {
	handlers map[string]Handler
}

// New returns a Dispatcher with the Phase 5 handler set registered.
func New() *Dispatcher {
	d := &Dispatcher{handlers: make(map[string]Handler)}
	d.Register(protocol.CommandInspectHost, HandleInspectHost)
	return d
}

// Register wires a handler for a command type. Registering a type outside
// protocol.KnownCommandTypes is a programming error and panics immediately
// — it must never happen at runtime from untrusted input.
func (d *Dispatcher) Register(commandType string, handler Handler) {
	if !protocol.KnownCommandTypes[commandType] {
		panic(fmt.Sprintf("dispatcher: refusing to register unknown command type %q", commandType))
	}
	d.handlers[commandType] = handler
}

// Dispatch runs the handler for commandType, or returns ErrUnknownCommand /
// ErrNotImplemented without executing anything.
func (d *Dispatcher) Dispatch(ctx context.Context, commandType string, payload json.RawMessage) (map[string]any, error) {
	if !protocol.KnownCommandTypes[commandType] {
		return nil, ErrUnknownCommand{Type: commandType}
	}
	handler, ok := d.handlers[commandType]
	if !ok {
		return nil, ErrNotImplemented{Type: commandType}
	}
	return handler(ctx, payload)
}

// Package transport will hold the Agent's outbound secure WebSocket client
// to the Control Plane (see protocols/README.md for the message contract).
//
// Phase 1 ships only this contract stub — establishing the connection,
// sending agent.register/agent.heartbeat, and handling
// control.deploy_command/control.instance_command are implemented alongside
// deployment behavior in a later phase.
package transport

import (
	"context"
	"errors"

	"github.com/healer-platform/agent/internal/config"
)

// Connect will dial the Control Plane's WebSocket endpoint and perform the
// agent.register handshake. Not implemented in Phase 1.
func Connect(_ context.Context, _ config.Config) error {
	return errors.New("transport.Connect: not implemented in Phase 1")
}

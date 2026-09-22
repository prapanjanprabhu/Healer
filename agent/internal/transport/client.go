// Package transport is the Agent's persistent outbound WebSocket
// connection to the Control Plane: dial, authenticate, exchange messages,
// and reconnect with exponential backoff whenever the connection drops.
package transport

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"sync"
	"time"

	"github.com/gorilla/websocket"
	"github.com/healer-platform/agent/internal/protocol"
	"github.com/healer-platform/agent/internal/version"
)

// SendFunc sends one message over the currently-open connection. It's only
// valid for the duration of the OnConnect/OnMessage/HeartbeatFn call it was
// handed to.
type SendFunc func(messageType string, payload any) error

// Client is the Agent's WebSocket connection to the Control Plane.
type Client struct {
	URL        string
	Credential string
	Logger     *slog.Logger

	// OnConnect runs once, right after the connection is accepted — the
	// Agent uses it to send agent.hello.
	OnConnect func(ctx context.Context, send SendFunc) error
	// OnMessage runs for every envelope received from the Control Plane.
	OnMessage func(ctx context.Context, envelope protocol.Envelope, send SendFunc) error
	// HeartbeatFn, if set, is called every HeartbeatEvery to produce the
	// next agent.heartbeat payload.
	HeartbeatFn    func(ctx context.Context) (protocol.HeartbeatPayload, error)
	HeartbeatEvery time.Duration

	// Dialer defaults to websocket.DefaultDialer; overridable by tests.
	Dialer *websocket.Dialer

	// MinBackoff/MaxBackoff default to 1s/30s; overridable by tests so
	// reconnect tests don't have to wait tens of seconds.
	MinBackoff time.Duration
	MaxBackoff time.Duration
}

// Run connects and, on any disconnect, reconnects with exponential
// backoff, until ctx is cancelled — at which point it returns ctx.Err().
// This is the Agent's entire connection lifetime; the only way out is a
// cancelled context (clean shutdown).
func (c *Client) Run(ctx context.Context) error {
	dialer := c.Dialer
	if dialer == nil {
		dialer = websocket.DefaultDialer
	}
	minBackoff, maxBackoff := c.MinBackoff, c.MaxBackoff
	if minBackoff <= 0 {
		minBackoff = time.Second
	}
	if maxBackoff <= 0 {
		maxBackoff = 30 * time.Second
	}
	b := newBackoff(minBackoff, maxBackoff)

	for {
		if err := ctx.Err(); err != nil {
			return err
		}

		err := c.runOnce(ctx, dialer, b)

		if ctxErr := ctx.Err(); ctxErr != nil {
			return ctxErr
		}

		wait := b.Next()
		if c.Logger != nil {
			c.Logger.Warn("connection lost; reconnecting", "error", err, "wait", wait.String())
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(wait):
		}
	}
}

func (c *Client) runOnce(ctx context.Context, dialer *websocket.Dialer, b *backoff) error {
	header := http.Header{}
	header.Set("Authorization", "Bearer "+c.Credential)

	conn, _, err := dialer.DialContext(ctx, c.URL, header)
	if err != nil {
		return fmt.Errorf("dial: %w", err)
	}
	defer conn.Close()
	b.Reset()

	connCtx, cancel := context.WithCancel(ctx)
	defer cancel()

	// gorilla/websocket reads don't respect context cancellation directly;
	// closing the connection is what unblocks a pending ReadJSON, which is
	// how a cancelled top-level context turns into a clean shutdown here.
	go func() {
		<-connCtx.Done()
		_ = conn.Close()
	}()

	var writeMu sync.Mutex
	send := func(messageType string, payload any) error {
		raw, err := json.Marshal(payload)
		if err != nil {
			return fmt.Errorf("marshal %s payload: %w", messageType, err)
		}
		envelope := protocol.Envelope{
			ProtocolVersion: protocol.Version,
			MessageID:       newMessageID(),
			Type:            messageType,
			Timestamp:       time.Now().UTC(),
			Payload:         raw,
		}
		writeMu.Lock()
		defer writeMu.Unlock()
		return conn.WriteJSON(envelope)
	}

	if c.OnConnect != nil {
		if err := c.OnConnect(connCtx, send); err != nil {
			return fmt.Errorf("on-connect: %w", err)
		}
	}

	if c.HeartbeatFn != nil && c.HeartbeatEvery > 0 {
		go c.heartbeatLoop(connCtx, send)
	}

	for {
		var envelope protocol.Envelope
		if err := conn.ReadJSON(&envelope); err != nil {
			if connCtx.Err() != nil {
				return connCtx.Err()
			}
			return fmt.Errorf("read: %w", err)
		}

		if !version.Compatible(envelope.ProtocolVersion) {
			if c.Logger != nil {
				c.Logger.Warn("ignoring message with an incompatible protocol version",
					"message_protocol_version", envelope.ProtocolVersion,
					"min_compatible_protocol_version", version.MinCompatibleProtocolVersion)
			}
			continue
		}

		if c.OnMessage != nil {
			if err := c.OnMessage(connCtx, envelope, send); err != nil && c.Logger != nil {
				c.Logger.Error("error handling message", "type", envelope.Type, "error", err)
			}
		}
	}
}

func (c *Client) heartbeatLoop(ctx context.Context, send SendFunc) {
	ticker := time.NewTicker(c.HeartbeatEvery)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			payload, err := c.HeartbeatFn(ctx)
			if err != nil {
				if c.Logger != nil {
					c.Logger.Warn("heartbeat collection failed", "error", err)
				}
				continue
			}
			if err := send(protocol.TypeAgentHeartbeat, payload); err != nil {
				if c.Logger != nil {
					c.Logger.Warn("heartbeat send failed", "error", err)
				}
				return // the read loop's error path will trigger reconnect
			}
		}
	}
}

// newMessageID returns a random RFC 4122-shaped identifier. A tiny
// hand-rolled generator avoids pulling in a UUID dependency for one field
// that's only ever used for log correlation, never parsed.
func newMessageID() string {
	var b [16]byte
	_, _ = rand.Read(b[:])
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	return fmt.Sprintf("%s-%s-%s-%s-%s",
		hex.EncodeToString(b[0:4]),
		hex.EncodeToString(b[4:6]),
		hex.EncodeToString(b[6:8]),
		hex.EncodeToString(b[8:10]),
		hex.EncodeToString(b[10:16]))
}

package transport

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/gorilla/websocket"
	"github.com/healer-platform/agent/internal/protocol"
)

// testServer is a minimal /ws/agent stand-in: it upgrades every connection
// and calls onConn for each one, letting each test decide what a
// connection does (close immediately, echo messages, etc).
func testServer(t *testing.T, onConn func(conn *websocket.Conn)) (*httptest.Server, *int32) {
	t.Helper()
	var connectCount int32
	upgrader := websocket.Upgrader{}

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		atomic.AddInt32(&connectCount, 1)
		onConn(conn)
	}))
	t.Cleanup(server.Close)
	return server, &connectCount
}

func wsURL(server *httptest.Server) string {
	return "ws" + strings.TrimPrefix(server.URL, "http")
}

func TestClientReconnectsAfterServerClosesConnection(t *testing.T) {
	server, connectCount := testServer(t, func(conn *websocket.Conn) {
		// Immediately close every connection — forces the client to
		// reconnect, over and over.
		conn.Close()
	})

	client := &Client{
		URL:        wsURL(server),
		Credential: "test-credential",
		MinBackoff: 10 * time.Millisecond,
		MaxBackoff: 50 * time.Millisecond,
	}

	ctx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
	defer cancel()

	_ = client.Run(ctx)

	if atomic.LoadInt32(connectCount) < 2 {
		t.Fatalf("expected at least 2 connection attempts, got %d", atomic.LoadInt32(connectCount))
	}
}

func TestClientShutsDownCleanlyOnContextCancel(t *testing.T) {
	connected := make(chan struct{})
	server, _ := testServer(t, func(conn *websocket.Conn) {
		close(connected)
		// Keep the connection open until the test closes it.
		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				return
			}
		}
	})

	client := &Client{
		URL:        wsURL(server),
		Credential: "test-credential",
		MinBackoff: 10 * time.Millisecond,
		MaxBackoff: 50 * time.Millisecond,
	}

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- client.Run(ctx) }()

	select {
	case <-connected:
	case <-time.After(2 * time.Second):
		t.Fatal("client never connected")
	}

	cancel()

	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Errorf("expected context.Canceled, got %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Run did not return promptly after context cancellation")
	}
}

func TestClientSendsHelloOnConnect(t *testing.T) {
	received := make(chan protocol.Envelope, 1)
	server, _ := testServer(t, func(conn *websocket.Conn) {
		var env protocol.Envelope
		if err := conn.ReadJSON(&env); err == nil {
			received <- env
		}
	})

	client := &Client{
		URL:        wsURL(server),
		Credential: "test-credential",
		MinBackoff: 10 * time.Millisecond,
		MaxBackoff: 50 * time.Millisecond,
		OnConnect: func(_ context.Context, send SendFunc) error {
			return send(protocol.TypeAgentHello, protocol.HelloPayload{
				AgentVersion: "test",
				OS:           "linux",
				Arch:         "amd64",
			})
		},
	}

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	go func() { _ = client.Run(ctx) }()

	select {
	case env := <-received:
		if env.Type != protocol.TypeAgentHello {
			t.Errorf("expected type %q, got %q", protocol.TypeAgentHello, env.Type)
		}
		if env.ProtocolVersion != protocol.Version {
			t.Errorf("expected protocol version %q, got %q", protocol.Version, env.ProtocolVersion)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("server never received agent.hello")
	}
}

func TestClientRejectsAuthenticationBeforeUpgrading(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer expected-credential" {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	client := &Client{
		URL:        wsURL(server),
		Credential: "wrong-credential",
		MinBackoff: 10 * time.Millisecond,
		MaxBackoff: 20 * time.Millisecond,
	}

	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	err := client.Run(ctx)
	if err == nil {
		t.Fatal("expected Run to eventually return the context deadline error")
	}
}

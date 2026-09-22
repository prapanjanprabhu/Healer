package enroll

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestEnrollSuccess(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body map[string]string
		_ = json.NewDecoder(r.Body).Decode(&body)
		if body["token"] != "good-token" {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(Response{
			AgentID: "agent-1", ServerID: "server-1", Credential: "issued-credential",
			ControlPlaneWSURL: "ws://localhost:8000/ws/agent",
		})
	}))
	defer server.Close()

	resp, err := Enroll(context.Background(), server.URL, "good-token")
	if err != nil {
		t.Fatalf("enroll: %v", err)
	}
	if resp.Credential != "issued-credential" {
		t.Errorf("credential = %q, want %q", resp.Credential, "issued-credential")
	}
}

func TestEnrollFailureSurfacesServerError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
		_, _ = w.Write([]byte(`{"detail":"invalid or expired token"}`))
	}))
	defer server.Close()

	_, err := Enroll(context.Background(), server.URL, "bad-token")
	if err == nil {
		t.Fatal("expected an error for a rejected enrollment token")
	}
}

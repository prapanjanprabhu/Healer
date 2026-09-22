// Package enroll performs the one-time REST call that exchanges a
// single-use enrollment token for a long-lived connection credential. See
// docs/agent-protocol.md.
package enroll

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// Response is what POST /agents/enroll returns.
type Response struct {
	AgentID           string `json:"agent_id"`
	ServerID          string `json:"server_id"`
	Credential        string `json:"credential"`
	ControlPlaneWSURL string `json:"control_plane_ws_url"`
}

// Enroll consumes token against controlPlaneURL (e.g.
// "http://localhost:8000") and returns the issued credential.
func Enroll(ctx context.Context, controlPlaneURL, token string) (Response, error) {
	body, err := json.Marshal(map[string]string{"token": token})
	if err != nil {
		return Response{}, fmt.Errorf("marshal request: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost,
		controlPlaneURL+"/agents/enroll", bytes.NewReader(body))
	if err != nil {
		return Response{}, fmt.Errorf("build request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: 15 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return Response{}, fmt.Errorf("enroll request: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return Response{}, fmt.Errorf("read enroll response: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return Response{}, fmt.Errorf("enroll failed: HTTP %d: %s", resp.StatusCode, string(respBody))
	}

	var result Response
	if err := json.Unmarshal(respBody, &result); err != nil {
		return Response{}, fmt.Errorf("parse enroll response: %w", err)
	}
	if result.Credential == "" {
		return Response{}, fmt.Errorf("enroll response did not include a credential")
	}
	return result, nil
}

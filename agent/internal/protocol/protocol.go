// Package protocol mirrors the Control Plane's wire contract in
// protocols/v2 — the envelope and message payload shapes exchanged over
// /ws/agent, and the closed set of structured command types. There is no
// shell/free-form command anywhere in this protocol.
package protocol

import (
	"encoding/json"
	"time"
)

// Version is the protocol_version this Agent speaks — see
// protocols/v2/envelope.schema.json.
const Version = "1.0"

// Envelope wraps every message exchanged over the WebSocket connection.
type Envelope struct {
	ProtocolVersion string          `json:"protocol_version"`
	MessageID       string          `json:"message_id"`
	Type            string          `json:"type"`
	Timestamp       time.Time       `json:"timestamp"`
	Payload         json.RawMessage `json:"payload"`
}

// Message types.
const (
	TypeAgentHello        = "agent.hello"
	TypeAgentHeartbeat    = "agent.heartbeat"
	TypeAgentCommandEvent = "agent.command_event"
	TypeControlCommand    = "control.command"
)

// HelloPayload is sent once, immediately after connecting — the capability
// report. See protocols/v2/agent-hello.schema.json.
type HelloPayload struct {
	AgentVersion string   `json:"agent_version"`
	OS           string   `json:"os"`
	Arch         string   `json:"arch"`
	Adapters     []string `json:"adapters,omitempty"`
}

// InstanceStatus is one entry in a heartbeat's per-instance status list.
type InstanceStatus struct {
	InstanceID string `json:"instance_id"`
	Status     string `json:"status"`
	Port       int    `json:"port,omitempty"`
}

// HeartbeatPayload is the periodic metrics snapshot. See
// protocols/v2/agent-heartbeat.schema.json.
type HeartbeatPayload struct {
	CPUPercent    float64          `json:"cpu_percent"`
	MemoryPercent float64          `json:"memory_percent"`
	DiskPercent   float64          `json:"disk_percent"`
	Instances     []InstanceStatus `json:"instances"`
}

// CommandEnvelope is the payload of a control.command message. See
// protocols/v2/command-envelope.schema.json.
type CommandEnvelope struct {
	CommandID      string          `json:"command_id"`
	IdempotencyKey string          `json:"idempotency_key"`
	Type           string          `json:"type"`
	Payload        json.RawMessage `json:"payload"`
	CreatedAt      time.Time       `json:"created_at"`
	ExpiresAt      *time.Time      `json:"expires_at"`
	CorrelationID  *string         `json:"correlation_id"`
}

// Command event statuses.
const (
	StatusAcknowledged = "acknowledged"
	StatusRunning      = "running"
	StatusSucceeded    = "succeeded"
	StatusFailed       = "failed"
	StatusTimedOut     = "timed_out"
)

// CommandEvent reports command progress/result. See
// protocols/v2/command-event.schema.json.
type CommandEvent struct {
	CommandID  string          `json:"command_id"`
	Status     string          `json:"status"`
	Result     json.RawMessage `json:"result,omitempty"`
	Error      *string         `json:"error,omitempty"`
	OccurredAt time.Time       `json:"occurred_at"`
}

// The ten structured command types the Agent will ever be asked to run.
const (
	CommandInspectHost     = "inspect_host"
	CommandValidateApp     = "validate_app"
	CommandDeployRelease   = "deploy_release"
	CommandStartInstance   = "start_instance"
	CommandStopInstance    = "stop_instance"
	CommandRestartInstance = "restart_instance"
	CommandInspectInstance = "inspect_instance"
	CommandCollectLogs     = "collect_logs"
	CommandCollectMetrics  = "collect_metrics"
	CommandUpdateProxy     = "update_proxy"
)

// KnownCommandTypes is the closed set the Control Plane may ever send.
// Anything not in this set is rejected as "unknown" rather than merely
// "unimplemented" — see internal/dispatcher.
var KnownCommandTypes = map[string]bool{
	CommandInspectHost:     true,
	CommandValidateApp:     true,
	CommandDeployRelease:   true,
	CommandStartInstance:   true,
	CommandStopInstance:    true,
	CommandRestartInstance: true,
	CommandInspectInstance: true,
	CommandCollectLogs:     true,
	CommandCollectMetrics:  true,
	CommandUpdateProxy:     true,
}

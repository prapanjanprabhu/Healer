// Package version holds the Agent's build version and the protocol
// compatibility floor it requires from a Control Plane.
package version

// Version is the Agent's build version, reported in agent.hello. A `var`
// (not `const`) so a release build can inject the real version via
// `-ldflags "-X github.com/healer-platform/agent/internal/version.Version=1.0.0"`
// (see `make release-agent`); an unreleased/dev build keeps this default.
var Version = "0.5.0-dev"

// MinCompatibleProtocolVersion is the oldest wire protocol_version this
// Agent build understands. It refuses to run against a Control Plane
// reporting anything older, rather than guess at a mismatched contract —
// see Compatible.
const MinCompatibleProtocolVersion = "1.0"

// Compatible reports whether protocolVersion (as reported by the Control
// Plane, e.g. in every envelope) is one this Agent build supports. V1 has
// exactly one protocol version, so this is an equality check; once a
// second version exists this is where the real comparison logic goes.
func Compatible(protocolVersion string) bool {
	return protocolVersion == MinCompatibleProtocolVersion
}

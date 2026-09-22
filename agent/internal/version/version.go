// Package version holds the Agent's build version. It is a plain constant in
// Phase 1; a later phase may inject this at build time via -ldflags.
package version

const Version = "0.1.0-dev"

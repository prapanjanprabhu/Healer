package version

import "testing"

func TestVersionIsSet(t *testing.T) {
	if Version == "" {
		t.Fatal("Version must not be empty")
	}
}

func TestCompatibleAcceptsTheSupportedProtocolVersion(t *testing.T) {
	if !Compatible(MinCompatibleProtocolVersion) {
		t.Fatalf("expected protocol version %q to be compatible", MinCompatibleProtocolVersion)
	}
}

func TestCompatibleRejectsAnUnknownProtocolVersion(t *testing.T) {
	if Compatible("99.0") {
		t.Fatal("expected an unrecognized protocol version to be reported incompatible")
	}
}

"""A fake Agent for integration testing — drives a real /ws/agent connection
the same way the Go agent (Phase 5) will, using Starlette's in-process
WebSocket test session (no real network, no real process).

This is the "fake Agent simulator" required by the Phase 4 spec.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

PROTOCOL_VERSION = "1.0"


def envelope(message_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "message_id": str(uuid.uuid4()),
        "type": message_type,
        "timestamp": datetime.now(UTC).isoformat(),
        "payload": payload,
    }


class FakeAgent:
    def __init__(
        self,
        ws_session,
        *,
        agent_version: str = "0.1.0-test",
        os: str = "linux",
        arch: str = "amd64",
        adapters: list[str] | None = None,
    ):
        self.ws = ws_session
        self.agent_version = agent_version
        self.os = os
        self.arch = arch
        self.adapters = adapters or ["linux-docker"]

    def hello(self) -> None:
        self.ws.send_json(
            envelope(
                "agent.hello",
                {
                    "agent_version": self.agent_version,
                    "os": self.os,
                    "arch": self.arch,
                    "adapters": self.adapters,
                },
            )
        )

    def heartbeat(
        self,
        *,
        cpu_percent: float = 5.0,
        memory_percent: float = 20.0,
        disk_percent: float = 30.0,
        instances: list[dict] | None = None,
    ) -> None:
        self.ws.send_json(
            envelope(
                "agent.heartbeat",
                {
                    "cpu_percent": cpu_percent,
                    "memory_percent": memory_percent,
                    "disk_percent": disk_percent,
                    "instances": instances or [],
                },
            )
        )

    def receive_command(self) -> dict:
        message = self.ws.receive_json()
        assert message["type"] == "control.command"
        return message["payload"]

    def send_event(
        self,
        command_id: str,
        event_status: str,
        *,
        result: dict | None = None,
        error: str | None = None,
    ) -> None:
        self.ws.send_json(
            envelope(
                "agent.command_event",
                {
                    "command_id": command_id,
                    "status": event_status,
                    "result": result,
                    "error": error,
                    "occurred_at": datetime.now(UTC).isoformat(),
                },
            )
        )

    def run_command_to_success(self, result: dict | None = None) -> dict:
        """Receives the next queued command and drives it through
        acknowledged -> running -> succeeded, the same sequence a real
        agent follows. Returns the command payload it received.
        """
        command = self.receive_command()
        self.send_event(command["command_id"], "acknowledged")
        self.send_event(command["command_id"], "running")
        self.send_event(command["command_id"], "succeeded", result=result or {"ok": True})
        return command

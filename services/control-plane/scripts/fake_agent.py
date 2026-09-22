#!/usr/bin/env python3
"""Standalone fake Agent — connects to a real running Control Plane over a
real network WebSocket (unlike tests/support/fake_agent.py, which drives an
in-process ASGI test transport). Useful for manual/dashboard demonstration
and for exercising the real deployed server, not just the test suite.

Usage:
    python scripts/fake_agent.py enroll \\
        --control-plane http://localhost:8000 --token <raw-enrollment-token>
    python scripts/fake_agent.py run \\
        --control-plane ws://localhost:8000/ws/agent --credential <raw-credential>

`run` connects, sends agent.hello + periodic agent.heartbeat, and
auto-completes any command it receives (acknowledged -> running ->
succeeded) with a trivial result — enough to prove the protocol end to end
without any real adapter logic (that's Phase 5+).
"""

import argparse
import asyncio
import json
import sys
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime

import websockets

PROTOCOL_VERSION = "1.0"


def envelope(message_type: str, payload: dict) -> dict:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "message_id": str(uuid.uuid4()),
        "type": message_type,
        "timestamp": datetime.now(UTC).isoformat(),
        "payload": payload,
    }


def cmd_enroll(args: argparse.Namespace) -> None:
    request = urllib.request.Request(
        f"{args.control_plane}/agents/enroll",
        data=json.dumps({"token": args.token}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        print(f"enroll failed: HTTP {exc.code} {exc.read().decode()}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(json.dumps(body, indent=2))
    print(
        f"\nSave this credential — it is shown exactly once: {body['credential']}", file=sys.stderr
    )


async def _run(args: argparse.Namespace) -> None:
    headers = {"Authorization": f"Bearer {args.credential}"}
    async with websockets.connect(args.control_plane, additional_headers=headers) as ws:
        print("connected", file=sys.stderr)
        await ws.send(
            json.dumps(
                envelope(
                    "agent.hello",
                    {
                        "agent_version": "0.1.0-fake",
                        "os": args.os,
                        "arch": "amd64",
                        "adapters": [
                            (
                                f"{args.os}-docker"
                                if args.os == "linux"
                                else "windows-waitress-service"
                            )
                        ],
                    },
                )
            )
        )

        async def heartbeat_loop() -> None:
            while True:
                await ws.send(
                    json.dumps(
                        envelope(
                            "agent.heartbeat",
                            {
                                "cpu_percent": 5.0,
                                "memory_percent": 20.0,
                                "disk_percent": 30.0,
                                "instances": [],
                            },
                        )
                    )
                )
                await asyncio.sleep(args.heartbeat_interval)

        heartbeat_task = asyncio.create_task(heartbeat_loop())
        try:
            async for raw_message in ws:
                message = json.loads(raw_message)
                if message["type"] != "control.command":
                    continue
                command = message["payload"]
                print(
                    f"received command: {command['type']} ({command['command_id']})",
                    file=sys.stderr,
                )
                for status in ("acknowledged", "running"):
                    await ws.send(
                        json.dumps(
                            envelope(
                                "agent.command_event",
                                {
                                    "command_id": command["command_id"],
                                    "status": status,
                                    "occurred_at": datetime.now(UTC).isoformat(),
                                },
                            )
                        )
                    )
                await ws.send(
                    json.dumps(
                        envelope(
                            "agent.command_event",
                            {
                                "command_id": command["command_id"],
                                "status": "succeeded",
                                "result": {"ok": True, "type": command["type"]},
                                "occurred_at": datetime.now(UTC).isoformat(),
                            },
                        )
                    )
                )
                print("command completed", file=sys.stderr)
        finally:
            heartbeat_task.cancel()


def cmd_run(args: argparse.Namespace) -> None:
    asyncio.run(_run(args))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    enroll_parser = subparsers.add_parser("enroll", help="consume a single-use enrollment token")
    enroll_parser.add_argument("--control-plane", required=True, help="e.g. http://localhost:8000")
    enroll_parser.add_argument("--token", required=True)
    enroll_parser.set_defaults(func=cmd_enroll)

    run_parser = subparsers.add_parser("run", help="connect and respond to commands")
    run_parser.add_argument(
        "--control-plane", required=True, help="e.g. ws://localhost:8000/ws/agent"
    )
    run_parser.add_argument("--credential", required=True)
    run_parser.add_argument("--os", default="linux", choices=["linux", "windows"])
    run_parser.add_argument("--heartbeat-interval", type=float, default=15.0)
    run_parser.set_defaults(func=cmd_run)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

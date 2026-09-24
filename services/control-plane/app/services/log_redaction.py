"""Redacts secrets and credentials out of log lines before they ever reach
an API response or the dashboard — see docs/metrics-and-logs.md.

Two layers, both applied to every line returned by log_service:
1. Known-value redaction: every secret value currently stored for the
   application (SecretRecord.encrypted_value — plaintext today, see
   secret_service's own docstring) is replaced outright if it appears
   verbatim in a line.
2. Pattern redaction: common "key=value"/"key: value" credential shapes are
   masked even when the value isn't one Healer already knows about (a
   stray database password in a traceback, an API key logged by the
   application itself).

Deliberately done here (Control Plane, Python) rather than on the Agent: one
implementation to test and update, reused for every log source, rather than
duplicating pattern logic in Go. The read path (Agent -> Control Plane ->
dashboard) is already an authenticated, internal boundary.
"""

import re

_KEY_VALUE_PATTERN = re.compile(
    r"""(?ix)
    (
        (?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|
           auth|credential|client[_-]?secret)
        \s*[:=]\s*
        ["']?
    )
    ([^\s"'&,;]+)
    """
)

_BEARER_PATTERN = re.compile(r"(?i)(bearer\s+)([A-Za-z0-9\-._~+/]+=*)")

_CONNECTION_STRING_PATTERN = re.compile(r"(://[^:/@\s]+:)([^@\s]+)(@)")

_REDACTED = "[REDACTED]"


def _mask_key_value(match: re.Match) -> str:
    return f"{match.group(1)}{_REDACTED}"


def _mask_bearer(match: re.Match) -> str:
    return f"{match.group(1)}{_REDACTED}"


def _mask_connection_string(match: re.Match) -> str:
    return f"{match.group(1)}{_REDACTED}{match.group(3)}"


def redact_line(line: str, known_secret_values: list[str] | None = None) -> str:
    redacted = line
    for value in known_secret_values or []:
        if value:
            redacted = redacted.replace(value, _REDACTED)
    redacted = _CONNECTION_STRING_PATTERN.sub(_mask_connection_string, redacted)
    redacted = _BEARER_PATTERN.sub(_mask_bearer, redacted)
    redacted = _KEY_VALUE_PATTERN.sub(_mask_key_value, redacted)
    return redacted


def redact_lines(lines: list[str], known_secret_values: list[str] | None = None) -> list[str]:
    return [redact_line(line, known_secret_values) for line in lines]

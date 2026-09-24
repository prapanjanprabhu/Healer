from app.services.log_redaction import redact_line, redact_lines


def test_redacts_key_value_password():
    line = 'DEBUG settings: password="hunter2" loaded'
    redacted = redact_line(line)
    assert "hunter2" not in redacted
    assert "[REDACTED]" in redacted


def test_redacts_bearer_token():
    line = "Authorization: Bearer abc123.def456-XYZ"
    redacted = redact_line(line)
    assert "abc123.def456-XYZ" not in redacted
    assert "Bearer" in redacted
    assert "[REDACTED]" in redacted


def test_redacts_connection_string_password():
    line = "connecting to postgresql://healer:changeme@postgres:5432/healer"
    redacted = redact_line(line)
    assert "changeme" not in redacted
    assert "healer:[REDACTED]@postgres" in redacted


def test_redacts_known_secret_value_verbatim():
    line = "calling upstream with key=sk-live-abcdefg1234567"
    redacted = redact_line(line, known_secret_values=["sk-live-abcdefg1234567"])
    assert "sk-live-abcdefg1234567" not in redacted


def test_leaves_ordinary_log_lines_untouched():
    line = "2026-09-24 10:00:00 INFO GET /health/ 200"
    assert redact_line(line) == line


def test_redact_lines_applies_to_every_line():
    lines = ["password=secret1", "no secrets here", "token: secret2"]
    redacted = redact_lines(lines)
    assert all("secret1" not in r and "secret2" not in r for r in redacted)
    assert redacted[1] == "no secrets here"

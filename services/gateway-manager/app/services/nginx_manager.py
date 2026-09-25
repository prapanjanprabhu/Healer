"""Renders and activates one application's Nginx server block inside the
dedicated Healer-managed directory, then validates and reloads the single
central Nginx installation this service is colocated with.

This module is the only code in Healer that ever writes to the Nginx
managed directory or invokes the nginx binary — and only ever with a fixed
argument list (never a shell string), only ever inside
`settings.nginx_managed_dir`, and only ever the two operations `nginx -t`
and `nginx -s reload` (see docs/security-boundaries.md). It never receives
or writes raw Nginx config text from the Control Plane — only structured
app_slug/domains/upstreams fields, which it renders itself from a fixed
template.
"""

import os
import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.core.config import settings

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)
_TEMPLATE = _env.get_template("app.conf.j2")

# Mirrors the Application.slug shape the Control Plane already guarantees
# (services/control-plane/app/services/application_service.py:_slugify) —
# checked again here since this is the boundary that turns a slug into a
# filesystem path and an Nginx upstream name.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


class InvalidAppSlug(ValueError):
    pass


# FastAPI runs sync routes (like /reload) in a threadpool, so two concurrent
# requests for two different apps genuinely run apply() concurrently in
# separate threads. Without this, `nginx -s reload` re-reads the *whole*
# managed directory, so app A's validated-and-about-to-reload config could
# pick up app B's just-written, not-yet-validated file — or the reverse:
# app A's successful validate+reload could be invalidated by app B's write
# landing in between. Serializing the whole validate-then-reload sequence
# makes each apply() atomic with respect to the others.
_apply_lock = threading.Lock()


@dataclass
class ReloadOutcome:
    ok: bool
    message: str


def _managed_dir() -> Path:
    return Path(settings.nginx_managed_dir)


def _managed_path(app_slug: str) -> Path:
    if not _SLUG_RE.match(app_slug):
        raise InvalidAppSlug(f"invalid app_slug {app_slug!r}")
    managed_dir = _managed_dir().resolve()
    path = (managed_dir / f"{app_slug}.conf").resolve()
    if path.parent != managed_dir:
        raise InvalidAppSlug("resolved path escapes the managed directory")
    return path


def render(app_slug: str, domains: list[dict], upstreams: list[dict]) -> str | None:
    """None means "no config for this app" — no domain or no healthy
    upstream — and the caller removes the managed file instead of writing
    one, taking the application out of routing rather than emitting a
    broken (e.g. empty) upstream block.
    """
    if not domains or not upstreams:
        return None
    upstream_name = f"healer_{app_slug.replace('-', '_')}"
    return _TEMPLATE.render(upstream_name=upstream_name, domains=domains, upstreams=upstreams)


def _write_or_remove(path: Path, content: str | None) -> None:
    if content is None:
        path.unlink(missing_ok=True)
        return
    tmp_path = path.parent / f"{path.name}.tmp"
    tmp_path.write_text(content)
    os.replace(tmp_path, path)


def _run_nginx(*args: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            [settings.nginx_binary, *args],
            capture_output=True,
            text=True,
            timeout=settings.nginx_reload_timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def validate() -> tuple[bool, str]:
    return _run_nginx("-t")


def reload_nginx() -> tuple[bool, str]:
    return _run_nginx("-s", "reload")


def apply(app_slug: str, domains: list[dict], upstreams: list[dict]) -> ReloadOutcome:
    """Atomically activate (or remove) one application's managed config:
    write the new state, validate the *whole* Nginx config with `nginx -t`,
    and only reload if that passes. Any failure — validation or reload —
    restores exactly the bytes that were on disk before this call, so one
    application's bad config can never replace another application's (or
    its own last) working configuration.
    """
    with _apply_lock:
        path = _managed_path(app_slug)
        existed_before = path.exists()
        previous_content = path.read_text() if existed_before else None

        new_content = render(app_slug, domains, upstreams)
        _write_or_remove(path, new_content)

        ok, detail = validate()
        if not ok:
            _write_or_remove(path, previous_content if existed_before else None)
            return ReloadOutcome(
                ok=False,
                message=f"nginx -t rejected the new configuration, restored the previous one: {detail}",
            )

        reload_ok, reload_detail = reload_nginx()
        if not reload_ok:
            _write_or_remove(path, previous_content if existed_before else None)
            validate()  # best-effort: keep the on-disk config in sync with what's actually loaded
            return ReloadOutcome(
                ok=False,
                message=f"nginx -s reload failed, restored the previous configuration: {reload_detail}",
            )

        if new_content is None:
            return ReloadOutcome(ok=True, message="no active domain/healthy upstream — routing removed")
        return ReloadOutcome(ok=True, message="activated and reloaded")

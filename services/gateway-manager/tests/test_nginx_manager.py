import shutil
import uuid
from pathlib import Path

import pytest

from app.core.config import settings
from app.services import nginx_manager
from app.services.nginx_manager import InvalidAppSlug


def _domain(hostname: str = "erp.ritrjpm.edu.in") -> list[dict]:
    return [{"hostname": hostname, "cert_path": "/etc/healer/certs/a.crt", "key_path": "/etc/healer/certs/a.key"}]


def _upstream(host: str = "10.0.0.5", port: int = 9034) -> list[dict]:
    return [{"host": host, "port": port}]


@pytest.fixture()
def managed_dir(tmp_path, monkeypatch) -> Path:
    managed = tmp_path / "healer"
    managed.mkdir()
    monkeypatch.setattr(settings, "nginx_managed_dir", str(managed))
    return managed


# --- render (pure, no filesystem/subprocess) --------------------------------------


def test_render_returns_none_without_a_domain_or_without_a_healthy_upstream():
    assert nginx_manager.render("acme", [], _upstream()) is None
    assert nginx_manager.render("acme", _domain(), []) is None
    assert nginx_manager.render("acme", [], []) is None


def test_render_produces_a_least_conn_upstream_and_matching_ssl_server_blocks():
    content = nginx_manager.render("acme-app", _domain(), _upstream())

    assert "upstream healer_acme_app {" in content
    assert "least_conn;" in content
    assert "server 10.0.0.5:9034;" in content
    assert "keepalive 32;" in content
    assert "server_name erp.ritrjpm.edu.in;" in content
    assert "ssl_certificate     /etc/healer/certs/a.crt;" in content
    assert "ssl_certificate_key /etc/healer/certs/a.key;" in content
    assert "proxy_pass http://healer_acme_app;" in content
    assert "return 301 https://$host$request_uri;" in content


def test_render_is_deterministic_for_the_same_input():
    first = nginx_manager.render("acme", _domain(), _upstream())
    second = nginx_manager.render("acme", _domain(), _upstream())
    assert first == second


# --- apply: slug/path safety -------------------------------------------------------


@pytest.mark.parametrize("bad_slug", ["../evil", "Has Spaces", "UPPER", "-leading-dash", "", "a" * 100])
def test_apply_rejects_slugs_that_are_not_a_safe_filesystem_name(bad_slug, managed_dir):
    with pytest.raises(InvalidAppSlug):
        nginx_manager.apply(bad_slug, _domain(), _upstream())


# --- apply: atomic activation and restore-on-failure (mocked nginx binary) --------


def test_apply_writes_and_reports_success_when_nginx_accepts_it(monkeypatch, managed_dir):
    monkeypatch.setattr(nginx_manager, "validate", lambda: (True, "syntax is ok"))
    monkeypatch.setattr(nginx_manager, "reload_nginx", lambda: (True, "signal process started"))

    outcome = nginx_manager.apply("acme", _domain(), _upstream())

    assert outcome.ok is True
    assert (managed_dir / "acme.conf").read_text().count("least_conn;") == 1
    assert not (managed_dir / "acme.conf.tmp").exists(), "the atomic temp file must never be left behind"


def test_apply_never_touches_another_applications_managed_file(monkeypatch, managed_dir):
    (managed_dir / "other-app.conf").write_text("# other app's working config\n")
    monkeypatch.setattr(nginx_manager, "validate", lambda: (True, "syntax is ok"))
    monkeypatch.setattr(nginx_manager, "reload_nginx", lambda: (True, ""))

    nginx_manager.apply("acme", _domain(), _upstream())

    assert (managed_dir / "other-app.conf").read_text() == "# other app's working config\n"


def test_apply_restores_the_previous_file_when_nginx_t_rejects_the_new_config(monkeypatch, managed_dir):
    """The exact scenario the phase spec asks for a test to prove: an invalid
    generated configuration must never replace the working configuration.
    """
    path = managed_dir / "acme.conf"
    path.write_text("# previous known-good config\n")
    reload_calls = []

    monkeypatch.setattr(
        nginx_manager, "validate", lambda: (False, 'unexpected "}" in acme.conf, line 4')
    )
    monkeypatch.setattr(nginx_manager, "reload_nginx", lambda: reload_calls.append(1) or (True, ""))

    outcome = nginx_manager.apply("acme", _domain(), _upstream())

    assert outcome.ok is False
    assert "restored the previous" in outcome.message
    assert path.read_text() == "# previous known-good config\n"
    assert reload_calls == [], "must never reload after nginx -t already rejected the config"


def test_apply_removes_a_brand_new_file_when_nginx_t_rejects_it_and_nothing_existed_before(
    monkeypatch, managed_dir
):
    path = managed_dir / "acme.conf"
    assert not path.exists()
    monkeypatch.setattr(nginx_manager, "validate", lambda: (False, "syntax error"))
    monkeypatch.setattr(nginx_manager, "reload_nginx", lambda: (True, ""))

    outcome = nginx_manager.apply("acme", _domain(), _upstream())

    assert outcome.ok is False
    assert not path.exists()


def test_apply_restores_the_previous_file_when_reload_fails(monkeypatch, managed_dir):
    path = managed_dir / "acme.conf"
    path.write_text("# previous known-good config\n")
    monkeypatch.setattr(nginx_manager, "validate", lambda: (True, "syntax is ok"))
    monkeypatch.setattr(nginx_manager, "reload_nginx", lambda: (False, "no such process"))

    outcome = nginx_manager.apply("acme", _domain(), _upstream())

    assert outcome.ok is False
    assert "restored the previous" in outcome.message
    assert path.read_text() == "# previous known-good config\n"


def test_apply_removes_a_previously_active_file_once_no_healthy_upstream_remains(monkeypatch, managed_dir):
    path = managed_dir / "acme.conf"
    path.write_text("# previously active\n")
    monkeypatch.setattr(nginx_manager, "validate", lambda: (True, "syntax is ok"))
    monkeypatch.setattr(nginx_manager, "reload_nginx", lambda: (True, ""))

    outcome = nginx_manager.apply("acme", _domain(), [])

    assert outcome.ok is True
    assert not path.exists()


# --- apply against a real nginx binary, when one is actually present --------------


def test_apply_against_a_real_nginx_rejects_a_missing_certificate_and_restores():
    """Runs the real `nginx -t` subprocess call (never `-s reload`, since
    validation fails first) against the real central Nginx this service
    would otherwise manage — skipped wherever no real nginx/managed
    directory is present (e.g. the plain host Python environment).
    """
    if shutil.which(settings.nginx_binary) is None:
        pytest.skip("requires a real nginx binary")
    managed_dir = Path(settings.nginx_managed_dir)
    if not managed_dir.is_dir():
        pytest.skip(f"managed directory {managed_dir} is not present in this environment")

    slug = f"selftest-{uuid.uuid4().hex[:8]}"
    path = managed_dir / f"{slug}.conf"
    assert not path.exists()
    try:
        outcome = nginx_manager.apply(
            slug,
            [{"hostname": f"{slug}.healer.test", "cert_path": "/nonexistent/a.crt", "key_path": "/nonexistent/a.key"}],
            [{"host": "127.0.0.1", "port": 65500}],
        )
        assert outcome.ok is False
        assert "restored" in outcome.message
        assert not path.exists()
    finally:
        path.unlink(missing_ok=True)

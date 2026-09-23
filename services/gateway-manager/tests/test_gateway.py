from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import nginx_manager
from app.services.nginx_manager import ReloadOutcome

client = TestClient(app)
AUTH_HEADERS = {"X-Gateway-Secret": settings.gateway_manager_shared_secret}


def _payload(**overrides) -> dict:
    payload = {
        "app_slug": "acme-erp",
        "domains": [
            {
                "hostname": "erp.ritrjpm.edu.in",
                "cert_path": "/etc/healer/certs/ritrjpm.edu.in.crt",
                "key_path": "/etc/healer/certs/ritrjpm.edu.in.key",
            }
        ],
        "upstreams": [{"host": "127.0.0.1", "port": 9034}],
    }
    payload.update(overrides)
    return payload


def test_reload_requires_a_well_formed_payload() -> None:
    response = client.post("/reload", json={}, headers=AUTH_HEADERS)
    assert response.status_code == 422


def test_reload_rejects_a_port_out_of_range() -> None:
    response = client.post(
        "/reload", json=_payload(upstreams=[{"host": "127.0.0.1", "port": 70000}]), headers=AUTH_HEADERS
    )
    assert response.status_code == 422


def test_reload_passes_the_structured_fields_through_to_nginx_manager(monkeypatch) -> None:
    captured = {}

    def fake_apply(app_slug, domains, upstreams):
        captured["app_slug"] = app_slug
        captured["domains"] = domains
        captured["upstreams"] = upstreams
        return ReloadOutcome(ok=True, message="activated and reloaded")

    monkeypatch.setattr(nginx_manager, "apply", fake_apply)

    response = client.post("/reload", json=_payload(), headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json() == {"ok": True, "message": "activated and reloaded"}
    assert captured["app_slug"] == "acme-erp"
    assert captured["domains"] == [
        {
            "hostname": "erp.ritrjpm.edu.in",
            "cert_path": "/etc/healer/certs/ritrjpm.edu.in.crt",
            "key_path": "/etc/healer/certs/ritrjpm.edu.in.key",
        }
    ]
    assert captured["upstreams"] == [{"host": "127.0.0.1", "port": 9034}]


def test_reload_reports_a_failed_activation_without_raising(monkeypatch) -> None:
    monkeypatch.setattr(
        nginx_manager,
        "apply",
        lambda *a: ReloadOutcome(ok=False, message="nginx -t rejected the new configuration"),
    )

    response = client.post("/reload", json=_payload(), headers=AUTH_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "rejected" in body["message"]


def test_reload_rejects_an_invalid_app_slug_as_a_bad_request() -> None:
    response = client.post("/reload", json=_payload(app_slug="../etc"), headers=AUTH_HEADERS)
    assert response.status_code == 400

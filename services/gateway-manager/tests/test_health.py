from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)
AUTH_HEADERS = {"X-Gateway-Secret": settings.gateway_manager_shared_secret}


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_reload_requires_the_shared_secret() -> None:
    response = client.post("/reload", json={"app_slug": "acme"})
    assert response.status_code == 401

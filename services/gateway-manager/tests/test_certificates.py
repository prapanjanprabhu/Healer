import datetime
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)
AUTH_HEADERS = {"X-Gateway-Secret": settings.gateway_manager_shared_secret}


def _write_self_signed_pair(tmp_path: Path, *, common_name: str, days_valid: int, key: rsa.RSAPrivateKey | None = None):
    key = key or rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.UTC)
    not_before = now - datetime.timedelta(days=max(1, -days_valid + 1))
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(now + datetime.timedelta(days=days_valid))
        .sign(key, hashes.SHA256())
    )

    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return str(cert_path), str(key_path)


def test_validate_requires_shared_secret(tmp_path):
    cert_path, key_path = _write_self_signed_pair(tmp_path, common_name="example.test", days_valid=365)
    response = client.post("/certificates/validate", json={"cert_path": cert_path, "key_path": key_path})
    assert response.status_code == 401


def test_valid_matching_pair_passes(tmp_path):
    cert_path, key_path = _write_self_signed_pair(tmp_path, common_name="erp.ritrjpm.edu.in", days_valid=365)
    response = client.post(
        "/certificates/validate", json={"cert_path": cert_path, "key_path": key_path}, headers=AUTH_HEADERS
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "erp.ritrjpm.edu.in" in body["subject"]
    names = {c["name"]: c["passed"] for c in body["checks"]}
    assert names["key_matches_cert"] is True


def test_mismatched_key_is_rejected(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    cert_path, _unused_key = _write_self_signed_pair(tmp_path / "a", common_name="a.test", days_valid=365)
    _unused_cert, key_path = _write_self_signed_pair(tmp_path / "b", common_name="b.test", days_valid=365)

    response = client.post(
        "/certificates/validate", json={"cert_path": cert_path, "key_path": key_path}, headers=AUTH_HEADERS
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    names = {c["name"]: c["passed"] for c in body["checks"]}
    assert names["key_matches_cert"] is False


def test_expired_certificate_is_flagged(tmp_path):
    cert_path, key_path = _write_self_signed_pair(tmp_path, common_name="expired.test", days_valid=-30)
    response = client.post(
        "/certificates/validate", json={"cert_path": cert_path, "key_path": key_path}, headers=AUTH_HEADERS
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    names = {c["name"]: c["passed"] for c in body["checks"]}
    assert names["expired"] is False


def test_missing_files_are_rejected(tmp_path):
    response = client.post(
        "/certificates/validate",
        json={"cert_path": str(tmp_path / "nope.crt"), "key_path": str(tmp_path / "nope.key")},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    names = {c["name"]: c["passed"] for c in body["checks"]}
    assert names["cert_path"] is False
    assert names["key_path"] is False

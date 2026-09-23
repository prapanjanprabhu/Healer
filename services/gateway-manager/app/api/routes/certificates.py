"""Existing CRT/KEY filesystem path validation — read-only introspection
only. This service never generates, uploads, or stores certificate
material; it only reads paths an administrator already put on disk and
reports back readable/matching/expiry facts. See docs/app-validation.md.
"""

import os
from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.auth import require_shared_secret

router = APIRouter(prefix="/certificates", tags=["certificates"], dependencies=[Depends(require_shared_secret)])

EXPIRY_WARNING_WINDOW = timedelta(days=30)


class CertificateValidateRequest(BaseModel):
    cert_path: str
    key_path: str


class CheckResult(BaseModel):
    name: str
    severity: str  # error | warning | info
    passed: bool
    message: str


class CertificateValidateResponse(BaseModel):
    ok: bool
    checks: list[CheckResult]
    subject: str | None = None
    issuer: str | None = None
    not_valid_before: str | None = None
    not_valid_after: str | None = None


def _readable_file_check(name: str, path: str) -> CheckResult:
    if not os.path.isfile(path):
        return CheckResult(name=name, severity="error", passed=False, message=f"{path} does not exist")
    if not os.access(path, os.R_OK):
        return CheckResult(name=name, severity="error", passed=False, message=f"{path} is not readable")
    return CheckResult(name=name, severity="info", passed=True, message=f"{path} exists and is readable")


def _load_certificate(path: str) -> tuple[x509.Certificate | None, CheckResult]:
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as exc:
        return None, CheckResult(name="cert_path", severity="error", passed=False, message=str(exc))
    try:
        cert = x509.load_pem_x509_certificate(data)
    except ValueError:
        try:
            cert = x509.load_der_x509_certificate(data)
        except ValueError:
            return None, CheckResult(
                name="cert_path", severity="error", passed=False,
                message="could not parse as a PEM or DER X.509 certificate",
            )
    return cert, CheckResult(name="cert_parse", severity="info", passed=True, message="certificate parsed")


def _load_private_key(path: str):
    with open(path, "rb") as f:
        data = f.read()
    try:
        return serialization.load_pem_private_key(data, password=None), None
    except TypeError:
        return None, CheckResult(
            name="key_path",
            severity="error",
            passed=False,
            message=(
                "the key file is password-protected — Healer only supports "
                "unencrypted key files"
            ),
        )
    except ValueError:
        try:
            return serialization.load_der_private_key(data, password=None), None
        except (ValueError, TypeError):
            return None, CheckResult(
                name="key_path", severity="error", passed=False,
                message="could not parse as a PEM or DER private key",
            )


def _public_key_bytes(public_key) -> bytes:
    return public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


@router.post("/validate", response_model=CertificateValidateResponse)
def validate_certificate(payload: CertificateValidateRequest) -> CertificateValidateResponse:
    checks: list[CheckResult] = []

    cert_readable = _readable_file_check("cert_path", payload.cert_path)
    key_readable = _readable_file_check("key_path", payload.key_path)
    checks += [cert_readable, key_readable]

    if not cert_readable.passed or not key_readable.passed:
        return CertificateValidateResponse(ok=False, checks=checks)

    cert, cert_check = _load_certificate(payload.cert_path)
    checks.append(cert_check)
    if cert is None:
        return CertificateValidateResponse(ok=False, checks=checks)

    private_key, key_error = _load_private_key(payload.key_path)
    if key_error is not None:
        checks.append(key_error)
        return CertificateValidateResponse(ok=False, checks=checks)
    checks.append(CheckResult(name="key_parse", severity="info", passed=True, message="key parsed"))

    try:
        matches = _public_key_bytes(cert.public_key()) == _public_key_bytes(private_key.public_key())
    except Exception:  # noqa: BLE001 - any mismatch in key type/shape means "doesn't match"
        matches = False
    checks.append(
        CheckResult(
            name="key_matches_cert",
            severity="error",
            passed=matches,
            message="the key matches the certificate's public key" if matches
            else "this key does NOT match the certificate — they are not a pair",
        )
    )

    now = datetime.now(UTC)
    not_before = cert.not_valid_before_utc
    not_after = cert.not_valid_after_utc

    if now < not_before:
        checks.append(
            CheckResult(
                name="not_yet_valid", severity="warning", passed=False,
                message=f"certificate is not valid until {not_before.isoformat()}",
            )
        )
    if now > not_after:
        checks.append(
            CheckResult(
                name="expired", severity="error", passed=False,
                message=f"certificate expired on {not_after.isoformat()}",
            )
        )
    elif not_after - now < EXPIRY_WARNING_WINDOW:
        checks.append(
            CheckResult(
                name="expiring_soon", severity="warning", passed=False,
                message=f"certificate expires soon, on {not_after.isoformat()}",
            )
        )

    # SHA-256 fingerprint is informational only — never used as a security
    # decision here, just handy for an administrator to eyeball.
    fingerprint = cert.fingerprint(hashes.SHA256()).hex()
    checks.append(
        CheckResult(name="fingerprint", severity="info", passed=True, message=f"sha256:{fingerprint}")
    )

    ok = all(c.passed or c.severity != "error" for c in checks)
    return CertificateValidateResponse(
        ok=ok,
        checks=checks,
        subject=cert.subject.rfc4514_string(),
        issuer=cert.issuer.rfc4514_string(),
        not_valid_before=not_before.isoformat(),
        not_valid_after=not_after.isoformat(),
    )

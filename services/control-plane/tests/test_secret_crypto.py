import pytest

from app.core import secret_crypto
from app.core.secret_crypto import SecretDecryptionError, decrypt_secret, encrypt_secret


def test_encrypt_then_decrypt_round_trips():
    token = encrypt_secret("hunter2")
    assert token != "hunter2"
    assert decrypt_secret(token) == "hunter2"


def test_encrypted_token_is_not_the_plaintext_value_anywhere_in_it():
    token = encrypt_secret("a-very-distinctive-marker-value")
    assert "a-very-distinctive-marker-value" not in token


def test_decrypt_rejects_a_token_encrypted_with_a_different_key(monkeypatch):
    token = encrypt_secret("hunter2")
    monkeypatch.setattr(secret_crypto.settings, "secret_encryption_key", "a-totally-different-key")
    with pytest.raises(SecretDecryptionError):
        decrypt_secret(token)


def test_decrypt_rejects_garbage_input():
    with pytest.raises(SecretDecryptionError):
        decrypt_secret("not-a-real-fernet-token")

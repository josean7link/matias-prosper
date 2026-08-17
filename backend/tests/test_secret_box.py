"""Tests for services/secret_box.py (Fase 0.5)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def _integrations_key(monkeypatch):
    monkeypatch.setenv("INTEGRATIONS_FERNET_KEY",
                        Fernet.generate_key().decode())
    from services import secret_box
    # Ensure the module reads the freshly-set env each test.
    yield


def test_roundtrip():
    from services.secret_box import encrypt, decrypt
    blob = encrypt("live_sk_ABCDEFGHIJ")
    assert isinstance(blob, (bytes, bytearray))
    assert decrypt(blob) == "live_sk_ABCDEFGHIJ"


def test_last4_masks_middle():
    from services.secret_box import last4
    assert last4("live_sk_ABCDEFGH") == "•••• EFGH"
    assert last4("xy") == "••••"
    assert last4("") == "••••"


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("INTEGRATIONS_FERNET_KEY", raising=False)
    from services.secret_box import encrypt, SecretBoxError
    with pytest.raises(SecretBoxError):
        encrypt("something")


def test_wrong_key_raises_no_secret_in_message(monkeypatch):
    from services.secret_box import encrypt, decrypt, SecretBoxError
    blob = encrypt("hunter2")
    # Rotate to a different key
    monkeypatch.setenv("INTEGRATIONS_FERNET_KEY",
                        Fernet.generate_key().decode())
    with pytest.raises(SecretBoxError) as e:
        decrypt(blob)
    assert "hunter2" not in str(e.value)


def test_encrypt_rejects_non_str():
    from services.secret_box import encrypt, SecretBoxError
    with pytest.raises(SecretBoxError):
        encrypt(b"bytes not allowed")


# ---------------------------------------------------------------------------
# Dual-key rotation (Fase 0.5.1 — consolidated from client_profile.py)
# ---------------------------------------------------------------------------
def test_previous_key_opens_old_ciphertext(monkeypatch):
    from services.secret_box import encrypt, decrypt
    old_key = os.environ["INTEGRATIONS_FERNET_KEY"]
    blob = encrypt("live_sk_OLD")
    # Rotate: new current, old becomes previous.
    monkeypatch.setenv("INTEGRATIONS_FERNET_KEY",
                        Fernet.generate_key().decode())
    monkeypatch.setenv("INTEGRATIONS_FERNET_KEY_PREVIOUS", old_key)
    assert decrypt(blob) == "live_sk_OLD"


def test_encrypt_always_uses_current_key(monkeypatch):
    from services.secret_box import encrypt
    old_key = os.environ["INTEGRATIONS_FERNET_KEY"]
    new_key = Fernet.generate_key().decode()
    monkeypatch.setenv("INTEGRATIONS_FERNET_KEY", new_key)
    monkeypatch.setenv("INTEGRATIONS_FERNET_KEY_PREVIOUS", old_key)
    blob = encrypt("fresh_value")
    # Must decrypt with the NEW key directly (never written w/ previous).
    assert Fernet(new_key.encode()).decrypt(bytes(blob)).decode() \
        == "fresh_value"


def test_secretbox_generic_env_pair(monkeypatch):
    """SecretBox works with any (current, previous) env-var pair — the
    MFA pair here, exactly as routes/client_profile.py consumes it."""
    from services.secret_box import SecretBox, SecretBoxError
    key_a = Fernet.generate_key().decode()
    key_b = Fernet.generate_key().decode()
    monkeypatch.setenv("MFA_FERNET_KEY", key_a)
    monkeypatch.delenv("MFA_FERNET_KEY_PREVIOUS", raising=False)
    box = SecretBox("MFA_FERNET_KEY", "MFA_FERNET_KEY_PREVIOUS")
    token = box.encrypt("JBSWY3DPEHPK3PXP")
    assert isinstance(token, str)
    assert box.decrypt(token) == "JBSWY3DPEHPK3PXP"
    # Rotate: mfa_pending ciphertexts written pre-rotation must still open.
    monkeypatch.setenv("MFA_FERNET_KEY", key_b)
    monkeypatch.setenv("MFA_FERNET_KEY_PREVIOUS", key_a)
    assert box.decrypt(token) == "JBSWY3DPEHPK3PXP"
    # Without the previous key, the old ciphertext must NOT open.
    monkeypatch.delenv("MFA_FERNET_KEY_PREVIOUS")
    with pytest.raises(SecretBoxError):
        box.decrypt(token)


def test_secretbox_missing_current_names_the_variable(monkeypatch):
    from services.secret_box import SecretBox, SecretBoxError
    monkeypatch.delenv("SOME_MISSING_KEY", raising=False)
    box = SecretBox("SOME_MISSING_KEY")
    with pytest.raises(SecretBoxError) as e:
        box.encrypt("x")
    assert "SOME_MISSING_KEY" in str(e.value)

"""Encryption-at-rest for secrets, with dual-key rotation (Fase 0.5.1).

Single home for Fernet handling. Two key *pairs* exist today, each an
independent blast-radius:

  * ``MFA_FERNET_KEY`` / ``MFA_FERNET_KEY_PREVIOUS`` — TOTP secrets
    (consumed by ``routes/client_profile.py``).
  * ``INTEGRATIONS_FERNET_KEY`` / ``INTEGRATIONS_FERNET_KEY_PREVIOUS`` —
    third-party provider credentials (Sumsub, Resend, S3, …).

Dual-key rotation contract (moved here from client_profile.py):
  * ``encrypt()`` ALWAYS writes with the current key.
  * ``decrypt()`` tries the current key first, then the previous key.
    Callers never learn which key opened the ciphertext — the
    re-encryption sweep is what actually rotates stored payloads.
  * When the sweep is confirmed complete, the operator removes the
    ``*_PREVIOUS`` variable from the environment.

Keys are read from the process environment at call time (never cached),
so a rotation only needs a process restart. ``INTEGRATIONS_FERNET_KEY``
is intentionally NOT written to any file in this repo — see
``docs/INTEGRATIONS_FERNET_KEY.md`` for how it is injected per
environment. If it is missing, the first encrypt/decrypt fails with a
``SecretBoxError`` naming the variable (the backend still boots).

Usage:
    from services.secret_box import SecretBox, encrypt, decrypt, last4

    mfa_box = SecretBox("MFA_FERNET_KEY", "MFA_FERNET_KEY_PREVIOUS")
    token   = mfa_box.encrypt("JBSWY3DP...")     # str, safe to store
    secret  = mfa_box.decrypt(token)

    blob = encrypt("live_sk_...")   # integrations pair, bytes
    val  = decrypt(blob)
    ui   = last4("live_sk_ABCDEFGH")             # "•••• EFGH"
"""
from __future__ import annotations

import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


class SecretBoxError(RuntimeError):
    """Raised when a box is misconfigured or a ciphertext cannot be
    decrypted. Never carries plaintext or ciphertext in its message."""


class SecretBox:
    """A Fernet box bound to a (current, previous) env-var key pair."""

    def __init__(self, current_env: str,
                 previous_env: Optional[str] = None) -> None:
        self._current_env = current_env
        self._previous_env = previous_env

    def _load(self, name: str) -> Optional[Fernet]:
        raw = os.environ.get(name)
        if not raw:
            return None
        try:
            return Fernet(raw.encode() if isinstance(raw, str) else raw)
        except Exception as e:  # noqa: BLE001
            raise SecretBoxError(f"{name} is not a valid Fernet key: {e}")

    def _current(self) -> Fernet:
        cur = self._load(self._current_env)
        if cur is None:
            raise SecretBoxError(
                f"{self._current_env} not configured — refusing to store "
                "or read encrypted secrets in plaintext. Inject it via the "
                "process environment (see docs/INTEGRATIONS_FERNET_KEY.md).")
        return cur

    def encrypt(self, value: str) -> str:
        """Encrypt with the CURRENT key. Returns a str Fernet token."""
        if not isinstance(value, str):
            raise SecretBoxError("encrypt() expects str")
        return self._current().encrypt(value.encode()).decode()

    def decrypt(self, blob: bytes | str) -> str:
        """Try the current key first, fall back to the previous key."""
        token = blob.encode() if isinstance(blob, str) else bytes(blob)
        try:
            return self._current().decrypt(token).decode()
        except InvalidToken:
            pass
        if self._previous_env:
            prev = self._load(self._previous_env)
            if prev is not None:
                try:
                    return prev.decrypt(token).decode()
                except InvalidToken:
                    pass
        raise SecretBoxError(
            f"ciphertext did not decrypt with {self._current_env}"
            + (f" nor {self._previous_env}" if self._previous_env else "")
            + ".")


# ---------------------------------------------------------------------------
# Integrations pair — module-level API kept for existing callers.
# ---------------------------------------------------------------------------
_INTEGRATIONS_BOX = SecretBox("INTEGRATIONS_FERNET_KEY",
                              "INTEGRATIONS_FERNET_KEY_PREVIOUS")


def encrypt(value: str) -> bytes:
    """Encrypt a provider credential (integrations pair). Returns bytes."""
    return _INTEGRATIONS_BOX.encrypt(value).encode()


def decrypt(blob: bytes | str) -> str:
    """Decrypt a ciphertext produced by `encrypt` (integrations pair)."""
    return _INTEGRATIONS_BOX.decrypt(blob)


def last4(value: str) -> str:
    """UI-safe preview: `•••• EFGH`. Never returns the middle bytes.

    Empty/short values collapse to `••••` — never echo the full value.
    """
    if not value or len(value) < 4:
        return "••••"
    return f"•••• {value[-4:]}"

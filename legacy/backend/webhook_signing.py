"""HMAC-SHA256 signing for webhook deliveries."""
from __future__ import annotations
import hmac
import hashlib
import json
import secrets as _secrets
from typing import Any


def generate_secret() -> str:
    return "whsec_" + _secrets.token_urlsafe(32)


def sign(secret: str, payload: Any, timestamp: str) -> str:
    body = payload if isinstance(payload, str) else json.dumps(payload, sort_keys=True, separators=(",", ":"))
    signed = f"{timestamp}.{body}".encode()
    sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={sig}"


def verify(secret: str, header: str, payload: Any) -> bool:
    """For external partners to verify. Not used server-side."""
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        ts, sig = parts["t"], parts["v1"]
        expected = sign(secret, payload, ts).split(",v1=")[1]
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False

"""MFA TOTP helpers."""
from __future__ import annotations
import pyotp
import qrcode
import io
import base64
from typing import Tuple

ISSUER = "Prosper"


def generate_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(email: str, secret: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name=ISSUER)


def qr_png_base64(uri: str) -> str:
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def verify_code(secret: str, code: str) -> bool:
    if not code or not secret:
        return False
    return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)

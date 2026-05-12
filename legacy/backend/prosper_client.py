"""Proxy client for the real Prosper Stellar Protocol APIs.

Base URL and credentials come from env. If PROSPER_API_ENABLED is not set,
the proxy is disabled and all calls return a simulated response so the
backoffice still works end-to-end.
"""
from __future__ import annotations
import os
from typing import Any, Dict, Optional
import httpx

PROSPER_API_BASE = os.environ.get(
    "PROSPER_API_BASE",
    "http://lb-backend-develop-1915190402.us-west-2.elb.amazonaws.com/api",
)
PROSPER_API_USER = os.environ.get("PROSPER_API_USER", "prosperDevelop")
PROSPER_API_PASS = os.environ.get("PROSPER_API_PASS", "T3st1ng_Pr0sp3r*")
PROSPER_API_ENABLED = os.environ.get("PROSPER_API_ENABLED", "false").lower() == "true"

_jwt_cache: Dict[str, Any] = {"token": None}


async def _login() -> Optional[str]:
    if not PROSPER_API_ENABLED:
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(
                f"{PROSPER_API_BASE}/v1/Auth/Login",
                json={"correo": PROSPER_API_USER, "passwd": PROSPER_API_PASS},
            )
            if r.status_code == 200:
                data = r.json()
                token = data.get("jwt") or data.get("token")
                _jwt_cache["token"] = token
                return token
    except Exception:
        return None
    return None


async def _auth_headers() -> Dict[str, str]:
    if not _jwt_cache.get("token"):
        await _login()
    tok = _jwt_cache.get("token")
    return {"Authorization": f"Bearer {tok}"} if tok else {}


async def call(method: str, path: str, body: Optional[dict] = None) -> Dict[str, Any]:
    """Call the Prosper upstream API. Returns a normalised response dict.

    When PROSPER_API_ENABLED is False, returns a simulated response.
    """
    if not PROSPER_API_ENABLED:
        return {
            "proxied": False,
            "simulated": True,
            "note": "PROSPER_API_ENABLED=false – simulated response",
            "request": {"method": method, "path": path, "body": body},
        }
    headers = await _auth_headers()
    url = f"{PROSPER_API_BASE}{path}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as c:
            if method.upper() == "GET":
                r = await c.get(url, headers=headers)
            else:
                r = await c.request(method.upper(), url, json=body or {}, headers=headers)
            try:
                data = r.json()
            except Exception:
                data = {"raw": r.text}
            return {"proxied": True, "status": r.status_code, "data": data}
    except Exception as e:
        return {"proxied": True, "status": 0, "error": str(e)}

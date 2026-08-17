"""Fase 2.1 — Paridad de flags del módulo KYB.

`KYB_MODULE_ENABLED` (backend/.env) y `NEXT_PUBLIC_KYB_MODULE_ENABLED`
(frontend/.env) deben moverse SIEMPRE juntos. Mismo patrón de riesgo
que INTERNAL_ROLES (ver test_middleware_roles_parity.py):

  * backend on / frontend off → las APIs existen pero ningún usuario
    puede llegar a las pantallas (alta muerta, silencioso).
  * backend off / frontend on → las pantallas renderizan y cada submit
    falla con 404 (experiencia rota de cara al público).

Limitación declarada: no podemos leer el valor RUNTIME del frontend
(Next.js hornea NEXT_PUBLIC_* en el build y no lo expone a pytest).
La alternativa más cercana es comparar las dos fuentes de verdad en
disco — los archivos .env que alimentan a ambos procesos en este pod.
Si algún entorno inyecta los flags por otra vía (supervisor/deploy),
este test cubre el caso base y la matriz de combinaciones queda
documentada en docs/kyb/fase2_signup.md.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BACKEND_ENV = REPO / "backend" / ".env"
FRONTEND_ENV = REPO / "frontend" / ".env"


def _read_flag(path: Path, key: str) -> str:
    text = path.read_text()
    m = re.search(rf"^{re.escape(key)}=(.*)$", text, re.MULTILINE)
    assert m, f"{key} no está definido en {path} — debe existir SIEMPRE"
    return m.group(1).strip().strip('"').strip("'").lower()


def test_kyb_flags_move_together():
    be = _read_flag(BACKEND_ENV, "KYB_MODULE_ENABLED")
    fe = _read_flag(FRONTEND_ENV, "NEXT_PUBLIC_KYB_MODULE_ENABLED")
    assert be == fe, (
        f"Flags KYB desalineados: backend KYB_MODULE_ENABLED={be!r} vs "
        f"frontend NEXT_PUBLIC_KYB_MODULE_ENABLED={fe!r}. Se cambian "
        "SIEMPRE juntos — ver docs/kyb/fase2_signup.md.")


def test_kyb_flags_have_valid_values():
    for path, key in ((BACKEND_ENV, "KYB_MODULE_ENABLED"),
                      (FRONTEND_ENV, "NEXT_PUBLIC_KYB_MODULE_ENABLED")):
        val = _read_flag(path, key)
        assert val in ("true", "false"), \
            f"{key}={val!r} en {path} — solo se admite true/false"

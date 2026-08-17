"""Fase 0 (Aug 2026) — Role parity: frontend edge Set ↔ backend enum.

`frontend/src/middleware.ts` hardcodes `INTERNAL_ROLES` as a JS Set
literal because Edge runtime can't import Python. That literal MUST
match `backend/roles.py::INTERNAL_ROLES` — otherwise:

  * Roles present in frontend but not backend → the edge routes them
    to /admin, then every /admin API call returns 403.
  * Roles present in backend but not frontend → the edge redirects
    them away from /admin they are entitled to see.

Both fail modes are silent from the user's point of view.

This test parses the middleware source with a regex (there is no
Python-friendly TS parser we can rely on in-repo), extracts the set,
and compares it to the backend enum. Regex is intentionally strict:
if the shape of the file changes, the test breaks visibly rather than
silently accepting a new format.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roles import INTERNAL_ROLES as BE_INTERNAL_ROLES   # noqa: E402


MIDDLEWARE = (Path(__file__).resolve().parents[2]
               / "frontend" / "src" / "middleware.ts")

# Matches:
#   const INTERNAL_ROLES = new Set([
#     "super_admin", "admin", ...
#   ]);
_SET_RE = re.compile(
    r"const\s+INTERNAL_ROLES\s*=\s*new\s+Set\s*\(\s*\[(.*?)\]\s*\)\s*;",
    re.DOTALL)


def _parse_edge_set() -> set[str]:
    src = MIDDLEWARE.read_text()
    m = _SET_RE.search(src)
    assert m, (f"Could not locate `const INTERNAL_ROLES = new Set([...])` "
                f"in {MIDDLEWARE}. If the shape changed, update the regex "
                f"in this test.")
    body = m.group(1)
    return set(re.findall(r'"([^"]+)"', body))


def _backend_set() -> set[str]:
    return {r.value for r in BE_INTERNAL_ROLES}


def test_middleware_internal_roles_match_backend():
    edge = _parse_edge_set()
    backend = _backend_set()
    only_edge = edge - backend
    only_backend = backend - edge
    assert not only_edge and not only_backend, (
        f"INTERNAL_ROLES divergence between frontend edge and backend enum.\n"
        f"  Only in edge (leak candidate): {sorted(only_edge) or 'none'}\n"
        f"  Only in backend (blocked user): {sorted(only_backend) or 'none'}\n"
        f"Edit `frontend/src/middleware.ts` and `backend/roles.py` in the "
        f"same change.")

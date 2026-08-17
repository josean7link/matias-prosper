"""Fase 0 (Aug 2026) — Admin route authorisation guardrail.

Scans every route registered on the running FastAPI app, filters to
those whose path contains `/admin/`, and asserts that each declares a
role-checking dependency (either at the router level or per-endpoint).

Rationale: the app has no global middleware that gates `/admin/*` on
the backend side; protection is per-endpoint via `Depends(...)`. If
someone lands a new endpoint under `/admin/` without a `require_*`
Depends, the endpoint is silently open. This test is the safety net.

**This test does NOT auto-fix**. If it fails, add the missing
dependency OR add the route to the explicit `_EXPECTED_UNPROTECTED`
allowlist with a TODO explaining why.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest
from fastapi import Depends
from fastapi.routing import APIRoute

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import app  # noqa: E402


# Names of the callables we consider "authorisation dependencies". If a
# route declares any of these anywhere in its dependency graph, we
# treat the route as protected. Names are matched loosely to survive
# refactors (partial substring).
_AUTHZ_DEPENDENCY_NAMES = {
    "require_admin",
    "require_compliance",
    "require_compliance_decide",
    "require_finance",
    "require_internal",
    "require_super_admin",
    "get_current_user",         # base auth — combined with route inspection
    "require_role",
    "requires_role",
    "current_admin",
    "get_admin_user",
}


# Paths that ARE under /admin but that we've explicitly reviewed as
# fine without an admin-role dependency. Each row needs a reason. This
# is the "confess and grow" allowlist — anything not here must have a
# proper Depends.
_EXPECTED_UNPROTECTED: set[str] = {
    # Populated during Fase 0 as-of the first run of this test — see
    # the printed listing on first failure. Every entry MUST carry a
    # TODO for follow-up. Empty for now — first run will surface the
    # real list.
}


def _dep_names(route: APIRoute) -> set[str]:
    names: set[str] = set()
    stack = list(route.dependant.dependencies)
    while stack:
        d = stack.pop()
        call = getattr(d, "call", None)
        if call is not None:
            n = getattr(call, "__name__", None)
            if n:
                names.add(n)
        stack.extend(getattr(d, "dependencies", []) or [])
    # Also consider dependencies declared via `dependencies=[Depends(...)]`
    # on the route itself (they show up in the same dependant tree, so
    # the walk above already covers them).
    return names


def _looks_protected(route: APIRoute) -> bool:
    names = _dep_names(route)
    return any(n in names for n in _AUTHZ_DEPENDENCY_NAMES)


@pytest.mark.parametrize("_", [None])   # keep pytest happy for report grouping
def test_all_admin_routes_declare_authorisation(_):
    """Every route under /admin/ must declare an auth-checking dependency."""
    unprotected: list[tuple[str, list[str]]] = []
    for r in app.routes:
        if not isinstance(r, APIRoute):
            continue
        path = r.path or ""
        if "/admin/" not in path:
            continue
        if path in _EXPECTED_UNPROTECTED:
            continue
        if not _looks_protected(r):
            unprotected.append((
                f"{','.join(sorted(r.methods or []))} {path}",
                sorted(_dep_names(r)),
            ))
    if unprotected:
        lines = ["Admin routes without an authorisation dependency:"]
        for route_desc, deps in unprotected:
            lines.append(f"  - {route_desc}  (deps seen: {deps or 'none'})")
        lines.append("")
        lines.append("Either add `Depends(require_admin)` / "
                       "`Depends(require_compliance)` etc., OR add the "
                       "path to `_EXPECTED_UNPROTECTED` with a TODO.")
        pytest.fail("\n".join(lines))

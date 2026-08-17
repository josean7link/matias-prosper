"""Fase 7 — Motor de cálculo de riesgo KYB.

Diseño:
  * `default_model()` devuelve el shape del documento de riesgo que
    Compliance edita en /settings/risk-model. Solo se usa como semilla:
    no se auto-persiste.
  * `compute(case, model, *, hits=None, ubos=None)` devuelve
    `{score, level, factors, model_version, computed_at}` — puro, sin
    I/O, testeable. `factors` es el desglose por factor (para la UI y
    el PDF).
  * `preview_impact(model, cases)` recorre casos abiertos y cuenta
    cuántos cambiarían de nivel al aplicar el modelo nuevo.

Se compara contra el modelo con `active=true` (o el activo declarado
por el caller). El motor NUNCA escribe en `kyb_cases`; el endpoint de
recompute decide si persistir.

Contrato de factor:
  {"key": str, "label": str, "type": "boolean"|"choice"|"count"|"range",
   "weight": int, "params": {...opcional...}}

Tipos:
  - boolean: sum weight si el predicado es true
  - choice: mapa valor→weight; el peso base se ignora
  - count: sum(weight * n), tope opcional en params.max
  - range: weight si el valor cae en [min, max]

Umbrales (`thresholds`):
  {"low_max": int, "medium_max": int}
  score <= low_max        → low
  score <= medium_max     → medium
  score >  medium_max     → high
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from models import utc_now


def default_model() -> dict:
    return {
        "version": 1,
        "active": True,
        "factors": [
            {"key": "country_risk", "label": "País de constitución",
             "type": "choice", "weight": 0,
             "params": {"map": {"AR": 5, "UY": 5, "US": 5, "OTHER": 25}}},
            {"key": "is_pep", "label": "UBO / representante es PEP",
             "type": "boolean", "weight": 30},
            {"key": "blocking_hits", "label": "Hits bloqueantes activos",
             "type": "count", "weight": 20, "params": {"max": 3}},
            {"key": "active_hits", "label": "Hits activos totales",
             "type": "count", "weight": 5, "params": {"max": 5}},
            {"key": "recently_incorporated",
             "label": "Empresa recientemente constituida",
             "type": "boolean", "weight": 10},
            {"key": "high_risk_activity",
             "label": "Actividad de alto riesgo declarada",
             "type": "boolean", "weight": 15},
        ],
        "thresholds": {"low_max": 20, "medium_max": 60},
        "review_months": {"low": 24, "medium": 12, "high": 6},
    }


def _factor_score(fdef: dict, ctx: dict) -> tuple[int, Any]:
    """Devuelve (aporte, valor observado) para un factor. No lanza."""
    ftype = fdef.get("type")
    key = fdef["key"]
    weight = int(fdef.get("weight") or 0)
    params = fdef.get("params") or {}
    val = ctx.get(key)
    if ftype == "boolean":
        return (weight if bool(val) else 0), bool(val)
    if ftype == "choice":
        m = params.get("map") or {}
        # "OTHER" es fallback si no está mapeado.
        return int(m.get(val, m.get("OTHER", 0))), val
    if ftype == "count":
        n = int(val or 0)
        cap = int(params.get("max") or 0)
        if cap > 0:
            n = min(n, cap)
        return weight * n, int(val or 0)
    if ftype == "range":
        lo = params.get("min")
        hi = params.get("max")
        try:
            v = float(val)
        except (TypeError, ValueError):
            return 0, val
        in_range = ((lo is None or v >= lo) and (hi is None or v <= hi))
        return (weight if in_range else 0), val
    return 0, val


def compute(case: dict, model: dict, *,
            hits: Optional[List[dict]] = None,
            ubos: Optional[List[dict]] = None,
            profile: Optional[dict] = None) -> dict:
    """Cálculo puro. Ver docstring del módulo."""
    hits = hits or []
    ubos = ubos or []
    profile = profile or {}

    ctx = {
        "country_risk": case.get("country_of_incorporation") or "OTHER",
        "is_pep": any(bool(u.get("is_pep")) for u in ubos),
        "blocking_hits": sum(1 for h in hits
                             if h.get("is_blocking")
                             and not (h.get("resolution") or {}).get(
                                 "decision")),
        "active_hits": sum(1 for h in hits
                           if not (h.get("resolution") or {}).get("decision")
                           or (h.get("resolution") or {}).get("decision")
                           == "confirmed"),
        "recently_incorporated": bool(
            profile.get("recently_incorporated_declared")),
        "high_risk_activity": bool(
            (profile.get("funds_origin") or {}).get("type")
            == "CLIENT_FUNDS"),
    }

    breakdown = []
    total = 0
    for fdef in (model.get("factors") or []):
        aporte, obs = _factor_score(fdef, ctx)
        total += aporte
        breakdown.append({"key": fdef["key"], "label": fdef.get("label"),
                          "weight": fdef.get("weight"),
                          "observed": obs, "score": aporte})

    thr = model.get("thresholds") or {}
    low_max = int(thr.get("low_max", 20))
    med_max = int(thr.get("medium_max", 60))
    if total <= low_max:
        level = "low"
    elif total <= med_max:
        level = "medium"
    else:
        level = "high"

    return {
        "score": total,
        "level": level,
        "factors": breakdown,
        "model_version": int(model.get("version") or 1),
        "computed_at": utc_now(),
    }


def compare_levels(old_level: Optional[str], new_level: str) -> Optional[str]:
    """Devuelve None si no cambia; si cambia, la etiqueta 'old→new'."""
    if not old_level:
        return f"none→{new_level}"
    if old_level == new_level:
        return None
    return f"{old_level}→{new_level}"

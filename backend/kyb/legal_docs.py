"""Registro versionado de documentos legales del signup KYB (Fase 3).

La aceptación registra versión + hash del CONTENIDO vigente al momento
de aceptar (calculado server-side — nunca se confía en el cliente).
Si mañana cambian los términos, se agrega una versión nueva acá y la
evidencia histórica no se reescribe.
"""
from __future__ import annotations

import hashlib

LEGAL_DOCS = [
    {"document_key": "terms_of_service", "version": "2026-06.1",
     "title": "Términos y Condiciones del Servicio",
     "url": "/terms",
     "content": ("PROSPER PROTOCOL — TÉRMINOS Y CONDICIONES DEL SERVICIO "
                 "(v2026-06.1). Infraestructura de rendimiento regulada "
                 "por CNV. El texto completo vigente es el publicado en "
                 "/terms a la fecha de esta versión.")},
    {"document_key": "privacy_policy", "version": "2026-06.1",
     "title": "Política de Privacidad",
     "url": "/privacy",
     "content": ("PROSPER PROTOCOL — POLÍTICA DE PRIVACIDAD (v2026-06.1). "
                 "El texto completo vigente es el publicado en /privacy a "
                 "la fecha de esta versión.")},
    {"document_key": "kyb_declaration", "version": "2026-06.1",
     "title": "Declaración jurada de veracidad de datos KYB",
     "url": "/terms#kyb",
     "content": ("Declaro bajo juramento que los datos e información "
                 "aportados en este expediente KYB son veraces, exactos y "
                 "completos (v2026-06.1).")},
]


def current_docs() -> list[dict]:
    """Docs vigentes con content_hash calculado (sin el content crudo)."""
    out = []
    for d in LEGAL_DOCS:
        out.append({"document_key": d["document_key"],
                    "version": d["version"], "title": d["title"],
                    "url": d["url"],
                    "content_hash": hashlib.sha256(
                        d["content"].encode()).hexdigest()})
    return out

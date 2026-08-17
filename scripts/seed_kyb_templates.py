"""Fase 5a — Siembra idempotente de plantillas de checklist manual.

Uso:  python scripts/seed_kyb_templates.py
Requiere KYB_MODULE_ENABLED=true. Idempotente por template_id fijo: si la
plantilla ya existe (cualquier versión), no la toca — las ediciones
posteriores de Compliance mandan.

URLs: solo fuentes verificadas con certeza. Las dudosas quedan None con
TODO para que Compliance las complete desde la pantalla de plantillas.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

SEED_TEMPLATES = [
    {
        "template_id": "tpl_screening_ar",
        "category": "screening",
        "country": "AR",
        "subject_types": ["company", "legal_representative", "ubo"],
        "items": [
            {"item_key": "un_consolidated",
             "label": "Consulta a la lista consolidada del Consejo de "
                      "Seguridad de la ONU",
             "description": "Buscar el nombre completo del sujeto (y alias "
                            "conocidos) en la lista consolidada de "
                            "sanciones de la ONU. Adjuntar captura del "
                            "resultado de la búsqueda.",
             "source_url": "https://main.un.org/securitycouncil/en/content/"
                           "un-sc-consolidated-list",
             "evidence_required": True,
             "possible_outcomes": ["clear", "hit", "unavailable"],
             "order": 1},
            {"item_key": "ofac_sdn",
             "label": "Consulta a la lista OFAC SDN (EE.UU.)",
             "description": "Buscar el sujeto en el buscador oficial de "
                            "sanciones de OFAC (SDN y no-SDN). Adjuntar "
                            "captura del resultado.",
             "source_url": "https://sanctionssearch.ofac.treas.gov/",
             "evidence_required": True,
             "possible_outcomes": ["clear", "hit", "unavailable"],
             "order": 2},
            {"item_key": "eu_sanctions",
             "label": "Consulta a las listas de sanciones de la Unión "
                      "Europea",
             "description": "Verificar el sujeto contra el mapa de "
                            "sanciones de la UE. Adjuntar captura.",
             "source_url": "https://www.sanctionsmap.eu/",
             "evidence_required": True,
             "possible_outcomes": ["clear", "hit", "unavailable"],
             "order": 3},
            {"item_key": "uif_repet",
             "label": "Consulta al RePET (UIF — Argentina)",
             "description": "Buscar el sujeto en el Registro Público de "
                            "Personas y Entidades vinculadas a actos de "
                            "Terrorismo y su Financiamiento. Adjuntar "
                            "captura.",
             "source_url": "https://repet.jus.gob.ar/",
             "evidence_required": True,
             "possible_outcomes": ["clear", "hit", "unavailable"],
             "order": 4},
            {"item_key": "adverse_media",
             "label": "Búsqueda de medios adversos",
             "description": "Búsqueda en medios y buscadores del sujeto "
                            "asociado a fraude, lavado, corrupción o "
                            "sanciones. Registrar en notas los términos "
                            "usados y adjuntar capturas de hallazgos "
                            "relevantes (o de la ausencia de resultados).",
             "source_url": None,   # búsqueda abierta: sin fuente única
             "evidence_required": True,
             "possible_outcomes": ["clear", "hit", "unavailable"],
             "order": 5},
        ],
    },
    {
        "template_id": "tpl_registry_ar",
        "category": "company_registry",
        "country": "AR",
        "subject_types": ["company"],
        "items": [
            {"item_key": "arca_constancia",
             "label": "Consulta de constancia de inscripción en ARCA",
             "description": "Obtener la constancia de inscripción fiscal "
                            "vigente y cotejar CUIT, razón social y "
                            "domicilio contra lo declarado en el "
                            "expediente. Adjuntar la constancia.",
             # TODO(Compliance): URL post-rebrand AFIP→ARCA sin verificar.
             "source_url": None,
             "evidence_required": True,
             "possible_outcomes": ["clear", "hit", "unavailable"],
             "order": 1},
            {"item_key": "registro_societario",
             "label": "Verificación de inscripción registral contra el "
                      "estatuto presentado",
             "description": "Cotejar el registro de inscripción (IGJ u "
                            "organismo registral de la jurisdicción), "
                            "número y fecha de inscripción contra el "
                            "instrumento constitutivo del expediente. "
                            "«hit» = discrepancia entre registro y "
                            "documentación. Adjuntar evidencia de la "
                            "consulta.",
             # TODO(Compliance): la fuente varía por jurisdicción (IGJ /
             # registros provinciales) — definir enlaces por provincia.
             "source_url": None,
             "evidence_required": True,
             "possible_outcomes": ["clear", "hit", "unavailable"],
             "order": 2},
        ],
    },
    {
        "template_id": "tpl_identity_global",
        "category": "identity",
        "country": None,   # aplica a todos los países
        "subject_types": ["legal_representative", "ubo"],
        # v2 — los ítems capturan el ACTO de verificación (qué miró la
        # persona), no la mera existencia del archivo en el legajo.
        "items": [
            {"item_key": "identity_match",
             "label": "Cotejo de nombre, apellido y número de documento "
                      "contra lo declarado",
             "description": "Abrir el documento de identidad del legajo y "
                            "comparar nombre, apellido y número contra los "
                            "datos declarados del sujeto. Registrar en las "
                            "notas los valores observados y si coinciden. "
                            "El documento del legajo alcanza como "
                            "evidencia; adjuntar solo si se consultó una "
                            "fuente adicional.",
             "source_url": None,
             "evidence_required": False,
             "possible_outcomes": ["clear", "hit", "unavailable"],
             "order": 1},
            {"item_key": "doc_validity",
             "label": "Verificación de vigencia del documento",
             "description": "Verificar la fecha de vencimiento del "
                            "documento y registrarla en las notas, "
                            "confirmando que es posterior a hoy y que no "
                            "hay señales de adulteración visibles.",
             "source_url": None,
             "evidence_required": False,
             "possible_outcomes": ["clear", "hit", "unavailable"],
             "order": 2},
            {"item_key": "doc_legibility",
             "label": "Legibilidad de la imagen del documento",
             "description": "Confirmar que la imagen cargada (frente y "
                            "dorso si existe) es legible: fotografía, "
                            "datos y número visibles sin cortes ni "
                            "reflejos. Registrar en las notas qué caras "
                            "se revisaron. «hit» = ilegible o incompleta "
                            "(corresponde observar el expediente).",
             "source_url": None,
             "evidence_required": False,
             "possible_outcomes": ["clear", "hit", "unavailable"],
             "order": 3},
        ],
    },
]


def _items_differ(a: list, b: list) -> bool:
    strip = lambda items: [{k: i.get(k) for k in
                            ("item_key", "label", "description",
                             "source_url", "evidence_required",
                             "possible_outcomes", "order")}
                           for i in items]
    return strip(a) != strip(b)


async def seed() -> None:
    from db import col
    from models import utc_now
    from kyb.flags import kyb_enabled
    from kyb.models import KYB_MANUAL_CHECK_TEMPLATES

    if not kyb_enabled():
        print("KYB_MODULE_ENABLED=false — no se siembra nada.")
        return
    created = skipped = upgraded = 0
    for tpl in SEED_TEMPLATES:
        latest = await col(KYB_MANUAL_CHECK_TEMPLATES).find(
            {"template_id": tpl["template_id"]},
            {"_id": 0}).sort("version", -1).limit(1).to_list(1)
        if not latest:
            await col(KYB_MANUAL_CHECK_TEMPLATES).insert_one(
                {**tpl, "version": 1, "active": True, "updated_by": "seed",
                 "created_at": utc_now(), "updated_at": utc_now()})
            created += 1
            continue
        cur = latest[0]
        # Upgrade SOLO si la última versión sigue siendo del seed: las
        # ediciones de Compliance mandan y nunca se pisan.
        if cur.get("updated_by") == "seed" and \
                _items_differ(cur.get("items") or [], tpl["items"]):
            new_version = cur["version"] + 1
            await col(KYB_MANUAL_CHECK_TEMPLATES).update_many(
                {"template_id": tpl["template_id"],
                 "version": {"$lt": new_version}},
                {"$set": {"active": False, "updated_at": utc_now()}})
            await col(KYB_MANUAL_CHECK_TEMPLATES).insert_one(
                {**tpl, "version": new_version, "active": True,
                 "updated_by": "seed", "created_at": utc_now(),
                 "updated_at": utc_now()})
            upgraded += 1
        else:
            skipped += 1
    print(f"Plantillas: {created} creadas, {upgraded} actualizadas "
          f"(versión nueva del seed), {skipped} intactas.")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / "backend" / ".env")
    asyncio.run(seed())

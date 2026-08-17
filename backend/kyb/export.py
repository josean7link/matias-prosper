"""Fase 7 — Exportación del legajo KYB (ZIP autocontenido).

El ZIP tiene que ser autocontenido: un tercero (auditor interno o
regulador) debe poder entender qué se verificó, cómo y quién lo hizo,
sin acceso al sistema.

Contenido:
  * case.json — dump completo del expediente (case, profile, ubos,
    verifications, hits, checks, resolución) sin ids internos de _id.
  * resumen.pdf — reportlab, formato legible: perfil, UBOs,
    verificaciones (modo + quién), riesgo con desglose, resolución.
  * documents/<slot>/<filename> — documentos vigentes por carpeta de
    slot, con nombres originales.
  * manual_evidence/<check_id>/<item_key>/<filename> — evidencia de
    cada ítem del checklist manual, con el detalle en un README.txt.
  * manual_evidence/_descartadas/<check_id>/<filename> — evidencias
    descartadas en sección aparte, con motivo y actor en el README.
  * audit.jsonl — log completo del expediente en JSON lines.

Cero secretos, cero storage_key, cero URLs con firma. Todos los blobs
se materializan desde GridFS al ZIP.
"""
from __future__ import annotations

import io
import json
import zipfile
from typing import Any

from db import col
from kyb.models import (KYB_BENEFICIAL_OWNERS, KYB_CASES,
                        KYB_COMPANY_PROFILES, KYB_DOCUMENTS,
                        KYB_MANUAL_CHECKS, KYB_SCREENING_HITS,
                        KYB_VERIFICATIONS)


def _clean(doc: Any) -> Any:
    """Elimina _id y campos sensibles recursivamente."""
    if isinstance(doc, list):
        return [_clean(x) for x in doc]
    if isinstance(doc, dict):
        return {k: _clean(v) for k, v in doc.items()
                if k not in ("_id", "storage_key", "raw_response_ref")}
    return doc


def _sanitize_name(s: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_"
                   for c in (s or ""))[:120] or "file"


async def _fetch_blob(storage_key: str) -> bytes:
    from services.storage import get_storage
    content, _ = await get_storage().get(storage_key)
    return content


def _render_pdf(bundle: dict) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, PageBreak)
    from reportlab.lib import colors

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm,
                            title=f"KYB {bundle['case']['case_id']}")
    styles = getSampleStyleSheet()
    h1 = styles["Heading1"]; h2 = styles["Heading2"]
    body = styles["BodyText"]
    small = ParagraphStyle("small", parent=body, fontSize=8,
                           textColor=colors.grey)

    story: list = []
    case = bundle["case"]
    profile = bundle["profile"] or {}
    story.append(Paragraph(f"Expediente KYB — {case['case_id']}", h1))
    story.append(Paragraph(
        f"Estado: <b>{case.get('status')}</b> · País: "
        f"{case.get('country_of_incorporation') or '—'} · Riesgo: "
        f"{(case.get('risk') or {}).get('level') or '—'}", body))
    if case.get("legacy_origin"):
        story.append(Paragraph(
            "<b>Expediente migrado del sistema anterior.</b> La "
            "documentación no fue capturada por esta plataforma y se "
            "re-verifica manualmente.", small))
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("Perfil societario", h2))
    prof_rows = [
        ["Razón social", profile.get("legal_name") or "—"],
        ["Tax ID", profile.get("tax_id") or "—"],
        ["Estructura legal", profile.get("legal_structure") or "—"],
        ["Nº inscripción", profile.get("registration_number") or "—"],
        ["Fecha inscripción", profile.get("registration_date") or "—"],
        ["Actividad", profile.get("activity_description") or "—"],
    ]
    t = Table(prof_rows, colWidths=[5 * cm, None])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                           ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(t); story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("Beneficiarios finales", h2))
    ubos = bundle["ubos"] or []
    if not ubos:
        story.append(Paragraph("Sin UBOs cargados.", body))
    else:
        ubo_rows = [["Nombre", "Doc.", "% part.", "PEP"]]
        for u in ubos:
            name = f"{u.get('first_name', '')} {u.get('last_name', '')}"
            ubo_rows.append([name.strip() or "—",
                             u.get("document_number") or u.get("tax_id")
                             or "—",
                             (str(u.get("ownership_percentage")) + "%")
                             if u.get("ownership_percentage") is not None
                             else "—",
                             "Sí" if u.get("is_pep") else "No"])
        ut = Table(ubo_rows, colWidths=[6 * cm, 4 * cm, 3 * cm, 2 * cm])
        ut.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]))
        story.append(ut)
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("Verificaciones", h2))
    vers = bundle["verifications"] or []
    if not vers:
        story.append(Paragraph("Sin verificaciones registradas.", body))
    else:
        vr = [["Categoría", "Sujeto", "Modo", "Fuente", "Por", "Resultado"]]
        for v in vers:
            vr.append([v.get("kind"), v.get("subject_id") or "—",
                       v.get("mode"), v.get("source"),
                       v.get("performed_by") or "—",
                       v.get("outcome") or v.get("status")])
        vt = Table(vr, colWidths=[3 * cm, 3.5 * cm, 2 * cm, 2 * cm,
                                  3 * cm, 2.5 * cm])
        vt.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]))
        story.append(vt)
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("Riesgo", h2))
    risk = case.get("risk") or {}
    if not risk:
        story.append(Paragraph("Sin cálculo de riesgo.", body))
    else:
        rr = [["Factor", "Observado", "Aporte"]]
        for f in risk.get("factors") or []:
            rr.append([f.get("label") or f.get("key"),
                       str(f.get("observed")), str(f.get("score"))])
        rr.append(["", "TOTAL", str(risk.get("score"))])
        rt = Table(rr, colWidths=[7 * cm, 6 * cm, 3 * cm])
        rt.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ]))
        story.append(rt)
        story.append(Paragraph(
            f"Nivel: <b>{risk.get('level') or '—'}</b> · Versión modelo: "
            f"{risk.get('model_version') or '—'} · Calculado: "
            f"{risk.get('computed_at') or '—'}", body))
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("Resolución", h2))
    res = case.get("resolution") or {}
    if not res:
        story.append(Paragraph("Expediente sin resolución final.", body))
    else:
        story.append(Paragraph(
            f"Decisión: <b>{res.get('decision')}</b><br/>"
            f"Razón: {res.get('reason_code') or '—'}<br/>"
            f"Notas: {res.get('notes') or '—'}<br/>"
            f"Decidido por: {res.get('decided_by') or res.get('by') or '—'}",
            body))

    story.append(PageBreak())
    story.append(Paragraph(
        "Nota: este PDF es un resumen legible. El expediente completo "
        "está en case.json (mismo ZIP), los documentos originales en "
        "documents/ y la evidencia de checklists en manual_evidence/. "
        "El log de auditoría está en audit.jsonl.", small))

    doc.build(story)
    return buf.getvalue()


async def _collect(case_id: str) -> dict:
    case = await col(KYB_CASES).find_one({"case_id": case_id}, {"_id": 0})
    profile = await col(KYB_COMPANY_PROFILES).find_one(
        {"case_id": case_id}, {"_id": 0})
    ubos = await col(KYB_BENEFICIAL_OWNERS).find(
        {"case_id": case_id}, {"_id": 0}).to_list(200)
    docs = await col(KYB_DOCUMENTS).find(
        {"case_id": case_id}, {"_id": 0}).sort("created_at", 1).to_list(500)
    vers = await col(KYB_VERIFICATIONS).find(
        {"case_id": case_id}, {"_id": 0}).to_list(200)
    hits = await col(KYB_SCREENING_HITS).find(
        {"case_id": case_id}, {"_id": 0}).to_list(500)
    checks = await col(KYB_MANUAL_CHECKS).find(
        {"case_id": case_id}, {"_id": 0}).to_list(200)
    audit = await col("audit_logs").find(
        {"$or": [{"resource_id": case_id},
                 {"metadata.case_id": case_id}]},
        {"_id": 0}).sort("timestamp", 1).to_list(5000)
    return {"case": case, "profile": profile, "ubos": ubos,
            "documents": docs, "verifications": vers, "hits": hits,
            "checks": checks, "audit": audit}


async def build_export_zip(case_id: str) -> bytes:
    bundle = await _collect(case_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1) case.json — dump completo limpio
        clean_bundle = {k: _clean(v) for k, v in bundle.items()
                        if k != "audit"}
        zf.writestr("case.json", json.dumps(clean_bundle,
                                            ensure_ascii=False, indent=2,
                                            default=str))

        # 2) resumen.pdf
        try:
            zf.writestr("resumen.pdf", _render_pdf(clean_bundle))
        except Exception as e:  # pragma: no cover — reportlab errores
            zf.writestr("resumen.pdf.error.txt",
                        f"No se pudo generar el PDF: {e}")

        # 3) documents/<slot>/<filename>
        current_docs = [d for d in (bundle["documents"] or [])
                        if d.get("is_current") and not d.get("discarded")]
        for d in current_docs:
            slot = _sanitize_name(d.get("slot") or "other")
            name = _sanitize_name(d.get("filename") or d["document_id"])
            path = f"documents/{slot}/{d['document_id']}__{name}"
            try:
                blob = await _fetch_blob(d.get("storage_key"))
                zf.writestr(path, blob)
            except Exception as e:  # pragma: no cover
                zf.writestr(path + ".error.txt",
                            f"No se pudo materializar: {e}")

        # 4) manual_evidence/<check_id>/<item_key>/<filename>
        # Todos los documentos de evidencia referenciados por checks.
        # Descartadas van a manual_evidence/_descartadas/.
        readme_lines: list[str] = ["# Evidencia de checklists manuales\n"]
        for chk in (bundle["checks"] or []):
            readme_lines.append(
                f"\n## Checklist {chk['check_id']} — {chk['category']} — "
                f"sujeto {chk.get('subject_id')} — {chk.get('status')}")
            readme_lines.append(
                f"Template: {chk.get('template_id')} v"
                f"{chk.get('template_version')}. Completado por: "
                f"{chk.get('completed_by') or '—'} el "
                f"{chk.get('completed_at') or '—'}.")
            for item in (chk.get("items") or []):
                if item.get("outcome"):
                    readme_lines.append(
                        f"- [{item['item_key']}] {item['label']}: "
                        f"outcome={item['outcome']} · "
                        f"notas={item.get('notes') or '—'}")
                for doc_id in (item.get("evidence_document_ids") or []):
                    d = next((x for x in (bundle["documents"] or [])
                              if x.get("document_id") == doc_id), None)
                    if not d:
                        continue
                    name = _sanitize_name(d.get("filename") or doc_id)
                    if d.get("discarded"):
                        base = ("manual_evidence/_descartadas/"
                                f"{chk['check_id']}")
                        readme_lines.append(
                            f"    · DESCARTADA {doc_id}: "
                            f"{d['discarded'].get('reason') or '—'} "
                            f"(por {d['discarded'].get('by') or '—'} el "
                            f"{d['discarded'].get('at') or '—'})")
                    else:
                        base = ("manual_evidence/"
                                f"{chk['check_id']}/"
                                f"{_sanitize_name(item['item_key'])}")
                    path = f"{base}/{doc_id}__{name}"
                    try:
                        blob = await _fetch_blob(d.get("storage_key"))
                        zf.writestr(path, blob)
                    except Exception as e:  # pragma: no cover
                        zf.writestr(path + ".error.txt",
                                    f"No se pudo materializar: {e}")
        zf.writestr("manual_evidence/README.md",
                    "\n".join(readme_lines))

        # 5) audit.jsonl
        lines = []
        for ev in (bundle["audit"] or []):
            lines.append(json.dumps(_clean(ev), ensure_ascii=False,
                                    default=str))
        zf.writestr("audit.jsonl", "\n".join(lines))

        # 6) MANIFEST.txt — resumen humano del contenido del ZIP
        zf.writestr(
            "MANIFEST.txt",
            f"KYB export — {case_id}\n"
            f"Documentos vigentes: {len(current_docs)}\n"
            f"Checklists: {len(bundle['checks'] or [])}\n"
            f"Verificaciones: {len(bundle['verifications'] or [])}\n"
            f"Hits: {len(bundle['hits'] or [])}\n"
            f"Eventos de auditoría: {len(bundle['audit'] or [])}\n")

    return buf.getvalue()

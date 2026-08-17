"""Fase 8 — Dispatcher central de notificaciones KYB.

Un solo punto de envío por evento. Idempotencia por
`(event_type, case_id, recipient, discriminator)` — así se conservan
los reenvíos legítimos (p. ej. una segunda invitación de equipo con
token nuevo dispara un nuevo email; una re-emisión del mismo estado
para el mismo destinatario no).

Con `RESEND_API_KEY` vacía el envío cae en modo preview: se persiste
en `outbound_emails` con `status="preview_only"` y nada sale a
internet. Cuando el usuario active la key, los mismos calls empiezan
a salir sin cambiar el código.

Los correos que dependen del proveedor externo
(`kyb.case.provider_alert`) están construidos pero NUNCA se disparan
mientras Sumsub siga postergado — no hay origen que los detone.
"""
from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, Optional


def _base_url() -> str:
    return (os.environ.get("PUBLIC_BASE_URL") or "").rstrip("/")


def _shell_style(body: str) -> str:
    # No importamos _shell del módulo global para evitar acoplarnos: si
    # cambia el layout, sigue funcionando.
    from integrations.email_sender import _shell
    return _shell(body)


def _idem(event_type: str, case_id: str, recipient: str,
          discriminator: str = "") -> str:
    seed = f"{event_type}|{case_id}|{recipient}|{discriminator}"
    return hashlib.sha256(seed.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Plantillas por evento
# ---------------------------------------------------------------------------
def _tpl_submitted(company_name: str, case_id: str) -> tuple[str, str]:
    subject = "Recibimos tu expediente"
    body = f"""
      <h1>Recibimos tu expediente</h1>
      <p>Tomamos el expediente de <strong>{company_name}</strong>
         (referencia <code>{case_id}</code>) para revisión.</p>
      <p>Te avisamos por este mismo medio cuando el equipo de
         Compliance tenga novedades: puede ser una solicitud de
         información, una aprobación o un rechazo.</p>
    """
    return subject, body


def _tpl_submitted_internal(company_name: str, case_id: str,
                            portal_url: str) -> tuple[str, str]:
    subject = f"Nuevo expediente KYB: {company_name}"
    body = f"""
      <h1>Nuevo expediente KYB</h1>
      <p><strong>{company_name}</strong> envió su expediente
         (<code>{case_id}</code>).</p>
      <p><a href="{portal_url}">Abrir en el portal</a></p>
    """
    return subject, body


def _tpl_info_required(company_name: str, sections: Dict[str, str],
                       portal_url: str) -> tuple[str, str]:
    labels = {"tax_identification": "Identificación fiscal",
              "legal_representative": "Representante legal",
              "company_data": "Datos de la empresa",
              "documentation": "Documentación y beneficiarios"}
    rows = "".join(
        f"<p style='margin:12px 0'><strong>{labels.get(k, k)}:</strong>"
        f"<br/>{v or ''}</p>" for k, v in sections.items())
    subject = "Tu expediente KYB tiene observaciones"
    body = f"""
      <h1>Necesitamos información adicional</h1>
      <p>Revisamos el expediente de <strong>{company_name}</strong> y
         encontramos observaciones en las siguientes secciones:</p>
      {rows}
      <p><a href="{portal_url}">Ingresá a corregirlas</a> y reenviá el
         expediente cuando esté listo.</p>
    """
    return subject, body


def _tpl_approved(company_name: str) -> tuple[str, str]:
    subject = "Tu expediente KYB fue aprobado"
    body = f"""
      <h1>Aprobamos tu expediente</h1>
      <p><strong>{company_name}</strong> quedó habilitada para operar.
         Te llegarán próximamente los pasos para completar la
         configuración de la cuenta.</p>
    """
    return subject, body


def _tpl_rejected(company_name: str, reason: str) -> tuple[str, str]:
    subject = "Tu expediente KYB no fue aprobado"
    body = f"""
      <h1>Tu expediente no fue aprobado</h1>
      <p>Revisamos el expediente de <strong>{company_name}</strong> y
         no podemos avanzar en esta oportunidad.</p>
      <p><strong>Motivo:</strong><br/>{reason or '—'}</p>
      <p>Si querés discutir esta decisión, respondé este correo.</p>
    """
    return subject, body


def _tpl_team_invitation(company_name: str, inviter: str, tax_id: str,
                         accept_url: str) -> tuple[str, str]:
    subject = f"Te invitaron a {company_name} en Prosper"
    body = f"""
      <h1>Te invitaron a {company_name}</h1>
      <p><strong>{inviter}</strong> te invitó a sumarte al equipo.</p>
      <p>Para aceptar, la invitación requiere que ingreses con el
         CUIT/CUIL <code>{tax_id}</code>. Si no es tu número, avisá a
         quien te invitó — no aceptes la invitación con otra
         identidad.</p>
      <p style="margin:24px 0">
        <a href="{accept_url}" style="background:#2563FF;color:#fff;
           text-decoration:none;padding:12px 20px;border-radius:8px;
           font-weight:600">Aceptar invitación</a>
      </p>
      <p style="font-size:12px;color:#6B7280">Este enlace vence en 7
         días y solo puede usarse una vez.</p>
    """
    return subject, body


def _tpl_expiring(company_name: str, days: int, portal_url: str
                  ) -> tuple[str, str]:
    subject = f"Tu expediente KYB expira en {days} días"
    body = f"""
      <h1>Falta poco</h1>
      <p>El expediente de <strong>{company_name}</strong> lleva mucho
         tiempo sin actividad. En <strong>{days} días</strong> se marca
         como expirado.</p>
      <p><a href="{portal_url}">Retomalo</a> — nada se borra, solo
         quedaría pausado hasta que lo reactives.</p>
    """
    return subject, body


def _tpl_manual_check_pending(company_name: str, case_id: str,
                              overdue_hours: int,
                              portal_url: str) -> tuple[str, str]:
    subject = f"Checklists KYB pendientes en {company_name}"
    body = f"""
      <h1>Checklists pendientes</h1>
      <p>El expediente <code>{case_id}</code> ({company_name}) tiene
         checklists manuales sin completar. SLA excedido en
         <strong>{overdue_hours}h</strong>.</p>
      <p><a href="{portal_url}">Abrir en el portal</a></p>
    """
    return subject, body


def _tpl_provider_alert(company_name: str, case_id: str, detail: str,
                        portal_url: str) -> tuple[str, str]:
    subject = f"Alerta de vigilancia continua: {company_name}"
    body = f"""
      <h1>Alerta de vigilancia continua</h1>
      <p>El proveedor externo emitió una alerta sobre el expediente
         ya aprobado <code>{case_id}</code>.</p>
      <p>{detail}</p>
      <p><a href="{portal_url}">Revisar en el portal</a></p>
    """
    return subject, body


# ---------------------------------------------------------------------------
# Dispatcher público
# ---------------------------------------------------------------------------
async def notify(event_type: str, *, case_id: str, recipient: str,
                 context: Optional[Dict[str, Any]] = None,
                 discriminator: str = "") -> dict:
    """Único punto de envío. Devuelve el registro de `outbound_emails`."""
    from integrations.email_sender import send_email
    ctx = context or {}
    company = ctx.get("company_name") or "tu empresa"
    portal = f"{_base_url()}/client/kyb"
    if event_type == "kyb.case.submitted":
        # Si el destinatario es interno (compliance), usar plantilla
        # interna. El discriminador `internal` los separa del email al
        # cliente para que ambos se envíen.
        if discriminator == "internal":
            subject, body = _tpl_submitted_internal(
                company, case_id, f"{_base_url()}/admin/compliance/kyb/"
                f"{case_id}")
        else:
            subject, body = _tpl_submitted(company, case_id)
    elif event_type == "kyb.case.info_required":
        subject, body = _tpl_info_required(company, ctx.get("sections") or {},
                                           portal)
    elif event_type == "kyb.case.approved":
        subject, body = _tpl_approved(company)
    elif event_type == "kyb.case.rejected":
        subject, body = _tpl_rejected(company, ctx.get("reason") or "")
    elif event_type == "kyb.team.invitation":
        subject, body = _tpl_team_invitation(
            company, ctx.get("inviter") or "El administrador",
            ctx.get("tax_id") or "", ctx.get("accept_url") or "")
    elif event_type == "kyb.case.expiring":
        subject, body = _tpl_expiring(
            company, int(ctx.get("days") or 7), portal)
    elif event_type == "kyb.manual_check.pending":
        subject, body = _tpl_manual_check_pending(
            company, case_id, int(ctx.get("overdue_hours") or 0),
            f"{_base_url()}/admin/compliance/kyb/{case_id}")
    elif event_type == "kyb.case.provider_alert":
        # Construido pero nunca se dispara — Sumsub postergada.
        subject, body = _tpl_provider_alert(
            company, case_id, ctx.get("detail") or "",
            f"{_base_url()}/admin/compliance/kyb/{case_id}")
    else:
        raise ValueError(f"event_type desconocido: {event_type}")

    return await send_email(
        to=recipient, subject=subject, html=_shell_style(body),
        template=event_type,
        context={"case_id": case_id, **ctx},
        idempotency_key=_idem(event_type, case_id, recipient, discriminator))

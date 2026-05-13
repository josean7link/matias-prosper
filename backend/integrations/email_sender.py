"""Phase 6 — Resend integration with mock-friendly fallback.

When `RESEND_API_KEY` is not configured, emails are stored as documents in
`outbound_emails` collection so the admin UI can preview the HTML. Once the
key is configured, the same `send_email()` call routes through Resend's API.
"""
from __future__ import annotations

import os
import logging
import secrets
from datetime import datetime, timezone
from typing import Optional, Literal

import httpx

from db import col, OUTBOUND_EMAILS

logger = logging.getLogger("prosper.email")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _get_setting(provider: str, key: str) -> Optional[str]:
    """Local copy of settings lookup to avoid circular imports."""
    from routes.admin_settings import setting_value
    return await setting_value(provider, key)


async def send_email(
    *, to: str, subject: str, html: str,
    template: str, context: Optional[dict] = None,
    org_id: Optional[str] = None, user_id: Optional[str] = None,
    actor_email: Optional[str] = None,
) -> dict:
    """Send (or stub-store) an email. Returns the saved record."""
    api_key   = (await _get_setting("resend", "api_key")) or os.environ.get("RESEND_API_KEY")
    from_addr = (await _get_setting("resend", "from_email")) \
                or os.environ.get("RESEND_FROM") or "onboarding@resend.dev"

    record = {
        "email_id":    f"em_{secrets.token_hex(6)}",
        "to":          to,
        "from":        from_addr,
        "subject":     subject,
        "template":    template,
        "context":     context or {},
        "html":        html,
        "org_id":      org_id,
        "user_id":     user_id,
        "actor_email": actor_email,
        "status":      "queued",
        "provider":    "resend" if api_key else "mock",
        "provider_id": None,
        "error":       None,
        "created_at":  _iso_now(),
        "delivered_at": None,
        "is_deleted":  False,
    }

    if not api_key:
        record["status"] = "preview_only"
        await col(OUTBOUND_EMAILS).insert_one(record.copy())
        logger.info(f"[email:mock] to={to} subject='{subject}' template={template}")
        record.pop("_id", None)
        return record

    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json"},
                json={"from": from_addr, "to": to, "subject": subject, "html": html})
        if r.status_code in (200, 202):
            data = r.json() or {}
            record["status"]      = "sent"
            record["provider_id"] = data.get("id")
            record["delivered_at"] = _iso_now()
        else:
            record["status"] = "failed"
            record["error"]  = f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        record["status"] = "failed"
        record["error"]  = str(e)

    await col(OUTBOUND_EMAILS).insert_one(record.copy())
    record.pop("_id", None)
    return record


# ---------------------------------------------------------------------------
# Templates — minimal HTML, easy to upgrade to react-email later
# ---------------------------------------------------------------------------
def _shell(content_html: str, lang: str = "es") -> str:
    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head><meta charset="utf-8">
<title>Prosper</title>
<style>
  body{{margin:0;padding:0;background:#F2F6FF;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#0B0F19}}
  .wrap{{max-width:560px;margin:0 auto;padding:32px 24px}}
  .card{{background:#fff;border-radius:14px;padding:32px;border:1px solid rgba(11,15,25,.08)}}
  .logo{{font-family:'Chivo',sans-serif;font-weight:900;color:#2563FF;font-size:22px;letter-spacing:-0.02em;margin-bottom:24px}}
  h1{{font-family:'Chivo',sans-serif;font-weight:800;font-size:22px;margin:0 0 12px;line-height:1.25}}
  p{{font-size:14px;line-height:1.55;color:#3a4055;margin:8px 0}}
  .btn{{display:inline-block;background:#2563FF;color:#fff!important;padding:12px 22px;border-radius:8px;text-decoration:none;font-weight:600;font-size:14px;margin:18px 0}}
  .meta{{font-family:'IBM Plex Mono',monospace;font-size:11px;color:#6B7280;text-transform:uppercase;letter-spacing:.12em;margin-top:24px}}
</style></head>
<body><div class="wrap"><div class="card"><div class="logo">prosper</div>{content_html}</div>
<p class="meta">© prosper · borderless on-chain financial services</p></div></body></html>"""


def t_invitation(*, name: str, org_name: str, link: str) -> tuple[str, str]:
    subject = f"Te invitamos a Prosper · {org_name}"
    body = f"""
      <h1>Hola {name},</h1>
      <p>Te invitamos a unirte al portal de <strong>{org_name}</strong> en Prosper.
      Vas a poder ver tus posiciones, suscribir/redimir tokens y gestionar a tu equipo.</p>
      <p><a class="btn" href="{link}">Aceptar invitación</a></p>
      <p style="font-size:12px;color:#6B7280">El link vence en 72 horas.<br/>
      Si no esperabas este email, ignoralo.</p>"""
    return subject, _shell(body)


def t_reset_password(*, name: str, link: str) -> tuple[str, str]:
    subject = "Restablecé tu contraseña · Prosper"
    body = f"""
      <h1>Hola {name},</h1>
      <p>Recibimos un pedido para restablecer tu contraseña.</p>
      <p><a class="btn" href="{link}">Restablecer contraseña</a></p>
      <p style="font-size:12px;color:#6B7280">El link vence en 24 horas.</p>"""
    return subject, _shell(body)


def t_kyb_link(*, org_name: str, link: str) -> tuple[str, str]:
    subject = f"Completar onboarding KYB · {org_name}"
    body = f"""
      <h1>Onboarding pendiente</h1>
      <p>Para activar la cuenta de <strong>{org_name}</strong> necesitamos completar la
      verificación corporativa (KYB).</p>
      <p><a class="btn" href="{link}">Completar KYB ahora</a></p>
      <p style="font-size:12px;color:#6B7280">El link vence en 72 horas.</p>"""
    return subject, _shell(body)


def t_document_requested(*, org_name: str, docs: list[str], link: str) -> tuple[str, str]:
    items = "".join(f"<li>{d}</li>" for d in docs)
    subject = f"Documentación adicional requerida · {org_name}"
    body = f"""
      <h1>Necesitamos algunos documentos</h1>
      <p>Para continuar con el onboarding de <strong>{org_name}</strong> nos falta:</p>
      <ul style="font-size:14px;line-height:1.55;color:#3a4055">{items}</ul>
      <p><a class="btn" href="{link}">Subir documentos</a></p>"""
    return subject, _shell(body)


def t_kyb_status(*, org_name: str, status: str, reason: str = "") -> tuple[str, str]:
    is_approved = status == "approved"
    title = "¡Bienvenidos a Prosper!" if is_approved else "Estado del onboarding KYB"
    body_html = f"""
      <h1>{title}</h1>
      <p>El estado de onboarding de <strong>{org_name}</strong> ahora es:
      <strong>{status}</strong>.</p>
      {f"<p>{reason}</p>" if reason else ""}"""
    if is_approved:
        body_html += "<p>Ya podés operar en el portal.</p>"
    subject = f"KYB {status} · {org_name}"
    return subject, _shell(body_html)

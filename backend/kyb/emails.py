"""Email de activación del signup KYB (Fase 2).

Usa la infraestructura existente (`integrations/email_sender.py`) con
la idempotencia de la Fase 0.5. Con RESEND_API_KEY vacía cae en modo
preview: se persiste en `outbound_emails` sin enviar — se deja así.

Clave de idempotencia: (event_type, case_id, recipient) + un
discriminador del token de activación. Sin el discriminador, un
reenvío legítimo (token nuevo) quedaría deduplicado contra el primer
envío y nunca saldría — el triple de la spec se conserva como prefijo.
"""
from __future__ import annotations

import hashlib
import os

EVENT_TYPE = "kyb.activation"


def _base_url() -> str:
    return (os.environ.get("PUBLIC_BASE_URL") or "").rstrip("/")


def activation_url(raw_token: str) -> str:
    return f"{_base_url()}/kyb/activate?token={raw_token}"


def idempotency_key(case_id: str, recipient: str, raw_token: str) -> str:
    token_disc = hashlib.sha256(raw_token.encode()).hexdigest()[:12]
    return f"{EVENT_TYPE}:{case_id}:{recipient}:{token_disc}"


async def send_activation_email(*, case_id: str, recipient: str,
                                company_name: str, raw_token: str) -> dict:
    from integrations.email_sender import _shell, send_email
    url = activation_url(raw_token)
    body = f"""
      <h1>Activá tu cuenta de Prosper</h1>
      <p>Recibimos la solicitud de alta empresarial de
         <strong>{company_name or "tu empresa"}</strong>.
         Hacé click para continuar la verificación de tu organización.</p>
      <p style="margin:28px 0">
        <a href="{url}"
           style="background:#2563FF;color:#ffffff;text-decoration:none;
                  padding:14px 28px;border-radius:10px;font-weight:600;
                  display:inline-block">Continuar verificación</a>
      </p>
      <p style="font-size:13px;color:#6B7280">Si el botón no funciona,
         copiá y pegá esta dirección en tu navegador:</p>
      <p style="font-family:'IBM Plex Mono',monospace;font-size:12px;
                word-break:break-all;background:#F2F6FF;border-radius:8px;
                padding:12px 16px;color:#2563FF">{url}</p>
      <p style="font-size:12px;color:#6B7280">El enlace vence en
         {int(float(os.environ.get('KYB_ACTIVATION_TOKEN_TTL_HOURS', 72)))} horas
         y puede usarse una sola vez. Si no solicitaste esta cuenta,
         ignorá este correo.</p>"""
    return await send_email(
        to=recipient,
        subject="Activá tu cuenta de Prosper",
        html=_shell(body),
        template="kyb_activation",
        context={"case_id": case_id},
        idempotency_key=idempotency_key(case_id, recipient, raw_token))


async def send_request_info_email(*, case_id: str, recipient: str,
                                  company_name: str,
                                  observations: dict) -> dict:
    """F6 — solo las secciones observadas; el texto es EXACTAMENTE el que
    escribió el analista (no hay notas internas que se filtren)."""
    from integrations.email_sender import _shell, send_email
    labels = {"tax_identification": "Identificación fiscal",
              "legal_representative": "Representante legal",
              "company_data": "Datos de la empresa",
              "documentation": "Documentación y beneficiarios"}
    rows = "".join(
        f"<p style='margin:12px 0'><strong>{labels.get(k, k)}:</strong><br/>"
        f"{(v or '')}</p>" for k, v in observations.items())
    body = f"""
      <h1>Necesitamos información adicional</h1>
      <p>Revisamos el expediente de <strong>{company_name or 'tu empresa'}
      </strong> y encontramos observaciones en las siguientes secciones:</p>
      {rows}
      <p>Ingresá a tu cuenta para corregirlas y reenviar el expediente.</p>"""
    payload = "|".join(f"{k}:{v}" for k, v in sorted(observations.items()))
    return await send_email(
        to=recipient,
        subject="Tu expediente KYB tiene observaciones",
        html=_shell(body),
        template="kyb_request_info",
        context={"case_id": case_id},
        idempotency_key=hashlib.sha256(
            f"kyb_request_info|{case_id}|{payload}".encode()).hexdigest())

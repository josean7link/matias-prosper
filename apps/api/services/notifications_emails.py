"""Bilingual email templates for deposit_credited events.

Two rails — ARSa and USDC — kept fully separated. ARSa templates NEVER
reference USDC and vice versa. Asserted in tests/test_notifications.py.

The copy is informative-only: announces the credited amount, currency,
date, and a CTA to the portal. NO yield promises, no marketing.

Amount formatting:
  * USDC: 2 decimal places, "1,234.56" (en) / "1.234,56" (es).
  * ARSa: 0 decimal places (whole units), "1,234" (en) / "1.234" (es).
  Both currencies use thousands separators per locale convention.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Literal

Lang = Literal["es", "en"]
Asset = Literal["arsa", "usdc"]


def _decimal_places(asset: Asset) -> int:
    # USDC uses 2 places for display; ARSa is a whole-unit token.
    return 2 if asset == "usdc" else 0


def _format_amount(amount_raw: str, asset: Asset, lang: Lang) -> str:
    """Render `1234.5` as `1.234,50` (es) or `1,234.50` (en)."""
    try:
        d = Decimal(str(amount_raw))
    except (InvalidOperation, ValueError, TypeError):
        return str(amount_raw)
    places = _decimal_places(asset)
    quant = Decimal(10) ** -places if places > 0 else Decimal(1)
    d = d.quantize(quant) if places > 0 else d.to_integral_value()
    # Build with `,` thousands + `.` decimal (en), then swap for `es`.
    s = f"{d:,.{places}f}"
    if lang == "es":
        # 1,234.50 → 1.234,50
        s = s.replace(",", "§").replace(".", ",").replace("§", ".")
    return s


def _shell(content_html: str, lang: Lang) -> str:
    title = "Prosper" if lang == "en" else "Prosper"
    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head><meta charset="utf-8"><title>{title}</title>
<style>
  body{{margin:0;padding:0;background:#F2F6FF;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#0B0F19}}
  .wrap{{max-width:560px;margin:0 auto;padding:32px 24px}}
  .card{{background:#fff;border-radius:14px;padding:32px;border:1px solid rgba(11,15,25,.08)}}
  .logo{{font-family:'Chivo',sans-serif;font-weight:900;color:#2563FF;font-size:22px;letter-spacing:-0.02em;margin-bottom:24px}}
  h1{{font-family:'Chivo',sans-serif;font-weight:800;font-size:22px;margin:0 0 12px;line-height:1.25}}
  p{{font-size:14px;line-height:1.55;color:#3a4055;margin:8px 0}}
  .amount{{font-size:28px;font-weight:800;color:#0B0F19;font-family:'Chivo',sans-serif;margin:18px 0 6px}}
  .currency{{font-size:13px;color:#6B7280;font-family:'IBM Plex Mono',monospace;text-transform:uppercase;letter-spacing:.12em}}
  .btn{{display:inline-block;background:#2563FF;color:#fff!important;padding:12px 22px;border-radius:8px;text-decoration:none;font-weight:600;font-size:14px;margin:18px 0}}
  .meta{{font-family:'IBM Plex Mono',monospace;font-size:11px;color:#6B7280;text-transform:uppercase;letter-spacing:.12em;margin-top:24px}}
  .ref{{font-family:'IBM Plex Mono',monospace;font-size:11px;color:#6B7280;word-break:break-all}}
</style></head>
<body><div class="wrap"><div class="card"><div class="logo">prosper</div>{content_html}</div>
<p class="meta">© prosper · borderless on-chain financial services</p></div></body></html>"""


# ---------------------------------------------------------------------------
# ARSa template — NEVER references USDC.
# ---------------------------------------------------------------------------
def t_deposit_credited_arsa(*, lang: Lang, amount: str, ref: str | None,
                                 date_iso: str, portal_url: str
                                 ) -> tuple[str, str]:
    amount_disp = _format_amount(amount, "arsa", lang)
    if lang == "en":
        subject = f"Deposit credited · {amount_disp} ARSa"
        body = f"""
          <h1>Your ARSa deposit was credited</h1>
          <p>We have received your transfer and credited your Prosper account.</p>
          <div class="amount">{amount_disp}</div>
          <div class="currency">ARSa</div>
          <p>Credited on {date_iso}.</p>
          {('<p class="ref">Reference: ' + ref + '</p>') if ref else ''}
          <p><a class="btn" href="{portal_url}">Open the portal</a></p>
          <p style="font-size:12px;color:#6B7280">
            This is an informational message about the credit only. We are not
            making any statement about returns. To invest your funds, head to
            the portal.</p>"""
    else:
        subject = f"Depósito acreditado · {amount_disp} ARSa"
        body = f"""
          <h1>Acreditamos tu depósito en ARSa</h1>
          <p>Recibimos tu transferencia y acreditamos los fondos en tu cuenta Prosper.</p>
          <div class="amount">{amount_disp}</div>
          <div class="currency">ARSa</div>
          <p>Acreditado el {date_iso}.</p>
          {('<p class="ref">Referencia: ' + ref + '</p>') if ref else ''}
          <p><a class="btn" href="{portal_url}">Abrir el portal</a></p>
          <p style="font-size:12px;color:#6B7280">
            Este es un aviso informativo sobre la acreditación. No estamos
            comunicando rendimiento. Para invertir tus fondos, ingresá al
            portal.</p>"""
    return subject, _shell(body, lang)


# ---------------------------------------------------------------------------
# USDC template — NEVER references ARSa.
# ---------------------------------------------------------------------------
def t_deposit_credited_usdc(*, lang: Lang, amount: str, ref: str | None,
                                 date_iso: str, portal_url: str
                                 ) -> tuple[str, str]:
    amount_disp = _format_amount(amount, "usdc", lang)
    if lang == "en":
        subject = f"Deposit credited · {amount_disp} USDC"
        body = f"""
          <h1>Your USDC deposit was credited</h1>
          <p>We detected your incoming USDC transfer on Stellar and credited it to your Prosper account.</p>
          <div class="amount">{amount_disp}</div>
          <div class="currency">USDC</div>
          <p>Credited on {date_iso}.</p>
          {('<p class="ref">Reference: ' + ref + '</p>') if ref else ''}
          <p><a class="btn" href="{portal_url}">Open the portal</a></p>
          <p style="font-size:12px;color:#6B7280">
            This is an informational message about the credit only. We are not
            making any statement about returns. To invest your funds, head to
            the portal.</p>"""
    else:
        subject = f"Depósito acreditado · {amount_disp} USDC"
        body = f"""
          <h1>Acreditamos tu depósito en USDC</h1>
          <p>Detectamos tu transferencia entrante de USDC en Stellar y la acreditamos en tu cuenta Prosper.</p>
          <div class="amount">{amount_disp}</div>
          <div class="currency">USDC</div>
          <p>Acreditado el {date_iso}.</p>
          {('<p class="ref">Referencia: ' + ref + '</p>') if ref else ''}
          <p><a class="btn" href="{portal_url}">Abrir el portal</a></p>
          <p style="font-size:12px;color:#6B7280">
            Este es un aviso informativo sobre la acreditación. No estamos
            comunicando rendimiento. Para invertir tus fondos, ingresá al
            portal.</p>"""
    return subject, _shell(body, lang)


# ---------------------------------------------------------------------------
# Short in-app titles/bodies (used by services/notifications.py for the
# bell dropdown). Same bilingual rules. Amount formatting same as email.
# ---------------------------------------------------------------------------
def inapp_copy_deposit_credited(*, lang: Lang, asset: Asset, amount: str
                                     ) -> tuple[str, str]:
    amount_disp = _format_amount(amount, asset, lang)
    if asset == "arsa":
        if lang == "en":
            return ("ARSa deposit credited",
                     f"{amount_disp} ARSa is now available in your account.")
        return ("Depósito en ARSa acreditado",
                 f"Ya tenés disponibles {amount_disp} ARSa en tu cuenta.")
    # usdc
    if lang == "en":
        return ("USDC deposit credited",
                 f"{amount_disp} USDC is now available in your account.")
    return ("Depósito en USDC acreditado",
             f"Ya tenés disponibles {amount_disp} USDC en tu cuenta.")

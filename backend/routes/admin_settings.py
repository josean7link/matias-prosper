"""Phase 5+ — Integration settings management.

Provides:
  - GET    /admin/settings/integrations           — list all providers + status
  - GET    /admin/settings/integrations/{provider}— full detail (masked secrets)
  - PATCH  /admin/settings/integrations/{provider}— update fields/docs/mode
  - POST   /admin/settings/integrations/{provider}/test — exercise the provider

Storage: collection `integration_settings`, 1 doc per provider.
Lookup precedence: env var (if set) > DB value > None.
Secrets are returned as `"••••<last4>"` when read; the raw value is only used
internally by `setting_value(provider, key)`.
"""
from __future__ import annotations

import os
import logging
from datetime import datetime, timezone
from typing import Any, Optional, List, Dict, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from audit import log_action
from auth import CurrentUser, requires_role
from db import col, INTEGRATION_SETTINGS
from roles import Role

logger = logging.getLogger("prosper.integrations")
router = APIRouter(prefix="/admin/settings", tags=["admin-settings"])

require_super = requires_role(Role.super_admin)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mask(value: Optional[str]) -> Optional[str]:
    if value is None: return None
    if value == "":   return ""
    s = str(value)
    if len(s) <= 4:   return "••••"
    return f"••••{s[-4:]}"


# ---------------------------------------------------------------------------
# Provider catalog — declarative definition of every supported integration
# ---------------------------------------------------------------------------
class FieldSpec(BaseModel):
    key: str
    label: str
    required: bool = True
    secret: bool = False        # mask in API responses
    placeholder: str = ""
    env_var: Optional[str] = None   # env var that overrides DB
    help: Optional[str] = None


class ProviderSpec(BaseModel):
    provider: str
    name: str
    category: Literal["kyc_kyb", "screening", "email", "tokenization",
                       "onramp", "notifications", "payments"]
    description: str
    docs_default: List[Dict[str, str]] = Field(default_factory=list)
    fields: List[FieldSpec]
    supports_mode: bool = False     # sandbox/live toggle
    supports_test: bool = False     # has a working /test endpoint
    badge_color: str = "primary"


CATALOG: List[ProviderSpec] = [
    ProviderSpec(
        provider="aiprise", name="AiPrise", category="kyc_kyb",
        description="KYC personas físicas + KYB jurídicas con scoring automático y webhooks.",
        supports_mode=True, supports_test=True, badge_color="primary",
        docs_default=[{"title": "AiPrise API reference",
                       "url": "https://docs.aiprise.com/api"}],
        fields=[
            FieldSpec(key="api_key_sandbox",  label="API key · sandbox",
                     secret=True, env_var="AIPRISE_API_KEY_SANDBOX"),
            FieldSpec(key="api_key_production", label="API key · production",
                     secret=True, env_var="AIPRISE_API_KEY_PRODUCTION"),
            FieldSpec(key="template_kyb_id", label="Template KYB id", required=False,
                     env_var="AIPRISE_TEMPLATE_KYB_ID"),
            FieldSpec(key="template_kyc_id", label="Template KYC id", required=False,
                     env_var="AIPRISE_TEMPLATE_KYC_ID"),
            FieldSpec(key="webhook_secret",  label="Webhook secret",
                     secret=True, env_var="AIPRISE_WEBHOOK_SECRET"),
        ]),
    ProviderSpec(
        provider="trm", name="TRM Labs", category="screening",
        description="Wallet screening on-chain · risk scoring · sanctions list · entity attribution.",
        supports_mode=True, supports_test=True, badge_color="warning",
        docs_default=[{"title": "TRM Labs Public API",
                       "url": "https://docs.trmlabs.com"}],
        fields=[
            FieldSpec(key="api_key", label="API key", secret=True,
                     env_var="TRM_LABS_API_KEY"),
            FieldSpec(key="base_url", label="Base URL",
                     placeholder="https://api.trmlabs.com",
                     env_var="TRM_LABS_BASE_URL"),
            FieldSpec(key="product", label="Producto contratado", required=False,
                     placeholder="public-api / tactical / wallet-screening",
                     env_var="TRM_LABS_PRODUCT"),
        ]),
    ProviderSpec(
        provider="resend", name="Resend", category="email",
        description="Email transaccional para OTP, magic links y notificaciones de compliance.",
        supports_test=True, badge_color="success",
        docs_default=[{"title": "Resend API docs",
                       "url": "https://resend.com/docs/api-reference/introduction"}],
        fields=[
            FieldSpec(key="api_key", label="API key", secret=True,
                     env_var="RESEND_API_KEY"),
            FieldSpec(key="from_email", label="From email",
                     placeholder="noreply@prosper.foundation",
                     env_var="RESEND_FROM"),
            FieldSpec(key="verified_domain", label="Dominio verificado", required=False,
                     placeholder="prosper.foundation"),
        ]),
    ProviderSpec(
        provider="prosper_tokenization", name="Prosper Tokenization · Stellar",
        category="tokenization",
        description="Emisión y redemption del token PUSD sobre Stellar. NAV publication + treasury ops.",
        supports_mode=True, supports_test=False, badge_color="primary",
        docs_default=[{"title": "Stellar SDK", "url": "https://developers.stellar.org/docs"},
                      {"title": "Asset issuance",
                       "url": "https://developers.stellar.org/docs/issuing-assets"}],
        fields=[
            FieldSpec(key="asset_code", label="Asset code",
                     placeholder="PUSD"),
            FieldSpec(key="issuer_pubkey", label="Issuer public key",
                     placeholder="GA…", env_var="STELLAR_ISSUER_PUBKEY"),
            FieldSpec(key="distribution_pubkey", label="Distribution public key",
                     placeholder="GA…", env_var="STELLAR_DISTRIBUTION_PUBKEY"),
            FieldSpec(key="distribution_secret", label="Distribution secret",
                     secret=True, required=False,
                     env_var="STELLAR_DISTRIBUTION_SECRET"),
            FieldSpec(key="network_passphrase", label="Network passphrase",
                     placeholder="Public Global Stellar Network ; September 2015",
                     env_var="STELLAR_NETWORK_PASSPHRASE"),
            FieldSpec(key="horizon_url", label="Horizon URL",
                     placeholder="https://horizon.stellar.org",
                     env_var="STELLAR_HORIZON_URL"),
        ]),
    ProviderSpec(
        provider="alfredpay", name="AlfredPay", category="onramp",
        description="Rampas fiat↔crypto. Onramp (DEPOSITO en ARS/USD → PUSD) + offramp (PUSD → fiat).",
        supports_mode=True, supports_test=False, badge_color="success",
        docs_default=[{"title": "AlfredPay API (pendiente)",
                       "url": "https://docs.alfredpay.com"}],
        fields=[
            FieldSpec(key="api_key", label="API key", secret=True,
                     env_var="ALFREDPAY_API_KEY"),
            FieldSpec(key="base_url", label="Base URL",
                     placeholder="https://api.alfredpay.com/v1",
                     env_var="ALFREDPAY_BASE_URL"),
            FieldSpec(key="webhook_secret", label="Webhook secret",
                     secret=True, env_var="ALFREDPAY_WEBHOOK_SECRET"),
            FieldSpec(key="supported_currencies", label="Monedas soportadas (csv)",
                     required=False, placeholder="ARS,USD,USDT"),
        ]),
    ProviderSpec(
        provider="slack", name="Slack", category="notifications",
        description="Notificaciones de compliance (alertas critical, decisiones KYB/KYC, reportes).",
        supports_test=True, badge_color="warning",
        docs_default=[{"title": "Slack incoming webhooks",
                       "url": "https://api.slack.com/messaging/webhooks"}],
        fields=[
            FieldSpec(key="webhook_url", label="Incoming webhook URL",
                     secret=True, env_var="SLACK_WEBHOOK_URL",
                     placeholder="https://hooks.slack.com/services/T…/B…/…"),
            FieldSpec(key="default_channel", label="Canal default",
                     required=False, placeholder="#prosper-compliance"),
            FieldSpec(key="severities_to_notify",
                     label="Severidades que disparan envío (csv)",
                     required=False, placeholder="critical,warning"),
        ]),
    ProviderSpec(
        provider="stripe", name="Stripe", category="payments",
        description="Procesador de pagos · ya configurado con test key en preview.",
        supports_mode=True, supports_test=False, badge_color="primary",
        docs_default=[{"title": "Stripe API reference",
                       "url": "https://stripe.com/docs/api"}],
        fields=[
            FieldSpec(key="api_key", label="Secret key", secret=True,
                     env_var="STRIPE_API_KEY"),
            FieldSpec(key="publishable_key", label="Publishable key",
                     env_var="STRIPE_PUBLISHABLE_KEY", required=False),
            FieldSpec(key="webhook_secret", label="Webhook secret",
                     secret=True, env_var="STRIPE_WEBHOOK_SECRET", required=False),
        ]),
]
CATALOG_BY_PROVIDER = {p.provider: p for p in CATALOG}


# ---------------------------------------------------------------------------
# Lookup helper used by other modules
# ---------------------------------------------------------------------------
async def setting_value(provider: str, key: str) -> Optional[str]:
    spec = CATALOG_BY_PROVIDER.get(provider)
    if not spec:
        return None
    field = next((f for f in spec.fields if f.key == key), None)
    if not field:
        return None
    # Env precedence
    if field.env_var:
        v = os.environ.get(field.env_var)
        if v: return v
    # DB fallback
    doc = await col(INTEGRATION_SETTINGS).find_one({"provider": provider}, {"_id": 0})
    if doc and doc.get("fields"):
        return (doc["fields"] or {}).get(key) or None
    return None


# ---------------------------------------------------------------------------
# Internal: assemble effective values + status for a provider
# ---------------------------------------------------------------------------
async def _provider_view(spec: ProviderSpec) -> dict:
    doc = await col(INTEGRATION_SETTINGS).find_one({"provider": spec.provider}, {"_id": 0}) or {}
    db_fields = doc.get("fields") or {}
    fields_out = []
    filled = 0
    for f in spec.fields:
        env_val = os.environ.get(f.env_var) if f.env_var else None
        raw_db  = db_fields.get(f.key)
        source  = "env" if env_val else ("db" if raw_db else None)
        value   = env_val or raw_db
        display = _mask(value) if f.secret else (value or None)
        if value: filled += 1
        fields_out.append({
            "key":      f.key,
            "label":    f.label,
            "required": f.required,
            "secret":   f.secret,
            "placeholder": f.placeholder,
            "env_var":  f.env_var,
            "help":     f.help,
            "value":    display,
            "source":   source,        # env | db | None
            "is_set":   bool(value),
        })

    required_total = sum(1 for f in spec.fields if f.required)
    required_filled = sum(1 for f in spec.fields
                          if f.required and any(
                              o["is_set"] for o in fields_out if o["key"] == f.key))
    if required_filled == required_total and required_total > 0:
        status = "active"
    elif required_filled > 0:
        status = "partial"
    else:
        status = "missing"

    return {
        "provider":     spec.provider,
        "name":         spec.name,
        "category":     spec.category,
        "description":  spec.description,
        "supports_mode": spec.supports_mode,
        "supports_test": spec.supports_test,
        "badge_color":  spec.badge_color,
        "status":       status,
        "mode":         doc.get("mode", "sandbox"),
        "fields":       fields_out,
        "docs":         doc.get("docs") or list(spec.docs_default),
        "notes":        doc.get("notes", ""),
        "last_test":    doc.get("last_test"),
        "updated_at":   doc.get("updated_at"),
        "updated_by":   doc.get("updated_by"),
        "required_filled": required_filled,
        "required_total":  required_total,
        "filled_total":    filled,
        "fields_total":    len(spec.fields),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/integrations")
async def list_integrations(_: CurrentUser = Depends(require_super)):
    items = [await _provider_view(p) for p in CATALOG]
    return {"items": items, "total": len(items)}


@router.get("/integrations/{provider}")
async def get_integration(provider: str, _: CurrentUser = Depends(require_super)):
    spec = CATALOG_BY_PROVIDER.get(provider)
    if not spec:
        raise HTTPException(404, f"Provider {provider} not in catalog")
    return await _provider_view(spec)


class DocLink(BaseModel):
    title: str
    url: str


class IntegrationPatch(BaseModel):
    fields: Optional[Dict[str, Any]] = None
    mode:   Optional[Literal["sandbox", "live"]] = None
    docs:   Optional[List[DocLink]] = None
    notes:  Optional[str] = None


@router.patch("/integrations/{provider}")
async def patch_integration(provider: str, body: IntegrationPatch,
                             user: CurrentUser = Depends(require_super)):
    spec = CATALOG_BY_PROVIDER.get(provider)
    if not spec:
        raise HTTPException(404, f"Provider {provider} not in catalog")
    valid_keys = {f.key for f in spec.fields}
    cleaned = body.model_dump(exclude_none=True)

    # Merge fields with existing DB doc (so a partial PATCH doesn't wipe stored secrets)
    existing = await col(INTEGRATION_SETTINGS).find_one(
        {"provider": provider}, {"_id": 0}) or {}
    new_fields = dict(existing.get("fields") or {})
    if "fields" in cleaned:
        # Reject masked sentinel values — frontend sends them when the secret
        # wasn't touched. We don't want to overwrite the stored secret with
        # the mask.
        for k, v in cleaned["fields"].items():
            if k not in valid_keys: continue
            if isinstance(v, str) and v.startswith("••••"): continue
            if v in ("", None):
                new_fields.pop(k, None)
            else:
                new_fields[k] = v
        cleaned["fields"] = new_fields

    if "docs" in cleaned:
        cleaned["docs"] = [d if isinstance(d, dict) else d.model_dump()
                            for d in cleaned["docs"]]

    cleaned.update({
        "provider":   provider,
        "updated_at": _now(),
        "updated_by": user.email,
    })
    await col(INTEGRATION_SETTINGS).update_one(
        {"provider": provider},
        {"$set": cleaned, "$setOnInsert": {"created_at": _now()}},
        upsert=True)

    audit_meta = {
        "changed_fields": list((body.fields or {}).keys()),  # KEY NAMES ONLY
        "mode": body.mode, "docs_count": len(body.docs or []),
    }
    await log_action(actor=user, action="settings.integration_patched",
                     resource_type="integration", resource_id=provider,
                     metadata=audit_meta)
    return await _provider_view(spec)


# ---------------------------------------------------------------------------
# Test connection — per-provider live probe
# ---------------------------------------------------------------------------
class TestResult(BaseModel):
    ok: bool
    message: str
    status_code: Optional[int] = None
    details: Optional[Dict[str, Any]] = None


async def _test_aiprise() -> TestResult:
    key = await setting_value("aiprise", "api_key_sandbox") \
       or await setting_value("aiprise", "api_key_production")
    if not key:
        return TestResult(ok=False, message="No API key configured")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://api.aiprise.com/v1/healthz",
                             headers={"Authorization": f"Bearer {key}"})
            return TestResult(ok=r.status_code < 500,
                               message=f"AiPrise responded {r.status_code}",
                               status_code=r.status_code)
    except Exception as e:
        return TestResult(ok=False, message=f"Network error: {e}")


async def _test_trm() -> TestResult:
    from integrations.trm_labs import screen_wallet
    res = await screen_wallet("GAXTSTGAXTSTGAXTSTGAXTSTGAXTSTGAXTSTGAXTSTGAXTSTGAXTST", "stellar")
    if res.get("status") == "unavailable":
        return TestResult(ok=False, message=res.get("error_reason") or "Unavailable",
                           details={"status": "unavailable"})
    if res.get("status") == "success":
        return TestResult(ok=True, message="TRM screened a sample address OK",
                           details={"risk_score": res.get("risk_score")})
    return TestResult(ok=False, message=res.get("error_reason") or res.get("status") or "unknown",
                       details={"status": res.get("status")})


async def _test_resend() -> TestResult:
    key = await setting_value("resend", "api_key")
    if not key:
        return TestResult(ok=False, message="No API key configured")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://api.resend.com/domains",
                             headers={"Authorization": f"Bearer {key}"})
            if r.status_code == 200:
                domains = (r.json() or {}).get("data") or []
                return TestResult(ok=True,
                    message=f"Resend OK · {len(domains)} domain(s) registered",
                    status_code=200,
                    details={"domains": [d.get("name") for d in domains]})
            return TestResult(ok=False,
                message=f"Resend responded {r.status_code}", status_code=r.status_code)
    except Exception as e:
        return TestResult(ok=False, message=f"Network error: {e}")


async def _test_slack() -> TestResult:
    url = await setting_value("slack", "webhook_url")
    if not url:
        return TestResult(ok=False, message="No webhook URL configured")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(url, json={
                "text": ":wave: Prosper · test message desde /admin/settings/integrations"})
            return TestResult(ok=r.status_code == 200,
                               message=f"Slack responded {r.status_code} · "
                                       f"({'message posted' if r.status_code == 200 else 'failed'})",
                               status_code=r.status_code)
    except Exception as e:
        return TestResult(ok=False, message=f"Network error: {e}")


TESTERS = {
    "aiprise": _test_aiprise,
    "trm":     _test_trm,
    "resend":  _test_resend,
    "slack":   _test_slack,
}


@router.post("/integrations/{provider}/test")
async def test_integration(provider: str, user: CurrentUser = Depends(require_super)):
    spec = CATALOG_BY_PROVIDER.get(provider)
    if not spec:
        raise HTTPException(404, "Provider not in catalog")
    if not spec.supports_test:
        raise HTTPException(400, "Provider does not support test connection")
    fn = TESTERS.get(provider)
    if not fn:
        raise HTTPException(400, "No tester implemented for this provider")
    result = await fn()
    record = {**result.model_dump(), "tested_at": _now(), "tested_by": user.email}
    await col(INTEGRATION_SETTINGS).update_one(
        {"provider": provider},
        {"$set": {"last_test": record, "provider": provider,
                  "updated_at": _now()}},
        upsert=True)
    await log_action(actor=user, action="settings.integration_tested",
                     resource_type="integration", resource_id=provider,
                     metadata={"ok": result.ok, "status_code": result.status_code})
    return record

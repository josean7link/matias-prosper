"""Sprint 11B — Client portal · Profile hardening.

Endpoints (all scoped to the authenticated user's own org/user):
  - PATCH  /v1/client/profile              extended fields (phone/lang/tz/full_name)
  - POST   /v1/client/avatar               base64 image upload (≤256KB)
  - DELETE /v1/client/avatar

  MFA (TOTP):
  - POST   /v1/client/mfa/setup            generate secret + provisioning_uri + QR
  - POST   /v1/client/mfa/verify           verify the first code, persist secret
                                            (encrypted Fernet) + return backup codes
  - POST   /v1/client/mfa/disable          disable MFA (requires current code or backup)
  - POST   /v1/client/mfa/regenerate-codes regenerate backup codes (requires code)

  Sessions:
  - GET    /v1/client/sessions             list user's active sessions
  - DELETE /v1/client/sessions/{id}        revoke single session
  - POST   /v1/client/sessions/revoke-others   revoke every session except current

  Notifications:
  - GET    /v1/client/notifications
  - PATCH  /v1/client/notifications

  Account deletion (with 7-day cooldown):
  - POST   /v1/client/account/request-deletion
  - POST   /v1/client/account/cancel-deletion
"""
from __future__ import annotations
import base64, io, secrets as _s, hashlib
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional

import pyotp, qrcode
import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from audit import log_action
from auth import CurrentUser, get_current_user
from db import col, ORGANIZATIONS, SESSIONS, USERS
from services.secret_box import SecretBox, SecretBoxError

router = APIRouter(prefix="/client", tags=["client-profile"])


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Helpers: TOTP secret at rest (SecretBox) + bcrypt for backup codes
#
# Fase 0.5.1: the dual-key Fernet logic (current + previous key, needed so
# a rotation does not break users with `mfa_pending`) now lives in
# `services/secret_box.py`. This route only maps SecretBoxError → HTTP 500.
# ---------------------------------------------------------------------------
_MFA_BOX = SecretBox("MFA_FERNET_KEY", "MFA_FERNET_KEY_PREVIOUS")


def _encrypt(plaintext: str) -> str:
    try:
        return _MFA_BOX.encrypt(plaintext)
    except SecretBoxError as e:
        raise HTTPException(500, str(e))


def _decrypt(ciphertext: str) -> str:
    try:
        return _MFA_BOX.decrypt(ciphertext)
    except SecretBoxError:
        raise HTTPException(500, "Failed to decrypt MFA secret")


def _hash_backup_code(code: str) -> str:
    return bcrypt.hashpw(code.encode("utf-8"),
                          bcrypt.gensalt(rounds=10)).decode("utf-8")


def _verify_backup_code(code: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(code.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _new_backup_codes(count: int = 10) -> list[str]:
    """Format: XXXX-XXXX (uppercase alphanumeric, 8 chars total + dash)."""
    import string
    alphabet = string.ascii_uppercase + string.digits
    out: list[str] = []
    while len(out) < count:
        code = "".join(_s.choice(alphabet) for _ in range(8))
        formatted = f"{code[:4]}-{code[4:]}"
        if formatted not in out:
            out.append(formatted)
    return out


async def _load_user(user_id: str) -> dict:
    user = await col(USERS).find_one({"user_id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(404, "User not found")
    return user


# ===========================================================================
# PROFILE — extended fields
# ===========================================================================
LANGUAGES = ("es", "en", "pt")
TIMEZONES_WHITELIST = (
    "America/Argentina/Buenos_Aires", "America/Sao_Paulo", "America/Santiago",
    "America/Bogota", "America/Mexico_City", "America/Lima", "America/Montevideo",
    "America/New_York", "America/Los_Angeles", "Europe/Madrid", "Europe/London",
    "UTC",
)


class ProfileIn(BaseModel):
    full_name:   Optional[str] = Field(None, max_length=80)
    phone:       Optional[str] = Field(None, max_length=24)
    language:    Optional[Literal["es", "en", "pt"]] = None
    timezone:    Optional[str] = Field(None, max_length=64)


@router.get("/profile")
async def get_profile(user: CurrentUser = Depends(get_current_user)):
    u = await _load_user(user.user_id)
    prefs = u.get("preferences") or {}
    return {
        "user_id":    u["user_id"],
        "email":      u["email"],
        "full_name":  u.get("full_name") or "",
        "phone":      u.get("phone") or "",
        "language":   prefs.get("language") or "es",
        "timezone":   prefs.get("timezone") or "America/Argentina/Buenos_Aires",
        "avatar_url": u.get("avatar_url"),
        "mfa_enabled": bool(u.get("mfa_enabled")),
        "notifications": u.get("notifications") or _default_notifs(),
        "deletion_requested": bool(u.get("deletion_requested")),
        "deletion_effective_at": u.get("deletion_effective_at"),
        "role":       u.get("role"),
        "org_id":     u.get("org_id"),
    }


@router.patch("/profile")
async def patch_profile(body: ProfileIn,
                         user: CurrentUser = Depends(get_current_user)):
    updates: dict = {}
    if body.full_name is not None:
        updates["full_name"] = body.full_name.strip()
    if body.phone is not None:
        # Very forgiving: digits, +, -, space, parens
        p = body.phone.strip()
        if p and not all(c.isdigit() or c in "+-() " for c in p):
            raise HTTPException(400, "Teléfono inválido")
        updates["phone"] = p

    prefs_update: dict = {}
    if body.language is not None:
        prefs_update["language"] = body.language
    if body.timezone is not None:
        if body.timezone not in TIMEZONES_WHITELIST:
            raise HTTPException(400, "Timezone no soportado")
        prefs_update["timezone"] = body.timezone

    if prefs_update:
        existing = (await _load_user(user.user_id)).get("preferences") or {}
        existing.update(prefs_update)
        updates["preferences"] = existing
    if not updates:
        raise HTTPException(400, "Nada para actualizar")
    updates["updated_at"] = _iso_now()

    await col(USERS).update_one({"user_id": user.user_id}, {"$set": updates})
    await log_action(actor=user, action="client.profile.update",
                      resource_type="user", resource_id=user.user_id,
                      metadata={"fields": list(updates.keys())})
    return {"ok": True, "updated": list(updates.keys())}


# ===========================================================================
# AVATAR — base64 data URL (≤256 KB after decode)
# ===========================================================================
class AvatarIn(BaseModel):
    data_url: str  # data:image/png;base64,...


_MAX_AVATAR_BYTES = 256 * 1024


@router.post("/avatar")
async def upload_avatar(body: AvatarIn,
                         user: CurrentUser = Depends(get_current_user)):
    s = body.data_url.strip()
    if not s.startswith("data:image/"):
        raise HTTPException(400, "Se espera un data URL de imagen")
    try:
        header, b64 = s.split(",", 1)
        raw = base64.b64decode(b64, validate=True)
    except Exception:
        raise HTTPException(400, "Avatar inválido (base64)")
    if len(raw) > _MAX_AVATAR_BYTES:
        raise HTTPException(413, f"Avatar demasiado grande (máx {_MAX_AVATAR_BYTES // 1024} KB)")
    # Persist directly as data URL — keeps storage simple, no S3 dependency
    await col(USERS).update_one(
        {"user_id": user.user_id},
        {"$set": {"avatar_url": s, "updated_at": _iso_now()}})
    await log_action(actor=user, action="client.avatar.upload",
                      resource_type="user", resource_id=user.user_id,
                      metadata={"bytes": len(raw)})
    return {"ok": True, "avatar_url": s}


@router.delete("/avatar")
async def delete_avatar(user: CurrentUser = Depends(get_current_user)):
    await col(USERS).update_one(
        {"user_id": user.user_id},
        {"$set": {"avatar_url": None, "updated_at": _iso_now()}})
    await log_action(actor=user, action="client.avatar.delete",
                      resource_type="user", resource_id=user.user_id, metadata={})
    return {"ok": True}


# ===========================================================================
# MFA — TOTP
# ===========================================================================
TOTP_ISSUER = "Prosper"


def _qr_data_url(text: str) -> str:
    qr = qrcode.QRCode(version=1,
                        error_correction=qrcode.constants.ERROR_CORRECT_M,
                        box_size=6, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0B0F19", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


@router.post("/mfa/setup")
async def mfa_setup(user: CurrentUser = Depends(get_current_user)):
    """Generate a *new* TOTP secret. If MFA is already enabled, this rotates
    the secret only after the user successfully verifies a new code via
    /mfa/verify. The pending secret lives in `user.mfa_pending` (encrypted)
    until then.
    """
    u = await _load_user(user.user_id)
    secret = pyotp.random_base32()
    totp   = pyotp.TOTP(secret)
    uri    = totp.provisioning_uri(name=u["email"], issuer_name=TOTP_ISSUER)
    encrypted = _encrypt(secret)

    await col(USERS).update_one(
        {"user_id": user.user_id},
        {"$set": {"mfa_pending": encrypted, "updated_at": _iso_now()}})
    await log_action(actor=user, action="client.mfa.setup_init",
                      resource_type="user", resource_id=user.user_id, metadata={})

    return {
        "provisioning_uri": uri,
        "secret":           secret,        # shown once for manual entry fallback
        "qr_data_url":      _qr_data_url(uri),
        "issuer":           TOTP_ISSUER,
        "account":          u["email"],
        "algorithm":        "SHA1", "digits": 6, "period": 30,
    }


class MfaVerifyIn(BaseModel):
    code: str = Field(..., min_length=6, max_length=8, pattern=r"^[0-9]{6}$")


@router.post("/mfa/verify")
async def mfa_verify(body: MfaVerifyIn,
                      user: CurrentUser = Depends(get_current_user)):
    u = await _load_user(user.user_id)
    pending = u.get("mfa_pending")
    if not pending:
        raise HTTPException(400, "No hay enrolamiento MFA en curso. Llamá /mfa/setup primero.")
    secret = _decrypt(pending)
    totp = pyotp.TOTP(secret)
    if not totp.verify(body.code, valid_window=1):
        raise HTTPException(401, "Código inválido. Verificá la hora de tu dispositivo.")

    codes = _new_backup_codes(10)
    hashed = [_hash_backup_code(c) for c in codes]

    await col(USERS).update_one(
        {"user_id": user.user_id},
        {"$set": {"mfa_enabled":      True,
                    "mfa_secret":       pending,
                    "mfa_backup_codes": hashed,
                    "mfa_enrolled_at":  _iso_now(),
                    "updated_at":       _iso_now()},
          "$unset": {"mfa_pending": ""}})

    await log_action(actor=user, action="client.mfa.enabled",
                      resource_type="user", resource_id=user.user_id, metadata={})
    return {
        "ok": True,
        "backup_codes": codes,  # plaintext — only chance to save them
        "warning": "Guardá estos códigos de recuperación. No se vuelven a mostrar.",
    }


class MfaDisableIn(BaseModel):
    code:        Optional[str] = Field(None, pattern=r"^[0-9]{6}$")
    backup_code: Optional[str] = None


@router.post("/mfa/disable")
async def mfa_disable(body: MfaDisableIn,
                       user: CurrentUser = Depends(get_current_user)):
    u = await _load_user(user.user_id)
    if not u.get("mfa_enabled"):
        raise HTTPException(400, "MFA no está activo")
    if not (body.code or body.backup_code):
        raise HTTPException(400, "Necesitás tu código TOTP o un backup code")

    valid = False
    if body.code and u.get("mfa_secret"):
        totp = pyotp.TOTP(_decrypt(u["mfa_secret"]))
        valid = totp.verify(body.code, valid_window=1)
    if not valid and body.backup_code:
        valid, _hash = await _consume_backup(user.user_id, body.backup_code,
                                              u.get("mfa_backup_codes") or [])
    if not valid:
        raise HTTPException(401, "Código inválido")

    await col(USERS).update_one(
        {"user_id": user.user_id},
        {"$set": {"mfa_enabled": False, "updated_at": _iso_now()},
          "$unset": {"mfa_secret": "", "mfa_backup_codes": "",
                      "mfa_pending": "", "mfa_enrolled_at": ""}})
    await log_action(actor=user, action="client.mfa.disabled",
                      resource_type="user", resource_id=user.user_id, metadata={})
    return {"ok": True}


@router.post("/mfa/regenerate-codes")
async def mfa_regenerate_codes(body: MfaVerifyIn,
                                user: CurrentUser = Depends(get_current_user)):
    u = await _load_user(user.user_id)
    if not u.get("mfa_enabled"):
        raise HTTPException(400, "MFA no está activo")
    totp = pyotp.TOTP(_decrypt(u["mfa_secret"]))
    if not totp.verify(body.code, valid_window=1):
        raise HTTPException(401, "Código inválido")

    codes  = _new_backup_codes(10)
    hashed = [_hash_backup_code(c) for c in codes]
    await col(USERS).update_one(
        {"user_id": user.user_id},
        {"$set": {"mfa_backup_codes": hashed, "updated_at": _iso_now()}})
    await log_action(actor=user, action="client.mfa.codes_regenerated",
                      resource_type="user", resource_id=user.user_id, metadata={})
    return {"ok": True, "backup_codes": codes,
             "warning": "Estos códigos reemplazan a los anteriores."}


async def _consume_backup(user_id: str, code: str,
                            hashed_list: list[str]) -> tuple[bool, Optional[str]]:
    for h in hashed_list:
        if _verify_backup_code(code, h):
            await col(USERS).update_one(
                {"user_id": user_id},
                {"$pull": {"mfa_backup_codes": h}})
            return True, h
    return False, None


# ===========================================================================
# SESSIONS — list / revoke
# ===========================================================================
@router.get("/sessions")
async def list_sessions(user: CurrentUser = Depends(get_current_user)):
    rows = await col(SESSIONS).find(
        {"user_id": user.user_id, "is_deleted": False, "revoked": False},
        {"_id": 0}).sort("last_seen_at", -1).to_list(100)
    items = []
    for r in rows:
        items.append({
            "session_id":    r["session_id"],
            "label":         r.get("label") or "Sesión",
            "ip":            r.get("ip") or "—",
            "user_agent":    r.get("user_agent") or "",
            "created_at":    r.get("created_at"),
            "last_seen_at":  r.get("last_seen_at"),
            "expires_at":    r.get("expires_at"),
            "is_current":    r["session_id"] == user.jti,
        })
    return {"items": items, "total": len(items)}


@router.delete("/sessions/{session_id}")
async def revoke_session(session_id: str,
                          user: CurrentUser = Depends(get_current_user)):
    res = await col(SESSIONS).update_one(
        {"session_id": session_id, "user_id": user.user_id, "revoked": False},
        {"$set": {"revoked": True, "revoked_at": _iso_now(),
                    "revoke_reason": "user_revoked"}})
    if not res.matched_count:
        raise HTTPException(404, "Sesión no encontrada")
    await log_action(actor=user, action="client.session.revoke",
                      resource_type="session", resource_id=session_id, metadata={})
    return {"ok": True, "was_current": session_id == user.jti}


@router.post("/sessions/revoke-others")
async def revoke_other_sessions(user: CurrentUser = Depends(get_current_user)):
    q: dict = {"user_id": user.user_id, "revoked": False}
    if user.jti:
        q["session_id"] = {"$ne": user.jti}
    res = await col(SESSIONS).update_many(
        q, {"$set": {"revoked": True, "revoked_at": _iso_now(),
                       "revoke_reason": "revoke_others"}})
    await log_action(actor=user, action="client.session.revoke_others",
                      resource_type="user", resource_id=user.user_id,
                      metadata={"count": res.modified_count})
    return {"ok": True, "revoked": res.modified_count}


# ===========================================================================
# NOTIFICATIONS — simple boolean toggles
# ===========================================================================
def _default_notifs() -> dict:
    return {
        "email_security_alerts":   True,
        "email_account_activity":  True,
        "email_yield_summary":     True,
        "email_marketing":         False,
        "inapp_alerts":            True,
        "inapp_transactions":      True,
    }


class NotificationsIn(BaseModel):
    email_security_alerts:  Optional[bool] = None
    email_account_activity: Optional[bool] = None
    email_yield_summary:    Optional[bool] = None
    email_marketing:        Optional[bool] = None
    inapp_alerts:           Optional[bool] = None
    inapp_transactions:     Optional[bool] = None


@router.get("/notifications")
async def get_notifications(user: CurrentUser = Depends(get_current_user)):
    u = await _load_user(user.user_id)
    return u.get("notifications") or _default_notifs()


@router.patch("/notifications")
async def patch_notifications(body: NotificationsIn,
                                user: CurrentUser = Depends(get_current_user)):
    u = await _load_user(user.user_id)
    notifs = u.get("notifications") or _default_notifs()
    for k, v in body.model_dump(exclude_none=True).items():
        notifs[k] = bool(v)
    await col(USERS).update_one(
        {"user_id": user.user_id},
        {"$set": {"notifications": notifs, "updated_at": _iso_now()}})
    await log_action(actor=user, action="client.notifications.update",
                      resource_type="user", resource_id=user.user_id,
                      metadata={"keys": list(body.model_dump(exclude_none=True).keys())})
    return notifs


# ===========================================================================
# ACCOUNT DELETION — 7-day cooldown then ops processes manually
# ===========================================================================
class DeletionRequestIn(BaseModel):
    reason:        Optional[str] = Field(None, max_length=400)
    confirm_email: str


@router.post("/account/request-deletion")
async def request_deletion(body: DeletionRequestIn,
                            user: CurrentUser = Depends(get_current_user)):
    if body.confirm_email.strip().lower() != user.email.lower():
        raise HTTPException(400, "El email de confirmación no coincide")
    effective = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    await col(USERS).update_one(
        {"user_id": user.user_id},
        {"$set": {"deletion_requested":     True,
                    "deletion_requested_at": _iso_now(),
                    "deletion_effective_at": effective,
                    "deletion_reason":       (body.reason or "").strip(),
                    "updated_at":            _iso_now()}})
    # Alert ops via audit log (real email TBD via Resend phase 12)
    await log_action(actor=user, action="client.account.deletion_requested",
                      resource_type="user", resource_id=user.user_id,
                      metadata={"reason": (body.reason or "")[:200],
                                  "effective_at": effective})
    return {"ok": True, "effective_at": effective,
             "message": "Tu cuenta será eliminada en 7 días salvo que canceles la solicitud."}


@router.post("/account/cancel-deletion")
async def cancel_deletion(user: CurrentUser = Depends(get_current_user)):
    u = await _load_user(user.user_id)
    if not u.get("deletion_requested"):
        raise HTTPException(400, "No hay una solicitud de eliminación pendiente")
    await col(USERS).update_one(
        {"user_id": user.user_id},
        {"$set": {"deletion_requested": False, "updated_at": _iso_now()},
          "$unset": {"deletion_requested_at": "", "deletion_effective_at": "",
                      "deletion_reason": ""}})
    await log_action(actor=user, action="client.account.deletion_cancelled",
                      resource_type="user", resource_id=user.user_id, metadata={})
    return {"ok": True}

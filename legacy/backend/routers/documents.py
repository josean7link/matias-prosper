"""Auto-split from routers.py (2026-04-20). Domain: documents."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Response, Request, UploadFile, File, Form, Header
from pydantic import BaseModel
import hashlib
import secrets
import uuid

from db import (
    col, ORGANIZATIONS, ONBOARDING, COMPLIANCE, FUNDS, PRODUCTS, NAV_SNAPSHOTS,
    TREASURY, POSITIONS, TRANSACTIONS, RECONCILIATION, API_APPS, API_KEYS,
    WEBHOOK_ENDPOINTS, WEBHOOK_DELIVERIES, ALERTS, REPORTS, AUDIT_LOGS,
    END_CUSTOMERS, ORG_USERS, USERS, SESSIONS, APPROVALS, IDEMPOTENCY, DOCUMENTS
)
from models import (
    User, Organization, OnboardingCase, ComplianceReview, Fund, Product,
    NavSnapshot, Position, TreasuryAccount, Transaction, ReconciliationRecord,
    ApiApp, ApiKey, WebhookEndpoint, WebhookDelivery, Alert, Report, AuditLog,
    EndCustomer, OrgUser, now_utc, new_id
)
from auth import (
    get_current_user, require_roles, exchange_session, upsert_user,
    create_session, delete_session,
)
import prosper_client
import seed as seed_module
import approvals as approvals_mod
import mfa as mfa_mod
import webhook_signing
import storage as storage_mod
from ._helpers import _strip_id, _log_audit, _user_scope, _apply_scope


# ==========================================================================
# DOCUMENTS (KYC / KYB via Emergent Object Storage)
# ==========================================================================


# ============================================================================
# DOCUMENTS (KYC / KYB uploads via Emergent Object Storage)
# ============================================================================
docs_router = APIRouter(prefix="/documents", tags=["documents"])

_ALLOWED_EXTS = {"pdf", "png", "jpg", "jpeg", "webp", "csv"}
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB

# Magic bytes (file signatures) for each allowed format — verified against the first
# bytes of the uploaded payload to defeat renamed/spoofed files.
_MAGIC_BYTES = {
    "pdf":  [b"%PDF-"],
    "png":  [b"\x89PNG\r\n\x1a\n"],
    "jpg":  [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
    "webp": [b"RIFF"],  # + "WEBP" at offset 8 (checked below)
    # csv has no reliable signature; we validate with a utf-8 decode heuristic instead.
}


def _sniff_matches(ext: str, data: bytes) -> bool:
    """Return True if the first bytes of `data` match the expected signature for `ext`."""
    if ext == "csv":
        # Accept only valid utf-8 (or ascii) text with no NUL bytes in the first 4 KB
        sample = data[:4096]
        if b"\x00" in sample:
            return False
        try:
            sample.decode("utf-8")
            return True
        except UnicodeDecodeError:
            return False
    if ext == "webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    sigs = _MAGIC_BYTES.get(ext, [])
    return any(data.startswith(sig) for sig in sigs)


def _can_view_doc(user: User, doc: dict) -> bool:
    if user.is_internal or user.platform_role == "super_admin":
        return True
    return bool(user.org_id) and doc.get("org_id") == user.org_id


@docs_router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    org_id: Optional[str] = Form(None),
    case_id: Optional[str] = Form(None),
    doc_type: str = Form("kyc"),
    user: User = Depends(get_current_user),
):
    """Upload a KYC/KYB document. Non-internal users may only upload to their own org."""
    # Resolve target org
    target_org = org_id or user.org_id
    if not target_org:
        raise HTTPException(400, "org_id is required")
    if not user.is_internal and user.platform_role != "super_admin":
        if target_org != user.org_id:
            raise HTTPException(403, "Cannot upload to another organization")

    ext = (file.filename.rsplit(".", 1)[-1] if "." in (file.filename or "") else "").lower()
    if ext not in _ALLOWED_EXTS:
        raise HTTPException(400, f"File type .{ext} not allowed")

    data = await file.read()
    if len(data) > _MAX_BYTES:
        raise HTTPException(413, "File exceeds 10MB limit")
    if len(data) == 0:
        raise HTTPException(400, "Empty file")

    # Defense in depth: reject files whose magic bytes don't match the extension
    if not _sniff_matches(ext, data):
        raise HTTPException(400, f"File content does not match .{ext} signature")

    content_type = file.content_type or storage_mod.guess_mime(file.filename or "")
    doc_id = f"doc_{new_id()}"
    storage_path = f"{storage_mod.APP_NAME}/kyc/{target_org}/{doc_id}.{ext}"

    try:
        result = await storage_mod.put_object(storage_path, data, content_type)
    except Exception as e:
        raise HTTPException(502, f"Storage upload failed: {e}")

    record = {
        "document_id": doc_id,
        "org_id": target_org,
        "case_id": case_id,
        "doc_type": doc_type,  # kyc | kyb | contract | other
        "original_filename": file.filename,
        "storage_path": result.get("path", storage_path),
        "content_type": content_type,
        "size": result.get("size", len(data)),
        "uploaded_by": user.user_id,
        "uploaded_by_email": user.email,
        "is_deleted": False,
        "created_at": now_utc().isoformat(),
    }
    await col(DOCUMENTS).insert_one(dict(record))
    await _log_audit(user, "document.uploaded", "document", doc_id,
                     metadata={"org_id": target_org, "doc_type": doc_type, "size": record["size"]})
    record.pop("_id", None)
    return record


@docs_router.get("")
async def list_documents(
    org_id: Optional[str] = None,
    case_id: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    q: Dict[str, Any] = {"is_deleted": False}
    if case_id:
        q["case_id"] = case_id
    if org_id:
        q["org_id"] = org_id
    # Scope: non-internal users may only list their own org's docs
    if not user.is_internal and user.platform_role != "super_admin":
        q["org_id"] = user.org_id or "__none__"
    items = await col(DOCUMENTS).find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"items": items, "total": len(items)}


@docs_router.get("/{document_id}/download")
async def download_document(
    document_id: str,
    auth: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    user: User = Depends(get_current_user),
):
    doc = await col(DOCUMENTS).find_one({"document_id": document_id, "is_deleted": False}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Document not found")
    if not _can_view_doc(user, doc):
        raise HTTPException(403, "Not authorized to view this document")
    try:
        data, _ct = await storage_mod.get_object(doc["storage_path"])
    except Exception as e:
        raise HTTPException(502, f"Storage fetch failed: {e}")
    return Response(
        content=data,
        media_type=doc.get("content_type", "application/octet-stream"),
        headers={"Content-Disposition": f'inline; filename="{doc.get("original_filename", document_id)}"'},
    )


@docs_router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    user: User = Depends(get_current_user),
):
    doc = await col(DOCUMENTS).find_one({"document_id": document_id, "is_deleted": False}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Document not found")
    if not _can_view_doc(user, doc):
        raise HTTPException(403, "Not authorized")
    await col(DOCUMENTS).update_one(
        {"document_id": document_id},
        {"$set": {"is_deleted": True, "deleted_at": now_utc().isoformat(), "deleted_by": user.user_id}},
    )
    await _log_audit(user, "document.deleted", "document", document_id)
    return {"ok": True}


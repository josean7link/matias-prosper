"""Self-service KYC docs upload for individuals — Phase 22+ widget.

POST /api/v1/client/me/andes-kyc-docs

Authenticated client_admin endpoint. Lets an individual user upload the
3 KYC docs (face, id_front, id_back) directly from the portal to unblock
themselves when their ramp_account is in `kyc_docs_required` (or the
deprecated alias `kyc_pending_andes`).

Backed by `services.andes_kyc.submit_andes_kyc_docs` which reuses the
already-provisioned Andes `provider_user_id`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from auth import CurrentUser, get_current_user
from db import col, RAMP_ACCOUNTS, ORGANIZATIONS
from services.andes_kyc import submit_andes_kyc_docs, AndesKycError

router = APIRouter(prefix="/client/me", tags=["client-kyc"])

_ALLOWED_STATES = {"kyc_docs_required", "kyc_pending_andes",
                    "kyc_docs_submitted"}


@router.post("/andes-kyc-docs")
async def client_submit_andes_kyc_docs(
    face: UploadFile = File(...),
    id_front: UploadFile = File(...),
    id_back: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
):
    org_id = user.org_id
    if not org_id:
        raise HTTPException(403, "No org scope on token")

    # Gate: org must be personal.
    org_doc = await col(ORGANIZATIONS).find_one(
        {"org_id": org_id}, {"_id": 0, "type": 1}) or {}
    if org_doc.get("type") != "personal":
        raise HTTPException(409, {"detail": "individual_only",
            "message": "Este flujo es para personas. Las cuentas business "
                       "tienen otro proceso — contactá soporte."})

    # Gate: ramp_account must be in a state that accepts re-upload.
    ramp = await col(RAMP_ACCOUNTS).find_one(
        {"org_id": org_id}, {"_id": 0, "onboarding_status": 1}) or {}
    state = ramp.get("onboarding_status")
    if state == "approved":
        raise HTTPException(409, "Tu cuenta ya está activa. No necesitás "
                                 "subir documentos.")
    if state not in _ALLOWED_STATES:
        raise HTTPException(409,
            f"Tu cuenta está en estado '{state}'. Este flujo solo aplica "
            f"si necesitamos tus documentos de identidad para Andes.")

    # Read files into memory (small, ≤10MB each).
    files_payload = {}
    for name, up in (("face", face), ("id_front", id_front),
                     ("id_back", id_back)):
        content = await up.read()
        files_payload[name] = (up.filename or f"{name}.jpg",
                                content,
                                up.content_type or "image/jpeg")

    try:
        return await submit_andes_kyc_docs(
            org_id=org_id, files=files_payload, actor=user,
            source="client_widget")
    except AndesKycError as e:
        # Always surface message; retryable flag goes in body.
        raise HTTPException(e.status, {"message": e.message,
                                         "retryable": e.retryable})

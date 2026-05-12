"""/ops-queue — Operations queue digest (approvals / KYB / alerts / webhooks / recon).

Webhook + reconciliation counts are placeholder zeroes until those modules ship
(Phase 4 / Phase 6). The shape is stable so the UI doesn't have to change.
"""
from fastapi import APIRouter, Depends

from auth import CurrentUser
from db import col, ALERTS, APPROVALS, ORGANIZATIONS

from ._deps import iso, require_dashboard, utc_now

router = APIRouter()


async def build_ops_queue() -> dict:
    """Pure function — also used by the WebSocket pusher."""
    appr_count = await col(APPROVALS).count_documents(
        {"status": "pending", "is_deleted": False})
    appr_top = await col(APPROVALS).find(
        {"status": "pending", "is_deleted": False}, {"_id": 0}
    ).sort("created_at", 1).to_list(3)

    al_count = await col(ALERTS).count_documents(
        {"status": "open", "is_deleted": False})
    al_top = await col(ALERTS).find(
        {"status": "open", "is_deleted": False}, {"_id": 0}
    ).sort("created_at", -1).to_list(3)

    kyb_count = await col(ORGANIZATIONS).count_documents(
        {"kyb_status": {"$in": ["pending", "in_review"]}, "is_deleted": False})
    kyb_top = await col(ORGANIZATIONS).find(
        {"kyb_status": {"$in": ["pending", "in_review"]}, "is_deleted": False},
        {"_id": 0, "org_id": 1, "commercial_name": 1, "kyb_status": 1, "created_at": 1},
    ).sort("created_at", 1).to_list(3)

    # TODO Phase 4 — webhook delivery module · Phase 6 — treasury reconciliation
    webhook_fail_count = 0
    recon_unmatched_count = 0

    return {
        "approvals":       {"count": appr_count, "items": appr_top},
        "kyb":             {"count": kyb_count,  "items": kyb_top},
        "alerts":          {"count": al_count,   "items": al_top},
        "webhook_failing": {"count": webhook_fail_count, "items": []},
        "reconciliation":  {"count": recon_unmatched_count, "items": []},
        "generated_at":    iso(utc_now()),
    }


@router.get("/ops-queue")
async def get_ops_queue(_: CurrentUser = Depends(require_dashboard)):
    return await build_ops_queue()

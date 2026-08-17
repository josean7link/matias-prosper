"""Tests de `apply_transition` (capa persistente) — EN BASE SCRATCH.

Confirma en particular que la reapertura especial rejected →
under_review de super_admin pasa por `apply_transition` y queda
auditada (kyb.case.state_changed), aunque esté fuera del grafo normal.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_SCRATCH_DB = "prosper_kyb_tests_transitions"
_ORIG_DB_NAME = os.environ.get("DB_NAME")

import db as db_module                                        # noqa: E402
from kyb.state_machine import (ForbiddenTransitionError,       # noqa: E402
                               apply_transition)


@pytest_asyncio.fixture()
async def _scratch():
    os.environ["DB_NAME"] = _SCRATCH_DB
    db_module._client = None
    admin = AsyncIOMotorClient(os.environ["MONGO_URL"])
    await admin.drop_database(_SCRATCH_DB)
    try:
        yield db_module.db()
    finally:
        await admin.drop_database(_SCRATCH_DB)
        admin.close()
        if _ORIG_DB_NAME is not None:
            os.environ["DB_NAME"] = _ORIG_DB_NAME
        else:
            os.environ.pop("DB_NAME", None)
        db_module._client = None


def _case(status: str) -> dict:
    return {"case_id": "kyb_trans_test", "org_id": "org_fake_t",
            "status": status, "is_deleted": False,
            "created_at": "2026-06-01T00:00:00+00:00",
            "updated_at": "2026-06-01T00:00:00+00:00"}


@pytest.mark.asyncio
async def test_rejected_reopen_by_super_admin_is_applied_and_audited(_scratch):
    d = _scratch
    await d["kyb_cases"].insert_one(_case("rejected"))
    case = await d["kyb_cases"].find_one({"case_id": "kyb_trans_test"})

    fields = await apply_transition(case, "under_review",
                                    actor_type="internal",
                                    actor_role="super_admin")
    assert fields["status"] == "under_review"

    doc = await d["kyb_cases"].find_one({"case_id": "kyb_trans_test"})
    assert doc["status"] == "under_review"

    audits = await d["audit_logs"].find(
        {"action": "kyb.case.state_changed"}).to_list(10)
    assert len(audits) == 1
    meta = audits[0]["metadata"]
    assert meta["from"] == "rejected" and meta["to"] == "under_review"
    assert meta["actor_type"] == "internal"
    assert audits[0]["resource_id"] == "kyb_trans_test"
    assert audits[0]["org_id"] == "org_fake_t"


@pytest.mark.asyncio
async def test_rejected_reopen_denied_for_non_super_admin(_scratch):
    d = _scratch
    await d["kyb_cases"].insert_one(_case("rejected"))
    case = await d["kyb_cases"].find_one({"case_id": "kyb_trans_test"})

    with pytest.raises(ForbiddenTransitionError):
        await apply_transition(case, "under_review",
                               actor_type="internal", actor_role="admin")
    # Nada persistido, nada auditado.
    doc = await d["kyb_cases"].find_one({"case_id": "kyb_trans_test"})
    assert doc["status"] == "rejected"
    assert await d["audit_logs"].count_documents({}) == 0


@pytest.mark.asyncio
async def test_normal_transition_is_audited(_scratch):
    d = _scratch
    await d["kyb_cases"].insert_one(_case("approved"))
    case = await d["kyb_cases"].find_one({"case_id": "kyb_trans_test"})

    fields = await apply_transition(case, "under_review",
                                    actor_type="system",
                                    reopen_reason="provider_alert")
    assert fields["reopen_reason"] == "provider_alert"
    doc = await d["kyb_cases"].find_one({"case_id": "kyb_trans_test"})
    assert doc["status"] == "under_review"
    assert doc["reopen_reason"] == "provider_alert"
    audits = await d["audit_logs"].find(
        {"action": "kyb.case.state_changed"}).to_list(10)
    assert len(audits) == 1
    assert audits[0]["metadata"]["reopen_reason"] == "provider_alert"
    assert audits[0]["metadata"]["actor_type"] == "system"

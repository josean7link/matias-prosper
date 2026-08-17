"""Tests de la migración KYB legacy (Fase 1) — EN BASE SCRATCH.

Corre íntegramente contra `prosper_kyb_tests_migration` (drop al inicio
y al final, incluso si un test falla). NUNCA toca la base real: ni
kyb_cases de producción, ni audit_logs de producción.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_SCRATCH_DB = "prosper_kyb_tests_migration"
_ORIG_DB_NAME = os.environ.get("DB_NAME")

import db as db_module                                        # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from migrate_legacy_kyb import (BACKUP_COLLECTION,             # noqa: E402
                                build_migrated_doc, migrate)


FAKE_SEEDS = ["kyb_test_seed_a", "kyb_test_seed_b"]
FAKE_REALS = ["kyb_test_apply_x", "kyb_test_apply_y"]


def _seed_doc(cid: str) -> dict:
    return {"case_id": cid, "org_id": None, "status": "pending",
            "legal_name": f"Seed {cid}", "is_deleted": False,
            "created_at": "2026-05-01T00:00:00+00:00",
            "updated_at": "2026-05-01T00:00:00+00:00"}


def _real_doc(cid: str, status: str) -> dict:
    return {"case_id": cid, "org_id": f"org_fake_{cid}", "status": status,
            "legal_name": f"Corp {cid}", "country": "AR",
            "applied_at": "2026-05-14T10:00:00+00:00",
            "checklist": [{"key": "k1", "checked": True}],
            "ubos": [{"name": "U"}], "provider": "self_apply",
            "decision_reason": "texto legacy", "is_deleted": False,
            "created_at": "2026-05-14T10:00:00+00:00",
            "updated_at": "2026-05-14T10:00:00+00:00"}


@pytest_asyncio.fixture()
async def _scratch():
    """Base scratch dedicada + cleanup garantizado (drop en teardown,
    corra lo que corra el test)."""
    os.environ["DB_NAME"] = _SCRATCH_DB
    db_module._client = None
    admin = AsyncIOMotorClient(os.environ["MONGO_URL"])
    await admin.drop_database(_SCRATCH_DB)
    d = db_module.db()
    # Seed: casos fake + respaldo fake (para ejercitar verify_backup).
    await d["kyb_cases"].insert_many(
        [_seed_doc(c) for c in FAKE_SEEDS]
        + [_real_doc(FAKE_REALS[0], "in_review"),
           _real_doc(FAKE_REALS[1], "approved")])
    await d[BACKUP_COLLECTION].insert_many(
        [{"backup": i} for i in range(5)])
    try:
        yield d
    finally:
        await admin.drop_database(_SCRATCH_DB)
        admin.close()
        if _ORIG_DB_NAME is not None:
            os.environ["DB_NAME"] = _ORIG_DB_NAME
        else:
            os.environ.pop("DB_NAME", None)
        db_module._client = None


async def _run(d, dry_run: bool) -> dict:
    return await migrate(d, dry_run=dry_run, seed_ids=FAKE_SEEDS,
                         real_ids=FAKE_REALS, verify_backup=True,
                         audit_enabled=True, verify_freshness=False)


@pytest.mark.asyncio
async def test_scratch_db_is_not_the_real_db(_scratch):
    assert os.environ["DB_NAME"] == _SCRATCH_DB
    assert _scratch.name == _SCRATCH_DB
    assert _scratch.name != (_ORIG_DB_NAME or "prosper_phase0")


@pytest.mark.asyncio
async def test_backup_check_aborts_without_backup(_scratch):
    d = _scratch
    await d[BACKUP_COLLECTION].delete_many({})  # noqa: PROSPER_ALLOW_UNFILTERED_DELETE
    with pytest.raises(RuntimeError, match="ABORT"):
        await _run(d, dry_run=True)


@pytest.mark.asyncio
async def test_dry_run_writes_nothing(_scratch):
    d = _scratch
    report = await _run(d, dry_run=True)
    assert len(report["seeds"]) == 2 and len(report["cases"]) == 2
    assert report["backup_docs"] == 5
    docs = await d["kyb_cases"].find({}).to_list(10)
    assert len(docs) == 4
    assert all(not x.get("legacy_origin") for x in docs)
    assert all(x["is_deleted"] is False for x in docs)
    assert await d["audit_logs"].count_documents({}) == 0  # dry-run no audita
    entry = report["cases"][0]
    for k in ("identificador_original", "status_legacy", "status_nuevo",
              "org_id", "org_opera_hoy", "campos_en_legacy_data"):
        assert k in entry


@pytest.mark.asyncio
async def test_migration_real_and_idempotent(_scratch):
    d = _scratch
    r1 = await _run(d, dry_run=False)
    assert len(r1["seeds"]) == 2 and len(r1["cases"]) == 2

    # Seeds: soft-delete, nunca borrado físico.
    for sid in FAKE_SEEDS:
        doc = await d["kyb_cases"].find_one({"case_id": sid})
        assert doc is not None and doc["is_deleted"] is True

    # Reales: migrados — se localizan por legacy_origin (case_id nuevo).
    migrated = await d["kyb_cases"].find(
        {"legacy_origin.source_id": {"$in": FAKE_REALS}}).to_list(10)
    assert len(migrated) == 2
    for doc in migrated:
        assert doc["status"] == "under_review"
        assert doc["priority"] == "normal"
        assert doc["legacy_origin"]["source_id"] in FAKE_REALS
        assert doc["legacy_origin"]["original_status"] in ("in_review",
                                                           "approved")
        assert doc["case_id"].startswith("kyb_")
        assert doc["case_id"] not in FAKE_REALS          # id nuevo generado
        assert doc["verification_modes"] == {
            "identity": "manual", "screening": "manual",
            "company_registry": "manual"}
        assert doc["risk"] is None
        secs = doc["sections"]
        assert set(secs) == {"tax_identification", "legal_representative",
                             "company_data", "documentation", "team"}
        assert all(v["status"] == "pending" and v["observation"]
                   for v in secs.values())
        ld = doc["legacy_data"]
        for k in ("checklist", "ubos", "provider", "decision_reason",
                  "legal_name", "country", "applied_at", "status"):
            assert k in ld

    # Auditoría: un kyb.case.legacy_migrated por caso, con before/after.
    audits = await d["audit_logs"].find(
        {"action": "kyb.case.legacy_migrated"}).to_list(10)
    assert len(audits) == 2
    for a in audits:
        assert a["metadata"]["before"]["case_id"] in FAKE_REALS
        assert a["metadata"]["after"]["status"] == "under_review"

    # ---- segunda corrida: idempotencia total ----
    total_before = await d["kyb_cases"].count_documents({})
    r2 = await _run(d, dry_run=False)
    assert r2["cases"] == [] and r2["seeds"] == []
    assert len(r2["skipped"]) == 4          # 2 seeds + 2 reales omitidos
    assert await d["kyb_cases"].count_documents({}) == total_before
    # No se re-audita lo ya migrado.
    assert await d["audit_logs"].count_documents(
        {"action": "kyb.case.legacy_migrated"}) == 2


@pytest.mark.asyncio
async def test_build_migrated_doc_preserves_everything():
    old = _real_doc("kyb_test_pure", "approved")
    new = build_migrated_doc(old)
    assert new["company_name_declared"] == old["legal_name"]
    assert new["country_of_incorporation"] == "AR"
    assert new["submitted_at"] == old["applied_at"]
    assert new["created_at"] == old["created_at"]        # se conserva
    assert new["legacy_origin"]["original_status"] == "approved"
    for k, v in old.items():
        if k in ("case_id", "org_id", "created_at", "updated_at",
                 "is_deleted"):
            continue
        assert new["legacy_data"][k] == v


# ---------------------------------------------------------------------------
# Verificación de frescura del backup vs vivo (nuevo aborto pre-migración)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_freshness_check_blocks_when_backup_stale(_scratch):
    """Si el backup diverge del vivo más allá de timestamps, migrar debe
    abortar antes de tocar nada."""
    d = _scratch
    live = await d["kyb_cases"].find({}).to_list(10)
    await d[BACKUP_COLLECTION].delete_many({})  # noqa: PROSPER_ALLOW_UNFILTERED_DELETE
    for doc in live:
        await d[BACKUP_COLLECTION].insert_one({**doc})
    # Mutamos el vivo (agregamos una entry de timeline) → backup viejo
    await d["kyb_cases"].update_one(
        {"case_id": FAKE_REALS[0]},
        {"$push": {"timeline": {"ts": "2026-07-01T00:00:00+00:00",
                                "by": "admin@x", "what": "decision.approve",
                                "meta": {"reason": "extra actividad"}}}})
    with pytest.raises(RuntimeError, match="ABORT\\[freshness\\]"):
        await migrate(d, dry_run=True, seed_ids=FAKE_SEEDS,
                      real_ids=FAKE_REALS, verify_backup=False,
                      audit_enabled=True, verify_freshness=True)


@pytest.mark.asyncio
async def test_freshness_check_passes_when_only_timestamps_differ(_scratch):
    """Si la única diferencia son campos de timestamp, no aborta."""
    d = _scratch
    live = await d["kyb_cases"].find({}).to_list(10)
    await d[BACKUP_COLLECTION].delete_many({})  # noqa: PROSPER_ALLOW_UNFILTERED_DELETE
    for doc in live:
        await d[BACKUP_COLLECTION].insert_one({**doc})
    # Cambiamos SOLO updated_at (timestamp puro)
    await d["kyb_cases"].update_one(
        {"case_id": FAKE_REALS[0]},
        {"$set": {"updated_at": "2099-01-01T00:00:00+00:00"}})
    report = await migrate(d, dry_run=True, seed_ids=FAKE_SEEDS,
                           real_ids=FAKE_REALS, verify_backup=False,
                           audit_enabled=True, verify_freshness=True)
    assert len(report["cases"]) == 2


@pytest.mark.asyncio
async def test_freshness_check_backup_missing_id_aborts(_scratch):
    d = _scratch
    live = await d["kyb_cases"].find({}).to_list(10)
    await d[BACKUP_COLLECTION].delete_many({})  # noqa: PROSPER_ALLOW_UNFILTERED_DELETE
    for doc in live:
        await d[BACKUP_COLLECTION].insert_one({**doc})
    # Sacamos un case_id esperado del backup
    await d[BACKUP_COLLECTION].delete_one({"case_id": FAKE_SEEDS[0]})
    with pytest.raises(RuntimeError, match="ABORT\\[freshness\\]"):
        await migrate(d, dry_run=True, seed_ids=FAKE_SEEDS,
                      real_ids=FAKE_REALS, verify_backup=False,
                      audit_enabled=True, verify_freshness=True)

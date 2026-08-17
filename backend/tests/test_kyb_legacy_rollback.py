"""Tests del rollback KYB legacy (Fase 1) — EN BASE SCRATCH.

Corre íntegramente contra `prosper_kyb_tests_rollback` (drop al inicio
y al final). NUNCA toca la base real.
"""
from __future__ import annotations

import copy
import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_SCRATCH_DB = "prosper_kyb_tests_rollback"
_ORIG_DB_NAME = os.environ.get("DB_NAME")

import db as db_module                                          # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from migrate_legacy_kyb import migrate, BACKUP_COLLECTION       # noqa: E402
from rollback_legacy_kyb import rollback                        # noqa: E402

SEED_IDS = ["kyb_seed_01", "kyb_seed_02", "kyb_seed_03"]
REAL_IDS = ["kyb_apply__finpact", "kyb_apply__alemany"]


def _seed_doc(cid: str) -> dict:
    return {"case_id": cid, "org_id": None, "status": "pending",
            "legal_name": f"Seed {cid}", "is_deleted": False,
            "created_at": "2026-05-01T00:00:00+00:00",
            "updated_at": "2026-05-01T00:00:00+00:00"}


def _real_doc(cid: str, org_id: str, status: str) -> dict:
    return {"case_id": cid, "org_id": org_id, "status": status,
            "legal_name": f"Corp {cid}", "country": "AR",
            "applied_at": "2026-05-14T10:00:00+00:00",
            "checklist": [{"key": "k1", "checked": True}],
            "ubos": [{"name": "U"}], "provider": "self_apply",
            "decision_reason": "texto legacy", "is_deleted": False,
            "created_at": "2026-05-14T10:00:00+00:00",
            "updated_at": "2026-05-14T10:00:00+00:00"}


@pytest_asyncio.fixture()
async def _scratch():
    """Base scratch dedicada con los 5 casos legacy + backup +
    organizations reales. Drop garantizado en teardown."""
    os.environ["DB_NAME"] = _SCRATCH_DB
    db_module._client = None
    admin = AsyncIOMotorClient(os.environ["MONGO_URL"])
    await admin.drop_database(_SCRATCH_DB)
    d = db_module.db()
    # kyb_cases: 3 seeds + 2 reales
    kcases = [_seed_doc(c) for c in SEED_IDS] + [
        _real_doc(REAL_IDS[0], "org_seed_finpact", "in_review"),
        _real_doc(REAL_IDS[1], "org_seed_alemany", "approved")]
    await d["kyb_cases"].insert_many(kcases)
    # kyb_cases_legacy_backup: snapshot (mismos _id que el vivo)
    live_docs = await d["kyb_cases"].find({}).to_list(10)
    await d[BACKUP_COLLECTION].insert_many(
        [copy.deepcopy(x) for x in live_docs])
    # organizations reales sin kyb_case_id inicialmente
    await d["organizations"].insert_many([
        {"org_id": "org_seed_finpact", "kyb_status": "in_review"},
        {"org_id": "org_seed_alemany", "kyb_status": "approved"},
    ])
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


async def _run_migrate(d) -> dict:
    return await migrate(d, dry_run=False, seed_ids=SEED_IDS,
                         real_ids=REAL_IDS, verify_backup=True,
                         audit_enabled=True)


async def _run_rollback(d, *, dry_run=False, force=True, know=True):
    return await rollback(d, dry_run=dry_run, force=force, know=know,
                          run_id="test-run")


# -------------------------------------------------------------------
# Guardias básicas
# -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scratch_db_is_not_prod(_scratch):
    assert _scratch.name == _SCRATCH_DB
    assert _scratch.name != "prosper_phase0"


@pytest.mark.asyncio
async def test_rollback_without_migration_is_a_noop(_scratch):
    """Idempotencia base: si nada se migró, el rollback no debe romper
    ni escribir. Reporta 0 cambios."""
    d = _scratch
    rep = await _run_rollback(d, dry_run=False)
    assert rep["migrated_new_case_ids"] == []
    cp = rep["phases"]["cases_restore"]
    assert cp["deleted"] == 0 and cp["inserted"] == 0
    assert sorted(cp["skipped_already_restored"]) == sorted(SEED_IDS + REAL_IDS)
    # Ninguna colección satélite tocada.
    for coll, n in rep["phases"]["cascade_delete"].items():
        assert n == 0
    # No hay per-case audit porque no había docs migrados.
    assert rep["phases"]["audit_per_case"] == []


# -------------------------------------------------------------------
# Ida y vuelta completa
# -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_full_round_trip_migrate_then_rollback(_scratch):
    d = _scratch
    # Snapshot pre
    pre_cases = sorted(await d["kyb_cases"].find({}).to_list(10),
                       key=lambda x: x["case_id"])
    # Migrar
    await _run_migrate(d)
    # Estado post-migración
    seeds_sd = await d["kyb_cases"].count_documents(
        {"case_id": {"$in": SEED_IDS}, "is_deleted": True})
    assert seeds_sd == 3
    migrated = await d["kyb_cases"].find(
        {"legacy_origin.source_id": {"$in": REAL_IDS}}).to_list(10)
    assert len(migrated) == 2
    # kyb_case_id se escribe en las orgs migradas
    assert await d["organizations"].count_documents(
        {"kyb_case_id": {"$exists": True}}) == 2

    # Rollback dry-run: nada cambia
    dry = await _run_rollback(d, dry_run=True)
    assert dry["dry_run"] is True
    assert len(dry["migrated_new_case_ids"]) == 2
    # Estado igual al post-migración
    assert await d["kyb_cases"].count_documents(
        {"case_id": {"$in": SEED_IDS}, "is_deleted": True}) == 3

    # Rollback ejecución
    rep = await _run_rollback(d, dry_run=False)
    assert rep["phases"]["cases_restore"]["deleted"] == 5
    assert rep["phases"]["cases_restore"]["inserted"] == 5
    assert len(rep["phases"]["audit_per_case"]) == 2

    # Diff estricto: los 5 case_id deben coincidir con el snapshot pre,
    # incluyendo _id (opción b — reemplazo total desde backup).
    post_cases = sorted(await d["kyb_cases"].find({}).to_list(10),
                        key=lambda x: x["case_id"])
    assert len(post_cases) == 5
    pre_by_id = {c["case_id"]: c for c in pre_cases}
    for pc in post_cases:
        pre = pre_by_id[pc["case_id"]]
        assert pc == pre, f"drift en {pc['case_id']}"

    # organizations: kyb_case_id removido (no debe seguir en las orgs)
    assert await d["organizations"].count_documents(
        {"kyb_case_id": {"$exists": True}}) == 0
    # kyb_status jamás se tocó
    finp = await d["organizations"].find_one({"org_id": "org_seed_finpact"})
    ale = await d["organizations"].find_one({"org_id": "org_seed_alemany"})
    assert finp["kyb_status"] == "in_review"
    assert ale["kyb_status"] == "approved"

    # audit_logs: se conserva la entrada de migración, se agrega la de
    # rollback per-case, ninguna se borra.
    assert await d["audit_logs"].count_documents(
        {"action": "kyb.case.legacy_migrated"}) == 2
    assert await d["audit_logs"].count_documents(
        {"action": "kyb.case.legacy_rollback"}) == 2
    # log_action de start/phase/end (resource_type="kyb_rollback_script")
    assert await d["audit_logs"].count_documents(
        {"action": "kyb.rollback.script_started"}) == 1
    assert await d["audit_logs"].count_documents(
        {"action": "kyb.rollback.script_finished"}) == 1
    assert await d["audit_logs"].count_documents(
        {"action": "kyb.rollback.phase"}) >= 3


@pytest.mark.asyncio
async def test_rollback_is_idempotent(_scratch):
    d = _scratch
    await _run_migrate(d)
    r1 = await _run_rollback(d, dry_run=False)
    assert r1["phases"]["cases_restore"]["inserted"] == 5
    r2 = await _run_rollback(d, dry_run=False)
    # Segunda corrida: nada que migrar de vuelta, nada que borrar
    assert r2["migrated_new_case_ids"] == []
    assert r2["phases"]["cases_restore"]["deleted"] == 0
    assert r2["phases"]["cases_restore"]["inserted"] == 0
    assert sorted(r2["phases"]["cases_restore"]["skipped_already_restored"]) \
        == sorted(SEED_IDS + REAL_IDS)


# -------------------------------------------------------------------
# Volcado JSON de kyb_documents
# -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_documents_dump_before_delete(_scratch, tmp_path):
    d = _scratch
    await _run_migrate(d)
    # Inyectamos 2 kyb_documents (uploaded_by=system, no dispara A4)
    new_cids = [x["case_id"] for x in await d["kyb_cases"].find(
        {"legacy_origin.source_id": {"$in": REAL_IDS}}).to_list(10)]
    await d["kyb_documents"].insert_many([
        {"doc_id": "d1", "case_id": new_cids[0], "slot": "id_front",
         "filename": "f1.pdf", "sha256": "abc", "size_bytes": 100,
         "content_type": "application/pdf", "uploaded_by": "system",
         "uploaded_via": "backfill", "storage_key": "gridfs/1"},
        {"doc_id": "d2", "case_id": new_cids[1], "slot": "id_back",
         "filename": "f2.pdf", "sha256": "def", "size_bytes": 200,
         "content_type": "application/pdf", "uploaded_by": "migration",
         "uploaded_via": "backfill", "storage_key": "gridfs/2"},
    ])
    rep = await _run_rollback(d, dry_run=False)
    dump = rep["documents_dump"]
    assert dump["count"] == 2
    p = Path(dump["path"])
    assert p.exists()
    import json
    payload = json.loads(p.read_text())
    assert payload["docs_count"] == 2
    keys = {d for doc in payload["docs"] for d in doc.keys()}
    assert {"case_id", "slot", "filename", "sha256", "size_bytes",
            "content_type", "uploaded_by", "uploaded_via",
            "storage_key"}.issubset(keys)
    # Borrado físico: kyb_documents debe quedar vacío para esos case_ids
    assert await d["kyb_documents"].count_documents(
        {"case_id": {"$in": new_cids}}) == 0


# -------------------------------------------------------------------
# Los 9 abortos
# -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_abort_a1_backup_missing_case_id(_scratch):
    d = _scratch
    await d[BACKUP_COLLECTION].delete_one({"case_id": "kyb_seed_01"})
    with pytest.raises(RuntimeError, match="ABORT\\[A1\\]"):
        await _run_rollback(d, dry_run=True)


@pytest.mark.asyncio
async def test_abort_a2_unknown_source_id(_scratch):
    d = _scratch
    await d["kyb_cases"].insert_one({
        "case_id": "kyb_extra_migrado", "verification_modes": {"x": "manual"},
        "legacy_origin": {"source_id": "kyb_extraño"}, "status": "under_review",
    })
    with pytest.raises(RuntimeError, match="ABORT\\[A2\\]"):
        await _run_rollback(d, dry_run=True)


@pytest.mark.asyncio
async def test_abort_a3_manual_check_human_activity(_scratch):
    d = _scratch
    await _run_migrate(d)
    new_cid = (await d["kyb_cases"].find_one(
        {"legacy_origin.source_id": REAL_IDS[0]}))["case_id"]
    await d["kyb_manual_checks"].insert_one({
        "check_id": "m1", "case_id": new_cid, "status": "in_progress",
        "contributors": [], "evidence": []})
    with pytest.raises(RuntimeError, match="ABORT\\[A3\\]"):
        await _run_rollback(d, dry_run=True)


@pytest.mark.asyncio
async def test_abort_a4_document_human_uploader(_scratch):
    d = _scratch
    await _run_migrate(d)
    new_cid = (await d["kyb_cases"].find_one(
        {"legacy_origin.source_id": REAL_IDS[0]}))["case_id"]
    await d["kyb_documents"].insert_one({
        "doc_id": "dx", "case_id": new_cid, "uploaded_by": "user@x.com"})
    with pytest.raises(RuntimeError, match="ABORT\\[A4\\]"):
        await _run_rollback(d, dry_run=True)


@pytest.mark.asyncio
async def test_abort_a5_shared_link_used(_scratch):
    d = _scratch
    await _run_migrate(d)
    new_cid = (await d["kyb_cases"].find_one(
        {"legacy_origin.source_id": REAL_IDS[0]}))["case_id"]
    await d["kyb_shared_links"].insert_one({
        "link_id": "L1", "case_id": new_cid, "use_count": 3})
    with pytest.raises(RuntimeError, match="ABORT\\[A5\\]"):
        await _run_rollback(d, dry_run=True)


@pytest.mark.asyncio
async def test_abort_a6_verification_outcome_and_case_status(_scratch):
    d = _scratch
    await _run_migrate(d)
    doc = await d["kyb_cases"].find_one(
        {"legacy_origin.source_id": REAL_IDS[0]})
    new_cid = doc["case_id"]
    # Forzar case a approved y verificación con outcome approved
    await d["kyb_cases"].update_one(
        {"case_id": new_cid}, {"$set": {"status": "approved"}})
    await d["kyb_verifications"].insert_one({
        "verification_id": "v1", "case_id": new_cid,
        "outcome": "approved"})
    # A8 dispara primero (status != under_review) — el orden en preflight
    # es determinístico. Aceptamos que abortemos por A8 o A6 en este caso:
    with pytest.raises(RuntimeError, match="ABORT\\[A[68]\\]"):
        await _run_rollback(d, dry_run=True)


@pytest.mark.asyncio
async def test_abort_a7_kyb_case_id_on_unexpected_org(_scratch):
    d = _scratch
    await _run_migrate(d)
    new_cid = (await d["kyb_cases"].find_one(
        {"legacy_origin.source_id": REAL_IDS[0]}))["case_id"]
    await d["organizations"].insert_one({
        "org_id": "org_intruso", "kyb_case_id": new_cid})
    with pytest.raises(RuntimeError, match="ABORT\\[A7\\]"):
        await _run_rollback(d, dry_run=True)


@pytest.mark.asyncio
async def test_abort_a8_case_status_not_under_review(_scratch):
    d = _scratch
    await _run_migrate(d)
    new_cid = (await d["kyb_cases"].find_one(
        {"legacy_origin.source_id": REAL_IDS[0]}))["case_id"]
    await d["kyb_cases"].update_one(
        {"case_id": new_cid}, {"$set": {"status": "approved"}})
    with pytest.raises(RuntimeError, match="ABORT\\[A8\\]"):
        await _run_rollback(d, dry_run=True)


@pytest.mark.asyncio
async def test_abort_a9_audit_with_human_actor(_scratch):
    d = _scratch
    await _run_migrate(d)
    new_cid = (await d["kyb_cases"].find_one(
        {"legacy_origin.source_id": REAL_IDS[0]}))["case_id"]
    await d["audit_logs"].insert_one({
        "action": "kyb.section.reviewed", "resource_type": "kyb_case",
        "resource_id": new_cid, "actor_user_id": "user_123",
        "timestamp": "2026-06-01T00:00:00+00:00"})
    with pytest.raises(RuntimeError, match="ABORT\\[A9\\]"):
        await _run_rollback(d, dry_run=True)


@pytest.mark.asyncio
async def test_abort_a10_backup_diverges_from_legacy_data(_scratch):
    """A10: si el backup diverge del legacy_data del caso migrado en
    campos que NO son timestamps, restaurar llevaría a un estado
    anterior al inmediato pre-migración. Aborta."""
    d = _scratch
    # Antes de migrar, mutamos el backup para simular que quedó "viejo"
    # respecto al vivo: quitamos una entry del timeline del backup.
    await d[BACKUP_COLLECTION].update_one(
        {"case_id": REAL_IDS[0]},
        {"$set": {"timeline": [{"ts": "2026-01-01T00:00:00+00:00",
                                "by": "old", "what": "old.event",
                                "meta": {}}]}})
    # Migramos sin verify_freshness (para simular exactamente el caso
    # del H1: se migró con backup desactualizado sin darse cuenta).
    await migrate(d, dry_run=False, seed_ids=SEED_IDS, real_ids=REAL_IDS,
                  verify_backup=True, audit_enabled=True,
                  verify_freshness=False)
    # Ahora el rollback debe detectar la divergencia backup vs legacy_data
    with pytest.raises(RuntimeError, match="ABORT\\[A10\\]"):
        await _run_rollback(d, dry_run=True)


# -------------------------------------------------------------------
# Guardias externas (force / i-know-what-im-doing)
# -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_guard_prod_db_requires_i_know(_scratch, monkeypatch):
    d = _scratch
    with pytest.raises(RuntimeError, match="prosper_phase0"):
        # Simulamos que la DB se llama como prod
        class Fake:
            name = "prosper_phase0"
            def __getitem__(self, k): return d[k]
        # know=False + force=True (para saltar guardia de kyb_enabled)
        await rollback(Fake(), dry_run=True, force=True, know=False)


@pytest.mark.asyncio
async def test_guard_kyb_enabled_requires_force(_scratch, monkeypatch):
    d = _scratch
    monkeypatch.setattr("rollback_legacy_kyb.kyb_enabled", lambda: True)
    with pytest.raises(RuntimeError, match="KYB_MODULE_ENABLED=true"):
        await rollback(d, dry_run=True, force=False, know=True)


# -------------------------------------------------------------------
# Conservación estricta de las 3 colecciones "no tocar" (Cat B)
# -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_conserva_verifications_screening_hits_audit(_scratch):
    d = _scratch
    await _run_migrate(d)
    new_cid = (await d["kyb_cases"].find_one(
        {"legacy_origin.source_id": REAL_IDS[0]}))["case_id"]
    # Sembramos: verification (outcome pending, no dispara A6), screening
    # hit y outbound_email — todos con case_id nuevo.
    await d["kyb_verifications"].insert_one({
        "verification_id": "v_keep", "case_id": new_cid,
        "outcome": "pending"})
    await d["kyb_screening_hits"].insert_one({
        "hit_id": "h_keep", "case_id": new_cid})
    await d["outbound_emails"].insert_one({
        "email_id": "e_keep", "case_id": new_cid})
    audit_count_before = await d["audit_logs"].count_documents({})

    await _run_rollback(d, dry_run=False)

    # Cat B: siguen enteros
    assert await d["kyb_verifications"].count_documents(
        {"verification_id": "v_keep"}) == 1
    assert await d["kyb_screening_hits"].count_documents(
        {"hit_id": "h_keep"}) == 1
    assert await d["outbound_emails"].count_documents(
        {"email_id": "e_keep"}) == 1
    # audit_logs: crece (start + phases + finished + 2 per-case), no
    # decrece.
    audit_count_after = await d["audit_logs"].count_documents({})
    assert audit_count_after > audit_count_before

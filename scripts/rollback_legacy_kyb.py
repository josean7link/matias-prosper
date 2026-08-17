"""Rollback de la migración KYB legacy — devuelve la DB al estado
pre-`migrate_legacy_kyb.py`.

USO:
    python scripts/rollback_legacy_kyb.py --dry-run
    python scripts/rollback_legacy_kyb.py --execute [--force] [--i-know-what-im-doing]

Requisitos por defecto para --execute:
  * KYB_MODULE_ENABLED debe estar apagado (o se exige --force explícito).
  * Si la DB apuntada es exactamente "prosper_phase0", se exige
    --i-know-what-im-doing (el testeo va contra copias, no contra prod).

Categoría A — SE REVIERTE, con filtro estricto por case_id:
  1. kyb_cases: restaurar los 5 desde kyb_cases_legacy_backup preservando
     el _id del backup (reemplazo total), borrando los 2 docs con
     case_id NUEVO y los 3 seeds soft-deleted.
  2. organizations.kyb_case_id: $unset en las 2 orgs migradas. NUNCA se
     toca `kyb_status`.
  3..9. Cascade DELETE por case_id ∈ NUEVOS en:
        kyb_manual_checks, kyb_external_subjects, kyb_shared_links,
        kyb_team_invitations, kyb_registry_reviews, kyb_documents
        (previo volcado obligatorio a JSON), kyb_notifications
        (si existe).

Categoría B — SE CONSERVA (no se toca):
  kyb_verifications, kyb_screening_hits, kyb_provider_calls,
  outbound_emails, audit_logs, bytes en GridFS.

Auditoría:
  * `log_action` con inicio, cada fase, finalización, resource_type
    "kyb_rollback_script" (no crea colección nueva).
  * `kyb.case.legacy_rollback` (kyb_audit) per-case con before/after.

Idempotencia:
  La reanudabilidad se deriva del estado real de las colecciones. Cada
  fase verifica lo que aún falta antes de escribir.

NUEVE ABORTOS obligatorios (más los 2 flags de guardia externos):
  A1. Backup no tiene los 5 case_id esperados.
  A2. Caso con verification_modes y legacy_origin.source_id fuera de los
      5 conocidos.
  A3. kyb_manual_checks con actividad humana (status in_progress|completed
      o contributors o evidence no vacíos).
  A4. kyb_documents con uploaded_by no in {system, migration}.
  A5. kyb_shared_links con use_count > 0.
  A6. kyb_verifications con outcome approved|rejected + caso en
      approved|rejected.
  A7. organizations.kyb_case_id apunta a case_id NUEVO desde org
      distinta a org_seed_finpact/alemany.
  A8. Caso migrado con status != under_review.
  A9. audit_logs con case_id NUEVO y actor_user_id no nulo.

Cualquier aborto → RuntimeError explícito nombrando colección, case_id y
motivo. El script nunca decide solo ante estado inesperado.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / "backend" / ".env")

from models import utc_now                              # noqa: E402
from kyb.flags import kyb_enabled                        # noqa: E402
from audit import log_action                             # noqa: E402
from kyb.audit import kyb_audit                          # noqa: E402

# ----------------------------------------------------------------------
# Constantes
# ----------------------------------------------------------------------
SEED_IDS = ["kyb_seed_01", "kyb_seed_02", "kyb_seed_03"]
REAL_IDS = ["kyb_apply__finpact", "kyb_apply__alemany"]
EXPECTED_BACKUP_IDS = SEED_IDS + REAL_IDS
EXPECTED_ORGS = {"org_seed_finpact", "org_seed_alemany"}

BACKUP_COLLECTION = "kyb_cases_legacy_backup"

# Colecciones satélite Cat A (cascade delete por case_id ∈ NUEVOS)
CASCADE_COLLECTIONS = [
    "kyb_manual_checks",
    "kyb_external_subjects",
    "kyb_shared_links",
    "kyb_team_invitations",
    "kyb_registry_reviews",
    # kyb_documents va aparte porque exige volcado JSON previo.
    "kyb_notifications",
]

PROD_DB_NAME = "prosper_phase0"

RESOURCE_TYPE_SCRIPT = "kyb_rollback_script"

# Campos que se ignoran al comparar backup vs legacy_data — timestamps
# puros y campos derivados que naturalmente cambian entre snapshots.
TIMESTAMP_FIELDS = {"updated_at", "created_at", "applied_at", "decided_at",
                    "next_review_at", "expires_at", "submitted_at",
                    "resolved_at"}


def _shape_for_diff(doc: dict) -> dict:
    """Copia del doc con timestamps pelados y timeline reducido a
    (by, what) — se ignoran ts internos porque son mutables por diseño.

    NO se remueve `_id`: el diff exige que _id coincida (opción b del
    usuario)."""
    out = {}
    for k, v in doc.items():
        if k in TIMESTAMP_FIELDS:
            continue
        if k == "timeline" and isinstance(v, list):
            out[k] = [{"by": e.get("by"), "what": e.get("what"),
                       "meta": e.get("meta")} for e in v]
            continue
        out[k] = v
    return out


def _compare_backup_vs_current(backup_doc: dict, current_doc: dict) -> list:
    """Diferencias significativas (fuera de timestamps) entre dos docs
    del mismo case_id. Devuelve lista de campos que difieren."""
    a = _shape_for_diff(backup_doc)
    b = _shape_for_diff(current_doc)
    changed = []
    for k in sorted(set(a) | set(b)):
        if a.get(k) != b.get(k):
            changed.append(k)
    return changed


# ----------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------
def _jsonable(obj: Any) -> Any:
    """Copia serializable a JSON de un doc de Mongo."""
    return json.loads(json.dumps(obj, default=str))


async def _log(action: str, run_id: str, metadata: dict) -> None:
    """log_action con actor=None (system), resource=script + run_id."""
    await log_action(actor=None, action=action,
                     resource_type=RESOURCE_TYPE_SCRIPT,
                     resource_id=run_id, metadata=metadata)


# ----------------------------------------------------------------------
# Preflight — 9 abortos
# ----------------------------------------------------------------------
async def _preflight(d, *, force: bool, know: bool) -> dict:
    """Corre las 9 verificaciones. Devuelve dict con:
      backup: {ids: [...], _id_map: {case_id: str(_id)}}
      migrated_new_case_ids: [...]  (los 2 case_id NUEVOS)
      migrated_docs: {source_id: current_doc}
    Cualquier violación → RuntimeError.
    """
    # Guardias externas (los 2 flags añadidos, no cuentan en los 9)
    if kyb_enabled() and not force:
        raise RuntimeError(
            "ABORT[guardia]: KYB_MODULE_ENABLED=true — el rollback normalmente "
            "se ejecuta con el módulo apagado. Reintente con --force para "
            "avanzar de todos modos.")
    if d.name == PROD_DB_NAME and not know:
        raise RuntimeError(
            f"ABORT[guardia]: la DB destino es {PROD_DB_NAME!r}. Los tests "
            "van contra copias (prosper_phase0_rollback_test_*). Si realmente "
            "es intencional, reintente con --i-know-what-im-doing.")

    # A1: backup con los 5 case_id esperados
    backup_docs = {}
    async for doc in d[BACKUP_COLLECTION].find({}):
        backup_docs[doc.get("case_id")] = doc
    faltantes = [cid for cid in EXPECTED_BACKUP_IDS if cid not in backup_docs]
    if faltantes:
        raise RuntimeError(
            f"ABORT[A1]: {BACKUP_COLLECTION!r} no contiene los case_id "
            f"esperados. Faltantes: {faltantes}. Presentes: "
            f"{sorted(backup_docs.keys())}. Total docs en backup: "
            f"{len(backup_docs)}.")
    if len(backup_docs) != 5:
        raise RuntimeError(
            f"ABORT[A1]: {BACKUP_COLLECTION!r} tiene {len(backup_docs)} docs, "
            f"se esperaban exactamente 5.")

    # A2: casos con verification_modes y source_id fuera de los conocidos
    async for doc in d["kyb_cases"].find(
            {"verification_modes": {"$exists": True}}):
        origin = (doc.get("legacy_origin") or {}).get("source_id")
        if origin is None:
            # No migrado — verification_modes puede venir de la vida nueva.
            continue
        if origin not in REAL_IDS:
            raise RuntimeError(
                f"ABORT[A2]: kyb_cases case_id={doc.get('case_id')!r} tiene "
                f"legacy_origin.source_id={origin!r} fuera de {REAL_IDS}.")

    # Descubrir case_ids NUEVOS (los 2 docs actualmente migrados)
    migrated_docs: dict[str, dict] = {}
    async for doc in d["kyb_cases"].find(
            {"legacy_origin.source_id": {"$in": REAL_IDS}}):
        src = doc["legacy_origin"]["source_id"]
        migrated_docs[src] = doc
    new_case_ids = [m["case_id"] for m in migrated_docs.values()]

    # A8: casos migrados con status != under_review
    for src, doc in migrated_docs.items():
        st = doc.get("status")
        if st != "under_review":
            raise RuntimeError(
                f"ABORT[A8]: case_id nuevo={doc.get('case_id')!r} (legacy "
                f"origen {src!r}) tiene status={st!r}, se esperaba "
                "'under_review'. Ya hubo intervención humana o de proveedor.")

    # A3: kyb_manual_checks con actividad humana
    if new_case_ids:
        async for doc in d["kyb_manual_checks"].find(
                {"case_id": {"$in": new_case_ids}}):
            st = doc.get("status")
            contributors = doc.get("contributors") or []
            evidence = doc.get("evidence") or []
            if (st in ("in_progress", "completed") or contributors
                    or evidence):
                raise RuntimeError(
                    f"ABORT[A3]: kyb_manual_checks id={doc.get('_id')} para "
                    f"case_id={doc.get('case_id')!r} tiene actividad humana "
                    f"(status={st!r}, contributors={len(contributors)}, "
                    f"evidence={len(evidence)}).")

    # A4: kyb_documents con uploaded_by fuera de {system, migration}
    if new_case_ids:
        async for doc in d["kyb_documents"].find(
                {"case_id": {"$in": new_case_ids}}):
            up = doc.get("uploaded_by")
            if up not in ("system", "migration"):
                raise RuntimeError(
                    f"ABORT[A4]: kyb_documents doc_id={doc.get('doc_id') or doc.get('_id')} "
                    f"case_id={doc.get('case_id')!r} uploaded_by={up!r} — se "
                    "esperaba 'system' o 'migration'. Hay evidencia humana.")

    # A5: kyb_shared_links con use_count > 0
    if new_case_ids:
        async for doc in d["kyb_shared_links"].find(
                {"case_id": {"$in": new_case_ids},
                 "use_count": {"$gt": 0}}):
            raise RuntimeError(
                f"ABORT[A5]: kyb_shared_links link_id={doc.get('link_id') or doc.get('_id')} "
                f"case_id={doc.get('case_id')!r} use_count={doc.get('use_count')}. "
                "El link fue usado.")

    # A6: kyb_verifications con outcome approved|rejected + caso en
    # approved|rejected. Como A8 ya exige under_review, esto en la práctica
    # no dispara — pero se mantiene la verificación de contrato.
    if new_case_ids:
        async for doc in d["kyb_verifications"].find(
                {"case_id": {"$in": new_case_ids},
                 "outcome": {"$in": ["approved", "rejected"]}}):
            case = migrated_docs.get(
                (doc.get("case_id") and next(
                    (s for s, m in migrated_docs.items()
                     if m["case_id"] == doc["case_id"]), None)))
            case_status = case.get("status") if case else None
            if case_status in ("approved", "rejected"):
                raise RuntimeError(
                    f"ABORT[A6]: kyb_verifications verification_id="
                    f"{doc.get('verification_id') or doc.get('_id')} "
                    f"case_id={doc.get('case_id')!r} outcome="
                    f"{doc.get('outcome')!r} y case.status={case_status!r}.")

    # A7: organizations.kyb_case_id apuntando a case_id NUEVO desde org
    # distinta a las esperadas
    if new_case_ids:
        async for org in d["organizations"].find(
                {"kyb_case_id": {"$in": new_case_ids}}):
            if org.get("org_id") not in EXPECTED_ORGS:
                raise RuntimeError(
                    f"ABORT[A7]: organizations org_id={org.get('org_id')!r} "
                    f"tiene kyb_case_id={org.get('kyb_case_id')!r} pero no "
                    f"pertenece a {EXPECTED_ORGS}.")

    # A9: audit_logs con case_id NUEVO y actor_user_id no nulo
    if new_case_ids:
        found = await d["audit_logs"].find_one(
            {"resource_type": "kyb_case",
             "resource_id": {"$in": new_case_ids},
             "actor_user_id": {"$ne": None}},
            {"actor_user_id": 1, "action": 1, "resource_id": 1, "_id": 0})
        if found:
            raise RuntimeError(
                f"ABORT[A9]: audit_logs tiene entrada con case_id NUEVO="
                f"{found.get('resource_id')!r}, actor_user_id="
                f"{found.get('actor_user_id')!r}, action="
                f"{found.get('action')!r}. Hay huella humana.")

    # A10: backup vs legacy_data — el backup debe reflejar el estado que
    # la migración capturó en `legacy_data`. Si difieren fuera de
    # timestamps, el backup se tomó a destiempo y restaurar llevaría a
    # un estado anterior al inmediato pre-migración.
    #
    # Comparación: para cada caso real migrado, tomamos el `legacy_data`
    # (que contiene la foto del legacy en el momento exacto de migrar)
    # y lo comparamos contra el backup del mismo case_id, excluyendo
    # timestamps y reduciendo timeline a (by, what, meta).
    for src, live in migrated_docs.items():
        ld = live.get("legacy_data") or {}
        if not ld:
            continue  # no hay legacy_data (migración muy antigua o rota)
        backup_doc = backup_docs.get(src)
        if not backup_doc:
            continue  # A1 ya cubrió esto
        # Reconstruir "backup shape" excluyendo campos estructurales del
        # legacy y timestamps (migrate_legacy_kyb.STRUCTURAL_FIELDS).
        b_shape = {k: v for k, v in backup_doc.items()
                   if k not in {"_id", "case_id", "org_id", "created_at",
                                "updated_at", "is_deleted"}
                   and k not in TIMESTAMP_FIELDS}
        # Timeline se reduce a (by, what, meta) — ts es mutable por diseño.
        if isinstance(b_shape.get("timeline"), list):
            b_shape["timeline"] = [{"by": e.get("by"),
                                    "what": e.get("what"),
                                    "meta": e.get("meta")}
                                   for e in b_shape["timeline"]]
        ld_shape = {k: v for k, v in ld.items() if k not in TIMESTAMP_FIELDS}
        if isinstance(ld_shape.get("timeline"), list):
            ld_shape["timeline"] = [{"by": e.get("by"),
                                     "what": e.get("what"),
                                     "meta": e.get("meta")}
                                    for e in ld_shape["timeline"]]
        diverged = sorted(k for k in set(b_shape) | set(ld_shape)
                          if b_shape.get(k) != ld_shape.get(k))
        if diverged:
            raise RuntimeError(
                f"ABORT[A10]: backup vs legacy_data divergen para "
                f"case_id={live.get('case_id')!r} (source_id={src!r}). "
                f"Campos con diferencia fuera de timestamps: {diverged}. "
                "Restaurar desde este backup llevaría a un estado ANTERIOR "
                "al inmediato pre-migración: se perdería la actividad "
                "capturada en `legacy_data` que no está reflejada en el "
                "backup. Regenerá el backup y volvé a intentar (idealmente "
                "esto no debería pasar: la migración habilita un aborto "
                "análogo, ver docs/kyb/activation_procedure.md).")

    return {
        "backup": {
            "ids": sorted(backup_docs.keys()),
            "_id_map": {cid: str(doc["_id"])
                        for cid, doc in backup_docs.items()},
            "docs": backup_docs,
        },
        "migrated_new_case_ids": sorted(new_case_ids),
        "migrated_docs": migrated_docs,
    }


# ----------------------------------------------------------------------
# Dump kyb_documents
# ----------------------------------------------------------------------
async def _dump_kyb_documents(d, new_case_ids: list[str],
                              run_id: str) -> dict:
    """Volcado obligatorio antes de borrar metadatos de kyb_documents."""
    out_path = f"/tmp/rollback_kyb_documents_{run_id}.json"
    docs = []
    if new_case_ids:
        async for doc in d["kyb_documents"].find(
                {"case_id": {"$in": new_case_ids}}):
            docs.append({
                "case_id": doc.get("case_id"),
                "doc_id": doc.get("doc_id"),
                "slot": doc.get("slot"),
                "filename": doc.get("filename"),
                "sha256": doc.get("sha256"),
                "size_bytes": doc.get("size_bytes"),
                "content_type": doc.get("content_type"),
                "uploaded_by": doc.get("uploaded_by"),
                "uploaded_via": doc.get("uploaded_via"),
                "storage_key": doc.get("storage_key"),
                "_mongo_id": str(doc.get("_id")),
            })
    payload = {
        "run_id": run_id,
        "generated_at": utc_now(),
        "db_name": d.name,
        "new_case_ids": new_case_ids,
        "docs_count": len(docs),
        "docs": docs,
    }
    Path(out_path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    return {"path": out_path, "count": len(docs)}


# ----------------------------------------------------------------------
# Rollback core
# ----------------------------------------------------------------------
async def rollback(d, *, dry_run: bool, force: bool, know: bool,
                   run_id: str | None = None) -> dict:
    """Núcleo del rollback. Público — usable desde tests con
    parametrización total."""
    run_id = run_id or f"rollback-{int(time.time())}"
    report: dict = {
        "dry_run": dry_run,
        "run_id": run_id,
        "db_name": d.name,
        "phases": {},
        "cases_before": {},
        "cases_after": {},
        "id_check": {},
        "documents_dump": None,
    }

    prev = await _preflight(d, force=force, know=know)
    backup = prev["backup"]
    new_case_ids: list[str] = prev["migrated_new_case_ids"]
    migrated_docs: dict[str, dict] = prev["migrated_docs"]

    report["backup"] = {
        "ids": backup["ids"],
        "_id_map": backup["_id_map"],
    }
    report["migrated_new_case_ids"] = new_case_ids

    # Confirmación de _id del backup vs vivo (para las 2 orgs reales).
    # La migración usa replace_one preservando el _id del doc real; para
    # los seeds el _id no se modificó (solo $set is_deleted). Reportar
    # coincidencia doc a doc.
    id_check: dict[str, dict] = {}
    for cid in EXPECTED_BACKUP_IDS:
        backup_id = backup["_id_map"][cid]
        if cid in SEED_IDS:
            live = await d["kyb_cases"].find_one({"case_id": cid})
        else:
            live = migrated_docs.get(cid)
        live_id = str(live["_id"]) if live else None
        id_check[cid] = {"backup_id": backup_id, "live_id": live_id,
                         "match": backup_id == live_id,
                         "live_present": live is not None}
    report["id_check"] = id_check

    if not dry_run:
        await _log("kyb.rollback.script_started", run_id, {
            "db_name": d.name, "new_case_ids": new_case_ids,
            "backup_ids": backup["ids"],
            "kyb_module_enabled": kyb_enabled(),
        })

    # Fase 1 — dump de kyb_documents (siempre se corre el conteo; el
    # archivo se escribe también en dry-run para inspección).
    dump_info = await _dump_kyb_documents(d, new_case_ids, run_id)
    report["documents_dump"] = dump_info
    report["phases"]["documents_dump"] = {"path": dump_info["path"],
                                          "count": dump_info["count"]}
    if not dry_run:
        await _log("kyb.rollback.phase", run_id, {
            "phase": "documents_dump", **dump_info})

    # Fase 2 — cascade delete de colecciones satélite (por case_id ∈
    # NUEVOS). Cat A punto 3..7 y 9.
    cascade_report: dict[str, int] = {}
    for coll in CASCADE_COLLECTIONS:
        if not new_case_ids:
            cascade_report[coll] = 0
            continue
        n = await d[coll].count_documents(
            {"case_id": {"$in": new_case_ids}})
        cascade_report[coll] = n
        if n and not dry_run:
            res = await d[coll].delete_many(
                {"case_id": {"$in": new_case_ids}})
            cascade_report[coll] = res.deleted_count
    # kyb_documents va aparte (después del dump)
    kdocs_n = await d["kyb_documents"].count_documents(
        {"case_id": {"$in": new_case_ids}}) if new_case_ids else 0
    cascade_report["kyb_documents"] = kdocs_n
    if kdocs_n and not dry_run:
        res = await d["kyb_documents"].delete_many(
            {"case_id": {"$in": new_case_ids}})
        cascade_report["kyb_documents"] = res.deleted_count
    report["phases"]["cascade_delete"] = cascade_report
    if not dry_run:
        await _log("kyb.rollback.phase", run_id, {
            "phase": "cascade_delete", **cascade_report})

    # Fase 3 — $unset organizations.kyb_case_id (Cat A punto 2)
    org_report: dict = {"matched": 0, "modified": 0}
    if new_case_ids:
        org_report["matched"] = await d["organizations"].count_documents(
            {"kyb_case_id": {"$in": new_case_ids}})
        if not dry_run:
            res = await d["organizations"].update_many(
                {"kyb_case_id": {"$in": new_case_ids}},
                {"$unset": {"kyb_case_id": ""}})
            org_report["modified"] = res.modified_count
    report["phases"]["organizations_unset_kyb_case_id"] = org_report
    if not dry_run:
        await _log("kyb.rollback.phase", run_id, {
            "phase": "organizations_unset_kyb_case_id", **org_report})

    # Fase 4 — restaurar kyb_cases (Cat A punto 1)
    # Snapshot "before" para auditoría per-case
    for src in REAL_IDS:
        current = migrated_docs.get(src)
        report["cases_before"][src] = _jsonable(current) if current else None

    # Estrategia: delete todos los docs cuyos case_id son (los 3 seeds +
    # los 2 nuevos), luego insert de los 5 del backup. Preserva _id.
    live_case_ids_to_delete: list[str] = []
    for sid in SEED_IDS:
        live = await d["kyb_cases"].find_one({"case_id": sid})
        if live:
            live_case_ids_to_delete.append(sid)
    live_case_ids_to_delete.extend(new_case_ids)

    cases_phase = {
        "live_case_ids_to_delete": live_case_ids_to_delete,
        "backup_case_ids_to_insert": [],
        "skipped_already_restored": [],
        "deleted": 0,
        "inserted": 0,
    }

    # Los que faltan del backup en vivo (no presentes) → insertar.
    for cid in EXPECTED_BACKUP_IDS:
        exists_live = await d["kyb_cases"].count_documents({"case_id": cid})
        # Contar coincidencia con backup shape (sin legacy_origin) para
        # idempotencia: si ya está restaurado (case_id de seed presente y
        # no soft-deleted; o real presente sin legacy_origin), no lo
        # tocamos.
        if cid in SEED_IDS and exists_live:
            live = await d["kyb_cases"].find_one({"case_id": cid})
            # Ya restaurado si is_deleted no está seteado (backup no lo
            # trae seteado en True — los seeds del backup lo tienen en
            # False o ausente).
            backup_doc = backup["docs"][cid]
            if live.get("is_deleted", False) is False \
                    and live.get("_id") == backup_doc.get("_id"):
                cases_phase["skipped_already_restored"].append(cid)
                continue
        if cid in REAL_IDS and exists_live:
            live = await d["kyb_cases"].find_one({"case_id": cid})
            if live and not live.get("legacy_origin"):
                cases_phase["skipped_already_restored"].append(cid)
                continue
        cases_phase["backup_case_ids_to_insert"].append(cid)

    if not dry_run:
        # Delete en vivo lo que hay que reemplazar (los que están en
        # backup_case_ids_to_insert). No borramos lo ya restaurado.
        to_delete_final = [cid for cid in live_case_ids_to_delete
                           if cid in cases_phase["backup_case_ids_to_insert"]
                           or cid in new_case_ids]
        if to_delete_final:
            del_res = await d["kyb_cases"].delete_many(
                {"case_id": {"$in": to_delete_final}})
            cases_phase["deleted"] = del_res.deleted_count
        # Insert de los faltantes desde el backup (preservando _id)
        docs_to_insert = [copy.deepcopy(backup["docs"][cid])
                          for cid in cases_phase["backup_case_ids_to_insert"]]
        if docs_to_insert:
            ins_res = await d["kyb_cases"].insert_many(docs_to_insert)
            cases_phase["inserted"] = len(ins_res.inserted_ids)

    report["phases"]["cases_restore"] = cases_phase
    if not dry_run:
        await _log("kyb.rollback.phase", run_id, {
            "phase": "cases_restore",
            "deleted": cases_phase["deleted"],
            "inserted": cases_phase["inserted"],
            "skipped": cases_phase["skipped_already_restored"]})

    # Snapshot "after"
    for src in REAL_IDS:
        after = await d["kyb_cases"].find_one({"case_id": src})
        report["cases_after"][src] = _jsonable(after) if after else None

    # Fase 5 — auditoría per-case kyb.case.legacy_rollback (only execute,
    # y solo si efectivamente había un caso migrado que revertir).
    audited_cases: list[str] = []
    if not dry_run and new_case_ids:
        for src in REAL_IDS:
            before = report["cases_before"].get(src)
            after = report["cases_after"].get(src)
            if before is None and after is None:
                continue  # nada que auditar
            await kyb_audit(
                "kyb.case.legacy_rollback",
                case_id=src, actor=None,
                org_id=(before or after or {}).get("org_id"),
                metadata={"before": before, "after": after,
                          "source_id": src, "run_id": run_id})
            audited_cases.append(src)
    report["phases"]["audit_per_case"] = audited_cases

    if not dry_run:
        await _log("kyb.rollback.script_finished", run_id, {
            "db_name": d.name,
            "cases_restored": len(audited_cases),
            "cascade_deleted_totals": cascade_report,
            "orgs_modified": org_report,
        })

    return report


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def print_report(report: dict) -> None:
    mode = "DRY-RUN (no se escribió nada)" if report["dry_run"] \
        else "EJECUCIÓN REAL"
    print(f"\n===== Rollback KYB legacy — {mode} =====")
    print(f"run_id: {report['run_id']}")
    print(f"db_name: {report['db_name']}")
    print(f"backup ids: {report['backup']['ids']}")
    print(f"migrated_new_case_ids: {report['migrated_new_case_ids']}")

    print("\n--- Verificación de _id (backup vs vivo pre-rollback) ---")
    for cid, chk in report["id_check"].items():
        state = "MATCH" if chk["match"] else (
            "AUSENTE EN VIVO" if not chk["live_present"] else "MISMATCH")
        print(f"  {cid}: backup._id={chk['backup_id']} vs "
              f"live._id={chk['live_id']} [{state}]")

    print("\n--- Fase: dump kyb_documents ---")
    d = report["phases"].get("documents_dump", {})
    print(f"  archivo: {d.get('path')}  docs: {d.get('count')}")

    print("\n--- Fase: cascade_delete (Cat A) ---")
    for coll, n in report["phases"].get("cascade_delete", {}).items():
        print(f"  {coll}: {n}")

    print("\n--- Fase: organizations $unset kyb_case_id ---")
    org = report["phases"].get("organizations_unset_kyb_case_id", {})
    print(f"  matched={org.get('matched')} modified={org.get('modified')}")

    print("\n--- Fase: kyb_cases restore ---")
    cp = report["phases"].get("cases_restore", {})
    print(f"  live_case_ids_to_delete: {cp.get('live_case_ids_to_delete')}")
    print(f"  backup_case_ids_to_insert: {cp.get('backup_case_ids_to_insert')}")
    print(f"  skipped_already_restored: {cp.get('skipped_already_restored')}")
    print(f"  deleted={cp.get('deleted')} inserted={cp.get('inserted')}")

    print("\n--- Fase: audit_per_case (kyb.case.legacy_rollback) ---")
    print(f"  {report['phases'].get('audit_per_case')}")
    print("=" * 46)


async def main() -> int:
    parser = argparse.ArgumentParser()
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--execute", action="store_true")
    parser.add_argument("--force", action="store_true",
                        help="Permite --execute con KYB_MODULE_ENABLED=true.")
    parser.add_argument("--i-know-what-im-doing", action="store_true",
                        dest="iknow",
                        help=f"Permite apuntar a {PROD_DB_NAME!r}.")
    parser.add_argument("--run-id", default=None,
                        help="Identificador de run (para JSON dump y audit).")
    args = parser.parse_args()

    import db as db_module
    d = db_module.db()
    try:
        report = await rollback(d, dry_run=args.dry_run,
                                force=args.force, know=args.iknow,
                                run_id=args.run_id)
    except RuntimeError as e:
        print(f"\n{e}\n", file=sys.stderr)
        return 2
    print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

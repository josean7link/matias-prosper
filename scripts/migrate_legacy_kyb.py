"""Migración de casos KYB legacy al modelo nuevo (Fase 1).

USO:
    python scripts/migrate_legacy_kyb.py --dry-run    # reporta, NO escribe
    python scripts/migrate_legacy_kyb.py --execute    # migración real

La ejecución real exige:
  * KYB_MODULE_ENABLED=true en el entorno.
  * flag --execute explícito.
  * que exista el respaldo `kyb_cases_legacy_backup` con >= 5 docs.

Qué hace:
  * Los 3 seed (org_id null): is_deleted=true (NUNCA borrado físico).
  * Los 2 reales (finpact, alemany): migra al modelo nuevo con
    status=under_review, case_id nuevo, legacy_origin con el id
    original, secciones pending con observación de sistema,
    verification_modes manual, TODO el doc original preservado en
    legacy_data sin transformar.
  * Escribe organizations.kyb_case_id en las 2 orgs migradas (campo
    inerte hoy). `organizations.kyb_status` NO SE TOCA JAMÁS.
  * Auditoría kyb.case.legacy_migrated con before/after completos.

Idempotente: detecta por presencia de `legacy_origin` (reales) y de
`is_deleted=true` (seeds). Correrla dos veces no duplica ni re-migra.

ADVERTENCIA DE IMPACTO CON KYB_MODULE_ENABLED=false:

  Bandeja legacy /admin/compliance/kyb — hoy 5 filas, después 0:
    * los 3 seed se ocultan por is_deleted=true;
    * finpact y alemany quedan ocultos porque la bandeja legacy filtra
      por `verification_modes: {$exists: false}` (blindaje Fase 2.2) y
      la migración escribe `verification_modes` en los 2 casos reales.
    Con el módulo nuevo apagado, esos 2 expedientes reales NO se ven
    en ninguna bandeja: la legacy los excluye por el filtro; la nueva
    no está publicada (flag off).

  Portal cliente /client (routes/client_portal.py):
    * Alemany: `organizations.kyb_status` no se toca y sigue en
      "approved" → stage "approved", 100 %. Sin cambio visible.
    * Finpact: el mismo filtro `verification_modes: {$exists: false}`
      hace que el case migrado no cuente para el progreso legacy. Si
      su `kyb_status` no es "in_review"/"needs_info", el stage cae a
      "not_started" y la barra a 0 %. Cambio observable en el portal.

  organizations.kyb_status NUNCA se modifica — la operatoria efectiva
  (can_operate) no cambia por esta migración.

Por estos efectos con el flag apagado, la ejecución real queda
bloqueada hasta confirmación explícita del operador; el procedimiento
de encendido está documentado en docs/kyb/activation_procedure.md.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / "backend" / ".env")

from models import utc_now                                  # noqa: E402
from kyb.flags import kyb_enabled                            # noqa: E402
from kyb.models import new_case_id, default_sections         # noqa: E402

SEED_IDS = ["kyb_seed_01", "kyb_seed_02", "kyb_seed_03"]
REAL_IDS = ["kyb_apply__finpact", "kyb_apply__alemany"]
BACKUP_COLLECTION = "kyb_cases_legacy_backup"
BACKUP_MIN_COUNT = 5

SYSTEM_OBSERVATION = ("Expediente migrado del módulo KYB anterior. La "
                      "documentación original no fue capturada por esta "
                      "plataforma y debe re-verificarse manualmente.")

# Campos del doc legacy que tienen lugar directo en el modelo nuevo.
# Todo lo demás va COMPLETO y sin transformar a legacy_data (los
# mapeados también se copian ahí, por conservadurismo: no se descarta
# ni transforma nada).
STRUCTURAL_FIELDS = {"_id", "case_id", "org_id", "created_at",
                     "updated_at", "is_deleted"}

# Campos de timestamp que naturalmente cambian entre snapshots — se
# ignoran en la comparación de frescura de backup.
TIMESTAMP_FIELDS = {"updated_at", "created_at", "applied_at", "decided_at",
                    "next_review_at", "expires_at", "submitted_at",
                    "resolved_at"}


def _timeline_shape(v):
    """Reduce timeline a (by, what, meta) — ts es mutable por diseño."""
    if not isinstance(v, list):
        return v
    return [{"by": e.get("by"), "what": e.get("what"), "meta": e.get("meta")}
            for e in v]


def _shape_for_freshness(doc: dict) -> dict:
    """Copia normalizada del doc para comparar backup vs vivo, ignorando
    timestamps puros y reduciendo timeline a estructura estable."""
    out = {}
    for k, v in doc.items():
        if k in TIMESTAMP_FIELDS:
            continue
        if k == "_id":
            continue  # el _id se compara aparte
        if k == "timeline":
            out[k] = _timeline_shape(v)
            continue
        out[k] = v
    return out


async def _assert_backup_fresh(d, seed_ids, real_ids) -> None:
    """Aborta la migración si `kyb_cases_legacy_backup` diverge del
    estado vivo de `kyb_cases` más allá de timestamps.

    Un backup viejo significa que si más tarde hay que rollback, se
    perdería la actividad in-between (esto se descubrió durante el test
    E2E del rollback — ver docs/kyb/activation_procedure.md).
    """
    expected_ids = list(seed_ids) + list(real_ids)
    for cid in expected_ids:
        backup = await d[BACKUP_COLLECTION].find_one({"case_id": cid})
        if backup is None:
            raise RuntimeError(
                f"ABORT[freshness]: {BACKUP_COLLECTION!r} no contiene "
                f"case_id={cid!r}. Regenerá el respaldo antes de migrar.")
        live = await d["kyb_cases"].find_one({"case_id": cid})
        if live is None:
            # El vivo no existe (caso ya movido o borrado antes de migrar):
            # No se puede comparar. La migración de todos modos fallará
            # en la fase siguiente si el vivo no está. No abortamos acá.
            continue
        # _id debe coincidir (opción b del usuario en el rollback).
        if backup.get("_id") != live.get("_id"):
            raise RuntimeError(
                f"ABORT[freshness]: {BACKUP_COLLECTION!r}._id ≠ live._id "
                f"para case_id={cid!r} "
                f"(backup._id={backup.get('_id')!r} vs "
                f"live._id={live.get('_id')!r}). "
                "Regenerá el respaldo antes de migrar.")
        b = _shape_for_freshness(backup)
        l = _shape_for_freshness(live)
        diff = sorted(k for k in set(b) | set(l) if b.get(k) != l.get(k))
        if diff:
            # Reporte detallado del delta en timeline si aplica
            extra = ""
            if "timeline" in diff:
                bt = b.get("timeline") or []
                lt = l.get("timeline") or []
                extra = (f" (timeline: backup_len={len(bt)} vs "
                         f"live_len={len(lt)})")
            raise RuntimeError(
                f"ABORT[freshness]: {BACKUP_COLLECTION!r} vs vivo divergen "
                f"para case_id={cid!r} en campos fuera de timestamps: "
                f"{diff}{extra}. El backup está DESACTUALIZADO — si se "
                "migra ahora y luego hace falta rollback, se perdería la "
                "actividad in-between. Regenerá el respaldo antes de "
                "migrar (ver docs/kyb/activation_procedure.md).")


def build_migrated_doc(old: dict) -> dict:
    """Doc nuevo a partir del legacy. Puro — sin I/O."""
    now = utc_now()
    legacy_data = {k: copy.deepcopy(v) for k, v in old.items()
                   if k not in STRUCTURAL_FIELDS}
    sections = default_sections()
    for s in sections.values():
        s["observation"] = SYSTEM_OBSERVATION
        s["observed_by"] = "system"
        s["observed_at"] = now
    return {
        "case_id": new_case_id(),
        "org_id": old.get("org_id"),
        "status": "under_review",
        "priority": "normal",
        "country_of_incorporation": old.get("country"),
        "applicant_email": None,     # el legacy no capturó email de applicant
        "applicant_name": None,
        "applicant_phone": None,
        "company_name_declared": old.get("legal_name"),
        "sections": sections,
        "verification_modes": {"identity": "manual", "screening": "manual",
                               "company_registry": "manual"},
        "risk": None,                # sin calcular
        "reopen_reason": None,
        "assigned_to": None,
        "submitted_at": old.get("applied_at"),
        "resolved_at": None,
        "next_review_at": None,
        "expires_at": None,
        "resolution": None,
        "suspended": None,
        "legacy_origin": {"source_id": old["case_id"],
                          "migrated_at": now,
                          "original_status": old.get("status")},
        "legacy_data": legacy_data,
        "is_deleted": False,
        "created_at": old.get("created_at") or now,
        "updated_at": now,
    }


async def _org_operability(d, org_id) -> dict:
    if not org_id:
        return {"exists": False}
    org = await d["organizations"].find_one({"org_id": org_id}, {"_id": 0})
    if not org:
        return {"exists": False}
    kyb = org.get("kyb_status")
    sanc = org.get("sanctions_status") or "pending"
    tr = org.get("travel_rule_status") or "pending"
    return {"exists": True, "kyb_status": kyb, "sanctions_status": sanc,
            "travel_rule_status": tr,
            "can_operate": kyb == "approved" and sanc == "clear"
                           and tr in ("clear", "na")}


async def migrate(d, *, dry_run: bool, seed_ids=None, real_ids=None,
                  verify_backup: bool = True,
                  audit_enabled: bool = True,
                  verify_freshness: bool = True) -> dict:
    """Núcleo de la migración. Parametrizable para tests (ids propios,
    sin verificación de backup, sin escritura de auditoría, sin
    verificación de frescura del backup vs vivo)."""
    seed_ids = seed_ids if seed_ids is not None else SEED_IDS
    real_ids = real_ids if real_ids is not None else REAL_IDS
    report: dict = {"dry_run": dry_run, "seeds": [], "cases": [],
                    "skipped": [], "errors": []}

    if verify_backup:
        n = await d[BACKUP_COLLECTION].count_documents({})
        if n < BACKUP_MIN_COUNT:
            raise RuntimeError(
                f"ABORT: respaldo {BACKUP_COLLECTION!r} tiene {n} docs "
                f"(esperado >= {BACKUP_MIN_COUNT}). No se migra sin backup.")
        report["backup_docs"] = n

    # Verificación de frescura del backup vs vivo — bloqueante.
    if verify_freshness:
        await _assert_backup_fresh(d, seed_ids, real_ids)

    kyb = d["kyb_cases"]

    # --- seeds → soft delete -------------------------------------------------
    for sid in seed_ids:
        doc = await kyb.find_one({"case_id": sid})
        if not doc:
            report["errors"].append(f"seed {sid} no encontrado")
            continue
        if doc.get("org_id") is not None:
            report["errors"].append(
                f"seed {sid} tiene org_id={doc['org_id']!r} — se esperaba "
                "null. NO se toca.")
            continue
        if doc.get("is_deleted") is True:
            report["skipped"].append(f"seed {sid} ya estaba is_deleted")
            continue
        report["seeds"].append({"case_id": sid, "action": "is_deleted=true"})
        if not dry_run:
            await kyb.update_one({"case_id": sid},
                                 {"$set": {"is_deleted": True,
                                           "updated_at": utc_now()}})

    # --- reales → modelo nuevo ----------------------------------------------
    for rid in real_ids:
        old = await kyb.find_one({"$or": [
            {"case_id": rid}, {"legacy_origin.source_id": rid}]})
        if not old:
            report["errors"].append(f"caso real {rid} no encontrado")
            continue
        if old.get("legacy_origin"):
            report["skipped"].append(
                f"{rid} ya migrado (legacy_origin presente) — idempotencia")
            continue
        before = {k: v for k, v in old.items() if k != "_id"}
        new_doc = build_migrated_doc(before | {"case_id": rid})
        operability = await _org_operability(d, old.get("org_id"))
        entry = {
            "identificador_original": rid,
            "status_legacy": old.get("status"),
            "status_nuevo": new_doc["status"],
            "case_id_nuevo": new_doc["case_id"],
            "org_id": old.get("org_id"),
            "org_opera_hoy": operability,
            "campos_en_legacy_data": sorted(new_doc["legacy_data"].keys()),
        }
        report["cases"].append(entry)
        if dry_run:
            continue
        # Reemplazo in-place del documento (mismo _id).
        await kyb.replace_one({"case_id": rid}, new_doc)
        # organizations.kyb_case_id (inerte hoy) — kyb_status NO SE TOCA.
        if old.get("org_id"):
            await d["organizations"].update_one(
                {"org_id": old["org_id"]},
                {"$set": {"kyb_case_id": new_doc["case_id"],
                          "updated_at": utc_now()}})
        if audit_enabled:
            from kyb.audit import kyb_audit
            await kyb_audit("kyb.case.legacy_migrated",
                            case_id=new_doc["case_id"], actor=None,
                            org_id=old.get("org_id"),
                            metadata={"before": before, "after": new_doc,
                                      "source_id": rid})
    return report


def print_report(report: dict) -> None:
    mode = "DRY-RUN (no se escribió nada)" if report["dry_run"] \
        else "EJECUCIÓN REAL"
    print(f"\n===== Migración KYB legacy — {mode} =====")
    if "backup_docs" in report:
        print(f"Respaldo {BACKUP_COLLECTION}: {report['backup_docs']} docs ✔")
    print(f"\nSeeds a marcar is_deleted=true: {len(report['seeds'])}")
    for s in report["seeds"]:
        print(f"  - {s['case_id']} → {s['action']}")
    print(f"\nCasos reales a migrar: {len(report['cases'])}")
    for c in report["cases"]:
        op = c["org_opera_hoy"]
        opera = ("SÍ — org.kyb_status="
                 f"{op.get('kyb_status')!r}, sanctions={op.get('sanctions_status')!r}, "
                 f"travel_rule={op.get('travel_rule_status')!r}"
                 if op.get("can_operate") else
                 f"NO (kyb={op.get('kyb_status')!r}, "
                 f"sanctions={op.get('sanctions_status')!r}, "
                 f"travel_rule={op.get('travel_rule_status')!r})"
                 if op.get("exists") else "org inexistente")
        print(f"\n  {c['identificador_original']}")
        print(f"    status legacy:  {c['status_legacy']!r}")
        print(f"    status nuevo:   {c['status_nuevo']!r}")
        print(f"    case_id nuevo:  {c['case_id_nuevo']}")
        print(f"    org_id:         {c['org_id']}")
        print(f"    ¿org opera hoy? {opera}")
        print("    NOTA: organizations.kyb_status NO se modifica — si la "
              "org opera hoy, sigue operando después de la migración.")
        print(f"    campos preservados en legacy_data "
              f"({len(c['campos_en_legacy_data'])}): "
              f"{', '.join(c['campos_en_legacy_data'])}")
    if report["skipped"]:
        print("\nOmitidos (idempotencia):")
        for s in report["skipped"]:
            print(f"  - {s}")
    if report["errors"]:
        print("\nERRORES:")
        for e in report["errors"]:
            print(f"  ! {e}")
    print("\nIMPACTO CON KYB_MODULE_ENABLED=false:")
    print("  Bandeja legacy /admin/compliance/kyb: hoy 5 filas → después 0.")
    print("    - los 3 seeds se ocultan por is_deleted=true;")
    print("    - finpact y alemany quedan ocultos porque la bandeja legacy")
    print("      filtra por verification_modes:{$exists:false} (blindaje")
    print("      Fase 2.2) y la migración escribe verification_modes en")
    print("      los 2 casos reales.")
    print("    Con el módulo nuevo apagado, ambos expedientes reales NO se")
    print("    ven en ninguna bandeja hasta que el flag se encienda.")
    print("  Portal cliente /client:")
    print("    - Alemany: kyb_status queda en 'approved' → stage 'approved',")
    print("      100 %. Sin cambio visible.")
    print("    - Finpact: el case migrado deja de contar para el progreso")
    print("      legacy (mismo filtro). Si su kyb_status no es")
    print("      'in_review'/'needs_info'/'approved', el stage cae a")
    print("      'not_started' y la barra a 0 %.")
    print("  organizations.kyb_status NO SE TOCA — can_operate no cambia.")
    print("  Procedimiento de encendido: docs/kyb/activation_procedure.md")
    print("=" * 46)


async def main() -> int:
    parser = argparse.ArgumentParser()
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    if args.execute and not kyb_enabled():
        print("ABORT: la ejecución real requiere KYB_MODULE_ENABLED=true.")
        return 1

    import db as db_module
    d = db_module.db()
    report = await migrate(d, dry_run=args.dry_run)
    print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

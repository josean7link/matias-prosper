# Procedimiento de encendido — Módulo KYB nuevo

Este documento describe el procedimiento operativo para encender el
módulo KYB nuevo y migrar los casos legacy, cuando la decisión de
activación se tome. Hasta esa decisión, el módulo permanece detrás de
`KYB_MODULE_ENABLED` / `NEXT_PUBLIC_KYB_MODULE_ENABLED` en `false` y
la migración legacy **no se ejecuta**.

Alcance: entorno preview. Producción exige un Deploy explícito
posterior; los pasos son los mismos, aplicados sobre las variables del
entorno productivo.

---

## Regla de oro

Los tres cambios — flag backend, flag frontend, ejecución de la
migración — forman una **única transición atómica**. No dejar
combinaciones intermedias vivas en preview ni en producción.

| Estado | `KYB_MODULE_ENABLED` | `NEXT_PUBLIC_KYB_MODULE_ENABLED` | migración |
|--------|----------------------|----------------------------------|-----------|
| Actual (reposo) | `false` | `false` | no ejecutada |
| Encendido (objetivo) | `true` | `true` | ejecutada una vez |

Ninguna otra combinación es válida. En particular:

- **Migrar con flags apagados deja los 2 casos reales invisibles en
  ambas bandejas y el progreso de Finpact en `/client` puede caer a
  0 %**. No hacerlo.
- Encender solo backend o solo frontend rompe la bandeja
  (backend responde pero UI no monta, o UI monta contra endpoints
  inexistentes).

---

## 0. Precondiciones antes de tocar nada

Ejecutar todo desde `/app`, con el backend en `development` y
`PROSPER_MODE=development` en preview.

- [ ] Se confirmó por escrito la decisión de activar y de ejecutar la
      migración (mismo movimiento).
- [ ] Nadie está operando la bandeja legacy en ese momento (no hay
      analistas revisando expedientes en vivo).
- [ ] El respaldo `kyb_cases_legacy_backup` sigue completo:
      ```bash
      python3 -c "
      import asyncio, os, sys
      sys.path.insert(0, 'backend')
      from motor.motor_asyncio import AsyncIOMotorClient
      from dotenv import load_dotenv
      load_dotenv('backend/.env')
      async def m():
          c = AsyncIOMotorClient(os.environ['MONGO_URL'])
          d = c[os.environ['DB_NAME']]
          n = await d['kyb_cases_legacy_backup'].count_documents({})
          print('backup docs:', n)
          assert n >= 5, 'BACKUP INCOMPLETO — abortar'
      asyncio.run(m())
      "
      ```
      Debe reportar `backup docs: 5`.
- [ ] **Regeneración obligatoria del respaldo desde el vivo** (paso
      añadido tras el hallazgo H1 del test E2E de rollback — ver
      sección 5). El respaldo debe ser una foto exacta e inmediata del
      estado vivo de `kyb_cases` justo antes del dry-run; si el
      respaldo lleva días guardado, la actividad in-between se perdería
      en un rollback. Comando:
      ```bash
      python3 -c "
      import asyncio, os, sys, copy
      sys.path.insert(0, 'backend')
      from motor.motor_asyncio import AsyncIOMotorClient
      from dotenv import load_dotenv
      load_dotenv('backend/.env')
      async def m():
          c = AsyncIOMotorClient(os.environ['MONGO_URL'])
          d = c[os.environ['DB_NAME']]
          live = await d['kyb_cases'].find({}).to_list(None)
          assert len(live) == 5, f'kyb_cases tiene {len(live)}, se esperaban 5'
          # Reemplazo total del respaldo (preservando _id de los vivos)
          await d['kyb_cases_legacy_backup'].delete_many({})
          for doc in live:
              await d['kyb_cases_legacy_backup'].insert_one({**doc})
          n = await d['kyb_cases_legacy_backup'].count_documents({})
          assert n == 5, f'respaldo regenerado tiene {n}, esperado 5'
          print('respaldo regenerado ok:', n, 'docs')
      asyncio.run(m())
      "
      ```
- [ ] **Verificación doc-a-doc de que backup y vivo coinciden** tras la
      regeneración (fuera de campos de timestamp puros y timeline
      normalizado):
      ```bash
      python3 -c "
      import asyncio, os, sys
      sys.path.insert(0, 'backend')
      sys.path.insert(0, 'scripts')
      from dotenv import load_dotenv
      load_dotenv('backend/.env')
      import db as db_module
      from migrate_legacy_kyb import _assert_backup_fresh, SEED_IDS, REAL_IDS
      async def m():
          d = db_module.db()
          await _assert_backup_fresh(d, SEED_IDS, REAL_IDS)
          print('backup fresco vs vivo: OK')
      asyncio.run(m())
      "
      ```
      Debe imprimir `backup fresco vs vivo: OK`. Si tira
      `ABORT[freshness]`, regenerar el respaldo de nuevo y NO
      continuar. La migración misma también valida esto y aborta si el
      respaldo no está fresco.
- [ ] `kyb_cases` en el estado esperado previo (5 documentos, todos
      con `is_deleted=false`, ninguno con `verification_modes` ni
      `legacy_origin`):
      ```bash
      python3 -c "
      import asyncio, os, sys
      sys.path.insert(0, 'backend')
      from motor.motor_asyncio import AsyncIOMotorClient
      from dotenv import load_dotenv
      load_dotenv('backend/.env')
      async def m():
          c = AsyncIOMotorClient(os.environ['MONGO_URL'])
          d = c[os.environ['DB_NAME']]
          docs = await d['kyb_cases'].find({}, {'_id':0, 'case_id':1,
              'is_deleted':1, 'verification_modes':1, 'legacy_origin':1}).to_list(None)
          for x in docs: print(x)
      asyncio.run(m())
      "
      ```
- [ ] Baseline actual de tests sin regresiones:
      ```bash
      python scripts/check_test_baseline.py
      ```
      Debe terminar con `NEW failures: 0`.
- [ ] Snapshot del estado observable actual, para comparar al final:
      - bandeja legacy `/admin/compliance/kyb`: cantidad de filas y
        badges por estado;
      - `/client` de Alemany: `stage` y `%`;
      - `/client` de Finpact: `stage` y `%`;
      - `organizations.kyb_status` de ambas orgs.

Si alguna precondición falla, **detener**. No continuar hasta
resolverla.

---

## 1. Re-ejecución del dry-run

El dry-run se corre siempre inmediatamente antes de la ejecución
real, con los datos actuales (no confiar en dry-runs históricos):

```bash
python scripts/migrate_legacy_kyb.py --dry-run
```

Validar en la salida:

- **Seeds a marcar `is_deleted=true`: 3** (los tres `kyb_seed_*`).
- **Casos reales a migrar: 2** (`kyb_apply__finpact`,
  `kyb_apply__alemany`).
- No hay entradas en **ERRORES**.
- Ninguna entrada dice "ya migrado (legacy_origin presente)".
- El bloque **IMPACTO** dice explícitamente que con el flag apagado
  la bandeja legacy pasaría de 5 a 0 filas y que `kyb_status` no se
  toca.

Si algo difiere, **detener** y revisar antes de continuar.

---

## 2. Encendido de flags (backend y frontend juntos)

Editar `/app/backend/.env`:

```
KYB_MODULE_ENABLED=true
```

Editar `/app/frontend/.env`:

```
NEXT_PUBLIC_KYB_MODULE_ENABLED=true
```

Reiniciar los servicios para que ambos flags queden efectivos antes
de la migración:

```bash
sudo supervisorctl restart backend frontend
```

Verificación inmediata (backend expone las rutas nuevas y sigue
sirviendo las legacy):

```bash
# nueva bandeja admin (Fase 6) — debe existir (200/401, no 404)
curl -s -o /dev/null -w "%{http_code}\n" \
  http://localhost:8001/api/v1/kyb/admin/cases
# alta autogestionada (Fase 2) — debe existir
curl -s -o /dev/null -w "%{http_code}\n" \
  -X POST http://localhost:8001/api/v1/kyb/signup/start \
  -H "Content-Type: application/json" -d '{}'
```

Con el flag apagado ambas responden `404`. Con el flag encendido
responden `401`/`422` (según auth/schema), nunca `404`.

En este momento la UI todavía no muestra casos reales en la bandeja
nueva porque la migración no se ejecutó: la Fase 6 monta la bandeja
sobre casos con `verification_modes`, y hoy ningún caso tiene ese
campo. Es lo esperado.

---

## 3. Ejecución de la migración

Una sola vez, en cuanto los flags están encendidos:

```bash
python scripts/migrate_legacy_kyb.py --execute
```

La salida debe terminar sin **ERRORES**. Si aparece cualquier error,
seguir el bloque de rollback (sección 5) antes de tocar nada más.

La ejecución es idempotente: un segundo `--execute` solo mostrará
"omitidos por idempotencia" para los 5 documentos.

---

## 4. Post-checks

Todos deben pasar antes de dar la fase por cerrada.

### 4.1. Estado en base

```bash
python3 -c "
import asyncio, os, sys
sys.path.insert(0, 'backend')
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv('backend/.env')
async def m():
    c = AsyncIOMotorClient(os.environ['MONGO_URL'])
    d = c[os.environ['DB_NAME']]
    print('kyb_cases:')
    for x in await d['kyb_cases'].find({}, {'_id':0, 'case_id':1,
        'status':1, 'is_deleted':1, 'org_id':1,
        'verification_modes':1, 'legacy_origin.source_id':1}).to_list(None):
        print(' ', x)
    print('kyb_cases_legacy_backup:',
          await d['kyb_cases_legacy_backup'].count_documents({}))
    for o in ('org_seed_finpact','org_seed_alemany'):
        org = await d['organizations'].find_one({'org_id': o},
            {'_id':0,'org_id':1,'kyb_status':1,'kyb_case_id':1})
        print(' org:', org)
asyncio.run(m())
"
```

Debe verse:

- 3 seeds con `is_deleted=true`, sin `verification_modes`, sin
  `legacy_origin`.
- 2 casos reales con `is_deleted=false`, `status='under_review'`,
  `verification_modes` completo (identity/screening/company_registry
  = `"manual"`) y `legacy_origin.source_id` igual al `case_id`
  original.
- `kyb_cases_legacy_backup`: **5 documentos, sin cambios**.
- `organizations.org_seed_finpact` y `org_seed_alemany`:
  `kyb_status` **igual al snapshot previo** (no se tocó) y
  `kyb_case_id` apuntando al `case_id` nuevo correspondiente.

### 4.2. Bandeja nueva

- `/admin/compliance/kyb` — la vista renderiza la bandeja nueva y
  muestra los dos casos reales (Finpact y Alemany) con estado
  `under_review`, banner legacy visible en el detalle, SLA calculado
  contra `submitted_at`.
- Detalle: al abrir cada caso se ven las tabs de Fase 6, la sección
  Verificaciones con modos `manual` y las manuales pendientes.
- La bandeja legacy anterior **ya no aparece** en esta ruta.

### 4.3. Portal cliente

- Alemany: `stage="approved"`, `%=100`, sin cambio vs. snapshot
  previo.
- Finpact: comparar contra snapshot previo. Si su `kyb_status` no era
  `approved`/`in_review`/`needs_info`, el `stage` se ve como
  `not_started` y `%` en `0`, según lo descrito en la advertencia de
  impacto. Esto es esperado con el módulo nuevo encendido, porque el
  progreso legacy dejó de contar y el módulo nuevo tiene su propia
  vista.
- `can_operate` de ambas orgs no debe cambiar (depende de
  `kyb_status`, `sanctions_status`, `travel_rule_status`, `paused`).

### 4.4. Flujos que no se tocan

Confirmar que no se rompieron caminos existentes:

- KYC personal (`kyc_docs_required`, `kyc_docs_submitted`,
  `kyc_pending_andes`) sigue igual.
- Depósitos / detector / snapshot de portfolio: sin cambio.
- `POST /webhooks/aiprise/kyb` y `POST /onboarding/alfred/kyb/start`
  no se tocaron.

### 4.5. Baseline

```bash
python scripts/check_test_baseline.py
```

Debe terminar con `NEW failures: 0`. Si aparecen regresiones, tratar
la fase como abierta hasta resolverlas.

---

## 5. Rollback

El rollback vive en `scripts/rollback_legacy_kyb.py`. **No inventar
comandos**: usar exclusivamente este script. Contrato completo,
abortos, decisiones y reporte E2E documentados abajo.

### 5.1. Cuándo usarlo

- La migración escribió (o intentó escribir) y hay que volver al
  estado pre-migración porque se detectó un problema.
- Se ejecuta **con el módulo apagado** (`KYB_MODULE_ENABLED=false`).
  El script lo verifica y aborta si el módulo está encendido, a menos
  que se pase `--force` explícito (para casos excepcionales donde
  igual haya que revertir con el módulo prendido).

### 5.2. Qué revierte y qué NO

**SE REVIERTE** (categoría A, cascade por `case_id ∈ NUEVOS`):
1. `kyb_cases`: restaura los 5 desde `kyb_cases_legacy_backup` con
   reemplazo total preservando el `_id` del respaldo, y borra los 2
   docs con `case_id` NUEVO generados por la migración.
2. `organizations.kyb_case_id`: `$unset` en las 2 orgs migradas.
   **NUNCA se toca `kyb_status`.**
3. `kyb_manual_checks`, `kyb_external_subjects`, `kyb_shared_links`,
   `kyb_team_invitations`, `kyb_registry_reviews`, `kyb_notifications`
   con `case_id ∈ NUEVOS`.
4. `kyb_documents` (metadatos): **volcado obligatorio a JSON antes de
   borrar** en `/tmp/rollback_kyb_documents_<run_id>.json`
   (case_id, slot, filename, sha256, size_bytes, content_type,
   uploaded_by, uploaded_via, storage_key, _mongo_id). Sin esto, los
   bytes conservados en GridFS quedan huérfanos sin forma de
   reasociarlos.

**SE CONSERVA** (categoría B, no se toca):
- `kyb_verifications` (única prueba del veredicto del proveedor).
- `kyb_screening_hits`.
- `kyb_provider_calls` (TTL 30 días, autolimpia).
- `outbound_emails`.
- `audit_logs` (append-only, jamás se borra). Se **agrega** una
  entrada `kyb.case.legacy_rollback` por caso con `before/after`,
  y entradas `kyb.rollback.script_started` / `.phase` / `.finished`
  vía `log_action`.
- Bytes en GridFS (solo se borra el metadato, no el binario).

### 5.3. Once abortos (9 del contrato + 2 guardias externas)

Ningún aborto es opcional. El script lanza `RuntimeError` explícito
nombrando colección, `case_id` y motivo.

| # | Motivo |
|---|--------|
| A1 | `kyb_cases_legacy_backup` no tiene los 5 `case_id` esperados. |
| A2 | Un caso legacy tiene `verification_modes` y `legacy_origin.source_id` fuera de los 5 conocidos. |
| A3 | `kyb_manual_checks` con actividad humana (`status in_progress/completed`, o `contributors`, o `evidence`). |
| A4 | `kyb_documents` con `uploaded_by ∉ {system, migration}`. |
| A5 | `kyb_shared_links` con `use_count > 0`. |
| A6 | `kyb_verifications` con `outcome ∈ {approved, rejected}` y caso también en `{approved, rejected}`. |
| A7 | `organizations.kyb_case_id` apunta a case_id NUEVO desde una org distinta a `org_seed_finpact`/`_alemany`. |
| A8 | Caso migrado con `status ≠ under_review`. |
| A9 | `audit_logs` con `case_id NUEVO` y `actor_user_id` no nulo (huella humana). |
| A10 | El respaldo diverge del `legacy_data` del caso migrado en campos fuera de timestamps — restaurar llevaría a un estado ANTERIOR al inmediato pre-migración. |
| Guardia | `KYB_MODULE_ENABLED=true` — se exige `--force` explícito. |
| Guardia | La DB destino es exactamente `prosper_phase0` — se exige `--i-know-what-im-doing` explícito. |

### 5.4. Comandos

**Dry-run** (verifica abortos, escribe el volcado JSON de kyb_documents
para inspección, no muta nada):

```bash
python scripts/rollback_legacy_kyb.py --dry-run
```

**Ejecución real** (con el módulo apagado, DB destino distinta a
`prosper_phase0`):

```bash
python scripts/rollback_legacy_kyb.py --execute
```

**Ejecución real contra `prosper_phase0` con el módulo apagado**:

```bash
python scripts/rollback_legacy_kyb.py --execute --i-know-what-im-doing
```

**Ejecución real con el módulo encendido** (excepcional):

```bash
python scripts/rollback_legacy_kyb.py --execute --force
```

Luego apagar flags si aún no lo están:

```
KYB_MODULE_ENABLED=false              # backend/.env
NEXT_PUBLIC_KYB_MODULE_ENABLED=false  # frontend/.env
```

y reiniciar servicios:

```bash
sudo supervisorctl restart backend frontend
```

Post-rollback: repetir sección 0 (precondiciones) para confirmar
que el estado quedó equivalente al inicial. `organizations.kyb_status`
no requiere reversión porque nunca se tocó.

### 5.5. Idempotencia y reanudabilidad

El script deriva la reanudabilidad del **estado real** de las
colecciones. Cada fase verifica antes de escribir; una segunda
corrida termina sin tocar nada si el rollback ya se completó. **No
existe** una colección `kyb_rollback_runs` — el log de progreso vive
en `audit_logs`.

### 5.6. Resultado del test de ida y vuelta (E2E)

Prueba ejecutada contra copia clonada de `prosper_phase0` en
`prosper_phase0_rollback_test_<run_id>` (nunca contra prod). Ver
comando de creación de copia en 5.8.

- ✔ Todos los `_id` del respaldo coinciden con los vivos pre-rollback
  (los 5 case_id: `kyb_seed_01/02/03`, `kyb_apply__finpact/alemany`).
- ✔ Fase `documents_dump`: escritura del JSON obligatoria previa al
  borrado de `kyb_documents`.
- ✔ Fase `cascade_delete`: borrado limpio en las 7 satélites Cat A.
- ✔ Fase `organizations $unset kyb_case_id`: solo `$unset` — sin
  `$set updated_at`. **Nota (H2)**: `updated_at` queda con el valor
  que puso la migración; decisión explícita del contrato (refleja la
  última mutación real del doc). `kyb_status` intacto.
- ✔ Fase `cases_restore`: `deleted=5, inserted=5` con `_id` del
  respaldo preservado.
- ✔ 2 entradas `kyb.case.legacy_rollback` con `before/after`.
- ✔ Diff pre → post-rollback en `kyb_cases` doc-a-doc: 0 diferencias
  cuando el respaldo está fresco.
- ✔ Δ `audit_logs`: +10 acciones (2 migrated + 2 rollback per-case +
  1 script_started + 4 phases + 1 script_finished). Todo lo demás
  (13 colecciones): 0 diferencias.
- Idempotencia: 2ª corrida del rollback termina con
  `deleted=0, inserted=0, skipped=[los 5]`.

### 5.7. Hallazgo H1 y la nueva red de seguridad

Durante el test E2E se descubrió que en `prosper_phase0` el respaldo
`kyb_cases_legacy_backup` **ya estaba desactualizado** respecto al
vivo (`kyb_seed_01.timeline`: 13 entries en backup vs 56 en vivo;
`kyb_apply__finpact.applied_at` divergía). Un rollback ejecutado en
ese estado habría llevado la DB al estado del día en que se tomó el
respaldo, perdiendo la actividad in-between y descubriéndose durante
la reversión.

Contramedidas incorporadas (bloqueantes):

1. **`scripts/migrate_legacy_kyb.py` — aborto `[freshness]`**:
   la migración compara `kyb_cases_legacy_backup` contra `kyb_cases`
   doc-a-doc fuera de timestamps (y con `timeline` reducido a
   `(by, what, meta)`) y aborta si divergen. Con esto, no se puede
   migrar con un respaldo viejo.

2. **`scripts/rollback_legacy_kyb.py` — aborto A10**:
   el rollback compara el respaldo contra el `legacy_data` de los
   casos migrados y aborta si divergen. Con esto, si por alguna razón
   la migración se ejecutó con un respaldo viejo (por ejemplo con
   `verify_freshness=False`), el rollback se niega a restaurar a un
   estado anterior al inmediato pre-migración.

3. **Sección 0 (arriba)**: regeneración obligatoria del respaldo desde
   el vivo como paso previo al dry-run.

### 5.8. Cómo generar la copia de test (para probar rollback sin tocar prod)

```bash
export RUN_ID=$(date +%s)
export MONGO_URL=$(grep MONGO_URL backend/.env | cut -d= -f2-)
export TARGET_DB="prosper_phase0_rollback_test_$RUN_ID"
mongodump --uri="$MONGO_URL" --db=prosper_phase0 \
  --archive=/tmp/dump_$RUN_ID.archive --gzip
mongorestore --uri="$MONGO_URL" \
  --archive=/tmp/dump_$RUN_ID.archive --gzip \
  --nsFrom='prosper_phase0.*' --nsTo="$TARGET_DB.*"
DB_NAME="$TARGET_DB" python scripts/rollback_legacy_kyb.py --dry-run
```

### 5.9. Notas duras

- **Nunca borrar `kyb_cases_legacy_backup`** ni sus documentos.
- No borrar eventos de `audit_logs` de la migración ni del rollback —
  quedan como registro histórico.
- No modificar `organizations.kyb_status` en ningún paso.
- No borrar bytes de GridFS (solo el metadato de `kyb_documents`).
- Nunca ejecutar el rollback contra `prosper_phase0` sin la copia
  del paso 5.8 primero verificada.
- Si el rollback aborta, detener y escalar. No forzar sin resolver
  la causa raíz reportada por el aborto.


---

## Referencias

- Scripts: `scripts/migrate_legacy_kyb.py` y
  `scripts/rollback_legacy_kyb.py` (dry-run vs. execute).
- Tests: `backend/tests/test_kyb_legacy_migration.py`,
  `backend/tests/test_kyb_legacy_rollback.py`.
- Filtro legacy: `backend/routes/compliance/kyb.py` línea 58,
  `verification_modes: {$exists: false}`.
- Filtro portal cliente: `backend/routes/client_portal.py`
  líneas 38-42.
- Flag backend: `backend/kyb/flags.py`.
- Flag frontend: `frontend/src/app/admin/compliance/kyb/page.tsx`
  línea 22 y `frontend/src/app/kyb/_components/KybShell.tsx`.
- Vocabularios: `docs/kyb/state_vocabularies.md`.

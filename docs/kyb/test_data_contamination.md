# Contaminación de datos de producción por la suite de tests

Relevado en Fase 1 (jun 2026). Documenta contaminación **existente** en
la base real (`prosper_phase0`) generada por la suite de tests, que
corre contra el backend vivo. Nada de esto se borra: `audit_logs` es
inmutable por diseño (`AuditMutationError` en update/delete) y así
debe quedar.

## 1. Entradas `kyb.decided` sintéticas en `audit_logs`

**Qué son:** registros de decisiones de compliance KYB que **nadie
tomó**. Los genera `routes/webhooks_aiprise.py:109` cuando la suite
ejercita el webhook de AiPrise con sesiones simuladas
(`tests/test_phase3_onboarding.py` y afines). `audit_logs` es evidencia
regulatoria — estos registros son ruido sintético dentro de ella.

**Cuántas y de cuándo** (medido 2026-06-11; crece con cada corrida
completa de la suite):

| Métrica | Valor |
|---|---|
| Total | 132 |
| Primera | 2026-05-12T23:30:24Z |
| Última | 2026-06-11 (misma corrida del relevamiento) |
| `actor_user_id` | `null` en las 132 |
| `ip` / `user_agent` | `null` en las 132 |

**Cómo se distinguen de un registro real — SÍ hay discriminador:**
el campo `metadata.session_id` lleva el prefijo `sim_` en **132 de
132** entradas (`sim_kyb_…`, generado por el simulador de
`routes/onboarding.py` — "KYC simulator sessions are prefixed
`sim_kyc_…`; KYB ones `sim_kyb_…`"). Un webhook real de AiPrise
llevaría el session id del proveedor, sin ese prefijo.

**Filtro para excluirlas en cualquier revisión/reporte:**
```js
db.audit_logs.find({
  action: "kyb.decided",
  "metadata.session_id": { $not: { $regex: "^sim_" } }
})   // → registros reales (hoy: 0)
```

**Salvedades:**
- `actor_user_id: null` NO sirve como discriminador por sí solo: un
  webhook real legítimo también llega sin actor.
- El discriminador depende de que el simulador conserve el prefijo
  `sim_`. Si alguna vez se cambia ese prefijo, este documento queda
  desactualizado — actualizarlo junto con el cambio.
- Mientras la suite siga corriendo contra el backend vivo, el conteo
  seguirá creciendo. La solución de fondo es el aislamiento de la
  suite (ver `docs/TEST_ISOLATION_BACKLOG.md`).

## 2. La suite manipula el MFA de un usuario real

`tests/test_phase11b_profile.py` (y el smoke e2e de la Fase 0.5.1)
enrolan y desenrolan MFA **del usuario real**
`client.admin@alemany.capital` vía la API viva: escriben y borran
`mfa_secret`, `mfa_backup_codes` y `mfa_enabled` en su documento de
`users`.

**Hoy es inocuo** porque ningún cliente tiene MFA activo (0 usuarios
con `mfa_enabled=true` al cierre de Fase 0). **El día que ese cliente
active MFA de verdad, una corrida de la suite le rompe el acceso**:
el test rota su secreto TOTP y al desenrolar le deja el MFA apagado
(o peor, enrolado con un secreto que el cliente no tiene).

Mitigación de fondo: mismo backlog de aislamiento (usuario de test
dedicado en base de test). Mientras tanto, cualquier activación real
de MFA de ese usuario debe coordinarse con una revisión de este test.

## 3. Otras escrituras de la suite sobre la base real

Inventario completo en `docs/TEST_ISOLATION_BACKLOG.md`. Los dos casos
de patrón destructivo sin filtro (`delete_many({})`) detectados:

| Test | Colección real que barría | Estado |
|---|---|---|
| `test_storage_gridfs.py` | `prosper_files.files/chunks`, `file_access_tokens` (colecciones COMPLETAS) | **Corregido Fase 1** — migrado a base scratch con drop en finally |
| `test_phase13_ramp_provider.py` | `ramp_provider_config` (4 veces, colección completa de config de proveedor ramp) | **Pendiente** — documentado, no tocado (decisión aparte) |

## 4. Eventos `kyb.*` del módulo nuevo generados por pruebas de UI en preview (Fase 3)

La prueba visual de la Fase 3 (flags encendidos temporalmente en
preview) dejó 4 eventos del módulo nuevo en el `audit_logs` real:
`kyb.case.created`, `kyb.signup.contact_saved`,
`kyb.signup.country_saved`, `kyb.signup.activated` (12 jun 2026).

**Cómo se distinguen de eventos reales:**
- `metadata.email` = `ui-test-fase3@preview-prosper.io` (dominio de
  prueba, en el evento `kyb.case.created`).
- `resource_id` = `kyb_0e286bf6ce5c` — un case_id que **ya no existe**
  en `kyb_cases` (los datos de la prueba fueron borrados; el log es
  inmutable y queda). Un evento real siempre referencia un caso vivo o
  soft-deleted.

Filtro: `db.audit_logs.find({action: /^kyb\./, "metadata.email":
/preview-prosper\.io$/})` o por `resource_id` huérfano.

Regla operativa para futuras pruebas de UI en preview con flag on: usar
siempre emails del dominio `@preview-prosper.io` para que esta marca se
mantenga consistente.

## 5. Eventos `kyb.*` de la prueba de UI de la Fase 4 (12 jun 2026)

La prueba visual de la Fase 4 (flags encendidos temporalmente, patrón
idéntico a la Fase 3) dejó eventos del módulo nuevo en `audit_logs`:
`kyb.case.created`, `kyb.signup.contact_saved`, `kyb.signup.country_saved`,
`kyb.signup.activated`, `kyb.document.uploaded`, `kyb.ubo.created`,
`kyb.ubo.confirmed`.

**Cómo se distinguen:** `metadata.email` =
`ui-test-fase4@preview-prosper.io` y `resource_id` = `kyb_5ac1706dd588`
(caso que ya no existe: los datos de la prueba — caso, org
`org_acfc09ce92a2`, user, UBO, documento y su binario GridFS — fueron
borrados; el log inmutable queda). Mismo filtro que la sección 4.

## 6. Eventos `kyb.*` de la prueba de UI de la Fase 5a (12 jun 2026)

La prueba visual de la Fase 5a (flags encendidos temporalmente) dejó
eventos del módulo nuevo en `audit_logs`: los del ciclo signup/case
(como §5) más `kyb.case.submitted`, `kyb.manual_check.generated` (×6) y
`kyb.manual_check.item_completed` (×1, actor `compliance@prosper.foundation`).

**Cómo se distinguen:** `metadata.email` =
`ui-test-fase5a@preview-prosper.io` y `case_id`/`resource_id` =
`kyb_ed17fa3097ce` (caso borrado junto con org `org_f57cef4d101f`, user,
UBO, 5 documentos + binarios GridFS y 6 checklists; el log inmutable
queda).

**Datos que QUEDAN a propósito** (contenido legítimo del módulo, invisible
con flag off): las 3 plantillas seed de `kyb_manual_check_templates` y el
doc singleton default de `kyb_verification_modes`.

Segunda prueba de UI (correcciones post-5a, mismo día): eventos análogos
con `metadata.email` = `ui-test-fase5a2@preview-prosper.io` y `case_id` =
`kyb_40924cbf6dda` (incluye `kyb.manual_check.evidence_discarded`). Datos
borrados (org `org_4b90c1301bce` incluida); el log inmutable queda.
También queda `tpl_identity_global` v2 activa (v1 inactiva) publicada por
el seed con upgrade.

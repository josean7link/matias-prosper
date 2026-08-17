# Dos vocabularios de estado KYB conviviendo (Fase 1)

Desde la Fase 1 existen **dos vocabularios de estado independientes**
que NO deben mezclarse. Unificarlos es una decisión pendiente para
cuando se retire la bandeja legacy (previsto: Fase 6).

## 1. Vocabulario legacy — `organizations.kyb_status`

Valores: `pending | in_review | approved | rejected | needs_info | paused`

**Alimenta:**
- `kyb_locked` en los feature flags de `/api/v1/me` (`server.py::_feature_flags`)
  → decide si un cliente **puede operar** (`canOperate`). Es lógica de
  bloqueo en producción con dinero real.
- La bandeja legacy `routes/compliance/kyb.py` escribe estos valores en
  `kyb_cases.status` (más `needs_info` en decisiones).
- Gates del middleware de Next.js y vistas del portal cliente.

**Regla dura del módulo nuevo: `organizations.kyb_status` no se escribe
NUNCA desde el módulo KYB nuevo.** Sus valores no existen en el
vocabulario nuevo y escribirlo produciría comportamiento impredecible
en la lógica de bloqueo.

## 2. Vocabulario nuevo — `kyb_cases.status` (modelo Fase 1)

Valores: `draft | in_progress | submitted | screening | under_review |
info_required | approved | rejected | expired`

**Alimenta:** la máquina de estados (`backend/kyb/state_machine.py`) y,
en fases futuras, la bandeja nueva de revisión. No alimenta `kyb_locked`
ni ninguna lógica de operación existente.

## Puente entre ambos

- `organizations.kyb_case_id` (agregado en Fase 1, default `None`):
  vincula la org con su caso del modelo nuevo. **Inerte hoy** — ningún
  flujo lo lee.
- Los casos migrados conservan el estado legacy original en
  `legacy_origin.original_status` y el doc completo en `legacy_data`.

## Solapamiento en `kyb_cases`

`kyb_cases` es UNA sola colección compartida: la bandeja legacy
(`/admin/compliance/kyb`) lee los mismos documentos que el modelo
nuevo extiende. Los estados legacy que la bandeja escribe
(`approved/rejected/needs_info`) y los del modelo nuevo coexisten en el
mismo campo `status`. Por eso la migración de los casos legacy es un
cambio observable en esa pantalla y está bloqueada hasta decisión
explícita (ver `scripts/migrate_legacy_kyb.py`).

## Decisión pendiente

Unificación de vocabularios + retiro de la bandeja legacy: se decide
cuando esa pantalla se reemplace (Fase 6). Hasta entonces, ninguna
migración de datos ni escritura cruzada entre vocabularios.

## Migración de casos legacy — POSTERGADA A FASE 6 (decisión Fase 1)

La migración de `kyb_seed_01/02/03` (soft-delete) y de
`kyb_apply__finpact` / `kyb_apply__alemany` (modelo nuevo) altera lo
que muestra la bandeja legacy `/admin/compliance/kyb` (5 filas → 2,
alemany `approved`→`under_review`), lo cual viola la regla de no
impacto observable con `KYB_MODULE_ENABLED=false`.

**Decisión del operador (Fase 1):** la migración real se ejecuta en la
**Fase 6**, junto con el reemplazo de la bandeja legacy, para que el
cambio de datos y el de pantalla ocurran juntos y no haya ventana de
inconsistencia. `scripts/migrate_legacy_kyb.py` queda bloqueado tal
como está (dry-run libre; `--execute` exige `KYB_MODULE_ENABLED=true`
+ confirmación explícita del operador). El dry-run ya fue validado
contra los datos reales sin escrituras.

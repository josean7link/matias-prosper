# Acceso de escritura al expediente KYB (Fase 3 → Fase 8)

## Estado actual (Fase 4)

Toda escritura sobre el expediente (`PUT /api/v1/kyb/case/*`,
`POST/DELETE .../documents*`, `POST/PUT/DELETE .../ubos*`,
`POST .../ubos/confirm`, `POST .../submit`) exige:
1. Sesión de cliente (cookie `prosper_session`), y
2. Rol **`client_admin`** de la organización dueña del caso
   (`_require_admin` en `backend/kyb/routes_case.py`).

Los demás roles de la org solo leen (`GET /kyb/case`). No existe ningún
camino de escritura sin sesión.

## Deuda declarada para la Fase 8 — enlace compartido

La Fase 8 introduce «Compartir link de acceso» (hoy deshabilitado en la
cabecera del wizard): un tercero SIN sesión y SIN rol (ej. el contador
de la empresa) debe poder **cargar documentación**.

Eso exige un camino de escritura nuevo que NO existe hoy:
- autenticado por token de `kyb_shared_links` (hash en reposo, scope[],
  expiración, revocación — la colección ya existe desde Fase 1),
- **acotado exclusivamente a los slots de documentación** (`POST
  /documents`, `confirm`) — jamás a las secciones de datos ni al CUIT,
- con `uploaded_via: "shared_link"` + `shared_link_id` en cada
  documento (los campos ya existen en el modelo `KybDocument`),
- y con los guards de estado actuales (`_guard_editable`) intactos.

**No implementado a propósito.** Quien tome la Fase 8: el punto de
entrada es desacoplar `_require_admin`/`get_case_ctx` en
`routes_case.py` hacia una dependencia que acepte sesión-admin O token
de shared link con scope de documentación. No descubrirlo tarde.

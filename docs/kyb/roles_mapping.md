# Mapeo de roles KYB — Fase 8

## Estado vigente

El enum `Role` (`backend/roles.py`) tiene dos roles de cliente:
`client_admin` y `client_user`. La sección Equipo del wizard KYB
propone tres roles operacionales:

| Wizard        | Descripción del wizard                             | Persistimos en `users.role` | `intended_role` |
|---------------|-----------------------------------------------------|-----------------------------|-----------------|
| ADMINISTRADOR | Puede ver y operar, pero no gestionar miembros      | `client_admin`              | `administrator` |
| OPERADOR      | Puede ver información y crear envíos de dinero      | `client_user` *(prometemos de menos)* | `operator` |
| SÓLO LECTURA  | Solo puede ver información, no puede operar         | `client_user`               | `read_only`     |

Decisión (opción B — feb 2026): OPERADOR se mapea a `client_user`
porque el matiz "operar sin gestionar miembros ni ver todo" no existe
todavía en el backend. Entre **prometer de más** y **dar de más**
elegimos prometer de más y ampliar permisos por pedido explícito.

La tarjeta del wizard aclara al usuario que la capacidad de OPERADOR
"está en implementación" para que la promesa coincida con lo que el
backend entrega hoy.

## Qué haría falta para cerrar el modelo real

Cerrar la brecha implica tocar, en orden:

1. `backend/roles.py` — agregar `client_operator` (y opcionalmente
   `client_readonly` si querés separarlo explícito de `client_user`).
   Actualizar `CLIENT_ROLES`.
2. `backend/server.py` — sumar entradas en el mapa de permisos por
   rol (`_permissions_for`). Definir a qué recursos accede cada uno
   (probablemente: `client_operator` = `client_admin` menos
   `user:write:self` y sin `api_keys:manage`; `client_readonly` =
   `client_user` sin ninguna escritura).
3. `frontend/src/middleware.ts` — sumar los nuevos strings al set
   `CLIENT_ROLES`. El test `test_middleware_roles_parity.py` verifica
   el espejo en cada CI.
4. `backend/routes/admin_clients/users.py` — extender el `Literal` de
   los endpoints de creación/edición para aceptar los nuevos roles.
5. `backend/routes/subclients.py`, `deposit_credited_handler.py`,
   `activation.py`, `client_kyc.py`, `client_invest.py`, `travel_rule.py`
   y `ramp_routes.py` — cada uno hace hoy chequeos explícitos por
   `client_admin`/`client_user`; revisar cada uno individualmente
   antes de asumir que un `client_operator` puede pasar por ahí.
6. `backend/kyb/routes_case.py` — hoy toda escritura del wizard exige
   `client_admin` (`_require_admin`). Decidir si el nuevo
   `client_operator` puede editar secciones del wizard o solo
   colaborar con documentación (equivalente a shared link).
7. Migración de usuarios existentes: `users` con
   `intended_role="operator"` deben migrarse a `role="client_operator"`
   una vez publicado el nuevo enum. Es un update masivo, no un cambio
   de esquema — el campo `intended_role` seguirá existiendo como
   trazabilidad.
8. Actualizar la tarjeta del wizard para eliminar la aclaración "en
   implementación".

Mientras esos ocho puntos no estén cerrados, `intended_role` sigue
siendo la fuente de verdad de la intención declarada por el
administrador en el wizard, y `role` sigue siendo la fuente de verdad
de lo que efectivamente puede hacer el usuario en el backend.

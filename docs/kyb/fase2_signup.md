# Fase 2 — Signup KYB: operación y prueba de email

## Email de activación — cómo disparar una prueba

Hoy `RESEND_API_KEY` está vacía → `integrations/email_sender.py` cae en
modo **preview**: el email se persiste en `outbound_emails` con
`status: "preview_only"` y NO se envía. Ese comportamiento se deja así;
la key la activa el operador después de verificar.

### Comando de prueba (contra el server con flag encendido)

Con `KYB_MODULE_ENABLED=true` en el backend, el flujo completo dispara
el email en el paso país. Para probar contra una casilla concreta
(reemplazar `CASILLA@DOMINIO`):

```bash
BASE=https://<host>   # o http://127.0.0.1:8001 en el pod
TOK=$(curl -s -X POST "$BASE/api/v1/kyb/signup/start" \
  -H "Content-Type: application/json" \
  -d '{"email":"CASILLA@DOMINIO","company_name":"Prueba Email SA"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['signup_token'])")
curl -s -X POST "$BASE/api/v1/kyb/signup/contact" \
  -H "Content-Type: application/json" \
  -d "{\"signup_token\":\"$TOK\",\"full_name\":\"Prueba Operador\",\"phone\":{\"country_code\":\"+54\",\"number\":\"1150000000\"}}"
curl -s -X POST "$BASE/api/v1/kyb/signup/country" \
  -H "Content-Type: application/json" \
  -d "{\"signup_token\":\"$TOK\",\"country\":\"AR\"}"
```

- Con `RESEND_API_KEY` vacía: verificar el registro en Mongo —
  `db.outbound_emails.find({to: "CASILLA@DOMINIO", template: "kyb_activation"})`
  (el HTML contiene la URL `/kyb/activate?token=…`).
- Con la key activa: el correo llega a la casilla; asunto
  «Activá tu cuenta de Prosper».
- Reenvío: `POST /api/v1/kyb/signup/resend` con `{"email": "CASILLA@DOMINIO"}`
  (límite 3/hora por email).

### Idempotencia

Clave: `kyb.activation:{case_id}:{recipient}:{token_disc}` — el triple
`(event_type, case_id, recipient)` de la spec + un discriminador del
token de activación (sha256 del claro, 12 hex). Sin el discriminador un
reenvío legítimo (token nuevo) quedaría deduplicado contra el primer
envío. Un retry del MISMO envío (mismo token) sí deduplica.

## Flags

| Variable | Dónde | Efecto |
|---|---|---|
| `KYB_MODULE_ENABLED` (false) | backend/.env | Registra las rutas `/api/v1/kyb/*` y los índices |
| `NEXT_PUBLIC_KYB_MODULE_ENABLED` (false) | frontend/.env | Renderiza las páginas `/kyb/*` (con false → 404) |
| `KYB_ACTIVATION_TOKEN_TTL_HOURS` (72) | backend/.env | TTL del magic link (un solo uso) |
| `KYB_SIGNUP_TOKEN_TTL_HOURS` (2) | backend/.env | TTL del token de wizard (multi-uso, solo contact/country) |

### Paridad de flags — SE CAMBIAN SIEMPRE JUNTOS

`KYB_MODULE_ENABLED` y `NEXT_PUBLIC_KYB_MODULE_ENABLED` son dos
variables porque viven en dos procesos distintos (FastAPI lee env en
runtime; Next.js hornea `NEXT_PUBLIC_*` en el build). El test
`tests/test_kyb_flag_parity.py` falla si los archivos .env divergen.
Nota: el flag del frontend requiere **rebuild/restart** del frontend
para tomar efecto; el del backend, restart del backend.

Matriz de combinaciones:

| Backend | Frontend | Resultado |
|---|---|---|
| false | false | Estado actual. Nada del módulo existe. ✔ |
| true | true | Módulo activo completo. ✔ |
| **true** | **false** | Silencioso y engañoso: las APIs `/api/v1/kyb/*` responden y los índices se crean, pero las pantallas dan 404 — nadie puede darse de alta y parece que "no pasa nada". Además la superficie pública de la API queda expuesta sin su UI. |
| **false** | **true** | Roto de cara al público: las pantallas renderizan, el usuario completa el formulario y cada submit falla con 404. La peor combinación — experiencia pública rota. |


## Anti-enumeración (resumen operativo)

- `start`/`resend`: 200 idéntico exista o no el email, con piso de
  tiempo de respuesta (350 ms) para igualar timing.
- Sondeos (email ya registrado, caso approved o rejected): **no se
  envía ningún correo** y queda `kyb.signup.probe_attempt` en
  `audit_logs` con el motivo — consultar para detectar patrones:
  `db.audit_logs.find({action: "kyb.signup.probe_attempt"})`.
- Canal residual conocido: quien recibe el señuelo de `start` puede
  notar que `contact` falla con 401 — indistinguible de un token
  vencido, pero un observador persistente podría inferir. Aceptado como
  trade-off en Fase 2 (documentado, no silencioso).

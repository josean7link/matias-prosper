# `INTEGRATIONS_FERNET_KEY` — inyección por entorno (Fase 0.5.1)

Clave Fernet que cifra en reposo las credenciales de integraciones de
terceros (Sumsub, Resend, S3, …) vía `services/secret_box.py`. Es un
par de claves independiente de `MFA_FERNET_KEY`: comprometer una no
expone lo cifrado con la otra.

## Regla

**Esta clave NO se escribe en ningún archivo del repo.** No va en
`backend/.env`, ni en ningún archivo trackeado o untrackeado dentro de
`/app`. La clave generada en Fase 0.5 (que vivió brevemente en
`backend/.env`, untrackeado) queda **descartada** — cada entorno carga
una clave nueva propia.

## Generar una clave

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Generarla en el entorno destino (o en una máquina segura) y cargarla
directamente en el mecanismo de inyección — nunca pegarla en un
archivo del repo, un chat, un ticket o un commit.

## Cómo se inyecta (sin archivos)

El backend lee `os.environ` en el momento de uso — cualquier mecanismo
que ponga la variable en el **entorno del proceso** sirve:

| Entorno | Mecanismo |
|---|---|
| Producción (deploy Emergent) | Variables de entorno / secret store del panel de deployment. Se cargan al crear el deploy; nunca tocan el repo. |
| Pod de preview | `environment=` en la conf de supervisor **fuera del repo** (`/etc/supervisor/conf.d/`), igual que `ANDES_API_KEY` del andes-gateway. Luego `sudo supervisorctl restart backend`. |
| Sesión local puntual | `export INTEGRATIONS_FERNET_KEY=...` en la shell antes de lanzar el proceso (muere con la shell; no persiste). |

Rotación: cargar la clave nueva en `INTEGRATIONS_FERNET_KEY` y la
anterior en `INTEGRATIONS_FERNET_KEY_PREVIOUS`. `secret_box` escribe
siempre con la actual y lee probando actual → anterior. Cuando el
sweep de re-cifrado esté confirmado, retirar `_PREVIOUS`.

## Comportamiento si falta

El backend **arranca igual** (la clave se lee de forma lazy). El
primer `encrypt()`/`decrypt()` de integraciones falla con un error
claro que nombra la variable, sin stacktrace de Fernet:

```
SecretBoxError: INTEGRATIONS_FERNET_KEY not configured — refusing to
store or read encrypted secrets in plaintext. Inject it via the
process environment (see docs/INTEGRATIONS_FERNET_KEY.md).
```

Ningún flujo actual de mainnet consume todavía este par de claves
(los consumidores llegan con el módulo KYB), por lo que su ausencia no
degrada nada existente.

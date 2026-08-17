# Suite de pytest — Prosper backend

Esta suite corre contra bases de datos **de test** — jamás contra la
base real de runtime (`prosper_phase0`). El `conftest.py` bloquea
cualquier intento de correr contra ella y aborta la sesión antes de
ejecutar un solo test.

## Cómo correr los tests

### Corrida por defecto (sin recursos reales)

```bash
cd /app/backend
DB_NAME=prosper_tests_default python -m pytest -q
```

La variable `DB_NAME` **debe** estar en la lista blanca del guard.
Patrones aceptados (regex sobre el nombre de la DB):

- `prosper_test[s][_<sufijo>]`
- `prosper_tests_default` (el default aplicado por el conftest si no
  se exporta ninguno)
- `prosper_kyb_tests[_<sufijo>]`
- `prosper_phase0_(test|tests|rollback_test)_<sufijo>`
- `prosper_aiprise_kyb_dropped_tests`
- `prosper_apply_individual_tests`
- `prosper_scratch[_<sufijo>]`

Si no se exporta `DB_NAME`, el conftest usa `prosper_tests_default`
automáticamente.

El host de Mongo debe estar en `{localhost, 127.0.0.1, mongo,
mongodb}`. Para permitir otros hosts (por ejemplo en un runner con
Mongo remoto autorizado), exportar:

```bash
export PROSPER_TESTS_ALLOWED_MONGO_HOSTS=mongo.internal.acme,10.0.0.5
```

### Tests contra APIs externas reales (marcados `live`)

Por defecto se **excluyen** (`addopts = -m "not live"` en `pytest.ini`).
Alcanzan sandboxes de terceros:

- `test_prosper_real_live.py` — pega contra el sandbox de Prosper.
  Requiere `PROSPER_MODE ∈ {development, production}` + credenciales
  `PROSPER_API_USER` / `PROSPER_API_PASS`.
- `test_alfred_real_live.py` — pega contra el sandbox de Alfred Pay
  Penny. Requiere `ALFRED_MODE ∈ {sandbox, production}` +
  `ALFRED_API_KEY` / `ALFRED_API_SECRET`.

Para correrlos explícitamente:

```bash
DB_NAME=prosper_tests_default python -m pytest -m live -q
```

## Qué protege el conftest

### Guard 1 — destino de Mongo autorizado

Corre en `pytest_configure`, antes que cualquier fixture. Aborta la
sesión (`pytest.exit(returncode=4)`) en tres escenarios:

1. `DB_NAME == "prosper_phase0"` (o cualquier alias explícitamente
   prohibido). Mensaje: apunta a la base real de producción.
2. `DB_NAME` no coincide con la whitelist. Mensaje: patrón inválido,
   exportar DB_NAME explícito.
3. `MONGO_URL` con host fuera de la lista permitida. Mensaje: usar
   `PROSPER_TESTS_ALLOWED_MONGO_HOSTS` para autorizarlo.

No hay skip ni warning: la sesión no arranca.

### Guard 2 — `delete_many({})` sin filtro

Corre en `pytest_collection_modifyitems`. Escanea `backend/tests/`
por la expresión `.delete_many({})` sin filtro y aborta si aparece.
Motivación: en el pasado esa expresión borró colecciones enteras al
correr accidentalmente contra la base real.

**Opt-out puntual** (solo para colecciones scratch garantizadas):

```python
await d[BACKUP_COLLECTION].delete_many({})  # noqa: PROSPER_ALLOW_UNFILTERED_DELETE
```

El comentario debe ir en la misma línea.

## Casos especiales

### Tests que levantan un uvicorn efímero

Algunos tests (`test_kyb_signup.py`, `test_simulate_and_magic_link_prod_blocked.py`)
levantan uvicorn de test en puertos alternativos (8013, 8014, etc.)
con `DB_NAME` scratch y flags específicos. Son 100% autocontenidos y
no dependen del backend del pod.

### Tests que aún dependen del backend del pod

Los siguientes archivos apuntan a `http://localhost:8001` (backend
real del pod) y **no** están aislados. En una corrida contra
`DB_NAME=prosper_tests_default` los endpoints responden pero contra
datos reales — deberían migrarse a servidores efímeros dedicados
como próximo paso:

- `test_sprint_a.py` (WS a puerto 8001)
- `test_iter31_p11_deposit_wallets.py`
- `test_phase1.py`, `test_phase3_operations.py`, `test_phase9_invest.py`
- `test_phase11a_extras.py`, `test_phase11_developer.py`,
  `test_phase11b_profile.py`
- `test_phase15_2_intl_offramp.py`
- `test_andes_kyc_widget.py`

### Tests que abren su propia DB de scratch dentro del fixture

Muchos tests (`test_apply_individual_still_works.py`,
`test_aiprise_kyb_dropped.py`, `test_kyb_legacy_rollback.py`,
`test_kyb_legacy_migration.py`, etc.) hacen
`os.environ["DB_NAME"] = "prosper_<algo>_tests"` en el fixture y
resetean el cliente Motor. Estos son seguros: escriben sólo en la DB
scratch dentro del fixture. El guard del conftest sólo mira la
`DB_NAME` inicial de la sesión.

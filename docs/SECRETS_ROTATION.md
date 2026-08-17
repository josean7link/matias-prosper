# Secrets rotation inventory (Fase 0, Aug 2026)

Every secret listed below was at some point present in a file that git
tracked. Even after the file has been untracked, the value **remains
in the git history** and must be treated as compromised until proven
otherwise.

The commit history has NOT been rewritten — this is a live-repo
inventory of what to rotate, not what has been rotated.

## What "rotated" means here

A secret is rotated only when **all** of these are true:
1. The provider issued a new value.
2. Every runtime environment that consumed the old value now uses the new one.
3. The old value has been revoked/invalidated on the provider side (not just replaced).
4. The date and operator of steps 1-3 is recorded below.

If a step is missing, the row status is `pending` — not `rotated`.

## Inventory

| Secret | Where it lives now | In git history? | Rotation status | Notes |
|---|---|---|---|---|
| `JWT_SECRET` | `backend/.env` (untracked as of Fase 0) | **YES** | pending | Signs `prosper_session` cookies. Rotating invalidates all live sessions — coordinate a maintenance window or accept a forced logout. |
| `GATEWAY_INTERNAL_TOKEN` | `backend/.env`, `services/andes-gateway/.env` | **YES** | pending | Auth between backend ↔ andes-gateway (in-cluster). Rotate both env files together. |
| `PROSPER_API_PASS` | `backend/.env` | **YES** | pending | Password for CMS user `prosperCMS@mail.com`. Ask Prosper CMS ops to reset. |
| `PROSPER_API_USER` | `backend/.env` | **YES** | pending | Not a secret in isolation but leaks the CMS account name. |
| `MFA_FERNET_KEY` | `backend/.env` | **YES** | in progress — Fase 0 | New key generated Fase 0; sweep script `scripts/reencrypt_mfa_secrets.py` rotates ciphertexts. `MFA_FERNET_KEY_PREVIOUS` retires only after sweep confirmed. At time of Fase 0 kickoff there are **0 users with `mfa_enabled=true`** and **1 with `mfa_pending`**, so ciphertext blast-radius is minimal. |
| `AIPRISE_API_KEY_SANDBOX` | `backend/.env` | **YES** | pending | AiPrise integration is deprecated (`AIPRISE_DEPRECATED=1`), lowering practical risk. Still rotate before ever re-enabling. |
| `AIPRISE_API_KEY_PRODUCTION` | `backend/.env` | **YES** | pending | Same as above. |
| `AIPRISE_WEBHOOK_SECRET` | `backend/.env` | **YES** | pending | HMAC secret for `POST /webhooks/aiprise/*`. If rotated, must also be updated on AiPrise dashboard. |
| `MONGO_URL` | `backend/.env` | **YES** | not applicable | `mongodb://localhost:27017` in preview — no credentials embedded. Verify per environment. |
| `RESEND_API_KEY` | `backend/.env` (empty in preview) | **YES** (empty) | not applicable | Currently unset. First real value must NOT be committed. |
| `EMERGENT_LLM_KEY` | `backend/.env` | **YES** | pending | Universal key for OpenAI/Anthropic/Gemini via Emergent. Prosper account key — rotate via Emergent Profile → Manage Plan → Universal Key. |
| `.andes-private-key.pem.MOCK.bak` (EC private key file) | `services/andes-gateway/.andes-private-key.pem.MOCK.bak` | **YES — file is tracked** | untrack + rotate | Despite the `MOCK` in the name, the file contents are a valid EC private key in PEM format. Removed from `prosper-clean-export.zip` in Fase 0, still present on the working tree and in git. Recommend: `git rm --cached` + generate a fresh key for the gateway. |

## `INTEGRATIONS_FERNET_KEY` — added Fase 0.5.1

The key generated in Fase 0.5 lived briefly in `backend/.env`
(untracked since Fase 0 → **not** in git history) and was **discarded**
in Fase 0.5.1. It is now removed from `backend/.env` and must never be
written to any file in the repo. Each environment injects its own
fresh value via the process environment — see
`docs/INTEGRATIONS_FERNET_KEY.md`. Rotation uses the dual-key pair
`INTEGRATIONS_FERNET_KEY` / `INTEGRATIONS_FERNET_KEY_PREVIOUS`
(handled by `services/secret_box.py`).

## Pendientes — cifrado en reposo NO migrado (decisión separada)

Campos que hoy declaran "encrypted on write" como placeholder o
directamente guardan el valor en claro. **NO migrar** hasta que una
fase lo autorice explícitamente: la migración exige un sweep de datos
existentes (leer → cifrar → reescribir cada documento) y es una
decisión operativa aparte, no un cambio de código puntual.

| Campo | Dónde | Estado real hoy |
|---|---|---|
| `User.mfa_secret` | `backend/models.py:78` | El modelo lo marca "encrypted on write — placeholder here". El flujo vivo (`routes/client_profile.py`) SÍ cifra con `SecretBox("MFA_FERNET_KEY", …)` antes de persistir; el placeholder del modelo sigue sin garantizarlo a nivel esquema. |
| `WebhookEndpoint.hmac_secret` | `backend/models.py:237` | Secreto HMAC de webhooks de cliente, **hoy en claro** en Mongo. Candidato al par `INTEGRATIONS_FERNET_KEY` vía `secret_box`. Requiere sweep de los documentos existentes en `webhook_endpoints` + camino de rollback. |

## `ANDES_API_KEY` — clarification

**Corrected Fase 0 (post-review).** An earlier version of this doc
said "there is no `ANDES_API_KEY` variable in this project". That was
only correct for `backend/.env`. The **andes-gateway** service does
consume an `ANDES_API_KEY`, injected by supervisor at process start
(see the andes-gateway section further down). All backend ↔ Andes
communication still goes through the gateway (using
`GATEWAY_INTERNAL_TOKEN`), not through a direct backend-owned
`ANDES_API_KEY`.

## Compromised secrets — high priority

### `services/andes-gateway/.andes-private-key.pem` (EC private key)

| Field | Value |
|---|---|
| Status | **COMPROMISED** — rotation pending at AndesLabs |
| Exposure window | 2026-06-05 18:58:38 UTC (commit `8ed9789`) → 2026-08-XX (Fase 0 untrack) |
| Path in git history | `services/andes-gateway/.andes-private-key.pem.MOCK.bak` — byte-identical copy of the live signing key |
| What it signs | JWTs sent by the gateway to AndesLabs (see `services/andes-gateway/src/server.ts:96` — `readFileSync(ANDES_PK_PATH,"utf8")` → `jsonwebtoken.sign(...)`) |
| Live path today | `services/andes-gateway/.andes-private-key.pem` (never tracked, listed in gateway `.gitignore`) |
| Fase 0 remediation | `git rm --cached services/andes-gateway/.andes-private-key.pem.MOCK.bak`; gateway `.gitignore` broadened to `*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.bak`, `*.old`, `*.copy`, `*.orig`, `*.backup` so a future rename does not re-slip. |
| What is NOT done | The compromised key still exists in commit history (untrack does not rewrite history) AND is still the active signing key on the running gateway. Rotation requires (a) generate new EC keypair, (b) register public half at AndesLabs, (c) swap `/app/services/andes-gateway/.andes-private-key.pem`, (d) restart gateway, (e) revoke old public half at AndesLabs. |

## Files that still leak inside the tracked tree (verified Fase 0)

Search performed:
```
git ls-files | xargs grep -lE "(bearer\s+[A-Za-z0-9]{20,}|BEGIN [A-Z ]+PRIVATE KEY|\"password\":\s*\"...)"
```
Result: 1 file.

- `services/andes-gateway/.andes-private-key.pem.MOCK.bak` — EC private
  key material. Listed above.

All other secrets currently live in `backend/.env` / `frontend/.env` /
`services/andes-gateway/.env`, which are now `.gitignore`d and
untracked as of Fase 0 (they remain in commit history).

## Recommended sequence (does not execute in Fase 0)

1. Rotate `MFA_FERNET_KEY` (in progress).
2. Untrack the EC private key file, regenerate the key, redeploy gateway.
3. Rotate `GATEWAY_INTERNAL_TOKEN` (backend + gateway simultaneously).
4. Rotate `JWT_SECRET` during a maintenance window (forces re-login).
5. Rotate CMS password with Prosper ops.
6. Rotate AiPrise keys (deprecated but still exposed).
7. Rewrite git history to purge tracked `.env` blobs (BFG / git filter-repo)
   after all rotations, OR accept that history holds only expired values.

## `services/andes-gateway/` credentials — added Fase 0 (post-review)

The andes-gateway service does **not** have a `.env` file. It reads
its configuration from process environment injected by supervisor:
`/etc/supervisor/conf.d/supervisord_andes_gateway.conf`. That
supervisord file **is not tracked in this repo** (lives in the pod
under `/etc/supervisor/conf.d/`) but the values it carries end up in
the running process. For inventory completeness, the variable names it
injects today (values redacted, never listed here):

| Variable | Purpose |
|---|---|
| `ANDES_GATEWAY_MODE` | `real` vs `mock` selector |
| `ANDES_API_KEY` | AndesLabs REST API key used by the gateway to talk to Andes upstream |
| `ANDES_JWT_PRIVATE_KEY_PATH` | Filesystem path to the EC private key that signs JWTs for AndesLabs (`.andes-private-key.pem`) |
| `PORT`, `HOST` | Listen socket |
| `GATEWAY_INTERNAL_TOKEN` | Shared secret between backend ↔ gateway |
| `LOG_LEVEL` | Logging verbosity |

Tracked-in-git status: **no `.env` file has ever existed in that
subdirectory** — confirmed via `git log --all --full-history -- "services/andes-gateway/.env*"`
(empty output). So no `.env` under `services/andes-gateway/` was ever
in history.

However, the PEM key file is a separate story:

| File | Tracked today? | In history? | Reads it who / what for |
|---|---|---|---|
| `services/andes-gateway/.andes-private-key.pem` | **NO** — listed in `services/andes-gateway/.gitignore` (line 10, `.andes-private-key.pem`) | not observed in `git log --diff-filter=A` | The **live** runtime key. `server.ts:96` reads it with `readFileSync(ANDES_PK_PATH, "utf8")` and passes to `jsonwebtoken.sign(...)` for AndesLabs auth. |
| `services/andes-gateway/.andes-private-key.pem.MOCK.bak` | **YES — currently tracked** | Yes — added by commit `8ed9789` (2026-06-05 18:58:38 UTC) | Nothing references this exact filename anywhere in the codebase. `grep -rn "andes-private-key\|\.pem\.MOCK\|MOCK\.bak"` matches only `server.ts` docstrings that describe the PEM path variable — none point to `.MOCK.bak`. |

**Byte comparison** run in Fase 0: the two files are **byte-identical**
(`diff` returns 0). Therefore the `.bak` file is not a mock separate
from production — it is a verbatim copy of the live signing key.
Anyone with clone access to this repo can extract the EC private key
that today signs JWTs against AndesLabs.

The commit `8ed9789` is titled `auto-commit for 13f74764-…` and
carries no human context on why the backup was tracked. No follow-up
commit is documented removing it.

**Rotation implication**: whatever we plan for `.andes-private-key.pem`
must include (a) rotating the EC keypair at AndesLabs, (b) untracking
`.andes-private-key.pem.MOCK.bak`, and (c) rewriting history if we
want the compromised key to disappear from the repo. Any single one
without the others is incomplete.

## Git-history rotation status for `services/andes-gateway/*` secrets

| Secret | Tracked path | In-history? | Rotation status |
|---|---|---|---|
| `ANDES_API_KEY` (gateway) | not in repo — supervisor conf only | **not observed in this repo's history** — supervisor file lives outside `/app` | pending — rotate at AndesLabs |
| `.andes-private-key.pem` (live) | ignored by gateway `.gitignore` | not observed | rotate + keep ignored |
| `.andes-private-key.pem.MOCK.bak` | **tracked** | **YES from `8ed9789`** | rotate + `git rm --cached` + history rewrite |
| `GATEWAY_INTERNAL_TOKEN` | not in gateway repo — supervisor conf + `backend/.env` | see JWT_SECRET row above | pending — rotate on both sides simultaneously |


## Purging the git history (decision required — NOT executed in Fase 0)

Untracking a file with `git rm --cached` removes it from the current
tree but leaves the blob in every commit that ever contained it.
Anyone who can `git clone` the repo can still `git show 8ed9789 --`
and recover the compromised key. To make the exposure disappear from
the repo itself, the history has to be rewritten.

### Tool
The current mainstream option is **`git filter-repo`**
(https://github.com/newren/git-filter-repo) — actively maintained,
recommended by GitHub over the legacy `git filter-branch` (which is
deprecated and orders of magnitude slower). `BFG Repo-Cleaner` is a
faster Java alternative for the specific case of "remove blobs by
path" and is fine here.

Example (illustrative — do NOT run without a fresh backup):
```
# Remove the .bak by path, everywhere in history
git filter-repo --path services/andes-gateway/.andes-private-key.pem.MOCK.bak --invert-paths

# Optional: also nuke the ever-tracked .env blobs
git filter-repo \
  --path backend/.env --invert-paths \
  --path frontend/.env --invert-paths
```

### Risks
1. **Every commit hash changes.** All refs (branches, tags, PRs, deploy
   markers, CI cache keys) that pointed at pre-rewrite commits become
   dangling. Any external system that stored a commit hash (Emergent
   auto-commit refs, deployment tags, release notes) will need to be
   reconciled or accepted as broken.
2. **Force-push is required.** After the rewrite the remote history no
   longer descends from the local rewritten history. Ordinary `push`
   fails; `push --force-with-lease` is needed.
3. **Everyone with a clone must reclone.** Any existing clone that a
   teammate keeps around will still have the old blobs. Merging their
   old branch back in re-introduces the compromised material.
4. **Signed commits are lost.** Any GPG/SSH-signed commits become
   invalid because the hashes they signed changed. Re-signing is
   possible but manual.
5. **Not a substitute for rotation.** Rewriting history does not
   revoke the compromised key at AndesLabs. A copy already exists on
   any past clone, mirror, backup, cache or third-party service that
   pulled at any point during the exposure window. **Rotate first, then
   optionally rewrite. Rewriting without rotating is theatre.**

### Impact on existing clones — checklist before executing
- [ ] All active contributors notified and ready to reclone.
- [ ] Every deployment target confirmed to reference either the new
      rewritten history or a specific artefact/tag that does not
      depend on old commit hashes.
- [ ] Any external tooling (Emergent Save-to-GitHub, CI, deploy
      dashboards) confirmed not to break on force-push.
- [ ] Backup of pre-rewrite state kept in a secure archive (`git
      clone --mirror` before running filter-repo).
- [ ] Rotation of every exposed secret already completed.

**Fase 0 leaves this decision open.** No rewrite executed.

## Private-key material observed in git history (Fase 0 audit)

Search:
```
git log --all --diff-filter=A --name-only \
  | grep -iE "\.(pem|key|p12|pfx|jks|keystore)$|private.*key|id_rsa|id_dsa|id_ecdsa|id_ed25519"
```
Result: **1 file**.

- `services/andes-gateway/.andes-private-key.pem.MOCK.bak` — added
  in commit `8ed9789`, still present in HEAD (untracked in Fase 0).

No other PEM/KEY/PKCS12 material appears to have ever been tracked.

# Prosper E2E Suite (Playwright)

Cross-browser end-to-end tests that exercise the **happy path** of the
Prosper platform via the public ingress.

## Quick start

```bash
cd /app/e2e
yarn install
npx playwright install chromium   # one-time, downloads the chromium binary
yarn test                          # runs against the default preview URL

# Override the target environment
PROSPER_BASE_URL=https://staging.example.com yarn test

# Headed (debug) mode
yarn test:headed

# Open the last HTML report
yarn report
```

## Suite contents

| Spec                              | Covers                                                 |
|-----------------------------------|--------------------------------------------------------|
| `01-admin-full-flow.spec.ts`      | Super-admin seeds demo → client lands on dashboard      |
| `02-api-key-flow.spec.ts`         | Plaintext-only-once + revoke security invariant         |
| `03-webhook-delivery.spec.ts`     | Endpoint create + HMAC-signed test delivery returns 2xx |
| `04-cross-org-security.spec.ts`   | 404 on cross-org reads + impersonation 403 + 401 anon   |
| `05-public-surfaces.spec.ts`      | /status, /terms, /privacy render + footer visible       |

## Conventions

- **Always rely on `data-testid` selectors.** Text-based selectors break
  on i18n changes.
- **Always clean up demo data.** Each spec that calls
  `/admin/ops/seed-demo-client` finishes with `/admin/ops/wipe-demo`.
- **Login via dev magic link** (`/api/v1/auth/dev-login?email=…`) — this
  short-circuits the OTP flow and only works when `RESEND_API_KEY` is
  unset (preview / staging).
- **Serial execution** is enforced via `fullyParallel: false` — RBAC
  specs share global state (demo orgs).
- **Retries**: 1 in CI, 0 locally. Adjust in `playwright.config.ts`.

## CI

A drop-in `.github/workflows/e2e.yml` is provided in the repo root.
It pulls in chromium, runs `yarn test`, uploads the HTML report.

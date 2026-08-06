# andes-gateway

Internal Node micro-service that wraps `@andeslabs/mint-sdk` for the FastAPI
backend. **Phase 13 = skeleton only** — every business endpoint returns 501
until Phase 14 wires the SDK.

## Why a separate service?
The Andes SDK is Node-only. Calling it from Python would require shelling
out per request or running a Pyodide-style bridge — both fragile and slow.
A small Node service over HTTP keeps the SDK boundary clean.

## Routes (Phase 13)

| Method | Path                          | Status       |
|--------|-------------------------------|--------------|
| GET    | `/health`                     | ✅ 200       |
| GET    | `/`                           | ✅ 200 (list)|
| POST   | `/accounts`                   | 🚧 501 stub  |
| POST   | `/wallets`                    | 🚧 501 stub  |
| GET    | `/wallets/forUser/:userId`    | 🚧 501 stub  |
| POST   | `/fiat`                       | 🚧 501 stub  |
| POST   | `/fiat/business`              | 🚧 501 stub  |
| GET    | `/fiat/funding`               | 🚧 501 stub  |
| POST   | `/fiat/withdraw`              | 🚧 501 stub  |
| POST   | `/international/quote`        | 🚧 501 stub  |
| POST   | `/international/offramp`      | 🚧 501 stub  |
| POST   | `/movements/list`             | 🚧 501 stub  |
| GET    | `/webhooks/signing-key`       | 🚧 501 stub  |

All non-`/health` routes require the header
`X-Internal-Token: <GATEWAY_INTERNAL_TOKEN>`.

## Run locally

```bash
cd services/andes-gateway
npm install
GATEWAY_INTERNAL_TOKEN=dev-internal-token-change-me PORT=8090 npm run dev
```

The Python `AndesAdapter` reads `ANDES_GATEWAY_URL` (default
`http://andes-gateway:8090`) and authenticates via the same token.

## Phase 14 checklist

* [ ] Replace each 501 stub with a real call into `@andeslabs/mint-sdk`
* [ ] Wire ES256 webhook signature verification with the project's signing key
* [ ] Add structured request/response logging with delivery-id correlation
* [ ] Add liveness + readiness probes for k8s

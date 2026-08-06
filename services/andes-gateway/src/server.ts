/**
 * Phase 14 — andes-gateway with real @andeslabs/mint-sdk integration.
 *
 * Two modes (selected via env var ANDES_GATEWAY_MODE):
 *
 *   real   ← default. Instantiates the SDK with ANDES_API_KEY +
 *            ANDES_JWT_PRIVATE_KEY (file path) and proxies requests.
 *
 *   mock   ← in-memory simulator with realistic shapes (UUID userIds, 56-char
 *            Stellar 'C…' addresses, 22-digit CVUs, status='completed'). Used
 *            when the real Andes credentials aren't available yet.
 *
 * Endpoints (all require the X-Internal-Token header except /health):
 *
 *   GET    /health
 *   POST   /accounts                       → andes.accounts.create({name})
 *   POST   /wallets                        → andes.wallets.create(chain,{user_id,asset})
 *   GET    /wallets/:userId                → andes.wallets.forUser(userId)
 *   POST   /fiat            (multipart)    → andes.fiat.create(body, files)
 *   POST   /fiat/business                  → andes.fiat.createBusiness(body)
 *   GET    /fiat/:userId                   → andes.fiat.forUser(userId)
 *
 * Errors: SDK throws AndesApiError → we surface {error, httpStatus, status,
 * body} with the same HTTP code so the Python adapter can branch cleanly.
 */
import { readFileSync } from "fs";
import { randomBytes, randomUUID } from "crypto";

import fastify from "fastify";
import multipart from "@fastify/multipart";
import pino from "pino";

import {
  AndesApiError,
  createClient,
  type AndesClient,
} from "@andeslabs/mint-sdk";

import {
  ANDES_EVENT_TYPES, AndesEventType,
  getMockPrivateKey, getMockPublicKey,
  signEs256Mock, signingPayload, verifyWebhookSignature,
} from "./webhooks";

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------
const logger = pino({ name: "andes-gateway",
                      level: process.env.LOG_LEVEL || "info" });

const PORT  = Number(process.env.PORT || 8090);
const HOST  = process.env.HOST || "0.0.0.0";
const TOKEN = process.env.GATEWAY_INTERNAL_TOKEN || "dev-internal-token-change-me";
const MODE  = (process.env.ANDES_GATEWAY_MODE || "real").toLowerCase();
const USE_KMS = (process.env.ANDES_USE_KMS || "false").toLowerCase() === "true";

const ANDES_API_KEY      = process.env.ANDES_API_KEY || "";
const ANDES_PK_PATH      = process.env.ANDES_JWT_PRIVATE_KEY_PATH || "";
const ANDES_BASE_URL     = process.env.ANDES_BASE_URL || undefined;
const ANDES_ISSUER       = process.env.ANDES_ISSUER || undefined;

// Phase 15 — receiver inside the FastAPI backend. The gateway forwards
// every VERIFIED webhook here. Uses the same X-Internal-Token as outbound.
const BACKEND_URL =
  process.env.BACKEND_INTERNAL_URL ||
  process.env.PROSPER_BACKEND_URL  ||
  "http://localhost:8001";
const BACKEND_WEBHOOK_PATH = "/api/v1/internal/ramp/webhook";
const WEBHOOK_MAX_AGE_MS = Number(process.env.WEBHOOK_MAX_AGE_MS || 5 * 60_000);

// ---------------------------------------------------------------------------
// SDK client (real mode only)
// ---------------------------------------------------------------------------
let andes: AndesClient | null = null;

function buildClient(): AndesClient {
  if (!ANDES_API_KEY) {
    throw new Error("ANDES_API_KEY missing — set it or use ANDES_GATEWAY_MODE=mock");
  }
  if (USE_KMS) {
    // TODO FASE 14+ — wire a real KMS signer. For now we keep the hook so
    // ops can flip ANDES_USE_KMS=true later without code changes.
    const signer = async (): Promise<string> => {
      throw new Error("KMS signer not implemented; toggle ANDES_USE_KMS=false");
    };
    return createClient({
      apiKey: ANDES_API_KEY,
      signer,
      baseUrl: ANDES_BASE_URL,
      issuer: ANDES_ISSUER,
    });
  }
  if (!ANDES_PK_PATH) {
    throw new Error("ANDES_JWT_PRIVATE_KEY_PATH missing (or set ANDES_USE_KMS=true)");
  }
  const privateKey = readFileSync(ANDES_PK_PATH, "utf8");
  return createClient({
    apiKey: ANDES_API_KEY,
    privateKey,
    baseUrl: ANDES_BASE_URL,
    issuer: ANDES_ISSUER,
  });
}

if (MODE === "real") {
  try {
    andes = buildClient();
    logger.info({ baseUrl: ANDES_BASE_URL, issuer: ANDES_ISSUER, useKms: USE_KMS },
                "andes-sdk client ready");
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    logger.error({ err: msg }, "failed to init andes-sdk — falling back to mock");
    // Don't crash the gateway in dev: degrade to mock so /health stays green.
    process.env.ANDES_GATEWAY_MODE = "mock";
  }
}
const currentMode = () => (andes ? "real" : "mock");

// ---------------------------------------------------------------------------
// In-memory mock store
// ---------------------------------------------------------------------------
type MockUser    = { userId: string; name: string };
type MockWallet  = { wallet_id: string; user_id: string; asset: "arsa"|"usdt"|"usdc";
                     protocol: "stellar"|"evm"; chain: "stellar"|"base"|"worldchain";
                     address: string; decimals: number; balance: string;
                     status: "pending"|"active"; activated_at: string | null };
type MockFiat    = { fiatAccountId: string; userId: string; cvu: string;
                     alias: string; status: "pending"|"completed";
                     onboardingStatus: "approved"|"pending_approval"|"rejected";
                     accountType: "user"|"business"; holderName: string };

const mock = {
  users:    new Map<string, MockUser>(),     // userId → user
  wallets:  new Map<string, MockWallet[]>(), // userId → wallets[]
  fiat:     new Map<string, MockFiat[]>(),   // userId → fiat[]
};

function mockStellarAddr(): string {
  // Soroban contract format: 56 chars, starts with 'C', base32 uppercase
  const body = randomBytes(40).toString("base64")
    .replace(/[^A-Z0-9]/gi, "")
    .toUpperCase().slice(0, 55);
  return "C" + body.padEnd(55, "0").slice(0, 55);
}
function mockCvu(): string {
  // 22-digit CVU; first 7 are bank+branch (fictional partner)
  let cvu = "0000003";
  for (let i = 0; i < 15; i++) cvu += Math.floor(Math.random() * 10);
  return cvu;
}
function mockAlias(name: string): string {
  const seed = (name || "client").toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 10);
  return `${seed || "client"}.andes.mock`;
}

// ---------------------------------------------------------------------------
// Fastify
// ---------------------------------------------------------------------------
const app = fastify({ logger, bodyLimit: 10 * 1024 * 1024 });
app.register(multipart, { limits: { fileSize: 8 * 1024 * 1024 } });

// Capture raw body on the webhook endpoint so we can verify the signature
// against the exact bytes Andes signed. Fastify's default JSON parser is fine
// for the rest of the gateway, but for /webhooks/andes we need both the raw
// bytes AND the parsed JSON.
app.addContentTypeParser("application/json", { parseAs: "buffer" },
  (req, body, done) => {
    (req as any).rawBody = body;
    if (!body || (body as Buffer).length === 0) return done(null, {});
    try {
      done(null, JSON.parse((body as Buffer).toString("utf8")));
    } catch (e) { done(e as Error, undefined); }
  });

// ------------------------------------------------------------------ health
app.get("/health", async () => ({
  ok: true,
  service: "andes-gateway",
  version: "0.2.0",
  phase: 14,
  mode: currentMode(),
  uptime_s: Math.floor(process.uptime()),
}));

// ------------------------------------------------------------------ auth
//
// Public endpoints (signed by Andes' webhook key, not by our internal token):
//   * /health
//   * /webhooks/andes   ← verifies ES256 against the (mock-or-real) public key
//
// Everything else requires X-Internal-Token (the FastAPI backend ↔ gateway).
app.addHook("onRequest", async (request, reply) => {
  if (request.url === "/health"
      || request.url.startsWith("/webhooks/andes")) return;
  const provided = request.headers["x-internal-token"];
  if (!provided || provided !== TOKEN) {
    reply.code(401).send({ ok: false,
                           error: "Invalid or missing X-Internal-Token" });
  }
});

// ------------------------------------------------------------------ error helper
function handleSdkError(err: unknown, reply: any) {
  if (err instanceof AndesApiError) {
    const status = err.httpStatus || 502;
    return reply.code(status).send({
      error: err.message,
      httpStatus: err.httpStatus,
      status: err.status,
      body: err.body,
    });
  }
  const msg = err instanceof Error ? err.message : String(err);
  return reply.code(502).send({ error: msg });
}

// ------------------------------------------------------------------ accounts
app.post("/accounts", async (req, reply) => {
  const body = (req.body || {}) as { name?: string };
  if (!body.name) return reply.code(400).send({ error: "name required" });
  try {
    if (andes) {
      const r = await andes.accounts.create({ name: body.name });
      return { userId: r.userId, name: body.name, mode: "real" };
    }
    const userId = randomUUID();
    mock.users.set(userId, { userId, name: body.name });
    return { userId, name: body.name, mode: "mock" };
  } catch (e) { return handleSdkError(e, reply); }
});

// ------------------------------------------------------------------ wallets
app.post("/wallets", async (req, reply) => {
  const body = (req.body || {}) as { user_id?: string; asset?: any; chain?: any };
  if (!body.user_id || !body.asset || !body.chain) {
    return reply.code(400).send({ error: "user_id, asset, chain required" });
  }
  try {
    if (andes) {
      const r = await andes.wallets.create(body.chain, {
        user_id: body.user_id, asset: body.asset });
      // Stellar wallets are created `pending` and become `active` via the
      // wallet.active webhook. EVM (base) wallets are active immediately.
      // The SDK response on Prod returns {address}; status is fetched via
      // GET /wallets/:userId — surface a sane default here.
      const status = (r as any).status
        || (body.chain === "stellar" ? "pending" : "active");
      return { address: r.address, user_id: body.user_id,
               asset: body.asset, chain: body.chain,
               status, mode: "real" };
    }
    const list = mock.wallets.get(body.user_id) || [];
    const existing = list.find(w => w.asset === body.asset && w.chain === body.chain);
    if (existing) return { ...existing, mode: "mock", existed: true };
    const protocol = body.chain === "stellar" ? "stellar" : "evm";
    const address = body.chain === "stellar"
      ? mockStellarAddr()
      : "0x" + randomBytes(20).toString("hex");
    // Phase 18 — Stellar wallets start pending; Base wallets are active.
    const status: "pending" | "active" =
      body.chain === "stellar" ? "pending" : "active";
    const w: MockWallet = {
      wallet_id: randomUUID(), user_id: body.user_id,
      asset: body.asset, protocol, chain: body.chain,
      address, decimals: body.asset === "arsa" ? 2 : 6, balance: "0",
      status,
      activated_at: status === "active" ? new Date().toISOString() : null,
    };
    list.push(w);
    mock.wallets.set(body.user_id, list);

    // Phase 18 — auto-emit `wallet.active` after a short delay for Stellar
    // mocks so the FastAPI receiver can flip status='active' E2E.
    if (status === "pending") {
      setTimeout(() => {
        const payload = { type: "wallet.active", data: {
          wallet_id: w.wallet_id,
          user_id:   w.user_id,
          asset:     w.asset,
          chain:     w.chain,
          address:   w.address,
          status:    "active",
          activated_at: new Date().toISOString(),
        }};
        // Mutate the in-memory mock so GET /wallets/:userId polls reflect it.
        w.status = "active";
        w.activated_at = payload.data.activated_at;
        fireMockWebhook("wallet.active", payload)
          .catch(e => logger.error({ err: String(e) },
                                       "auto-activate wallet failed"));
      }, 800);
    }
    return { ...w, mode: "mock" };
  } catch (e) { return handleSdkError(e, reply); }
});

app.get("/wallets/:userId", async (req, reply) => {
  const { userId } = req.params as { userId: string };
  try {
    if (andes) {
      const list = await andes.wallets.forUser(userId);
      return { items: list, mode: "real" };
    }
    return { items: mock.wallets.get(userId) || [], mode: "mock" };
  } catch (e) { return handleSdkError(e, reply); }
});

// ------------------------------------------------------------------ fiat (multipart passthrough)
app.post("/fiat", async (req, reply) => {
  try {
    if (andes) {
      // The SDK accepts (body, files) where each file is
      // {buffer, filename, contentType}. Re-build from multipart parts.
      const body: Record<string, any> = {};
      const files: Record<string, any> = {};
      const parts = req.parts();
      for await (const part of parts) {
        if (part.type === "file") {
          const buf = await part.toBuffer();
          files[part.fieldname] = {
            buffer:      buf,
            filename:    part.filename || `${part.fieldname}.jpg`,
            contentType: part.mimetype || "image/jpeg",
          };
        } else {
          body[part.fieldname] = part.value;
        }
      }
      const r = await andes.fiat.create(body as any, files as any);
      return { ...r, mode: "real" };
    }
    // Mock — collect form fields, skip files
    const body: Record<string, any> = {};
    const parts = req.parts();
    for await (const part of parts) {
      if (part.type !== "file") body[part.fieldname] = part.value;
    }
    const userId = body.userId || body.user_id || randomUUID();
    const fa: MockFiat = {
      fiatAccountId: randomUUID(), userId,
      cvu: mockCvu(),
      alias: body.alias || mockAlias(body.holderName || body.holder_name || "client"),
      status: "completed",
      onboardingStatus: "approved",
      accountType: "user",
      holderName: body.holderName || body.holder_name || "" };
    const list = mock.fiat.get(userId) || [];
    list.push(fa);
    mock.fiat.set(userId, list);
    return { ...fa, mode: "mock" };
  } catch (e) { return handleSdkError(e, reply); }
});

app.post("/fiat/business", async (req, reply) => {
  const body = (req.body || {}) as any;
  try {
    if (andes) {
      const r = await andes.fiat.createBusiness(body);
      return { ...r, mode: "real" };
    }
    const userId = body.userId || body.user_id || randomUUID();
    const fa: MockFiat = {
      fiatAccountId: randomUUID(), userId,
      cvu: mockCvu(),
      alias: body.alias || mockAlias(body.businessName || body.holderName || "biz"),
      status: "completed",
      onboardingStatus: "approved",
      accountType: "business",
      holderName: body.businessName || body.holderName || "" };
    const list = mock.fiat.get(userId) || [];
    list.push(fa);
    mock.fiat.set(userId, list);
    return { ...fa, mode: "mock" };
  } catch (e) { return handleSdkError(e, reply); }
});

app.get("/fiat/:userId", async (req, reply) => {
  const { userId } = req.params as { userId: string };
  try {
    if (andes) {
      const list = await andes.fiat.forUser(userId);
      return { items: list, mode: "real" };
    }
    return { items: mock.fiat.get(userId) || [], mode: "mock" };
  } catch (e) { return handleSdkError(e, reply); }
});

// ------------------------------------------------------------------ Phase 15 — fiat movements (deposits + withdrawals)
//
// Wraps `andes.fiat.movementsForUser(userId)`. Returns ALL CVU movements
// the user has — deposits credited by the bank, ARSa mints, withdraws to
// a CVU. The Python adapter sync job persists them into ramp_movements
// so the client portal renders the transaction log without depending on
// webhook delivery.
//
// Query:
//   GET /fiat/movements?user_id=<andes_user_id>&limit=200
app.get("/fiat/movements", async (req, reply) => {
  const q = req.query as { user_id?: string; limit?: string };
  if (!q.user_id) {
    reply.code(400);
    return { error: "missing_user_id" };
  }
  try {
    if (andes) {
      const items = await andes.fiat.movementsForUser(q.user_id, {
        limit: q.limit ? Math.min(Number(q.limit), 500) : 200,
      } as any);
      return { items, mode: "real" };
    }
    return { items: [], mode: "mock" };
  } catch (e) { return handleSdkError(e, reply); }
});

// ------------------------------------------------------------------ wallet transfers list (see line ~1194 — already exists,
// scoped by userId query). Removed duplicate to avoid FST_ERR_DUPLICATED_ROUTE.


// ------------------------------------------------------------------ Phase 15 — fiat withdrawal (offramp)
//
// Body shape (snake_case for parity with Python adapter):
//   { user_id, fiat_account_id, chain, asset, amount, to_cvu?, to_alias? }
// Real → andes.fiat.withdraw(...); Mock → records pending tx, returns
// {transactionId, status:"Pending"}. The real completion arrives via webhook.
app.post("/fiat/withdraw", async (req, reply) => {
  const body = (req.body || {}) as {
    user_id?: string; fiat_account_id?: string; chain?: any; asset?: any;
    amount?: string | number; to_cvu?: string; to_alias?: string;
  };
  if (!body.user_id || !body.amount || (!body.to_cvu && !body.to_alias)) {
    return reply.code(400).send({
      error: "user_id, amount and one of (to_cvu | to_alias) required" });
  }
  const asset = body.asset || "arsa";
  const chain = body.chain || "stellar";
  try {
    if (andes) {
      const r = await (andes.fiat as any).withdraw({
        user_id: body.user_id,
        fiat_account_id: body.fiat_account_id,
        chain, asset,
        amount: String(body.amount),
        to_cvu: body.to_cvu, to_alias: body.to_alias });
      return { ...r, mode: "real" };
    }
    // MOCK — debit wallet immediately so the user sees their balance drop,
    // and queue the settlement via a fiat.withdrawal.success webhook 250ms
    // later (the FastAPI receiver flips status="Success").
    const list = mock.wallets.get(body.user_id) || [];
    const w = list.find(x => x.asset === asset && x.chain === chain);
    const amountNum = Number(body.amount);
    if (!w || Number(w.balance) < amountNum) {
      return reply.code(409).send({ error: "Insufficient ARSa balance",
                                       balance: w?.balance || "0",
                                       requested: String(amountNum) });
    }
    w.balance = (Number(w.balance) - amountNum)
      .toFixed(asset === "arsa" ? 2 : 6);

    const tx = {
      transactionId: "wd_" + randomBytes(8).toString("hex"),
      user_id: body.user_id,
      amount: String(body.amount),
      asset, chain,
      to_cvu: body.to_cvu || null,
      to_alias: body.to_alias || null,
      status: "Pending" as const,
      created_at: new Date().toISOString(),
    };
    // Fire-and-forget: emit a settlement webhook after a short delay so
    // the FastAPI receiver can mark the row as Success E2E.
    setTimeout(() => {
      const payload = { type: "fiat.withdrawal.success", data: {
        transactionId: tx.transactionId, status: "Success",
        amount: tx.amount, asset: tx.asset,
        userId: tx.user_id,
        toCvu: tx.to_cvu, toAlias: tx.to_alias,
      }};
      fireMockWebhook("fiat.withdrawal.success", payload)
        .catch(e => logger.error({ err: String(e) }, "auto-settle withdrawal failed"));
    }, 250);

    return { ...tx, mode: "mock" };
  } catch (e) { return handleSdkError(e, reply); }
});

// CVU/alias lookup — returns the holder name so the UI can show "Estás por
// transferir a Juan Pérez · DNI 30…" before confirming.
app.get("/fiat/cvu-lookup", async (req, reply) => {
  const { cvu, alias } = req.query as { cvu?: string; alias?: string };
  if (!cvu && !alias) {
    return reply.code(400).send({ error: "cvu or alias query required" });
  }
  try {
    if (andes) {
      const r = await (andes.fiat as any).cvuLookup({ cvu, alias });
      return { ...r, mode: "real" };
    }
    // MOCK — synthesize a plausible holder
    const seed = (cvu || alias || "x").replace(/[^0-9a-z]/gi, "").slice(-4);
    const first = ["María","Juan","Lucía","Diego","Sofía"][parseInt(seed[0]||"0",36) % 5];
    const last  = ["Pérez","García","Fernández","López","Rodríguez"][parseInt(seed[1]||"0",36) % 5];
    return {
      cvu: cvu || null, alias: alias || null,
      holderName: `${first} ${last}`,
      holderTaxId: "20" + (Math.floor(Math.random()*1e8)+1e8).toString().slice(0,8) + "9",
      bank: "Banco Mock S.A.",
      mode: "mock",
    };
  } catch (e) { return handleSdkError(e, reply); }
});

// ------------------------------------------------------------------ Phase 15 — webhooks/andes (PUBLIC, ES256-verified)
//
// Andes calls this endpoint with x-webhook-timestamp / x-webhook-signature /
// x-webhook-delivery-id. We verify against the cached public key, then
// forward to the FastAPI receiver. The HTTP status from FastAPI is returned
// AS-IS so Andes' built-in retry policy works correctly.
let cachedAndesPublicKey: import("crypto").KeyObject | null = null;
async function getAndesPublicKey() {
  if (cachedAndesPublicKey) return cachedAndesPublicKey;
  if (andes) {
    try {
      const r = await (andes.webhooks as any).signingKey();
      const pem = r?.publicKey || r?.pem || r;
      if (typeof pem === "string") {
        const { createPublicKey } = await import("crypto");
        cachedAndesPublicKey = createPublicKey({ key: pem, format: "pem" });
        return cachedAndesPublicKey;
      }
    } catch (e) {
      logger.warn({ err: String(e) }, "could not fetch andes signing key — falling back to mock");
    }
  }
  cachedAndesPublicKey = getMockPublicKey();
  return cachedAndesPublicKey;
}

app.post("/webhooks/andes", async (req, reply) => {
  const rawBody: Buffer = (req as any).rawBody || Buffer.alloc(0);
  const ts        = String(req.headers["x-webhook-timestamp"] || "");
  const sig       = String(req.headers["x-webhook-signature"] || "");
  const deliveryId = String(req.headers["x-webhook-delivery-id"]
                            || "dlv_" + randomBytes(6).toString("hex"));

  const pub = await getAndesPublicKey();
  const v = verifyWebhookSignature({
    rawBody, timestamp: ts, signature: sig, publicKey: pub,
    maxAgeMs: WEBHOOK_MAX_AGE_MS,
  });
  if (!v.ok) {
    logger.warn({ reason: v.reason, deliveryId, ts }, "webhook rejected");
    return reply.code(401).send({ error: "invalid signature", reason: v.reason });
  }

  // Forward to FastAPI
  const payload = (req.body || {}) as Record<string, any>;
  const eventType = String(payload.type || payload.event || "unknown");
  const forwardBody = {
    event_type: eventType,
    delivery_id: deliveryId,
    payload,
    signature_valid: true,
    headers: {
      "x-webhook-timestamp": ts,
      "x-webhook-signature": sig,
      "x-webhook-delivery-id": deliveryId,
    },
  };
  try {
    const r = await fetch(BACKEND_URL + BACKEND_WEBHOOK_PATH, {
      method: "POST",
      headers: { "Content-Type": "application/json",
                  "X-Internal-Token": TOKEN },
      body: JSON.stringify(forwardBody),
    });
    const text = await r.text();
    let body: unknown;
    try { body = JSON.parse(text); } catch { body = { raw: text }; }
    return reply.code(r.status).send(body);
  } catch (e) {
    logger.error({ err: String(e) }, "webhook forward to FastAPI failed");
    return reply.code(502).send({ error: "backend unreachable" });
  }
});

// ------------------------------------------------------------------ Phase 16 — project stats + webhook deliveries + capabilities
//
// project.stats() / project.statsTimeseries() power the "Rampa (Andes)" admin
// dashboard. webhooks.deliveries() lets ops cross-check what Andes thinks it
// sent vs. what FastAPI received. capabilities() lets the backoffice render
// the right "what does this provider support?" panel.

app.get("/project/stats", async (_req, reply) => {
  try {
    if (andes) {
      const r = await (andes as any).project.stats();
      return { ...r, mode: "real" };
    }
    // MOCK — derive plausible numbers from the in-process state so the
    // dashboard isn't empty when developing.
    const accounts = mock.users.size;
    let walletCount = 0;
    let arsa = 0, usdc = 0, usdt = 0;
    for (const ws of mock.wallets.values()) {
      walletCount += ws.length;
      for (const w of ws) {
        if (w.asset === "arsa") arsa += Number(w.balance) || 0;
        if (w.asset === "usdc") usdc += Number(w.balance) || 0;
        if (w.asset === "usdt") usdt += Number(w.balance) || 0;
      }
    }
    return {
      mode: "mock",
      project_id: process.env.ANDES_PROJECT_ID || "prj_mock_prosper",
      accounts:     accounts,
      wallets:      walletCount,
      cvu_count:    [...mock.fiat.values()].reduce((n, l) => n + l.length, 0),
      tvl_arsa:     arsa.toFixed(2),
      tvl_usdc:     usdc.toFixed(2),
      tvl_usdt:     usdt.toFixed(2),
      deposit_count_30d:    Math.max(0, accounts * 3),
      withdrawal_count_30d: Math.max(0, accounts),
      volume_arsa_30d:      (arsa * 1.4).toFixed(2),
    };
  } catch (e) { return handleSdkError(e, reply); }
});

app.get("/project/stats-timeseries", async (req, reply) => {
  const { window = "30d", bucket = "1d" } = (req.query || {}) as
    { window?: string; bucket?: string };
  try {
    if (andes) {
      const r = await (andes as any).project.statsTimeseries({ window, bucket });
      return { ...r, mode: "real" };
    }
    // MOCK — last 30 daily points with smooth fake growth
    const points: { ts: string; volume_arsa: string; accounts: number;
                     deposits: number; withdrawals: number }[] = [];
    const now = Date.now();
    let acc = Math.max(1, mock.users.size);
    let vol = 50_000;
    for (let i = 29; i >= 0; i--) {
      const t = new Date(now - i * 86_400_000);
      vol *= 1 + (Math.random() * 0.06 - 0.01);
      acc += i % 4 === 0 ? 1 : 0;
      points.push({
        ts:           t.toISOString().slice(0, 10),
        volume_arsa:  vol.toFixed(2),
        accounts:     acc,
        deposits:     Math.floor(2 + Math.random() * 4),
        withdrawals:  Math.floor(Math.random() * 3),
      });
    }
    return { mode: "mock", window, bucket, points };
  } catch (e) { return handleSdkError(e, reply); }
});

app.get("/webhooks/deliveries", async (req, reply) => {
  const { limit = "100" } = (req.query || {}) as { limit?: string };
  try {
    if (andes) {
      const r = await (andes as any).webhooks.deliveries({
        limit: Number(limit) || 100 });
      return { items: r, mode: "real" };
    }
    // MOCK — we don't keep a persistent delivery log on the gateway, so we
    // surface a synthetic "no historical data" payload that the UI handles
    // gracefully. In real mode the SDK returns the canonical list.
    return { items: [], mode: "mock",
              note: "Mock mode: gateway forwards live webhooks but does not "
                    + "keep a long-term delivery log. Use real mode for audit." };
  } catch (e) { return handleSdkError(e, reply); }
});

app.get("/capabilities", async (_req, _reply) => ({
  active: andes ? "real" : "mock",
  providers: {
    alfred: {
      id: "alfred",
      producedAssets: ["arsa"],
      chains: ["stellar"],
      supportsDedicatedAccounts: false,
      supportsBalances: false,
      supportsKYC: true,
      onrampModel: "order",
    },
    andeslabs: {
      id: "andeslabs",
      producedAssets: ["arsa", "usdc", "usdt"],
      chains: ["stellar", "polygon", "arbitrum"],
      supportsDedicatedAccounts: true,
      supportsBalances: true,
      supportsKYC: true,
      onrampModel: "deposit-driven",
    },
  },
}));

// ------------------------------------------------------------------ Phase 16.x — webhook registration with Andes
//
// Idempotent: if a subscription with the same URL already exists, just
// returns the existing one. Otherwise creates it.
app.get("/webhooks/subscriptions", async (_req, reply) => {
  try {
    if (andes) {
      const list = await (andes.webhooks as any).list();
      return { items: list, mode: "real" };
    }
    return { items: [], mode: "mock" };
  } catch (e) { return handleSdkError(e, reply); }
});

app.post("/webhooks/subscribe", async (req, reply) => {
  const body = (req.body || {}) as { url?: string; events?: string[] };
  if (!body.url) return reply.code(400).send({ error: "url required" });
  const events = body.events && body.events.length
    ? body.events
    : [...ANDES_EVENT_TYPES];
  if (!andes) {
    return { mode: "mock", note: "Real mode required to register webhook",
              url: body.url, events };
  }
  try {
    // Idempotent: check existing first
    let existing: any[] = [];
    try {
      existing = await (andes.webhooks as any).list();
    } catch { /* some SDKs only expose .create */ }
    const match = (existing || []).find((s: any) =>
      (s.url || s.endpoint) === body.url);
    if (match) {
      return { ok: true, created: false, subscription: match, mode: "real" };
    }
    const created = await (andes.webhooks as any).create({
      url: body.url, events });
    return { ok: true, created: true, subscription: created, mode: "real" };
  } catch (e) { return handleSdkError(e, reply); }
});

app.delete("/webhooks/subscribe", async (req, reply) => {
  const { id } = (req.query || {}) as { id?: string };
  if (!id) return reply.code(400).send({ error: "id required" });
  try {
    if (andes) {
      await (andes.webhooks as any).delete(id);
      return { ok: true, id };
    }
    return { ok: true, id, mode: "mock" };
  } catch (e) { return handleSdkError(e, reply); }
});


// Local helper used by the mock auto-settle hooks (withdrawal/deposit) so the
// gateway can simulate Andes calling back without leaving the process.
async function fireMockWebhook(eventType: AndesEventType, payload: any) {  const body = Buffer.from(JSON.stringify(payload), "utf8");
  const ts = Date.now().toString();
  const sig = signEs256Mock(ts, body);
  const deliveryId = "dlv_" + randomBytes(6).toString("hex");
  const url = `http://127.0.0.1:${PORT}/webhooks/andes`;
  const r = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-webhook-timestamp": ts,
      "x-webhook-signature": sig,
      "x-webhook-delivery-id": deliveryId,
    },
    body,
  });
  return { status: r.status, deliveryId, eventType };
}

// ------------------------------------------------------------------ DEV helper: simulate fiat deposit
app.post("/dev/simulate-deposit", async (req, reply) => {
  if (andes) return reply.code(404).send({
    error: "Simulator only available in mock mode" });
  const body = (req.body || {}) as
    { user_id?: string; amount?: number; asset?: string; chain?: string;
      fire_webhook?: boolean };
  if (!body.user_id || !body.amount) {
    return reply.code(400).send({ error: "user_id, amount required" });
  }
  const asset = (body.asset || "arsa") as MockWallet["asset"];
  const chain = (body.chain || "stellar") as MockWallet["chain"];
  let list = mock.wallets.get(body.user_id) || [];
  let w = list.find(x => x.asset === asset && x.chain === chain);
  if (!w) {
    const protocol = chain === "stellar" ? "stellar" : "evm";
    const address = chain === "stellar"
      ? mockStellarAddr() : "0x" + randomBytes(20).toString("hex");
    const status: "pending" | "active" =
      chain === "stellar" ? "pending" : "active";
    w = { wallet_id: randomUUID(), user_id: body.user_id,
          asset, protocol, chain, address,
          decimals: asset === "arsa" ? 2 : 6, balance: "0",
          status,
          activated_at: status === "active" ? new Date().toISOString() : null };
    list.push(w);
    mock.wallets.set(body.user_id, list);
  }
  w.balance = (Number(w.balance) + body.amount).toFixed(asset === "arsa" ? 2 : 6);

  // Phase 15 — by default we also fire a signed `fiat.deposit.success`
  // webhook so the FastAPI receiver persists a ramp_movements row, refreshes
  // balance + audits the deposit exactly like a real Andes flow would.
  // Pass `fire_webhook=false` to opt out (legacy Phase-14 tests).
  let webhook: any = null;
  if (body.fire_webhook !== false) {
    const wallet = w;
    const payload = { type: "fiat.deposit.success", data: {
      transactionId: "dep_" + randomBytes(8).toString("hex"),
      userId: body.user_id,
      amount: String(body.amount),
      asset, chain,
      walletAddress: wallet.address,
      mint_receipt_hash: "MINT_" + randomBytes(8).toString("hex").toUpperCase(),
      timestamp: new Date().toISOString(),
    }};
    try {
      webhook = await fireMockWebhook("fiat.deposit.success", payload);
    } catch (e) {
      webhook = { status: 0, error: String(e) };
    }
  }
  return { ok: true, wallet: w, webhook };
});

// Arbitrary fire-and-forget signed webhook for E2E tests.
app.post("/dev/fire-webhook", async (req, reply) => {
  if (andes) return reply.code(404).send({
    error: "Only available in mock mode" });
  const body = (req.body || {}) as { type?: AndesEventType; data?: any };
  if (!body.type) return reply.code(400).send({ error: "type required" });
  if (!ANDES_EVENT_TYPES.includes(body.type)) {
    return reply.code(400).send({ error: `unknown type ${body.type}`,
                                     allowed: ANDES_EVENT_TYPES });
  }
  // Phase 18 — when a deposit webhook is fired, bump the mock wallet balance
  // so /balances reflects reality (Andes Prod always bumps on its side first).
  if (body.type === "fiat.deposit.success" && body.data?.userId) {
    const uid   = String(body.data.userId);
    const asset = (body.data.asset || "arsa") as "arsa"|"usdt"|"usdc";
    const chain = (body.data.chain || "stellar") as "stellar"|"base"|"worldchain";
    const amt   = Number(body.data.amount || 0);
    const list  = mock.wallets.get(uid) || [];
    const w     = list.find(x => x.asset === asset && x.chain === chain);
    if (w && amt > 0) {
      w.balance = String(Number(w.balance || 0) + amt);
    }
  }
  const payload = { type: body.type, data: body.data || {} };
  try {
    const r = await fireMockWebhook(body.type, payload);
    return r;
  } catch (e) {
    return reply.code(502).send({ error: String(e) });
  }
});

// ───────────────────────────────────────────────────── Phase 15.2 — International
// off-ramp (ARS → BOB/PEN/PYG) + crypto wallet-to-wallet transfers.
//
// Real mode: thin wrapper around `andes.international.*` and
// `andes.wallets.transfers.*`. Mock mode: deterministic shapes used by the
// FastAPI orchestrator + UI tests. Webhooks `international.offramp.success`/
// `failed` and `crypto.transfer.success`/`failed` are emitted by the same
// helpers as the rest.

interface MockIntlAccount {
  id: string; userId: string; country: "bob"|"pen"|"pyg";
  account_number: string; account_holder_name: string;
  account_holder_last_name: string; bank: string | null;
  document_number: string; document_type: string;
  account_type: string; created_at: string;
}
interface MockIntlOfframp {
  id: string; user_id: string; country: "bob"|"pen"|"pyg";
  fiat_account_id: string; from_currency: "ARS"; from_amount: string;
  to_currency: "BOB"|"PEN"|"PYG"; to_amount: string;
  bridge_currency: "USDT"; bridge_amount: string;
  bridge_in_rate: string; bridge_out_rate: string;
  status: "Pending"|"Success"|"Failed"; started_at: string;
}
interface MockTransfer {
  transactionId: string; wallet_transaction_id: string;
  user_id: string; chain: "stellar"|"base"|"worldchain";
  asset: "arsa"|"usdc"|"usdt"; from_address: string; to_address: string;
  amount: string; tx_hash: string | null;
  status: "Pending"|"Success"|"Failed"; started_at: string;
}
const mockIntl = {
  accounts:  new Map<string, MockIntlAccount[]>(),  // by userId
  offramps:  new Map<string, MockIntlOfframp[]>(),  // by userId
};
const mockTransfers = new Map<string, MockTransfer[]>(); // by userId

const MOCK_RATES = {
  ars_usdt: "1100",     // 1 USDT = 1100 ARS
  usdt_bob: "6.95",
  usdt_pen: "3.74",
  usdt_pyg: "7300",
};

// ----- Cotization + banks
app.get("/intl/cotization", async (_req, reply) => {
  try {
    if (andes) return await andes.international.cotization();
    return {
      ars_usdt: MOCK_RATES.ars_usdt,
      usdt_bob: MOCK_RATES.usdt_bob,
      usdt_pen: MOCK_RATES.usdt_pen,
      usdt_pyg: MOCK_RATES.usdt_pyg,
      updated_at: new Date().toISOString(),
    };
  } catch (e) { return handleSdkError(e, reply); }
});

app.get<{ Params: { country: "bob"|"pen"|"pyg" } }>(
  "/intl/banks/:country",
  async (req, reply) => {
    const c = req.params.country;
    if (!["bob","pen","pyg"].includes(c))
      return reply.code(400).send({ error: "country must be bob|pen|pyg" });
    try {
      if (andes) return await (andes.international.banks as any)[c]();
      const mockBob = [
        { id: "1010", name: "Banco Unión",       acronym: "BUN", country: "bo" },
        { id: "1020", name: "Banco Mercantil",   acronym: "BME", country: "bo" },
      ];
      const mockPen = [
        { id: "BCP",  name: "Banco de Crédito",  acronym: "BCP", country: "pe" },
        { id: "BBVA", name: "BBVA Continental",  acronym: "BBVA",country: "pe" },
      ];
      const mockPyg = { "85": "Banco Itau", "86": "Banco Continental",
                         "87": "Visión Banco" };
      return c === "bob" ? mockBob : c === "pen" ? mockPen : mockPyg;
    } catch (e) { return handleSdkError(e, reply); }
  });

// ----- Accounts (destinatarios)
app.post<{ Params: { country: "bob"|"pen"|"pyg" }, Body: {
  userId?: string; accountNumber?: string; bankCode?: any;
  accountHolder?: string; accountHolderName?: string;
  accountHolderLastName?: string; accountType?: any;
  documentNumber?: string; documentType?: any;
  bankName?: string; phoneNumber?: string;
} }>(
  "/intl/accounts/:country",
  async (req, reply) => {
    const c = req.params.country;
    const body = req.body || {};
    if (!body.userId) return reply.code(400).send({ error: "userId required" });
    try {
      if (andes) {
        if (c === "bob")  await andes.international.accounts.fiat.createBob(body as any);
        if (c === "pen")  await andes.international.accounts.fiat.createPen(body as any);
        if (c === "pyg")  return await andes.international.accounts.fiat.createPyg(body as any);
        return { ok: true };
      }
      const id = "intl_" + randomBytes(8).toString("hex");
      const acc: MockIntlAccount = {
        id, userId: body.userId!, country: c,
        account_number: body.accountNumber || "",
        account_holder_name: body.accountHolder || body.accountHolderName || "",
        account_holder_last_name: body.accountHolderLastName || "",
        bank: body.bankName || (body.bankCode ? `Bank ${body.bankCode}` : null),
        document_number: body.documentNumber || "",
        document_type: body.documentType || "DNI",
        account_type: body.accountType || "checking",
        created_at: new Date().toISOString(),
      };
      const list = mockIntl.accounts.get(body.userId!) || [];
      list.push(acc);
      mockIntl.accounts.set(body.userId!, list);
      // The real Bob/Pen endpoints return void; createPyg returns pygFiatAccountId.
      // For symmetry we always echo the id from the FastAPI side.
      if (c === "pyg") return { pygFiatAccountId: id };
      return { ok: true, id };
    } catch (e) { return handleSdkError(e, reply); }
  });

app.get<{ Querystring: { userId?: string } }>("/intl/accounts",
  async (req, reply) => {
    const userId = req.query.userId;
    try {
      if (andes) return await andes.international.accounts.fiat.list({ userId });
      const items = userId
        ? (mockIntl.accounts.get(userId) || [])
        : [...mockIntl.accounts.values()].flat();
      return items;
    } catch (e) { return handleSdkError(e, reply); }
  });

// ----- Quotes
app.post<{ Params: { country: "bob"|"pen" }, Body: {
  fromAmount?: string; paymentMethodType?: any } }>(
  "/intl/quote/:country", async (req, reply) => {
    const c = req.params.country;
    if (!["bob","pen"].includes(c))
      return reply.code(400).send({ error: "POST quote only for bob|pen; use GET for pyg" });
    const body = req.body || {};
    if (!body.fromAmount) return reply.code(400).send({ error: "fromAmount required" });
    try {
      if (andes) {
        if (c === "bob") return await andes.international.quotes.arsBob(body as any);
        return await andes.international.quotes.arsPen(body as any);
      }
      const fromAmount = String(body.fromAmount);
      const arsUsdt = Number(MOCK_RATES.ars_usdt);
      const usdtOut = c === "bob" ? Number(MOCK_RATES.usdt_bob)
                                   : Number(MOCK_RATES.usdt_pen);
      const usdt = Number(fromAmount) / arsUsdt;
      const toAmount = (usdt * usdtOut).toFixed(2);
      const exp = new Date(Date.now() + 60_000).toISOString();
      return {
        quotes: {
          arsUsdt: {
            quoteId: "q_arsusdt_" + randomBytes(5).toString("hex"),
            fromCurrency: "ARS", toCurrency: "USDT",
            fromAmount, toAmount: usdt.toFixed(6),
            chain: "stellar", expiration: exp, fees: [],
            rate: MOCK_RATES.ars_usdt },
          [c === "bob" ? "usdtBob" : "usdtPen"]: {
            quoteId: `q_usdt${c}_` + randomBytes(5).toString("hex"),
            fromCurrency: "USDT",
            toCurrency: c === "bob" ? "BOB" : "PEN",
            fromAmount: usdt.toFixed(6), toAmount,
            chain: "stellar", expiration: exp, fees: [],
            rate: String(usdtOut) },
        },
        fee: { percent: 1.0, amount: (Number(fromAmount) * 0.01).toFixed(2),
                totalAmount: fromAmount },
      };
    } catch (e) { return handleSdkError(e, reply); }
  });

app.get("/intl/quote/pyg", async (_req, reply) => {
  try {
    if (andes) return await andes.international.quotes.arsPyg();
    return { ars_usdt_rate: MOCK_RATES.ars_usdt,
             usdt_pyg_rate: MOCK_RATES.usdt_pyg,
             fee_percent: 1.0 };
  } catch (e) { return handleSdkError(e, reply); }
});

// ----- Offramp (execute)
app.post<{ Params: { country: "bob"|"pen"|"pyg" }, Body: {
  userId?: string; fiatAccountId?: string;
  arsAmount?: string; arsUsdtQuoteId?: string;
  usdtBobQuoteId?: string; usdtPenQuoteId?: string;
}}>(
  "/intl/offramp/:country", async (req, reply) => {
    const c = req.params.country;
    const body = req.body || {};
    if (!body.userId || !body.fiatAccountId)
      return reply.code(400).send({ error: "userId + fiatAccountId required" });
    try {
      if (andes) {
        if (c === "bob")  await andes.international.offramp.createArsBob(body as any);
        if (c === "pen")  await andes.international.offramp.createArsPen(body as any);
        if (c === "pyg")  await andes.international.offramp.createArsPyg(body as any);
        return { ok: true };
      }
      // Compute mock to_amount from inputs (PYG uses arsAmount directly)
      const arsAmount = c === "pyg"
        ? Number(body.arsAmount || 0)
        : Number(body.arsUsdtQuoteId ? "12345" : 0);  // fallback for mock
      const usdt = arsAmount / Number(MOCK_RATES.ars_usdt);
      const dest = c === "bob" ? Number(MOCK_RATES.usdt_bob)
                  : c === "pen" ? Number(MOCK_RATES.usdt_pen)
                  : Number(MOCK_RATES.usdt_pyg);
      const toAmount = (usdt * dest).toFixed(2);
      const id = "off_" + randomBytes(8).toString("hex");
      const off: MockIntlOfframp = {
        id, user_id: body.userId!, country: c,
        fiat_account_id: body.fiatAccountId!,
        from_currency: "ARS", from_amount: String(arsAmount),
        to_currency: c === "bob" ? "BOB" : c === "pen" ? "PEN" : "PYG",
        to_amount: toAmount,
        bridge_currency: "USDT", bridge_amount: usdt.toFixed(6),
        bridge_in_rate: MOCK_RATES.ars_usdt, bridge_out_rate: String(dest),
        status: "Pending", started_at: new Date().toISOString(),
      };
      const list = mockIntl.offramps.get(body.userId!) || [];
      list.push(off);
      mockIntl.offramps.set(body.userId!, list);
      // Auto-fire success webhook after a short delay
      setTimeout(() => {
        off.status = "Success";
        fireMockWebhook("international.offramp.success", { type: "international.offramp.success",
            data: { id, transactionId: id, userId: body.userId!, country: c,
                     from_amount: off.from_amount, to_amount: off.to_amount,
                     status: "Success" } })
          .catch(e => logger.error({ err: String(e) },
                                       "auto-fire intl offramp failed"));
      }, 1200);
      return { ok: true, ...off };
    } catch (e) { return handleSdkError(e, reply); }
  });

app.get<{ Querystring: { userId?: string } }>("/intl/offramp",
  async (req, reply) => {
    const userId = req.query.userId;
    try {
      if (andes) return await andes.international.offramp.list({ userId });
      const items = userId
        ? (mockIntl.offramps.get(userId) || [])
        : [...mockIntl.offramps.values()].flat();
      return items;
    } catch (e) { return handleSdkError(e, reply); }
  });

// ───────────────────────────────────────────────── Phase 15.2 — Crypto transfers
app.post<{ Body: { user_id?: string; chain?: any; asset?: any;
                     to_address?: string; amount?: number | string } }>(
  "/wallets/transfers", async (req, reply) => {
  const body = (req.body || {}) as { user_id?: string; chain?: any;
                                          asset?: any; to_address?: string;
                                          amount?: number | string };
  if (!body.user_id || !body.chain || !body.asset || !body.to_address
        || !body.amount) {
    return reply.code(400).send({ error:
      "user_id, chain, asset, to_address, amount required" });
  }
  try {
    if (andes) {
      const r = await andes.wallets.transfers.create({
        user_id: body.user_id, chain: body.chain, asset: body.asset,
        to_address: body.to_address, amount: Number(body.amount),
      });
      return r;
    }
    const wallets = mock.wallets.get(body.user_id) || [];
    const src = wallets.find(w => w.asset === body.asset
                                       && w.chain === body.chain);
    if (!src) return reply.code(404).send({ error: "source wallet not found" });
    if (Number(src.balance) < Number(body.amount))
      return reply.code(400).send({ error: "insufficient balance" });
    // Debit immediately (mock)
    src.balance = String(Number(src.balance) - Number(body.amount));
    const txId = "tx_" + randomBytes(8).toString("hex");
    const t: MockTransfer = {
      transactionId: txId, wallet_transaction_id: txId,
      user_id: body.user_id, chain: body.chain, asset: body.asset,
      from_address: src.address, to_address: body.to_address,
      amount: String(body.amount), tx_hash: null,
      status: "Pending", started_at: new Date().toISOString(),
    };
    const lst = mockTransfers.get(body.user_id) || [];
    lst.push(t);
    mockTransfers.set(body.user_id, lst);
    // Auto-fire success webhook after a short delay
    setTimeout(() => {
      t.status = "Success";
      t.tx_hash = "0x" + randomBytes(32).toString("hex");
      fireMockWebhook("crypto.transfer.success", { type: "crypto.transfer.success",
          data: { transactionId: txId, userId: body.user_id,
                   chain: body.chain, asset: body.asset,
                   to_address: body.to_address,
                   amount: String(body.amount), tx_hash: t.tx_hash,
                   status: "Success" } })
        .catch(e => logger.error({ err: String(e) },
                                     "auto-fire transfer success failed"));
    }, 1000);
    return { transactionId: txId, wallet_transaction_id: txId,
              user_id: body.user_id, chain: body.chain, asset: body.asset,
              from_address: src.address, to_address: body.to_address,
              amount: String(body.amount), tx_hash: null,
              status: "Pending", started_at: t.started_at };
  } catch (e) { return handleSdkError(e, reply); }
});

app.get<{ Querystring: { userId?: string } }>("/wallets/transfers",
  async (req, reply) => {
    const userId = req.query.userId;
    try {
      if (andes) {
        if (userId) return await andes.wallets.transfers.forUser(userId);
        return await andes.wallets.transfers.list();
      }
      const items = userId
        ? (mockTransfers.get(userId) || [])
        : [...mockTransfers.values()].flat();
      return items;
    } catch (e) { return handleSdkError(e, reply); }
  });


// ---------------------------------------------------------------------------
// Phase 20 — ARSa <-> USDC conversion (MOCK; replace with real Andes swap)
// ---------------------------------------------------------------------------
// TODO(phase20): replace `mockConvert*` with the real Andes swap endpoint once
// Andes exposes it. The contract here mirrors what we expect from the SDK:
//   POST /convert/arsa-usdc  { amount_arsa }
//      → { quote_id, usdc_out, rate, rate_source, quoted_at, expires_at }
//   POST /convert/usdc-arsa  { amount_usdc }
//      → { quote_id, arsa_out, rate, rate_source, quoted_at, expires_at }
//
// Rate is configurable via env (CONVERSION_MOCK_ARSA_PER_USDC, default 1500).
// Quote TTL via CONVERSION_QUOTE_TTL_SECONDS (default 60s).
const CONV_RATE = Number(process.env.CONVERSION_MOCK_ARSA_PER_USDC || 1500);
const CONV_TTL  = Number(process.env.CONVERSION_QUOTE_TTL_SECONDS    || 60);

function mkQuote(direction: "arsa_to_usdc" | "usdc_to_arsa",
                  fromAmount: number) {
  const now = Date.now();
  const quote_id = "qte_" + randomBytes(8).toString("hex");
  const rate = CONV_RATE; // ARSa per USDC; same in both directions for mock
  const usdc_out  = +(fromAmount / rate).toFixed(6);
  const arsa_out  = +(fromAmount * rate).toFixed(6);
  return {
    quote_id,
    direction,
    rate: String(rate),
    rate_source: "mock-fixed",
    quoted_at:   new Date(now).toISOString(),
    expires_at:  new Date(now + CONV_TTL * 1000).toISOString(),
    ttl_seconds: CONV_TTL,
    ...(direction === "arsa_to_usdc"
        ? { amount_arsa: String(fromAmount), usdc_out: String(usdc_out) }
        : { amount_usdc: String(fromAmount), arsa_out: String(arsa_out) }),
  };
}

app.post<{ Body: { amount_arsa?: number | string } }>(
  "/convert/arsa-usdc", async (req, reply) => {
    const amt = Number((req.body || {}).amount_arsa);
    if (!Number.isFinite(amt) || amt <= 0) {
      return reply.code(400).send({ error: "amount_arsa > 0 required" });
    }
    // TODO(phase20): if andes && andes.convert?.arsaToUsdc → use real swap.
    return mkQuote("arsa_to_usdc", amt);
  });

app.post<{ Body: { amount_usdc?: number | string } }>(
  "/convert/usdc-arsa", async (req, reply) => {
    const amt = Number((req.body || {}).amount_usdc);
    if (!Number.isFinite(amt) || amt <= 0) {
      return reply.code(400).send({ error: "amount_usdc > 0 required" });
    }
    // TODO(phase20): if andes && andes.convert?.usdcToArsa → use real swap.
    return mkQuote("usdc_to_arsa", amt);
  });



// ------------------------------------------------------------------ root
app.get("/", async () => ({
  ok: true,
  service: "andes-gateway",
  phase: 14,
  mode: currentMode(),
  endpoints: [
    "GET    /health",
    "POST   /accounts",
    "POST   /wallets",
    "GET    /wallets/:userId",
    "POST   /fiat",
    "POST   /fiat/business",
    "GET    /fiat/:userId",
    "POST   /fiat/withdraw",
    "GET    /fiat/cvu-lookup",
    "POST   /webhooks/andes  (PUBLIC, ES256-verified)",
    "GET    /project/stats",
    "GET    /project/stats-timeseries",
    "GET    /webhooks/deliveries",
    "GET    /capabilities",
    "POST   /dev/simulate-deposit  (mock only)",
    "POST   /dev/fire-webhook       (mock only)",
    "POST   /convert/arsa-usdc      (Phase 20 · mock swap)",
    "POST   /convert/usdc-arsa      (Phase 20 · mock swap)",
  ],
}));

// ------------------------------------------------------------------ start
async function start() {
  try {
    await app.listen({ host: HOST, port: PORT });
    logger.info({ host: HOST, port: PORT, mode: currentMode() },
                "andes-gateway listening");
  } catch (err) {
    logger.error({ err }, "failed to start andes-gateway");
    process.exit(1);
  }
}
start();

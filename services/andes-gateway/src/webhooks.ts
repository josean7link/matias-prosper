/**
 * Phase 15 — Andes webhook signing helpers (mock + real).
 *
 * The official Andes SDK signs every webhook with ES256 (ECDSA P-256 over
 * SHA-256). Each delivery includes 3 headers:
 *
 *   x-webhook-timestamp     ms epoch when Andes signed the body
 *   x-webhook-signature     base64url ES256 signature
 *   x-webhook-delivery-id   stable per delivery (for idempotency)
 *
 * The signing payload is "<timestamp>.<rawBody>" exactly.
 *
 * Mock mode: we ship a static EC P-256 keypair so tests are reproducible.
 * Real mode: at boot we call `andes.webhooks.signingKey()` to fetch the
 * tenant's current public key and cache it (refreshable on 401).
 */
import { createPrivateKey, createPublicKey, createSign, createVerify,
         KeyObject } from "crypto";

/* eslint-disable max-len */

// Static P-256 keypair used in MOCK mode. Both the signer (gateway) and the
// verifier (gateway receive endpoint) use the same one so the round-trip is
// trivially testable. NEVER use these in production — they're committed to
// git on purpose.
export const MOCK_PRIVATE_PEM = `-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgAIYSdoCKFSSSiQsB
tgLAruBmeN8CYqOD31ITtCG4g+6hRANCAAQ1WJDlMtbjpbVzh3UzpfGZxeMrkfQ0
075/eWfFjC3QHOoE8fd5UXhth7AnKek2uM8Mn2jYct21zzgeOb1JLxJq
-----END PRIVATE KEY-----`;

export const MOCK_PUBLIC_PEM = `-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAENViQ5TLW46W1c4d1M6XxmcXjK5H0
NNO+f3lnxYwt0BzqBPH3eVF4bYewJynpNrjPDJ9o2HLdtc84Hjm9SS8Sag==
-----END PUBLIC KEY-----`;

let cachedPublicKey: KeyObject | null = null;
let cachedPrivateKey: KeyObject | null = null;

export function getMockPrivateKey(): KeyObject {
  if (!cachedPrivateKey) {
    cachedPrivateKey = createPrivateKey({ key: MOCK_PRIVATE_PEM, format: "pem" });
  }
  return cachedPrivateKey;
}
export function getMockPublicKey(): KeyObject {
  if (!cachedPublicKey) {
    cachedPublicKey = createPublicKey({ key: MOCK_PUBLIC_PEM, format: "pem" });
  }
  return cachedPublicKey;
}

/** Build the canonical signing payload Andes uses: `<timestamp>.<rawBody>` */
export function signingPayload(timestamp: string, rawBody: Buffer | string): Buffer {
  const body = Buffer.isBuffer(rawBody) ? rawBody : Buffer.from(rawBody, "utf8");
  return Buffer.concat([Buffer.from(`${timestamp}.`, "utf8"), body]);
}

/** Sign (mock helper, used by `/dev/fire-webhook`). Returns base64url. */
export function signEs256Mock(timestamp: string, rawBody: Buffer | string): string {
  const sign = createSign("SHA256");
  sign.update(signingPayload(timestamp, rawBody));
  sign.end();
  // Use IEEE-P1363 (r || s) — what Andes' verifyWebhookSignature expects.
  const sig = sign.sign({ key: getMockPrivateKey(), dsaEncoding: "ieee-p1363" });
  return sig.toString("base64url");
}

/** Verify ES256 (ieee-p1363 base64url). Throws on max-age violation. */
export function verifyWebhookSignature(params: {
  rawBody: Buffer;
  timestamp: string;
  signature: string;
  publicKey: KeyObject;
  maxAgeMs?: number;
}): { ok: boolean; reason?: string } {
  const { rawBody, timestamp, signature, publicKey, maxAgeMs = 5 * 60_000 } = params;
  if (!timestamp || !signature) return { ok: false, reason: "missing-headers" };

  const tsNum = Number(timestamp);
  if (!Number.isFinite(tsNum)) return { ok: false, reason: "ts-not-numeric" };
  const age = Math.abs(Date.now() - tsNum);
  if (age > maxAgeMs) return { ok: false, reason: `stale (${age}ms > ${maxAgeMs}ms)` };

  let sigBuf: Buffer;
  try {
    sigBuf = Buffer.from(signature, "base64url");
  } catch {
    return { ok: false, reason: "signature-not-b64url" };
  }

  try {
    const verify = createVerify("SHA256");
    verify.update(signingPayload(timestamp, rawBody));
    verify.end();
    const ok = verify.verify({ key: publicKey, dsaEncoding: "ieee-p1363" }, sigBuf);
    return { ok, reason: ok ? undefined : "bad-signature" };
  } catch (e) {
    // crypto.verify throws on malformed signatures (e.g. wrong length for
    // P-256 IEEE-P1363, non-base64-ish bytes). Per Phase 15 PRD we must
    // surface this as 401, never 5xx — so we treat it like any other
    // signature failure.
    return { ok: false, reason: `malformed-signature: ${(e as Error).message}` };
  }
}

/** The list of event types we currently dispatch. Used both at /webhooks/andes
 *  registration time AND by the mock /dev/fire-webhook simulator. */
export const ANDES_EVENT_TYPES = [
  "wallet.active",
  "fiat.account.created",
  "fiat.deposit.success",
  "fiat.deposit.failed",
  "fiat.withdrawal.success",
  "fiat.withdrawal.failed",
  "crypto.transfer.success",
  "crypto.transfer.failed",
  "international.offramp.success",
  "international.offramp.failed",
] as const;
export type AndesEventType = (typeof ANDES_EVENT_TYPES)[number];

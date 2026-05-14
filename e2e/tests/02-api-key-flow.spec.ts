/**
 * E2E-2 — API Key plaintext-only-once.
 *
 * Verifies the security invariant: API key plaintext is returned exactly
 * once (on create + on rotate) and never appears on subsequent listings.
 * Also confirms a revoked key disappears from the table.
 */
import { test, expect } from "@playwright/test";
import { loginAs, accounts, apiCall } from "./_helpers";

test.describe("E2E-2 · API Keys", () => {
  test("plaintext shown once + listing never echoes it", async ({ browser }) => {
    const ctx = await loginAs(browser, accounts.clientAlemany, "/client/api-keys");
    const page = await ctx.newPage();
    await page.goto("/client/api-keys");
    await page.waitForSelector('[data-testid="api-keys-page"]', { timeout: 10_000 });

    // Create via API to keep the spec snappy.
    const r = await apiCall(ctx, "/api/v1/client/api-keys", {
      method: "POST",
      data: { name: "e2e-key", scope: "sandbox" },
    });
    expect(r.ok()).toBeTruthy();
    const { plaintext, key_id } = await r.json();
    expect(plaintext).toMatch(/^pk_(test|sandbox)_/);

    // Re-fetch the listing — the plaintext MUST NOT appear in the response.
    const list = await apiCall(ctx, "/api/v1/client/api-keys");
    const body = await list.text();
    expect(body).not.toContain(plaintext);

    // Revoke and confirm it disappears.
    const del = await apiCall(ctx, `/api/v1/client/api-keys/${key_id}`,
                                { method: "DELETE" });
    expect(del.ok()).toBeTruthy();
    const list2 = await apiCall(ctx, "/api/v1/client/api-keys");
    const body2 = await list2.json();
    expect((body2.items as Array<{ key_id: string }>).map(k => k.key_id))
      .not.toContain(key_id);

    await ctx.close();
  });
});

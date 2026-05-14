/**
 * E2E-3 — Webhook signed delivery.
 *
 * Registers a webhook endpoint (HMAC-signed by us) + triggers the
 * sample-payload `test` delivery + verifies the delivery log shows the
 * 2xx response. We use `httpbin.org/anything` as the receiver — it
 * echoes the request back, including our HMAC header.
 */
import { test, expect } from "@playwright/test";
import { loginAs, accounts, apiCall } from "./_helpers";

test.describe("E2E-3 · Webhook delivery", () => {
  test("registers endpoint + signed test delivery returns 2xx", async ({ browser }) => {
    const ctx = await loginAs(browser, accounts.clientAlemany);

    // Create the webhook endpoint via API.
    const create = await apiCall(ctx, "/api/v1/client/webhooks", {
      method: "POST",
      data: {
        url: "https://httpbin.org/anything",
        events: ["onramp.confirmed", "subscribe.confirmed"],
        description: "e2e-webhook",
      },
    });
    expect(create.ok()).toBeTruthy();
    const { webhook } = await create.json();
    const wid = webhook.webhook_id as string;

    // Trigger a test delivery.
    const tr = await apiCall(ctx, `/api/v1/client/webhooks/${wid}/test`,
                              { method: "POST" });
    expect(tr.ok()).toBeTruthy();
    const trBody = await tr.json();
    expect(trBody.ok).toBe(true);
    expect(trBody.delivery.http_code).toBeGreaterThanOrEqual(200);
    expect(trBody.delivery.http_code).toBeLessThan(300);

    // Cleanup.
    await apiCall(ctx, `/api/v1/client/webhooks/${wid}`, { method: "DELETE" });
    await ctx.close();
  });
});

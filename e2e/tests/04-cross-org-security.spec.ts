/**
 * E2E-4 — Cross-org security invariants.
 *
 *  - A client_admin of org A can not read positions / users from org B
 *    (responses are 404, never 403, to avoid org enumeration).
 *  - A client_admin can not use the `X-Acting-As-Org` header (internal only).
 *  - An unauthenticated request to a client endpoint returns 401.
 */
import { test, expect, request } from "@playwright/test";
import { loginAs, accounts, apiCall } from "./_helpers";

const BASE = process.env.PROSPER_BASE_URL
  ?? "https://15b54ecb-7c4d-4e40-932c-37af86d0770c.preview.emergentagent.com";

test.describe("E2E-4 · Cross-org security", () => {
  test("client A cannot read client B resources", async ({ browser }) => {
    // Get a real position_id for Finpact via super_admin.
    const admin = await loginAs(browser, accounts.superAdmin);
    const seed = await apiCall(admin, "/api/v1/admin/ops/seed-demo-client", {
      method: "POST", data: { auto_approve: true, seed_history: true },
    });
    expect(seed.ok()).toBeTruthy();
    const { org_id: demoOrgId } = await seed.json();

    // Now log in as a *different* client (Alemany) and try to read demoOrgId's data.
    const alemany = await loginAs(browser, accounts.clientAlemany);
    const cross = await apiCall(alemany, `/api/v1/organizations/${demoOrgId}`);
    expect(cross.status()).toBe(404);

    // The `X-Acting-As-Org` header must be ignored for client roles.
    const impersonation = await alemany.request.fetch(
      `${BASE}/api/v1/organizations`,
      { headers: { "X-Acting-As-Org": demoOrgId } });
    expect(impersonation.status()).toBe(403);

    // Cleanup
    await apiCall(admin, "/api/v1/admin/ops/wipe-demo",
                   { method: "POST", data: { confirm: "WIPE-DEMO" } });
    await admin.close();
    await alemany.close();
  });

  test("unauthenticated requests return 401", async () => {
    const anon = await request.newContext({ baseURL: BASE,
                                              ignoreHTTPSErrors: true });
    const r = await anon.get("/api/v1/client/me");
    expect(r.status()).toBe(401);
    await anon.dispose();
  });
});

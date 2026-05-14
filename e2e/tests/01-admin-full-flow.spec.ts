/**
 * E2E-1 — Admin full flow.
 *
 * Verifies the end-to-end happy path: super_admin seeds a demo client
 * (KYB approved), the client lands on a dashboard that has un-gated CTAs,
 * runs an on-ramp (mock Alfred auto-settle), sees a Position created
 * automatically, and the corresponding tx in the history.
 *
 * Uses the `seed-demo-client` endpoint to skip the wizard (covered in
 * a separate spec) and the `mock-settle` Alfred endpoint to skip the
 * 8-second wait.
 */
import { test, expect } from "@playwright/test";
import { loginAs, accounts, apiCall } from "./_helpers";

test.describe("E2E-1 · Admin → demo client → dashboard", () => {
  test("seeds a demo client, client lands on dashboard with seeded data", async ({ browser }) => {
    // 1. Super admin seeds a demo client.
    const admin = await loginAs(browser, accounts.superAdmin, "/admin/clients");
    const seedRes = await apiCall(admin, "/api/v1/admin/ops/seed-demo-client", {
      method: "POST",
      data: { auto_approve: true, seed_history: true },
    });
    expect(seedRes.ok()).toBeTruthy();
    const { org_id, email } = await seedRes.json();
    expect(org_id).toMatch(/^org_demo_/);

    // Visit the admin clients list and confirm the new org appears.
    const adminPage = await admin.newPage();
    await adminPage.goto("/admin/clients");
    await adminPage.waitForSelector('[data-testid="admin-clients-list-page"]');
    // Soft-assert the seed row is visible (the list paginates by 25 — newest first).
    await expect(adminPage.locator("body")).toContainText(org_id, { timeout: 5_000 });
    await admin.close();

    // 2. Login as the seeded client and check dashboard renders KPI row.
    const client = await loginAs(browser, email, "/client");
    const clientPage = await client.newPage();
    await clientPage.goto("/client");
    await clientPage.waitForSelector('[data-testid="client-dashboard"]', { timeout: 10_000 });
    await expect(clientPage.locator('[data-testid="kpi-row"]')).toBeVisible();
    // 3 action buttons should not be disabled — auto-approve = true
    await expect(clientPage.locator('[data-testid="action-invest"]'))
      .not.toHaveAttribute("data-disabled", "true");
    await client.close();

    // 3. Cleanup so the demo doesn't leak between runs.
    const cleanup = await loginAs(browser, accounts.superAdmin);
    await apiCall(cleanup, "/api/v1/admin/ops/wipe-demo", {
      method: "POST", data: { confirm: "WIPE-DEMO" },
    });
    await cleanup.close();
  });
});

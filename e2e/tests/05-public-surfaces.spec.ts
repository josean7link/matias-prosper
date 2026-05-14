/**
 * E2E-5 — Public surfaces (Status, Terms, Privacy).
 *
 *  - /status renders without auth + shows the 7 service rows.
 *  - /terms and /privacy render their main heading.
 *  - The public footer is present on all three.
 */
import { test, expect } from "@playwright/test";

test.describe("E2E-5 · Public pages", () => {
  test("/status shows service list + footer", async ({ page }) => {
    await page.goto("/status");
    await page.waitForSelector('[data-testid="status-page"]', { timeout: 10_000 });
    await expect(page.locator('[data-testid="status-list"]')).toBeVisible();
    for (const id of ["mongo", "api", "admin", "client", "webhooks",
                       "alfred", "prosper"]) {
      await expect(page.locator(`[data-testid="status-${id}"]`)).toBeVisible();
    }
    await expect(page.locator('[data-testid="public-footer"]')).toBeVisible();
  });

  test("/terms renders without auth", async ({ page }) => {
    await page.goto("/terms");
    await page.waitForSelector('[data-testid="terms-page"]', { timeout: 10_000 });
    await expect(page.locator("h1")).toHaveText(/Términos de Servicio/i);
    await expect(page.locator('[data-testid="public-footer"]')).toBeVisible();
  });

  test("/privacy renders without auth", async ({ page }) => {
    await page.goto("/privacy");
    await page.waitForSelector('[data-testid="privacy-page"]', { timeout: 10_000 });
    await expect(page.locator("h1")).toHaveText(/Política de Privacidad/i);
    await expect(page.locator('[data-testid="public-footer"]')).toBeVisible();
  });
});

/** Helpers shared across E2E specs — dev magic link login + small utils. */
import { Browser, BrowserContext, Page, request, APIRequestContext } from "@playwright/test";

const SUPER_ADMIN = "admin@prosper.foundation";
const CLIENT_ALEMANY = "client.admin@alemany.capital";
const CLIENT_FINPACT = "client.admin@finpact.io";

/**
 * Returns a fresh `BrowserContext` already logged in as the given email
 * via the dev magic link. Cookies are set automatically.
 */
export async function loginAs(browser: Browser, email: string,
                                next = "/admin"): Promise<BrowserContext> {
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    baseURL: process.env.PROSPER_BASE_URL
      ?? "https://15b54ecb-7c4d-4e40-932c-37af86d0770c.preview.emergentagent.com",
  });
  const page = await ctx.newPage();
  await page.goto(`/api/v1/auth/dev-login?email=${encodeURIComponent(email)}&next=${next}`,
                  { waitUntil: "domcontentloaded" });
  await page.close();
  return ctx;
}

export const accounts = {
  superAdmin: SUPER_ADMIN,
  clientAlemany: CLIENT_ALEMANY,
  clientFinpact: CLIENT_FINPACT,
};

/**
 * Calls the backend with an authenticated cookie context — useful for
 * priming state without going through the UI.
 */
export async function apiCall(
  ctx: BrowserContext,
  path: string,
  init: { method?: string; data?: unknown } = {},
) {
  return ctx.request.fetch(path, {
    method: init.method ?? "GET",
    data: init.data,
    headers: { "Content-Type": "application/json" },
  });
}

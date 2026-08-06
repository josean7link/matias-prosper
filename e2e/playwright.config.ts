import { defineConfig, devices } from "@playwright/test";

/**
 * Prosper E2E — Playwright config.
 *
 * BASE_URL points to the preview ingress by default; override via
 * `PROSPER_BASE_URL=https://staging.example.com pnpm test`.
 */
const BASE_URL = process.env.PROSPER_BASE_URL
  ?? "https://15b54ecb-7c4d-4e40-932c-37af86d0770c.preview.emergentagent.com";

export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  fullyParallel: false,                 // RBAC tests share state — keep serial
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: BASE_URL,
    ignoreHTTPSErrors: true,
    trace: "retain-on-failure",
    video: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
  ],
});

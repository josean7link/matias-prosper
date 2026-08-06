/** @type {import('next').NextConfig} */
const path = require("path");
const createNextIntlPlugin = require("next-intl/plugin");
const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

// BACKEND_URL: server-side only env var (no NEXT_PUBLIC_ prefix — never
// exposed to the client bundle). Set to the Render backend URL in production.
// Falls back to localhost for local dev without Docker.
const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8001";

const nextConfig = {
  reactStrictMode: true,
  experimental: {
    typedRoutes: false,
    // Monorepo: explicitly pin the workspace tracing root so Next.js's
    // `findPagesDir` + `getPageStaticInfo` resolve source files
    // relative to `/app/frontend`, not the yarn workspaces root `/app`.
    // Without this, the Docker production build fails during
    // "Collecting page data" with ENOENT on src/app/**/page.tsx.
    outputFileTracingRoot: path.join(__dirname, "../"),
  },
  // ESLint runs in CI; don't block production builds on stylistic rules
  // (e.g. react/no-unescaped-entities).
  eslint: { ignoreDuringBuilds: true },
  // TypeScript: same — the type-check job runs separately (`yarn typecheck`).
  // Avoids deploys breaking on third-party type incompatibilities like
  // `lucide-react` icon ForwardRef vs custom ComponentType signatures.
  typescript: { ignoreBuildErrors: true },
  // Proxy /api/* to the FastAPI backend.
  // - Local dev:   BACKEND_URL defaults to http://localhost:8001
  // - Production:  Set BACKEND_URL=https://<your-app>.onrender.com in Vercel
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` }];
  },
};
module.exports = withNextIntl(nextConfig);

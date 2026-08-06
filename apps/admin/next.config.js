/** @type {import('next').NextConfig} */
const path = require("path");
const createNextIntlPlugin = require("next-intl/plugin");
const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

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
  // Proxy /api/* to the FastAPI backend during dev — the same-origin /api path
  // works in production thanks to the kubernetes ingress.
  async rewrites() {
    return [{ source: "/api/:path*", destination: "http://localhost:8001/api/:path*" }];
  },
};
module.exports = withNextIntl(nextConfig);

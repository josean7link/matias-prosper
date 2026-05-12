/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  experimental: { typedRoutes: false },
  // Proxy /api/* to the FastAPI backend during dev — the same-origin /api path
  // works in production thanks to the kubernetes ingress.
  async rewrites() {
    return [{ source: "/api/:path*", destination: "http://localhost:8001/api/:path*" }];
  },
};
module.exports = nextConfig;

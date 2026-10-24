/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone bundles the server plus only the dependencies it actually
  // traces, which is what the Docker runtime stage copies.
  output: "standalone",

  // Without this, Next guesses the tracing root by walking up looking for a
  // lockfile and can land several directories above the project — the output
  // then appears at .next/standalone/<those>/<dirs>/server.js instead of
  // .next/standalone/server.js, and the Dockerfile COPY finds nothing.
  outputFileTracingRoot: process.cwd(),
  reactStrictMode: true,
  // The panel and the API live on the Django side; the marketing site only
  // reads public endpoints (plans, showcase) so nothing here needs auth.
  async rewrites() {
    const api = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
  // Renamed with the rebrand (UpMarket -> NMarketing): old links, shares and
  // search results for /compare/upmarket-vs-* must keep landing on the page.
  async redirects() {
    const slugs = ["marketing-agency", "freelancer", "doing-it-yourself"];
    return slugs.flatMap((s) => [
      { source: `/compare/upmarket-vs-${s}`, destination: `/compare/nmarketing-vs-${s}`, permanent: true },
      { source: `/fa/compare/upmarket-vs-${s}`, destination: `/compare/nmarketing-vs-${s}`, permanent: true },
      { source: `/en/compare/upmarket-vs-${s}`, destination: `/en/compare/nmarketing-vs-${s}`, permanent: true },
    ]);
  },
  images: { remotePatterns: [{ protocol: "http", hostname: "127.0.0.1" }] },
};
export default nextConfig;

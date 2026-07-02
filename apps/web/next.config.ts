import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output so the Docker runner stage only ships server.js + traced deps.
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
};

export default nextConfig;

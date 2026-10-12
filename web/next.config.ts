import path from "node:path";
import type { NextConfig } from "next";

// The browser only ever talks to this Next.js app. Requests to /api/* are proxied to the Python API,
// so there is no cross-origin setup and the API address never reaches the browser.
const API_URL = process.env.API_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false,
  images: {
    // Photos come straight from Unsplash's own resizing CDN (see src/lib/image-loader.ts), not /_next/image.
    loader: "custom",
    loaderFile: "./src/lib/image-loader.ts",
    // Product photos come from Unsplash's image CDN only.
    remotePatterns: [{ protocol: "https", hostname: "images.unsplash.com", pathname: "/photo-**" }],
  },
  turbopack: {
    root: path.resolve(__dirname),
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Permissions-Policy", value: "camera=(), geolocation=(), microphone=(self)" },
        ],
      },
    ];
  },
};

export default nextConfig;

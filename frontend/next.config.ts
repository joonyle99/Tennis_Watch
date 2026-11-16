import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Docker 이미지를 만들 때만 단독 실행용 묶음으로 빌드한다(frontend/Dockerfile).
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;

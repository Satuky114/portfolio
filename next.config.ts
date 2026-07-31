import type { NextConfig } from "next";

// GitHub Pages 子路径部署：站点挂在 satuky114.github.io/portfolio
const basePath = "/portfolio";

const nextConfig: NextConfig = {
  output: "export",
  basePath,
  trailingSlash: true,
  images: {
    unoptimized: true,
  },
  env: {
    NEXT_PUBLIC_BASE_PATH: basePath,
  },
};

export default nextConfig;

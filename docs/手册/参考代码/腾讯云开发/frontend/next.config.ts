import type { NextConfig } from "next";

// 后端地址不写在这里：/api/* 由 proxy.ts 在每次请求时读 process.env.BACKEND_URL 转发，
// 同一个镜像换环境只改环境变量，不用重新构建（next.config 的 rewrites 在构建时就固定了）。
const nextConfig: NextConfig = {
  output: "standalone", // 云托管容器：只带运行所需文件，启动命令 node server.js
  poweredByHeader: false,
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

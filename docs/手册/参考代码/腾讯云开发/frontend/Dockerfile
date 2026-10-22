# 腾讯云开发 云托管（CloudBase Run）前端镜像。构建目录 = frontend/。
# 浏览器只访问这个服务；/api/* 由 proxy.ts 在服务器端转发到后端服务。
# 运行时环境变量（填在云托管控制台"环境变量"里，改了不用重新构建）：
#   BACKEND_URL          后端服务地址，例如 https://<后端服务域名>
#   PROXY_SHARED_SECRET  与后端同名变量相同的值（至少 16 位随机字符）
# 服务端口：读平台注入的 PORT，没有则用 3000；云托管控制台里的"服务端口"要填同一个值（3000）。

# ---------- 1. 安装依赖 ----------
FROM node:22-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# 国内构建慢时可加 --registry=https://registry.npmmirror.com
RUN npm ci --no-audit --no-fund

# ---------- 2. 构建 ----------
FROM node:22-slim AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# ---------- 3. 运行 ----------
FROM node:22-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000 \
    TZ=Asia/Shanghai

# standalone 产物不含静态资源和 public，按官方要求补进去
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static
COPY --from=builder --chown=node:node /app/public ./public

# 非 root 运行（node 镜像自带 node 用户）
USER node

EXPOSE 3000
# server.js 读取 PORT / HOSTNAME 环境变量：监听 0.0.0.0:${PORT:-3000}
CMD ["node", "server.js"]

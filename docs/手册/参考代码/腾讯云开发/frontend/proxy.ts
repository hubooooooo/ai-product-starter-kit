// Next.js 16 的 proxy（原 middleware，运行在 Node.js 运行时）：把 /api/* 原样转发到后端。
// 后端地址和共享密钥都在每次请求时从 process.env 读取——同一个镜像换环境只改环境变量，不用重新构建。
import type { NextRequest } from "next/server";

import {
  MAX_BODY_BYTES,
  buildForwardHeaders,
  buildResponseHeaders,
  buildUpstreamUrl,
  errorJson,
  parseBackendUrl,
  statusAllowsBody,
} from "@/lib/proxy/forward";

// 模型生成最长约：单次超时 × 重试次数；留足余量
const UPSTREAM_TIMEOUT_MS = 90_000;

export async function proxy(request: NextRequest): Promise<Response> {
  const backend = parseBackendUrl(process.env.BACKEND_URL);
  if (!backend) {
    console.error("[proxy] BACKEND_URL is not configured");
    return errorJson(503, "BACKEND_NOT_CONFIGURED", "服务暂时不可用，请稍后再试");
  }

  const method = request.method.toUpperCase();
  const declared = Number(request.headers.get("content-length") ?? "0");
  if (declared > MAX_BODY_BYTES) {
    return errorJson(413, "PAYLOAD_TOO_LARGE", "提交的内容太大了");
  }
  let body: ArrayBuffer | undefined;
  if (method !== "GET" && method !== "HEAD") {
    body = await request.arrayBuffer();
    if (body.byteLength > MAX_BODY_BYTES) {
      return errorJson(413, "PAYLOAD_TOO_LARGE", "提交的内容太大了");
    }
  }

  const url = buildUpstreamUrl(backend, request.nextUrl.pathname, request.nextUrl.search);
  let upstream: Response;
  try {
    upstream = await fetch(url, {
      method,
      headers: buildForwardHeaders(request.headers, process.env.PROXY_SHARED_SECRET),
      body,
      redirect: "manual",
      cache: "no-store",
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
  } catch (err) {
    const name = err instanceof Error ? err.name : "unknown";
    // 只记错误类型，不记地址以外的任何请求内容
    console.error(`[proxy] upstream request failed type=${name} path=${request.nextUrl.pathname}`);
    if (name === "TimeoutError") {
      return errorJson(504, "BACKEND_TIMEOUT", "服务响应太慢，请稍后再试");
    }
    return errorJson(502, "BACKEND_UNAVAILABLE", "服务暂时连不上，请稍后再试");
  }

  return new Response(statusAllowsBody(upstream.status) ? upstream.body : null, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: buildResponseHeaders(upstream.headers),
  });
}

export const config = {
  matcher: "/api/:path*",
};

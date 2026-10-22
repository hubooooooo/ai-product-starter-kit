// /api/* 转发到后端时的纯函数（不依赖 Next 运行时，便于单元测试）。
// 规则：
// - 访客真实 IP 只取云托管边缘写入的 x-envoy-external-address（X-Forwarded-For 在云托管上可被客户端伪造）；
// - 浏览器自带的 x-client-ip / x-proxy-secret 一律丢弃，由这里重新写入；
// - 不在日志里输出密钥或完整请求头。

/** 云托管边缘写入的访客 IP 头（客户端无法伪造）。 */
export const EDGE_IP_HEADER = "x-envoy-external-address";
/** 转发给后端的访客 IP 头；后端只在 x-proxy-secret 正确时信任它。 */
export const CLIENT_IP_HEADER = "x-client-ip";
/** 前端与后端共享密钥的请求头。 */
export const PROXY_SECRET_HEADER = "x-proxy-secret";

/** 请求体上限（本产品的接口请求体都很小）。 */
export const MAX_BODY_BYTES = 64 * 1024;

const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "proxy-connection",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

// 转发前从浏览器请求里去掉的头：逐跳头、长度/主机（由 fetch 重算）、可伪造的来源 IP 头、我们自己要写的头
const STRIP_REQUEST = new Set([
  ...HOP_BY_HOP,
  "host",
  "content-length",
  "expect",
  "forwarded",
  "x-forwarded-for",
  "x-forwarded-host",
  "x-forwarded-port",
  "x-forwarded-proto",
  "x-real-ip",
  EDGE_IP_HEADER,
  CLIENT_IP_HEADER,
  PROXY_SECRET_HEADER,
]);

// 回给浏览器前去掉的头：逐跳头；fetch 已自动解压且可能改变长度，所以编码与长度头也去掉
const STRIP_RESPONSE = new Set([...HOP_BY_HOP, "content-encoding", "content-length"]);

/** BACKEND_URL 是否可用：必须是 http(s) 绝对地址。 */
export function parseBackendUrl(raw: string | undefined): URL | null {
  const value = raw?.trim();
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url : null;
  } catch {
    return null;
  }
}

/** 拼出后端地址：后端基础地址（可带路径前缀）+ 原请求路径 + 查询串。 */
export function buildUpstreamUrl(backend: URL, pathname: string, search: string): string {
  const base = backend.origin + backend.pathname.replace(/\/+$/, "");
  return base + pathname + (search ?? "");
}

/** 从边缘头里取访客 IP；没有或格式可疑时返回 null。 */
export function visitorIpFrom(headers: Headers): string | null {
  const raw = headers.get(EDGE_IP_HEADER);
  if (!raw) return null;
  const first = raw.split(",")[0]?.trim() ?? "";
  if (!first || first.length > 64 || !/^[0-9A-Fa-f.:]+$/.test(first)) return null;
  return first;
}

/** 生成转发给后端的请求头。 */
export function buildForwardHeaders(incoming: Headers, secret: string | undefined): Headers {
  const out = new Headers();
  incoming.forEach((value, key) => {
    const name = key.toLowerCase();
    if (STRIP_REQUEST.has(name) || name.startsWith("x-middleware-")) return;
    out.append(name, value);
  });
  const ip = visitorIpFrom(incoming);
  if (ip) out.set(CLIENT_IP_HEADER, ip);
  const key = secret?.trim();
  if (key) out.set(PROXY_SECRET_HEADER, key);
  return out;
}

/** 生成回给浏览器的响应头：Set-Cookie 逐条保留。 */
export function buildResponseHeaders(upstream: Headers): Headers {
  const out = new Headers();
  upstream.forEach((value, key) => {
    const name = key.toLowerCase();
    if (STRIP_RESPONSE.has(name) || name === "set-cookie") return;
    out.append(name, value);
  });
  for (const cookie of upstream.getSetCookie()) out.append("set-cookie", cookie);
  return out;
}

/** 统一错误体 {"error": {"code", "message"}}。 */
export function errorJson(status: number, code: string, message: string): Response {
  return Response.json({ error: { code, message } }, { status, headers: { "cache-control": "no-store" } });
}

/** 这些状态码不能带响应体。 */
export function statusAllowsBody(status: number): boolean {
  return !(status === 204 || status === 205 || status === 304 || (status >= 100 && status < 200));
}

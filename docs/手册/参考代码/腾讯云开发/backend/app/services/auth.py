"""邀请码登录的确定性逻辑：会话签名 / 校验、登录失败限流、客户端 IP。

会话 Cookie = base64url(JSON 载荷) + "." + HMAC-SHA256 签名（密钥来自环境变量 SESSION_SECRET）。
载荷里有：用户标签、所用邀请码的指纹（不是码本身）、过期时间。
每次请求都会核对"这个指纹现在还对应这个标签"——邀请码从 INVITE_CODES 删掉或换掉后，旧会话立即失效。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time

from app.core.config import MIN_PROXY_SECRET_LEN, Settings

SESSION_COOKIE = "xhs_session"
LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_SECONDS = 15 * 60


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def code_fingerprint(secret: str, code: str) -> str:
    return hmac.new(secret.encode(), b"invite:" + code.encode(), hashlib.sha256).hexdigest()[:24]


def match_invite_code(settings: Settings, code: str) -> str | None:
    """返回邀请码对应的标签；不对返回 None。逐个用常量时间比较，避免按耗时猜码。"""
    found = None
    for known, label in settings.invite_codes.items():
        if hmac.compare_digest(known.encode(), code.encode()):
            found = label
    return found


def make_session(settings: Settings, label: str, code: str, now: float | None = None) -> str:
    now = time.time() if now is None else now
    payload = _b64e(json.dumps({"l": label, "c": code_fingerprint(settings.session_secret, code),
                                "e": int(now) + settings.session_max_age_seconds},
                               ensure_ascii=False, separators=(",", ":")).encode())
    return f"{payload}.{_sign(settings.session_secret, payload)}"


def read_session(settings: Settings, token: str | None, now: float | None = None) -> str | None:
    """校验会话，返回用户标签；签名不对、过期、邀请码已作废都返回 None。"""
    if not token or not settings.auth_configured or token.count(".") != 1:
        return None
    payload, sig = token.split(".")
    if not hmac.compare_digest(_sign(settings.session_secret, payload), sig):
        return None
    try:
        data = json.loads(_b64d(payload))
        label, fp, exp = str(data["l"]), str(data["c"]), int(data["e"])
    except (ValueError, KeyError, TypeError):
        return None
    if exp < (time.time() if now is None else now):
        return None
    for code, lb in settings.invite_codes.items():
        if lb == label and hmac.compare_digest(code_fingerprint(settings.session_secret, code), fp):
            return label
    return None


PROXY_CLIENT_IP_HEADER = "x-client-ip"   # 前端代理写入的访客真实 IP
PROXY_SECRET_HEADER = "x-proxy-secret"   # 前端代理证明"我是自己人"的共享密钥


def proxied_client_ip(settings: Settings, proxy_secret: str | None, forwarded_ip: str | None) -> str | None:
    """前端（Next 代理）转发来的访客 IP。只有请求带着与 PROXY_SHARED_SECRET 相同的 x-proxy-secret 才信任；
    密钥没配置或短于 16 位、密钥不对、没带密钥，一律返回 None（退回原来的取 IP 方式）。常量时间比较。"""
    secret = settings.proxy_shared_secret
    if len(secret) < MIN_PROXY_SECRET_LEN or not proxy_secret or not forwarded_ip or not forwarded_ip.strip():
        return None
    if not hmac.compare_digest(secret.encode(), proxy_secret.encode()):
        return None
    return forwarded_ip.strip()[:64]


def client_ip(settings: Settings, peer: str | None, forwarded_for: str | None, trusted_ip: str | None = None,
              proxied_ip: str | None = None) -> str:
    """限流用的来源 IP。proxied_ip（已经 proxied_client_ip 校验过的前端代理头）优先。
    PROXY_HOPS=0：直接用 TCP 对端地址（本机）。
    PROXY_HOPS=N：服务前面有 N 层可信代理，取 X-Forwarded-For 从右数第 N 个（最左边的值客户端可伪造，不用）。"""
    if proxied_ip:
        return proxied_ip
    # CLIENT_IP_HEADER：平台网关写入、客户端无法伪造的来源 IP 头（腾讯云云托管实测为 x-envoy-external-address；
    # X-Forwarded-For / X-Real-IP 在云托管上会被客户端自带的值覆盖，不能用来限流）
    if settings.client_ip_header and trusted_ip and trusted_ip.strip():
        return trusted_ip.strip()
    if settings.proxy_hops > 0 and forwarded_for:
        hops = [h.strip() for h in forwarded_for.split(",") if h.strip()]
        if hops:
            return hops[-settings.proxy_hops] if len(hops) >= settings.proxy_hops else hops[0]
    return peer or "unknown"


class LoginLimiter:
    """登录失败限流：同一来源 IP 连续失败 5 次，锁定 15 分钟；成功一次清零。

    状态只放在进程内存里：服务按单实例运行（云托管实例数固定为 1），这样足够。
    代价是服务重启后计数清零——这只是防刷措施，不是业务数据，可以接受。改成多实例时需要换成数据库或 Redis。
    """

    MAX_TRACKED = 10_000  # 防止被大量不同 IP 撑爆内存

    def __init__(self, max_failures: int = LOGIN_MAX_FAILURES, lock_seconds: int = LOGIN_LOCK_SECONDS) -> None:
        self.max_failures = max_failures
        self.lock_seconds = lock_seconds
        self._state: dict[str, tuple[int, float]] = {}  # ip -> (连续失败次数, 锁定到期时间戳)
        self._lock = threading.Lock()

    def locked_seconds_left(self, ip: str, now: float | None = None) -> int:
        now = time.time() if now is None else now
        with self._lock:
            _, until = self._state.get(ip, (0, 0.0))
            return max(0, int(until - now + 0.999)) if until > now else 0

    def record_failure(self, ip: str, now: float | None = None) -> int:
        """记一次失败；返回还能再试几次（0 表示已锁定）。"""
        now = time.time() if now is None else now
        with self._lock:
            if len(self._state) >= self.MAX_TRACKED:
                self._prune(now)
            count, until = self._state.get(ip, (0, 0.0))
            if until and until <= now:  # 上一轮锁定已过期，重新计数
                count = 0
            count += 1
            until = now + self.lock_seconds if count >= self.max_failures else 0.0
            self._state[ip] = (count, until)
            return max(0, self.max_failures - count)

    def record_success(self, ip: str) -> None:
        with self._lock:
            self._state.pop(ip, None)

    def reset(self) -> None:
        with self._lock:
            self._state.clear()

    def _prune(self, now: float) -> None:
        for ip in [k for k, (_, until) in self._state.items() if until <= now]:
            del self._state[ip]
        if len(self._state) >= self.MAX_TRACKED:
            self._state.clear()


login_limiter = LoginLimiter()

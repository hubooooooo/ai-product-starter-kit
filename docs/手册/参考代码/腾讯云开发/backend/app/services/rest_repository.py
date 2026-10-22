"""数据读写的第二种实现：腾讯云开发 PostgreSQL 的 HTTPS 网关（PostgREST 语法），DATA_BACKEND=cloudbase_rest 时启用。

为什么不用数据库驱动：云开发环境自带的 PostgreSQL 是共享集群，没有内网地址；开公网要放开安全组。改走官方网关：
  GET    {base}/{表}?select=...&列=eq.值&order=created_at.desc&limit=N
  POST   {base}/{表}           JSON 请求体，Prefer: return=representation 拿回整行（含数据库生成的 id）
  PATCH  {base}/{表}?id=eq.X
  计数   Prefer: count=exact，读响应头 Content-Range（如 0-9/42、*/0）
鉴权：Authorization: Bearer <CLOUDBASE_API_KEY>。这是服务端 API Key（管理员权限），只在后端用，
不下发浏览器、不写日志、不出现在错误信息里。

与 SQL 实现行为一致：时间戳由应用生成（UTC），id 由数据库自增（与 SQL 表结构相同，见 migrations/001_init.sql）；
所有查询都带 owner_id 条件（权限判断在后端）。
网络策略：连接 5 秒、读取 15 秒超时；只有幂等的 GET 在连接失败或 5xx 时重试 1 次；写操作不重试（避免重复写入）。
失败一律转成统一错误 {"error": {"code", "message"}}，不带堆栈、地址或 Key。
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.core.config import Settings
from app.core.errors import AppError
from app.models.generation import SCHEMA_VERSION

logger = logging.getLogger("app.rest_db")
# httpx 默认 INFO 日志会打出完整网关地址（含按用户过滤的查询条件），压到 WARNING，日志只留元信息
logging.getLogger("httpx").setLevel(logging.WARNING)

TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=15.0, pool=5.0)
GET_RETRIES = 1  # 只给 GET
T_GEN = "generations"
T_USER = "users"
GEN_COLUMNS = "id,schema_version,owner_id,topic,audience,titles,status,attempts,model,created_at"


class RestConfigError(RuntimeError):
    """启动时配置不全：直接让服务启动失败（fail fast），信息里只有变量名，没有值。"""


def _unavailable() -> AppError:
    return AppError("DB_UNAVAILABLE", "数据库暂时连不上，请稍后重试", 503)


def _bad_response() -> AppError:
    return AppError("DB_ERROR", "数据读写失败，请稍后重试", 502)


@dataclass
class GenerationRecord:
    """与 ORM 的 Generation 有同样的属性，接口层不需要区分来源。"""
    id: int
    schema_version: int
    owner_id: str
    topic: str
    audience: str
    titles: list
    status: str
    attempts: int
    model: str
    created_at: datetime


def _parse_time(raw: str) -> datetime:
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _record(row: dict) -> GenerationRecord:
    try:
        return GenerationRecord(
            id=int(row["id"]), schema_version=int(row.get("schema_version") or SCHEMA_VERSION),
            owner_id=str(row["owner_id"]), topic=str(row["topic"]), audience=str(row.get("audience") or ""),
            titles=list(row["titles"]), status=str(row["status"]), attempts=int(row["attempts"]),
            model=str(row["model"]), created_at=_parse_time(str(row["created_at"])))
    except (KeyError, TypeError, ValueError):
        logger.error("rest row shape unexpected table=%s", T_GEN)
        raise _bad_response() from None


def parse_content_range_total(value: str | None) -> int:
    """Content-Range: '0-9/42' → 42；'*/0' → 0。总数是 '*'（没要 count）或格式不对时报错。"""
    if not value or "/" not in value:
        raise ValueError("missing content-range")
    total = value.rsplit("/", 1)[1].strip()
    if not total.isdigit():
        raise ValueError("content-range has no exact total")
    return int(total)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


class RestRepository:
    def __init__(self, base_url: str, api_key: str, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/") + "/", timeout=TIMEOUT, transport=transport,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            follow_redirects=False)

    def close(self) -> None:
        self._client.close()

    # ---------- 底层请求 ----------

    def _request(self, method: str, table: str, *, params: dict | None = None, json=None,
                 headers: dict | None = None) -> httpx.Response:
        attempts = 1 + (GET_RETRIES if method == "GET" else 0)
        for i in range(attempts):
            try:
                resp = self._client.request(method, table, params=params, json=json, headers=headers)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                logger.warning("rest %s %s connect failed type=%s attempt=%s", method, table, type(exc).__name__, i + 1)
                if i + 1 < attempts:
                    continue
                raise _unavailable() from None
            except httpx.HTTPError as exc:  # 读超时等：GET 也不重试，避免叠加等待
                logger.error("rest %s %s failed type=%s", method, table, type(exc).__name__)
                raise _unavailable() from None
            if resp.status_code >= 500:
                logger.warning("rest %s %s status=%s attempt=%s", method, table, resp.status_code, i + 1)
                if i + 1 < attempts:
                    continue
                raise _unavailable()
            return resp
        raise _unavailable()  # pragma: no cover  循环总会 return 或 raise

    def _check(self, resp: httpx.Response, method: str, table: str, ok: tuple[int, ...] = (200, 201, 204)) -> None:
        if resp.status_code in ok:
            return
        # 网关错误体形如 {"code":"MISSING_CREDENTIALS","message":"...","requestId":"..."}（已实测）。
        # 只记状态码、网关错误码和 requestId（便于找腾讯云排查）；message 不记也不转给用户（可能含请求内容）
        code = request_id = ""
        try:
            body = resp.json()
            if isinstance(body, dict):
                code = str(body.get("code", ""))[:64]
                request_id = str(body.get("requestId", ""))[:64]
        except ValueError:
            pass
        logger.error("rest %s %s status=%s code=%s request_id=%s", method, table, resp.status_code, code, request_id)
        if resp.status_code in (401, 403):  # Key 错 / 无权限：属于服务端配置问题
            raise _unavailable()
        raise _bad_response()

    def _rows(self, resp: httpx.Response) -> list[dict]:
        try:
            data = resp.json()
        except ValueError:
            data = None
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            logger.error("rest response is not a json array")
            raise _bad_response()
        return data

    # ---------- 与 SqlRepository 相同的接口 ----------

    def ping(self) -> None:
        resp = self._request("GET", T_GEN, params={"select": "id", "limit": "1"})
        self._check(resp, "GET", T_GEN)

    def touch_user(self, label: str, now: datetime) -> None:
        """登录成功：已有用户 → 更新 last_login_at；没有 → 新建。并发首次登录撞唯一约束（409）视为已建好。"""
        resp = self._request("PATCH", T_USER, params={"label": f"eq.{label}"}, json={"last_login_at": _iso(now)},
                             headers={"Prefer": "return=representation"})
        self._check(resp, "PATCH", T_USER)
        if self._rows(resp):
            return
        resp = self._request("POST", T_USER, json={"label": label, "created_at": _iso(now), "last_login_at": _iso(now)},
                             headers={"Prefer": "return=minimal"})
        if resp.status_code == 409:
            return
        self._check(resp, "POST", T_USER)

    def save_generation(self, *, owner_id: str, topic: str, audience: str, titles: list[dict], status: str,
                        attempts: int, model: str, now: datetime | None = None) -> GenerationRecord:
        body = {"schema_version": SCHEMA_VERSION, "owner_id": owner_id, "topic": topic, "audience": audience,
                "titles": titles, "status": status, "attempts": attempts, "model": model,
                "created_at": _iso(now or datetime.now(timezone.utc))}
        resp = self._request("POST", T_GEN, params={"select": GEN_COLUMNS}, json=body,
                             headers={"Prefer": "return=representation"})
        self._check(resp, "POST", T_GEN)
        rows = self._rows(resp)
        if len(rows) != 1:
            logger.error("rest insert returned rows=%s", len(rows))
            raise _bad_response()
        return _record(rows[0])

    def list_generations(self, owner_id: str, limit: int = 20) -> list[GenerationRecord]:
        resp = self._request("GET", T_GEN, params={"select": GEN_COLUMNS, "owner_id": f"eq.{owner_id}",
                                                   "order": "created_at.desc,id.desc", "limit": str(int(limit))})
        self._check(resp, "GET", T_GEN)
        return [_record(r) for r in self._rows(resp)]

    def get_generation(self, owner_id: str, gen_id: int) -> GenerationRecord | None:
        row = self.get_generation_by_id(gen_id)
        return row if row is not None and row.owner_id == owner_id else None

    def get_generation_by_id(self, gen_id: int) -> GenerationRecord | None:
        """不按用户过滤，只给接口层区分 404 / 403（与 SQL 实现一致）。"""
        resp = self._request("GET", T_GEN, params={"select": GEN_COLUMNS, "id": f"eq.{int(gen_id)}", "limit": "1"})
        self._check(resp, "GET", T_GEN)
        rows = self._rows(resp)
        return _record(rows[0]) if rows else None

    def count_generations_today(self, owner_id: str, now: datetime | None = None) -> int:
        from app.services.repository import start_of_today_utc
        resp = self._request("GET", T_GEN, params={"select": "id", "owner_id": f"eq.{owner_id}",
                                                   "created_at": f"gte.{_iso(start_of_today_utc(now))}", "limit": "1"},
                             headers={"Prefer": "count=exact"})
        self._check(resp, "GET", T_GEN, ok=(200, 206))
        try:
            return parse_content_range_total(resp.headers.get("content-range"))
        except ValueError:
            logger.error("rest count missing exact total")
            raise _bad_response() from None


# ---------- 模块级单例：整个进程共用一个连接池 ----------

_repo: RestRepository | None = None
_lock = threading.Lock()


def check_config(settings: Settings) -> None:
    missing = []
    if not settings.cloudbase_api_key:
        missing.append("CLOUDBASE_API_KEY")
    if not settings.cloudbase_rest_url:
        missing.append("CLOUDBASE_ENV_ID（或 CLOUDBASE_REST_URL）")
    if missing:
        raise RestConfigError("DATA_BACKEND=cloudbase_rest 但缺少环境变量：" + "、".join(missing)
                              + "。请在云托管控制台的环境变量里填写后重新部署")
    if not settings.cloudbase_rest_url.startswith("https://"):
        raise RestConfigError("CLOUDBASE_REST_URL 必须以 https:// 开头（API Key 不能走明文 http）")


def init_rest(settings: Settings, transport: httpx.BaseTransport | None = None) -> RestRepository:
    """服务启动时调用：配置不全直接抛错，服务起不来（比上线后才发现存不了数据好）。"""
    global _repo
    check_config(settings)
    with _lock:
        if _repo is not None:
            _repo.close()
        _repo = RestRepository(settings.cloudbase_rest_url, settings.cloudbase_api_key, transport=transport)
    logger.info("db ready backend=cloudbase_rest")
    return _repo


def get_rest_repo(settings: Settings) -> RestRepository:
    if _repo is None:
        return init_rest(settings)
    return _repo


def reset_rest() -> None:
    global _repo
    with _lock:
        if _repo is not None:
            _repo.close()
        _repo = None

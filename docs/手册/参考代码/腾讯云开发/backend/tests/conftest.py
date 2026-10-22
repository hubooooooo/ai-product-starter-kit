"""测试一律 mock 模型、用临时数据库，离线可跑，不碰 data/app.db，也不连真实云数据库。

数据层两种实现跑同一套接口测试（部署手册第六节）：
- sql：SQLAlchemy + 临时 SQLite 文件
- rest：DATA_BACKEND=cloudbase_rest，网关换成内存里的假 PostgREST（FakeGateway，httpx.MockTransport）
"""
from __future__ import annotations

import json
from datetime import datetime
from urllib.parse import parse_qsl

import httpx
import pytest
from fastapi.testclient import TestClient

GOOD = {"titles": [
    {"style": "数字型", "text": "3分钟搞定的低卡早餐"},
    {"style": "提问型", "text": "低卡早餐真的吃不饱吗？"},
    {"style": "反差型", "text": "越吃越瘦的早餐长这样"},
    {"style": "情绪型", "text": "终于找到不挨饿的早餐了"},
    {"style": "干货型", "text": "低卡早餐搭配公式收好"},
]}

# backend/.env 里可能有的变量：测试前一律清掉，避免本机配置影响测试（也避免测试连到真实云数据库）
_ENV_TO_CLEAR = ["DATA_BACKEND", "CLOUDBASE_ENV_ID", "CLOUDBASE_API_KEY", "CLOUDBASE_REST_URL", "REQUIRE_SERVER_DB",
                 "REQUIRE_LOGIN", "INVITE_CODES", "SESSION_SECRET", "COOKIE_SECURE", "SESSION_MAX_AGE_DAYS",
                 "PROXY_HOPS", "CLIENT_IP_HEADER", "PROXY_SHARED_SECRET", "DAILY_GENERATION_LIMIT"]

FAKE_GATEWAY_KEY = "fake-gateway-key-for-tests-only"


class FakeClient:
    """按顺序返回预设文本；可抛出预设异常。记录调用次数和收到的 prompt。"""
    model_name = "fake-model"

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def complete(self, prompt):
        from app.services.model_client import ModelReply
        self.prompts.append(prompt)
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return ModelReply(text=item, model=self.model_name, latency_ms=1)


def _ts(v: str) -> datetime:
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


class FakeGateway:
    """内存版 PostgREST，只实现本产品用到的语法：select / eq / gte / order / limit / count=exact /
    POST return=representation|minimal / PATCH；users.label 唯一（重复返回 409）。"""

    def __init__(self, key: str = FAKE_GATEWAY_KEY) -> None:
        self.key = key
        self.tables: dict[str, list[dict]] = {"generations": [], "users": []}
        self.next_id = {"generations": 1, "users": 1}
        self.calls: list[tuple[str, str]] = []
        self.fail_next: list[int] = []  # 预设接下来几次返回的状态码（测试重试 / 错误映射）

    def _filter(self, rows, params):
        out = rows
        for k, v in params:
            if k in ("select", "order", "limit"):
                continue
            op, _, val = v.partition(".")
            if op == "eq":
                out = [r for r in out if str(r.get(k)) == val]
            elif op == "gte":
                out = [r for r in out if _ts(r[k]) >= _ts(val)]
            else:
                raise AssertionError(f"FakeGateway 不支持的条件 {k}={v}")
        return out

    def handler(self, request: httpx.Request) -> httpx.Response:
        table = request.url.path.rstrip("/").rsplit("/", 1)[-1]
        self.calls.append((request.method, table))
        if request.headers.get("authorization") != f"Bearer {self.key}":
            return httpx.Response(401, json={"code": "MISSING_CREDENTIALS", "message": "x", "requestId": "r1"})
        if self.fail_next:
            return httpx.Response(self.fail_next.pop(0), json={"code": "INJECTED", "message": "x", "requestId": "r2"})
        params = parse_qsl(request.url.query.decode())
        rows = self.tables[table]
        prefer = request.headers.get("prefer", "")
        if request.method == "GET":
            got = self._filter(rows, params)
            order = dict(params).get("order")
            if order:
                for part in reversed(order.split(",")):
                    col, _, direction = part.partition(".")
                    key = (lambda r, c=col: _ts(r[c])) if col == "created_at" else (lambda r, c=col: r[c])
                    got = sorted(got, key=key, reverse=direction == "desc")
            total = len(got)
            if "limit" in dict(params):
                got = got[: int(dict(params)["limit"])]
            headers = {}
            if "count=exact" in prefer:
                headers["content-range"] = f"0-{len(got) - 1}/{total}" if got else f"*/{total}"
            return httpx.Response(200, json=[dict(r) for r in got], headers=headers)
        if request.method == "POST":
            body = json.loads(request.content)
            if table == "users" and any(r["label"] == body["label"] for r in rows):
                return httpx.Response(409, json={"code": "23505", "message": "dup", "requestId": "r3"})
            row = {"id": self.next_id[table], **body}
            self.next_id[table] += 1
            rows.append(row)
            if "return=representation" in prefer:
                return httpx.Response(201, json=[dict(row)])
            return httpx.Response(201)
        if request.method == "PATCH":
            body = json.loads(request.content)
            got = self._filter(rows, params)
            for r in got:
                r.update(body)
            return httpx.Response(200, json=[dict(r) for r in got])
        return httpx.Response(405)


@pytest.fixture()
def good_json():
    return json.dumps(GOOD, ensure_ascii=False)


@pytest.fixture(params=["sql", "rest"])
def backend(request):
    return request.param


@pytest.fixture()
def app_env(tmp_path, monkeypatch, backend):
    for name in _ENV_TO_CLEAR:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("MODEL_API_KEY", "")
    from app.core import db
    from app.services import rest_repository
    from app.services.auth import login_limiter
    db._engine = None
    db._SessionLocal = None
    rest_repository.reset_rest()
    login_limiter.reset()
    gateway = None
    if backend == "rest":
        monkeypatch.setenv("DATA_BACKEND", "cloudbase_rest")
        monkeypatch.setenv("CLOUDBASE_ENV_ID", "test-env")
        # 万一假网关没注入上，请求会打到不存在的域名而失败，绝不会连到真实云数据库
        monkeypatch.setenv("CLOUDBASE_REST_URL", "https://fake-gateway.invalid/v1/rdb/rest")
        monkeypatch.setenv("CLOUDBASE_API_KEY", FAKE_GATEWAY_KEY)
        gateway = FakeGateway()
        from app.core.config import get_settings
        rest_repository.init_rest(get_settings(), transport=httpx.MockTransport(gateway.handler))
    from app.main import app
    app.dependency_overrides.clear()
    app.state.fake_gateway = gateway
    yield app
    app.dependency_overrides.clear()
    rest_repository.reset_rest()
    login_limiter.reset()


@pytest.fixture()
def make_client(app_env):
    from app.services.model_client import get_model_client

    def _make(replies):
        fake = FakeClient(replies)
        app_env.dependency_overrides[get_model_client] = lambda: fake
        return TestClient(app_env), fake
    return _make


@pytest.fixture()
def repo(app_env):
    """直接拿当前后端的 repository（测试里造"别人的数据"用）。"""
    from app.core.config import get_settings
    from app.core import db

    def _get():
        if get_settings().data_backend == "cloudbase_rest":
            from app.services.rest_repository import get_rest_repo
            return get_rest_repo(get_settings())
        from app.services.repository import SqlRepository
        if db._SessionLocal is None:
            db.init_db()
        return SqlRepository(db._SessionLocal())
    return _get

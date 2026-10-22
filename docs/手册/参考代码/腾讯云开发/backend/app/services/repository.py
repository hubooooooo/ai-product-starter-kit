"""数据读写。所有查询都按 owner_id 过滤（权限判断在后端）。

两种实现，接口相同（见 Repository）：
- SqlRepository：SQLAlchemy，本地 SQLite / DATABASE_URL 指向的 PostgreSQL（默认，DATA_BACKEND=sql）
- RestRepository：腾讯云开发 PostgreSQL 的 HTTPS 网关（DATA_BACKEND=cloudbase_rest，见 rest_repository.py）
接口层只通过 get_repo 依赖拿实现，不关心是哪一种。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from fastapi import Depends
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_session
from app.models.generation import SCHEMA_VERSION, Generation
from app.models.user import User


def save_generation(session: Session, *, owner_id: str, topic: str, audience: str, titles: list[dict],
                    status: str, attempts: int, model: str) -> Generation:
    row = Generation(schema_version=SCHEMA_VERSION, owner_id=owner_id, topic=topic, audience=audience,
                     titles=titles, status=status, attempts=attempts, model=model)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def list_generations(session: Session, owner_id: str, limit: int = 20) -> list[Generation]:
    stmt = (select(Generation).where(Generation.owner_id == owner_id)
            .order_by(Generation.created_at.desc(), Generation.id.desc()).limit(limit))
    return list(session.scalars(stmt))


def get_generation(session: Session, owner_id: str, gen_id: int) -> Generation | None:
    stmt = select(Generation).where(Generation.owner_id == owner_id, Generation.id == gen_id)
    return session.scalars(stmt).first()


def get_generation_by_id(session: Session, gen_id: int) -> Generation | None:
    """不按用户过滤，只给接口层用来区分"不存在"(404) 和"不是你的"(403)。"""
    return session.get(Generation, gen_id)


# 每日上限按北京时间自然日计算（中国无夏令时，固定 UTC+8，不依赖系统时区数据）
DAY_TZ = timezone(timedelta(hours=8))


def start_of_today_utc(now: datetime | None = None) -> datetime:
    """返回带时区的 UTC 时间。PostgreSQL 的 timestamptz 按绝对时刻比较；SQLite 存的是 UTC 数字，
    带时区的值写入/比较时同样按 UTC 数字处理。不能传不带时区的值：PostgreSQL 会按数据库时区去理解它。"""
    now = now or datetime.now(timezone.utc)
    local_midnight = now.astimezone(DAY_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(timezone.utc)


def count_generations_today(session: Session, owner_id: str, now: datetime | None = None) -> int:
    stmt = select(func.count(Generation.id)).where(Generation.owner_id == owner_id,
                                                  Generation.created_at >= start_of_today_utc(now))
    return int(session.scalar(stmt) or 0)


# ---------------- 统一接口 ----------------

class Repository(Protocol):
    def ping(self) -> None: ...
    def touch_user(self, label: str, now: datetime) -> None: ...
    def save_generation(self, *, owner_id: str, topic: str, audience: str, titles: list[dict], status: str,
                        attempts: int, model: str) -> Any: ...
    def list_generations(self, owner_id: str, limit: int = 20) -> list: ...
    def get_generation(self, owner_id: str, gen_id: int) -> Any: ...
    def get_generation_by_id(self, gen_id: int) -> Any: ...
    def count_generations_today(self, owner_id: str, now: datetime | None = None) -> int: ...


class SqlRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def ping(self) -> None:
        self.session.execute(text("SELECT 1")).scalar_one()

    def touch_user(self, label: str, now: datetime) -> None:
        user = self.session.scalars(select(User).where(User.label == label)).first()
        if user is None:
            self.session.add(User(label=label, created_at=now, last_login_at=now))
        else:
            user.last_login_at = now
        try:
            self.session.commit()
        except IntegrityError:  # 同一标签并发首次登录：另一请求已建好用户记录，不影响本次登录
            self.session.rollback()

    def save_generation(self, **kw) -> Generation:
        return save_generation(self.session, **kw)

    def list_generations(self, owner_id: str, limit: int = 20) -> list[Generation]:
        return list_generations(self.session, owner_id, limit)

    def get_generation(self, owner_id: str, gen_id: int) -> Generation | None:
        return get_generation(self.session, owner_id, gen_id)

    def get_generation_by_id(self, gen_id: int) -> Generation | None:
        return get_generation_by_id(self.session, gen_id)

    def count_generations_today(self, owner_id: str, now: datetime | None = None) -> int:
        return count_generations_today(self.session, owner_id, now)


def get_repo(session: Session | None = Depends(get_session)) -> Repository:
    """FastAPI 依赖：按 DATA_BACKEND 返回实现。cloudbase_rest 时 get_session 给的是 None。"""
    settings = get_settings()
    if settings.data_backend == "cloudbase_rest":
        from app.services.rest_repository import get_rest_repo
        return get_rest_repo(settings)
    return SqlRepository(session)

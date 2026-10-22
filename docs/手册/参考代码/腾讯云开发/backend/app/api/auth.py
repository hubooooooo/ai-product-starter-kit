"""接口：邀请码登录 / 退出 / 当前用户；以及所有数据接口共用的 current_owner 依赖。

REQUIRE_LOGIN=1：数据接口必须带有效会话，否则 401；记录按登录用户（邀请码标签）隔离。
REQUIRE_LOGIN 未开启：本机验收模式，所有记录归属 "local"，不需要登录。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app.core.config import DEFAULT_OWNER_ID, Settings, get_settings
from app.core.errors import AppError
from app.services.repository import Repository, get_repo
from app.services.auth import (PROXY_CLIENT_IP_HEADER, PROXY_SECRET_HEADER, SESSION_COOKIE, client_ip,
                               login_limiter, make_session, match_invite_code, proxied_client_ip, read_session)

logger = logging.getLogger("app.auth")
router = APIRouter()


class LoginRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=64, description="邀请码")


class MeOut(BaseModel):
    require_login: bool
    logged_in: bool
    user: str | None = Field(None, description="登录用户的标签；未登录或本机模式为 null")


class OkOut(BaseModel):
    ok: bool = True


def current_owner(request: Request) -> str:
    settings = get_settings()
    if not settings.require_login:
        return DEFAULT_OWNER_ID
    label = read_session(settings, request.cookies.get(SESSION_COOKIE))
    if label is None:
        raise AppError("UNAUTHORIZED", "请先输入邀请码登录", 401)
    return label


def _set_cookie(response: Response, settings: Settings, value: str) -> None:
    response.set_cookie(SESSION_COOKIE, value, max_age=settings.session_max_age_seconds, path="/",
                        httponly=True, samesite="lax", secure=settings.cookie_secure)


@router.post("/login", response_model=MeOut)
def login(body: LoginRequest, request: Request, response: Response,
          repo: Repository = Depends(get_repo)) -> MeOut:
    settings = get_settings()
    if not settings.auth_configured:
        logger.error("login unavailable: INVITE_CODES or SESSION_SECRET not configured")
        raise AppError("AUTH_NOT_CONFIGURED", "登录功能还没配置好，请联系管理员", 503)
    ip = client_ip(settings, request.client.host if request.client else None,
                   request.headers.get("x-forwarded-for"),
                   request.headers.get(settings.client_ip_header) if settings.client_ip_header else None,
                   proxied_client_ip(settings, request.headers.get(PROXY_SECRET_HEADER),
                                     request.headers.get(PROXY_CLIENT_IP_HEADER)))
    left = login_limiter.locked_seconds_left(ip)
    if left:
        raise AppError("LOGIN_LOCKED", f"输错次数太多，请 {max(1, (left + 59) // 60)} 分钟后再试", 429)
    label = match_invite_code(settings, body.code.strip())
    if label is None:
        remaining = login_limiter.record_failure(ip)
        logger.warning("login failed remaining=%s", remaining)
        if remaining == 0:
            raise AppError("LOGIN_LOCKED", "输错次数太多，请 15 分钟后再试", 429)
        raise AppError("INVALID_CODE", f"邀请码不对，还可以再试 {remaining} 次", 401)
    login_limiter.record_success(ip)
    repo.touch_user(label, datetime.now(timezone.utc))  # 有则更新最近登录时间，无则新建
    _set_cookie(response, settings, make_session(settings, label, body.code.strip()))
    logger.info("login ok user=%s", label)
    return MeOut(require_login=settings.require_login, logged_in=True, user=label)


@router.post("/logout", response_model=OkOut)
def logout(response: Response) -> OkOut:
    settings = get_settings()
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax", secure=settings.cookie_secure)
    return OkOut()


@router.get("/me", response_model=MeOut)
def me(request: Request) -> MeOut:
    settings = get_settings()
    label = read_session(settings, request.cookies.get(SESSION_COOKIE))
    return MeOut(require_login=settings.require_login, logged_in=label is not None, user=label)

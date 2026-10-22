# 腾讯云开发 云托管（CloudBase Run）镜像。构建目录 = backend/。
# REQUIRE_SERVER_DB=1：容器里不许用 SQLite（实例重启会丢数据）。满足其一才能启动：
#   DATA_BACKEND=cloudbase_rest（经云开发 HTTPS 网关读写，需 CLOUDBASE_ENV_ID + CLOUDBASE_API_KEY），
#   或 DATABASE_URL 指向 PostgreSQL。
# 服务端口：读平台注入的 PORT，没有则用 8080；云托管控制台里的"服务端口"要填同一个值（8080）。
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai \
    REQUIRE_SERVER_DB=1 \
    CLIENT_IP_HEADER=x-envoy-external-address

WORKDIR /app

# 只装运行依赖（测试工具在 requirements-dev.txt，不进镜像）。国内构建慢时可加 -i 镜像源
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY static ./static

# 非 root 运行
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

EXPOSE 8080
# 用 sh -c 才能展开 ${PORT:-8080}；exec 让 uvicorn 成为 1 号进程，能收到平台的停止信号
CMD ["sh", "-c", "exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]

-- 001_init.sql —— 小红书标题助手 建表（PostgreSQL，可重复执行）
--
-- 用途：DATA_BACKEND=cloudbase_rest 时，服务不连数据库驱动、不会自动建表，需要先由 AI 用命令行执行一次本文件：
--       tcb db execute -e <环境ID> --sql "$(grep -v '^--' backend/migrations/001_init.sql)"
-- 结构与 app/models/user.py、app/models/generation.py 完全一致（与 SQLAlchemy create_all 生成的表相同）：
--       表名、列名、类型、长度、可空性、主键、唯一约束、索引。改模型时必须同步新增 002_*.sql，不要改本文件。
-- 时间戳和 schema_version 由应用写入（UTC）；id 由数据库自增（SERIAL）。
-- 表名：演练环境里只有这一个产品，所以没加前缀。新产品照抄时改成 <英文短名>_users、<英文短名>_generations：
--       同一个云开发环境会放多个产品、共用一个数据库（部署手册第六节）。
--
-- 权限：两张表都开启行级安全（RLS），并且【不】给 anon / authenticated 等浏览器侧角色建任何策略
--       → 用 Publishable Key 或用户 AccessToken 从浏览器调网关，读写都拿不到任何行。
--       后端用的服务端 API Key（管理员权限）会绕过 RLS：2026-10-22 已实测——表开启 RLS 且无任何策略时，
--       带服务端 API Key 的 GET 返回 200 并拿到行；不带 Authorization 返回 401（MISSING_CREDENTIALS）。
--       每次新环境部署后仍要复查一遍：
--         1) 后端 /api/health 返回 {"status":"ok"}，登录、生成、历史都正常（API Key 能读写，含插入时用到的自增序列）；
--         2) 用 Publishable Key 请求 GET .../v1/rdb/rest/generations?select=id&limit=1，应拿不到任何行或被拒。
--       如果 1) 失败，不要关闭 RLS，改为只给 API Key 对应的数据库角色加策略。

CREATE TABLE IF NOT EXISTS users (
    id            SERIAL                   NOT NULL,
    label         VARCHAR(64)              NOT NULL,
    created_at    TIMESTAMP WITH TIME ZONE NOT NULL,
    last_login_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (label)
);

CREATE TABLE IF NOT EXISTS generations (
    id             SERIAL                   NOT NULL,
    schema_version INTEGER                  NOT NULL,
    owner_id       VARCHAR(64)              NOT NULL,
    topic          TEXT                     NOT NULL,
    audience       VARCHAR(64)              NOT NULL,
    titles         JSON                     NOT NULL,
    status         VARCHAR(16)              NOT NULL,
    attempts       INTEGER                  NOT NULL,
    model          VARCHAR(128)             NOT NULL,
    created_at     TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_generations_owner_id ON generations (owner_id);
CREATE INDEX IF NOT EXISTS ix_generations_owner_id_created_at ON generations (owner_id, created_at);

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE generations ENABLE ROW LEVEL SECURITY;

# 参考代码：上线到腾讯云开发 CloudBase

这些文件来自 2026-10-22 上线演练的产品"小红书标题助手"（输入笔记主题，生成 5 个标题，带邀请码登录和历史记录），在腾讯云开发免费体验版上**实测部署并通过外网验收**。部署手册各步骤引用的就是这里的实现。

**用法**：照着改，不要从零写。表名、字段名、业务接口按自己产品替换；登录、限流、数据网关、代理转发、打包这几块的做法保持不变。复制进产品文件夹后，按通用手册的双层验收补齐测试，`verify.sh` 全部通过再部署。

| 文件 | 做什么 | 对应部署手册 | 需要按产品改的地方 |
| --- | --- | --- | --- |
| `set_cloudrun_env.py` | 给云托管服务写入环境变量和规格，用最新镜像重新发布，等待结果；密钥只从本地文件读，输出打码 | 第九节、第十节前端部分 | 不用改，按开头注释传参 |
| `backend/app/services/repository.py` | 数据访问接口 + 按 `DATA_BACKEND` 选实现（本地 SQLAlchemy / 线上网关） | 第六节 | 方法名和字段换成自己产品的 |
| `backend/app/services/rest_repository.py` | 经 `https://<环境ID>.api.tcloudbasegateway.com/v1/rdb/rest` 读写 PostgreSQL：服务端 API Key、超时、只对读请求重试、计数、错误转统一结构且不泄露 Key | 第六节 | 表名、字段、查询条件 |
| `backend/migrations/001_init.sql` | 可重复执行的建表语句；开 RLS 不建策略 | 第六节 | 表结构 |
| `backend/app/services/auth.py` | 邀请码匹配、会话签名、登录失败限流、来源 IP 判定（`x-envoy-external-address`；前端代理带 `x-client-ip` + 共享密钥时才信任） | 第十一节、第十节前端部分 | 一般不用改 |
| `backend/app/api/auth.py` | 登录 / 退出 / 当前用户接口，HttpOnly Cookie | 第十一节 | 一般不用改 |
| `backend/Dockerfile`、`.dockerignore` | 云托管镜像：`python:3.12-slim`、非 root、监听 `${PORT:-8080}`、`REQUIRE_SERVER_DB=1`、`CLIENT_IP_HEADER` | 第七节 | 依赖文件名、启动模块 |
| `backend/.env.example` | 后端全部环境变量名和说明（不含值） | 第九节 | 增删业务变量 |
| `backend/tests/conftest.py` | 同一套接口测试分别跑本地 SQLite 和"内存假网关"两种实现；测试开始时清掉 `DATA_BACKEND` 等变量，避免误连真实云库 | 第六节 | 夹具里的表和字段 |
| `frontend/proxy.ts`、`lib/proxy/forward.ts` | Next.js 16 运行时代理：`/api/*` 转发到 `BACKEND_URL`，带回 Set-Cookie，写入真实 IP 和共享密钥，超时与错误返回统一结构 | 第十节前端部分；前端手册 12.5 | 一般不用改 |
| `frontend/next.config.ts`、`Dockerfile`、`.dockerignore`、`.env.example` | `output: "standalone"`、多阶段构建、`node server.js`、端口 3000 | 第十节前端部分 | 一般不用改 |

另有 `给产品经理的上线指引-范例.md`：验证时由另一个 AI 只读手册写出的"发给产品经理的每段话"，覆盖注册实名、开通环境、启用云托管、填密钥、授权、费用确认、发邀请码、验收清单。AI 带产品经理上线时可参照它的语气和颗粒度，环境名、网址按实际替换。

注意：

- 这里只是关键文件，不是完整项目；所依赖的配置读取（`app/core/config.py`）、统一错误（`app/core/errors.py`）等按通用手册自己的项目结构实现，名字对不上时以自己的项目为准。
- 任何地方都不要打印或返回完整请求头：云托管注入的 `x-cloudbase-context` 里有平台临时凭证（部署手册第十二节）。
- 平台接口或页面变了，以 `tcb ... --help` 和控制台为准，并回来更新这里和部署手册。

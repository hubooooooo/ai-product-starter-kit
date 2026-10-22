# AI Agent 产品上线部署手册 V2.0（腾讯云开发 CloudBase 版）

> **阅读分工**：本手册由 AI 在"阶段 4 上线"和"阶段 5 收尾"读取。产品经理不读本手册，只按 AI 当时给出的"照着点"清单操作，最后照第六部分验收清单打勾。
>
> 本手册与工具包根目录 `AGENTS.md` 冲突时，以 `AGENTS.md` 为准；AI 发现冲突必须当场指出。路径约定见 `AGENTS.md` 第 9 节：`backend/`、`docs/` 等都指产品文件夹 `projects/<产品名>/` 里的。

## 这份手册有什么用

把已验收的后端（和前端）变成任何人都能打开的 https 网址，带登录、数据隔离、数据不丢、出问题能查。

默认路线是**腾讯云开发 CloudBase**：一个"环境"里自带云托管（跑程序）、PostgreSQL 数据库、云存储和平台分配的 https 网址，不需要自有域名，也就不用办 ICP 备案。个人实名认证即可，不需要企业认证。

### 版本说明

- **V2.0（2026-10-22）**：默认平台从火山引擎 veFaaS 换成腾讯云开发。依据是 2026-10-22 的一次完整上线演练（产品"小红书标题助手"，从注册账号到外网验收全部实测）。火山引擎路线需要企业认证才有云数据库，个人用户只能走"常驻实例 + 自动备份"的过渡档，步骤多、每月常驻费用约一两百元；云开发个人认证即可用自带数据库，免费体验版 0 元。本版删除过渡档、企业认证分档和火山引擎专属步骤。
- **V1.2 及以前**：火山引擎 veFaaS 路线，见 Git 历史。

### 适用范围与已知边界

- 适用：MVP 上线给小范围用户试用（几十人以内）；后端为 Python FastAPI 容器，前端为 Next.js（可选）。
- 不在范围：自有域名与备案、对公众正式运营、高并发。
- **默认网址的提示页**：平台分配的是测试域名。浏览器第一次打开时，腾讯云会先显示"页面访问提示"（"测试域名，仅供开发测试使用……请勿泄露个人信息、账号密码"），等 3 秒点「确定访问」才进入产品；命令行请求看不到它。只有绑定已备案的自有域名才能去掉。AI 必须在发网址时提前告诉产品经理，并请他转告每位试用者"看到提示点确定访问，这不是出错"。
- **待实测**（照做时如与实际不符，以控制台和 `tcb ... --help` 为准，并把差异记进 `docs/项目状态.md`）：云存储（文件上传）；日志告警；免费额度的真实消耗速度。
- 参考代码：`docs/手册/参考代码/腾讯云开发/`，是本手册各步骤在演练产品里实测通过的实现，照着改，不要从零写。

---

## 分工：产品经理做什么，AI 做什么

| 事项 | 谁做 | 说明 |
| --- | --- | --- |
| 注册腾讯云、实名认证、开通云开发环境、启用云托管 | 产品经理 | AI 给"照着点"清单（第一部分），每步看到的页面截图给 AI |
| 创建服务端 API Key | 产品经理 | 在控制台创建后**自己粘贴进 AI 建好的本地文件**，不贴进对话 |
| 浏览器授权命令行登录 | 产品经理 | AI 执行登录命令后浏览器弹出授权页，核对用户码、点授权 |
| 费用确认 | 产品经理 | 任何会扣钱的选择（升级套餐、充值），AI 先说清金额，产品经理回复"确认"后才动 |
| 建表、写线上配置、部署、排错、验收测试 | AI | 全部用命令行完成 |

### 部署类命令需要产品经理授权

部署、删除服务、写线上配置都会改动产品经理云账号里对外可访问的资源。编码工具（如 Claude Code）可能拦下这类命令并要求确认。AI 遇到拦截时：说明这一步会做什么、花不花钱、怎么撤销，请产品经理明确同意；产品经理同意后可以把这类命令加入工具的允许名单。不得绕过拦截。

---

## 费用（以控制台当时显示为准）

| 套餐 | 价格 | 资源 | 适合 |
| --- | --- | --- | --- |
| 免费体验版 | 0 元，一次 6 个月，到期前 1 个月内可续 6 个月 | 每月 3000 资源点（1000 点 = 1 元）；**不支持加购和超额付费，用完即停，不会产生欠费** | 开发验收、小范围试用（默认） |
| 个人版 | 19.9 元/月（2026-10 限时价，原价 39.9） | 每月 4 万资源点，可加购、可超额按量付费 | 每天都有人用、免费额度不够时 |

- **每个账号只能有一个免费体验版环境**，删了就没有了。
- 消耗估算（按官方单价折算，**待用量统计核实**）：云托管 0.25 核 / 0.5 GB 规格运行时约 30 点/小时；实例数最小设为 0 时，只有处理请求的时间才计费。数据库按使用时间计。模型调用费用在模型厂商那边单独计，不占资源点。
- 用量查看：控制台左侧「套餐用量」，或 AI 执行 `tcb env usage -e <环境ID>`。统计最多延迟 2 天。
- **搭配购买是推销**：下单页底部"搭配购买"里的存储、数据库、DDoS 等都另外收费，一律不勾。

---

# 第一部分：云平台准备（产品经理照着点，AI 引导）

> AI 把下表逐步转述给产品经理，每步请对方截图回来核对。2026-10-22 实测的页面如下；页面改版时以截图为准，看不懂的地方 AI 先查再答，不让产品经理猜。

## 一、注册与实名

| 步骤 | 去哪 / 点什么 | 看到什么算对 |
| --- | --- | --- |
| 1 注册 | `https://cloud.tencent.com/register`，选"微信扫码注册"，手机微信扫码确认 | 进入腾讯云控制台，右上角有头像 |
| 2 实名 | `https://console.cloud.tencent.com/developer/auth`，选"个人认证"，推荐"微信扫码认证"（用已实名的微信刷脸） | 显示已完成个人认证 |

注意：用微信或 QQ 登录过腾讯云的人可能**早就有账号**，而且可能有几分钱的历史欠费。有欠费时连 0 元订单也付不了（见第三步）。

## 二、开通云开发环境（免费体验版）

| 步骤 | 去哪 / 点什么 / 填什么 | 看到什么算对 |
| --- | --- | --- |
| 1 | 打开 `https://tcb.cloud.tencent.com/dev` | 云开发控制台，显示"暂无环境" |
| 2 | 点「新建环境」（会在新标签页打开购买页） | 看到套餐卡片：免费体验版 / 个人版 / 标准版 / 企业版 |
| 3 | 地域选 **上海**（新加坡不支持本手册的云托管 + PostgreSQL 组合）；环境名称填小写字母开头、只含小写字母数字和 `-`，如 `myapp-demo`；套餐选 **免费体验版** | 购买时长显示"免费试用 6 个月" |
| 4 | 数据库选 **PostgreSQL 数据库**（默认就是）。环境建好后**不能再换数据库类型** | PostgreSQL 卡片被选中 |
| 5 | 兑换码：鼠标移到输入框下方"关注公众号"，用微信扫码关注，在公众号里发"领取兑换码"，把收到的码粘进输入框 | 输入框不再标红 |
| 6 | 确认总金额 ¥0.00，点「立即购买」→ 确认订单页**底部搭配购买一个都不勾** → 「去支付」 | 支付成功 |
| 7 | 回到 `https://tcb.cloud.tencent.com/dev` | 环境列表里出现新环境，状态正常，套餐"体验版" |

**0 元订单报"账户余额不足，支付失败"**：账户有历史欠费。去费用中心订单管理 `https://console.cloud.tencent.com/deal`，对这笔"待支付"订单点「付款」，付款页会显示"账户欠费金额 X 元"。AI 把金额告诉产品经理、确认后用微信在线支付补齐即可，订单本身仍是 0 元。重复下单产生的多余待支付订单，等环境建好后再取消（先取消可能作废兑换码）。

## 三、启用云托管

| 步骤 | 去哪 / 点什么 | 看到什么算对 |
| --- | --- | --- |
| 1 | 云开发控制台左侧「云函数 / 托管」→ 中间栏「云托管」下的「服务管理」（不要点"创建服务"） | 页面底部有「启用云托管」按钮 |
| 2 | 勾选"我已知晓《腾讯云云开发服务条款》及云托管付费模式"，点「启用云托管」 | 弹出 CODING 第三方软件授权声明 |
| 3 | 点「同意并继续」（声明的是部署他人软件需有授权，部署自己的代码不涉及） | 出现"服务列表"，暂无服务 |

不启用就部署，命令会报"云托管资源未开通"。免费体验版下云托管用量从资源点里扣，不会另外扣账户余额。

## 四、创建服务端 API Key

后端程序读写数据库要用这把密钥（原因见第六节）。它有服务端权限，**只能放在后端，永远不能出现在前端代码里**。

| 步骤 | 去哪 / 点什么 | 看到什么算对 |
| --- | --- | --- |
| 1 | 控制台左下角「环境管理」→「API Key 配置」→ 下方"服务端 API Key"区域的「创建 API Key」（不是上方的"客户端 Publishable Key"） | 弹出"创建 API Key"窗口 |
| 2 | 名称用英文小写，如 `myapp-backend`；过期时间选 **180 天**（演练或临时测试选 30 天） | — |
| 3 | 点「创建」，复制弹出的密钥（通常只显示一次） | — |
| 4 | 用"文本编辑"打开 AI 指定的本地文件（`backend/.env`，Finder 里按 Command + Shift + 句号显示隐藏文件），粘到 `CLOUDBASE_API_KEY=` 后面，保存 | 回对话只说"填好了" |

**AI 做**：先建好 `backend/.env` 并用 `git check-ignore` 确认被忽略；产品经理填好后只检查长度，不打印值。到期前 2 周提醒产品经理按同样步骤新建一把，替换线上配置后删除旧的。

## 五、命令行登录（浏览器授权）

**AI 做**：安装 CLI 并在后台执行登录：

```bash
npm i -g @cloudbase/cli      # 本手册按 CloudBase CLI 3.8.7 实测
tcb login                    # 设备授权：输出一个授权链接和"用户码"，浏览器会自动打开
```

**产品经理照着点**：在弹出的授权页核对用户码与 AI 给的一致，点「授权」。AI 用 `tcb env list` 确认能看到环境（记下环境 ID，形如 `myapp-demo-1a2b3c4d...`）。

登录成功后 CLI 可能再问"是否收集使用数据"，后台运行时无法回答会直接退出，不影响登录结果。

---

# 第二部分：部署全流程（AI 为主）

## 六、数据怎么存：PostgreSQL + 平台网关

**为什么不直连数据库**：免费体验版的 PostgreSQL 是共享集群，控制台"内网地址"为空；开外网地址必须配安全组白名单，而免费版云托管没有固定出口 IP，只能对全网开放，等于把数据库暴露在公网上（控制台提示也明确"不建议"）。所以后端一律**通过平台的 HTTPS 网关读写数据库**：

- 地址：`https://<环境ID>.api.tcloudbasegateway.com/v1/rdb/rest/<表名>`，语法与 PostgREST 一致（`?select=`、`col=eq.值`、`order=created_at.desc`、`limit=`；写入加请求头 `Prefer: return=representation`；计数加 `Prefer: count=exact` 读 `Content-Range`）。
- 认证：请求头 `Authorization: Bearer <服务端 API Key>`。实测：服务端 API Key 不受行级安全（RLS）限制；不带 Key 返回 401 `MISSING_CREDENTIALS`。
- 网关报错形如 `{"code":"...","message":"...","requestId":"..."}`：后端日志只记 code 和 requestId，转换成产品统一错误结构后再返回，不把原文给用户。

**对开发阶段的要求**（通用手册第九节）：数据读写集中在一个 repository 层。本地开发和 mock 测试用 SQLAlchemy + SQLite；上线时用环境变量 `DATA_BACKEND=cloudbase_rest` 切到网关实现，两种实现跑同一套接口测试（参考 `参考代码/腾讯云开发/backend/tests/conftest.py`：网关实现用内存里的假网关跑）。

- `backend/.env` 里 **`DATA_BACKEND` 保持留空**：pytest 和重启检查也读这个文件，写成 `cloudbase_rest` 会让测试去连真实云库。本地连云库冒烟时只在那条命令前临时加 `DATA_BACKEND=cloudbase_rest`。
- 本地冒烟会把记录写进线上数据库：冒烟用的邀请码标签统一以 `smoke-` 开头，冒烟结束后删掉：`tcb db execute -e <环境ID> --sql "DELETE FROM <业务表> WHERE owner_id LIKE 'smoke-%'"`（表名、字段按产品改）。
- 在 Mac 上用 Python 访问本机服务返回 502 时，多半是系统代理在拦截：脚本里 httpx 加 `trust_env=False`，或设 `NO_PROXY=localhost,127.0.0.1`。

**建表**（AI 用命令行执行，不需要产品经理去控制台）：

```bash
tcb db execute -e <环境ID> --sql "SELECT 1"                                   # 连通性
tcb db execute -e <环境ID> --sql "$(grep -v '^--' backend/migrations/001_init.sql)"
```

迁移文件要求：`CREATE TABLE IF NOT EXISTS`，可重复执行；每张业务表 `ENABLE ROW LEVEL SECURITY` 且**不建任何策略**，这样浏览器端的 Publishable Key 读不到任何数据，后端的服务端 Key 不受影响。上线后复查每张表都已开启：`tcb db execute -e <环境ID> --sql "SELECT c.relname, c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind = 'r'"`，每行第二列都应为 `true`。

## 七、打包

后端目录放 `Dockerfile` 和 `.dockerignore`，云托管在云端构建镜像，本机不需要装 Docker。

- 基础镜像 `python:3.12-slim`；只装运行依赖（测试依赖单独放 `requirements-dev.txt`）；非 root 用户运行。
- 启动命令：`CMD ["sh", "-c", "exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]`，部署时 `--port 8080`。
- 镜像里设 `REQUIRE_SERVER_DB=1`：没配云端数据后端时程序拒绝启动，防止数据写进容器、重启就丢。
- 镜像里设 `CLIENT_IP_HEADER=x-envoy-external-address`（原因见第十一节）。
- `.dockerignore` 排除 `.venv`、`data`、`__pycache__`、`.pytest_cache`、`tests`、`.env` 与所有 `.env.*`（`.env.example` 除外）。

## 八、首次部署（建出服务）

```bash
cd backend
tcb cloudrun deploy -e <环境ID> -s <服务名> --source . --port 8080 \
  --min-num 0 --max-num 1 --open-access-types PUBLIC --force --wait
```

- 第一次部署会因为还没配线上配置而**启动失败**（`CreateVersion failed`，运行日志里是 `REQUIRE_SERVER_DB` 的报错）。这是预期内的：目的只是把服务建出来、构建出镜像。
- 查原因：`tcb cloudrun record list -e <环境ID> -s <服务名>` 拿 BuildId 和 RunId；构建日志 `tcb cloudrun logs build -e <环境ID> -s <服务名> --build-id <BuildId>`；运行日志 `tcb cloudrun logs process -e <环境ID> --run-id <RunId>`。构建日志最后是 `Image pushed successfully` 说明打包没问题。
- 服务的公网地址在 `tcb api tcbr DescribeCloudRunServerDetail --api-version 2022-02-17 --body '{"EnvId":"<环境ID>","ServerName":"<服务名>"}'` 返回的 `DefaultDomainName`，形如 `https://<服务名>-xxxx.sh.run.tcloudbase.com`。

## 九、写入线上配置（环境变量）

`tcb cloudrun deploy` 没有设置环境变量的参数。用云托管接口 `UpdateCloudRunServer` 一次性写入环境变量和规格，并用上一步构建出的镜像重新发布：

- 镜像地址：`tcb api tcbr DescribeCloudRunDeployRecord --api-version 2022-02-17 --body '{"EnvId":"<环境ID>","ServerName":"<服务名>"}'` 返回记录里的 `ImageUrl`（注意取**最新**一条）。
- 请求体：`{"EnvId", "ServerName", "DeployInfo": {"DeployType": "image", "ImageUrl": "<镜像地址>", "ReleaseType": "FULL"}, "Items": [...]}`，`Items` 的键名必须是：

| 键 | 写法 | 取值 |
| --- | --- | --- |
| `EnvParam`（没有 s） | `{"Key":"EnvParam","Value":"<JSON 字符串>"}` | 全部环境变量 |
| `CpuSpecs` | `FloatValue` | `0.25` |
| `MemSpecs` | `FloatValue` | `0.5` |
| `MinNum` / `MaxNum` | `IntValue` | `0` / `1` |
| `Port` | `IntValue` | `8080` |

  写成 `EnvParams`、`Cpu`、`Mem` 会被静默忽略，新版本照样启动失败。CLI 默认规格是 1 核 / 2 GB，会更快耗光免费额度，必须改小。
- **密钥不上命令行、不进对话**：AI 先生成 `backend/.env.secrets`（邀请码、会话密钥、前后端共享密钥，已被 `.gitignore` 忽略），再用参考脚本 `docs/手册/参考代码/腾讯云开发/set_cloudrun_env.py` 写入：它从 `backend/.env` 和 `backend/.env.secrets` 读取指定变量、自动取该服务最新镜像、提交后等待发布结果，输出里所有值打码。示例见脚本开头注释。
- 进度：`tcb api tcbr DescribeServerManageTask --api-version 2022-02-17 --body '{"EnvId","ServerName","TaskId":<返回的 TaskId>}'`，等到 `finished`；`failed` 时按第八节看运行日志。
- 写入后用 `DescribeCloudRunServerDetail` 核对 `EnvParams` 里的**变量名**齐全、规格正确，只看键名不打印值。
- **每次写入都是整组覆盖**：没列进去的变量会从线上消失。所以每次都按下面的清单把变量列全，不能只写要改的那一个。

**环境变量清单**（键名以本项目代码为准）：

| 变量 | 值 |
| --- | --- |
| `DATA_BACKEND` | `cloudbase_rest` |
| `CLOUDBASE_ENV_ID` / `CLOUDBASE_API_KEY` | 环境 ID / 服务端 API Key |
| `MODEL_API_KEY` / `MODEL_BASE_URL` / `MODEL_NAME` / `MODEL_TIMEOUT_SECONDS` | 模型配置；超时要大于最长一次模型调用 |
| `REQUIRE_LOGIN` | `1` |
| `INVITE_CODES` | `码1:标签1,码2:标签2`（第十节） |
| `SESSION_SECRET` | AI 生成的随机长串 |
| `COOKIE_SECURE` | `1` |
| `DAILY_GENERATION_LIMIT` | 每人每天模型调用上限，按决策台账 D4 换算并经产品经理确认 |
| `PROXY_SHARED_SECRET` | 有正式前端时：AI 生成的随机长串，前后端两个服务配同一个值（见第十节前端部分） |

## 十、更新版本（已上线后再发布）

```bash
./verify.sh <产品名>                     # 先在工具包根目录执行，全部通过再继续
cd projects/<产品名>/backend
tcb --yes cloudrun deploy -e <环境ID> -s <服务名> --source . --port 8080 \
  --min-num 0 --max-num 1 --open-access-types PUBLIC --force --wait
```

- 必须带全局参数 `--yes`：服务已存在时 CLI 会问"是否灰度发布"，不带 `--yes` 在后台运行会卡住退出；`--yes` 选默认项"不灰度，发布成功后自动切换"。
- 重新部署**保留**之前写入的环境变量和规格（实测）。要改环境变量时再按第九节用接口写。
- 上传代码包偶尔报 `socket hang up`，是网络抖动，重试即可。
- 发布后按第十一节从外网验证，不通过就回滚：`tcb cloudrun traffic --help` 查看切回旧版本的方法。

### 只上线后端、没有正式前端时

产品经理决定先用阶段 2 的临时验收页上线时（需在决策台账记录），验收页要补上邀请码登录框和 `<meta name="viewport">`，否则手机上没法用。正式前端做好后按下一小节部署，临时页随之废弃。

### 前端（Next.js）单独部署（2026-10-22 实测）

有正式前端时，前端是**第二个云托管服务**。用户只访问前端地址；前端在服务端把 `/api/*` 转发给后端，浏览器与后端之间没有跨域，登录 Cookie 落在前端地址下。

1. **代码**（前端手册 12.5、21.6 节）：`proxy.ts` 在请求时读取 `BACKEND_URL` 转发 `/api/*`，带回状态码、响应体和每一条 Set-Cookie；转发时写入 `x-client-ip`（取前端收到的 `x-envoy-external-address`，覆盖客户端自带的同名头）和 `x-proxy-secret`（= `PROXY_SHARED_SECRET`）。后端只在 `x-proxy-secret` 正确时信任 `x-client-ip`，否则仍用自己收到的 `x-envoy-external-address`。不做这一步，后端看到的来源全是前端服务器，登录限流会把所有用户一起锁住。
2. **打包**：`frontend/Dockerfile` 多阶段构建（`node:22-slim`，`npm ci` → `npm run build` → 拷贝 `.next/standalone`、`.next/static`、`public`），非 root 运行，`HOSTNAME=0.0.0.0`、`PORT=3000`，`CMD ["node","server.js"]`；`.dockerignore` 排除 `node_modules`、`.next`、`.env*`、`tests`。字体用系统字体或 `next/font/local`。
3. **部署**：先部署后端（第八、九节），再部署前端。前端不依赖必填环境变量，首次部署就能启动成功：

```bash
cd projects/<产品名>/frontend
tcb --yes cloudrun deploy -e <环境ID> -s <产品名>-web --source . --port 3000 \
  --min-num 0 --max-num 1 --open-access-types PUBLIC --force --wait
```

4. **写入前端配置**（第九节同一个脚本）：`BACKEND_URL` = 后端服务的 `DefaultDomainName`；`PROXY_SHARED_SECRET` 与后端相同（两边都从 `backend/.env.secrets` 读同一个值）。
5. **验证**：经前端地址跑外网冒烟（登录、生成、历史、隔离）；经前端连续输错触发 429，带伪造的 `x-client-ip`、`x-envoy-external-address`、`X-Forwarded-For` 仍是 429；同一台电脑绕开前端直连后端也是 429（说明前端带过去的是真实 IP）；**换一个网络**（如手机关掉 Wi-Fi 用 5G）仍能正常登录（说明没有把所有人一起锁住）。
6. 对外公布的是前端地址；后端地址只用于排错。第一次打开时前后端都要冷启动，可能等 5～10 秒。

---

# 第三部分：上线后必做

## 十一、登录与数据隔离

默认**邀请码登录**：

- **一人一码、码即身份、不得共用**：每个码对应一个用户标签。两个人共用一个码就是同一个用户，隔离失效。分发时向产品经理讲清这一点。
- 会话放 HttpOnly、Secure、SameSite=Lax 的 Cookie，前端不自己存 token；会话用 `SESSION_SECRET` 签名。
- 所有数据接口按当前登录用户过滤；访问他人数据返回 403；权限判断在后端。
- 邀请码由 AI 生成，在对话里交给产品经理分发；码本身不写进仓库和 `docs/项目状态.md`，状态文件只记分发记录（给了谁、什么时候）。
- 换码：更新 `INVITE_CODES` 并按第九节写入；给同一个人换码时保留原标签，历史数据不丢。
- **登录失败限流**：同一来源连续失败 5 次，锁定 15 分钟。**来源 IP 必须取请求头 `x-envoy-external-address`**（镜像里 `CLIENT_IP_HEADER` 已设）。实测：云托管上 `X-Forwarded-For`、`X-Real-IP` 会被客户端自带的值覆盖，用它们限流可以被伪造地址绕过；`x-envoy-external-address` 由平台写入，伪造不了。限流状态放进程内存时，`MaxNum` 必须是 1。
- 每用户每日模型调用上限（`DAILY_GENERATION_LIMIT`）。

**AI 做**：部署后从外网验证：未登录被拒、错码被拒、对码能登录；两个码分别登录，A 看不到 B 的记录、按编号取 B 的记录被拒；连续输错触发 429，且带伪造的 `X-Forwarded-For` 和 `x-envoy-external-address` 请求头仍是 429。注意限流会锁住 AI 和产品经理共用的网络 15 分钟，放在产品经理验收之后再测。

## 十二、安全禁令（实测踩过）

- **不得打印、记录或返回完整请求头**。云托管会在每个请求里注入 `x-cloudbase-context`，其中含平台签发的临时凭证（含管理员权限的访问令牌，有效期约 5 天）。2026-10-22 演练中，一个"返回全部请求头"的临时排查接口把它暴露了约 7 分钟。排查只取需要的单个请求头，排查代码随用随删。
- 日志只记元信息（请求 ID、耗时、错误码），不记密钥、密码、完整用户文档。
- 服务端 API Key、模型 Key 只在 `backend/.env`（本地）和云托管环境变量（线上）。
- CLI 报错时可能把带临时签名（`q-ak` 等参数）的上传地址整段打出来：不要把 CLI 的原始报错贴进对话、文档或证据包，只摘错误类型和 requestId。

## 十三、文件存储（待实测）

用到图片、音频等文件时，用环境自带的云存储，私有读写，下载走短时效的临时链接，只给当前用户自己的文件签名。CLI 入口 `tcb storage --help`，PostgreSQL 环境的存储桶与权限可用 `tcb db execute` 管理（见 `tcb db execute --help` 示例）。照做时把实际步骤补进本节。

## 十四、日志与排错

- 运行日志：`tcb cloudrun logs process -e <环境ID> --run-id <RunId>`；构建日志：`tcb cloudrun logs build ...`。
- 每个请求生成 trace_id 串联模型调用等环节；错误告警按决策台账 D7 选择国内服务。

---

# 第四部分：排错清单（实测遇到的）

| 现象 | 原因 | 解决 |
| --- | --- | --- |
| 0 元订单"账户余额不足，支付失败" | 账户有历史欠费 | 订单管理里对待支付订单点「付款」，补齐欠费（第二节） |
| 部署报"云托管资源未开通" | 环境里还没启用云托管 | 第三节启用 |
| `CreateVersion failed`，运行日志 `Back-off restarting failed container` | 新版本启动失败，多为环境变量没配 | 看运行日志；按第九节写入配置 |
| 写了环境变量，容器里仍然没有 | `Items` 键名写成了 `EnvParams` / `Cpu` / `Mem` | 用 `EnvParam`、`CpuSpecs`、`MemSpecs` |
| 重新部署命令后台运行时直接退出、没发布 | 卡在"是否灰度发布"提问 | 加全局参数 `tcb --yes cloudrun deploy ...` |
| 网址返回 `SERVICE_VERSION_NOT_FOUND` | 还没有一个启动成功的版本 | 先让某个版本发布成功 |
| 网址 503 | 服务删除中或无可用实例 | 看服务状态和运行日志 |
| 输错锁定可被伪造地址绕过 | 用了 `X-Forwarded-For` 取来源 IP | 改用 `x-envoy-external-address`（第十一节） |
| 网关 401 `MISSING_CREDENTIALS` | 没带或带错服务端 API Key | 检查 `CLOUDBASE_API_KEY`；Key 过期就新建 |
| 第一次打开要等 5～10 秒 | 实例数最小为 0，冷启动 | 正常；需要秒开再评估最小实例数 1（持续消耗资源点） |
| 浏览器先出现"页面访问提示"，HTTP 状态 404 | 平台对测试域名加的提醒页 | 等 3 秒点「确定访问」；只有绑定已备案的自有域名能去掉 |
| 上传代码包报 `socket hang up` | 网络抖动 | 重试部署命令 |
| Mac 上 Python 访问本机服务返回 502 | 系统代理拦截了本机地址 | httpx 加 `trust_env=False`，或设 `NO_PROXY=localhost,127.0.0.1` |
| pytest 意外去连真实云库 | `backend/.env` 里写了 `DATA_BACKEND=cloudbase_rest` | 改回留空，只在冒烟命令前临时设置 |
| 免费额度用完，服务停了 | 3000 点/月耗尽 | 等下月重置，或经产品经理确认升级个人版 |

---

# 第五部分：AI 执行总流程清单

> 上线的唯一顺序来源。逐项打勾。

## 准备
- [ ] 读本手册全文、`docs/项目状态.md`、项目代码；按 `AGENTS.md` 第 7 节对账
- [ ] `./verify.sh <产品名>` 各项通过或不适用
- [ ] 确认决策台账 D4（成本上限）、D5（登录）、D6（留存）、D7（隐私 / 出境）、D9（上线套餐）已定
- [ ] 交付《上线方案摘要》，存为 `docs/阶段文档/上线方案摘要.md`：用哪个套餐、预计资源点消耗、产品经理要做哪几步、预计耗时；产品经理确认后再继续

## 产品经理照着点（第一部分）
- [ ] 注册、实名
- [ ] 开通免费体验版环境（上海、PostgreSQL、兑换码、不勾搭配购买）
- [ ] 启用云托管
- [ ] 创建服务端 API Key 并填进 `backend/.env`
- [ ] 浏览器授权 `tcb login`

## 代码改造
- [ ] 数据层支持 `DATA_BACKEND=cloudbase_rest`，迁移 SQL 开 RLS 不建策略
- [ ] Dockerfile / .dockerignore（第七节），镜像设 `REQUIRE_SERVER_DB=1`、`CLIENT_IP_HEADER`
- [ ] 邀请码登录、按用户隔离、登录限流、每日上限（第十一节）
- [ ] 没有任何打印完整请求头的代码（第十二节）
- [ ] 本地用 `DATA_BACKEND=cloudbase_rest` 连真实云数据库和真实模型跑一遍冒烟，再部署

## 部署
- [ ] `tcb db execute` 建表并复查 RLS
- [ ] 首次 `tcb cloudrun deploy`（预期启动失败）
- [ ] `UpdateCloudRunServer` 写入环境变量与 0.25 核 / 0.5 GB / 0～1 实例，等任务 `finished`
- [ ] `/api/health` 外网返回正常
- [ ] 有正式前端时：部署前端服务、写入 `BACKEND_URL` 与 `PROXY_SHARED_SECRET`（第十节前端部分）

## 上线后验证
- [ ] 外网冒烟：登录、真实生成、历史、隔离（第十一节）；删除冒烟写入的 `smoke-` 记录
- [ ] 再发布一次新版本（`tcb --yes cloudrun deploy ...`），确认登录和历史数据都还在（云端数据不随版本丢失）
- [ ] 产品经理按第六部分验收（电脑 + 无痕窗口 + 手机）
- [ ] 产品经理验收完成后再测登录限流与防伪造；有前端时加测"直连后端也被锁"和"换网络仍能登录"
- [ ] 证据包放 `docs/evidence/阶段4/`，运行 `./verify.sh <产品名> 阶段4` 并填是否表

## 收尾（阶段 5）
- [ ] 产品文件夹的 `README.md` 写上访问地址、登录方式、更新版本的命令
- [ ] `tcb logout` 退出本机命令行登录（部署用凭据）；**服务端 API Key 是线上运行用的，不删**
- [ ] 在 `docs/项目状态.md` 记下服务端 API Key 的到期日，到期前 2 周提醒更换
- [ ] 更新 `docs/项目状态.md`：阶段、访问地址、邀请码分发记录（不含码本身）

---

# 第六部分：上线后验收清单（产品经理照做）

- [ ] 打开访问地址（https 开头），页面能正常显示（第一次可能要等 5～10 秒）
- [ ] 输入邀请码能登录；输错邀请码被拒并有明确提示
- [ ] 生成一次，几秒内出结果；刷新页面记录还在
- [ ] 用另一个邀请码在无痕窗口登录：看不到第一个人的记录
- [ ] 手机浏览器用同一个码登录：记录和电脑一致
- [ ] 第一次打开先看到腾讯云"页面访问提示"，点「确定访问」后进入产品（这是测试域名的提醒，不是出错）
- [ ] AI 的证据包里有外网冒烟、限流防伪造、重新发布后数据仍在的结果

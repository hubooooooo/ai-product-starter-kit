"""给腾讯云开发云托管服务写入环境变量和规格，并用该服务最新构建的镜像重新发布。

为什么需要它：`tcb cloudrun deploy` 没有设置环境变量的参数；接口 UpdateCloudRunServer 的
Items 键名必须是 EnvParam / CpuSpecs / MemSpecs（写成 EnvParams / Cpu / Mem 会被静默忽略）。

密钥只从本地文件读（--from-file，dotenv 格式），不出现在命令行和输出里；输出中的值一律打码。
【注意】每次写入都是整组覆盖：没列进 --keys / --set 的变量会从线上消失。所以每次都把全部变量列全，不能只写要改的那一个。

用法示例（后端，变量按产品增删）：
  python set_cloudrun_env.py --env-id <环境ID> --service <产品>-backend --port 8080 \
      --from-file backend/.env --from-file backend/.env.secrets \
      --keys CLOUDBASE_API_KEY,MODEL_API_KEY,MODEL_BASE_URL,MODEL_NAME,INVITE_CODES,SESSION_SECRET,PROXY_SHARED_SECRET \
      --set DATA_BACKEND=cloudbase_rest --set CLOUDBASE_ENV_ID=<环境ID> --set REQUIRE_LOGIN=1 --set COOKIE_SECURE=1 \
      --set MODEL_TIMEOUT_SECONDS=30 --set DAILY_GENERATION_LIMIT=50

用法示例（前端，有正式前端时）：
  python set_cloudrun_env.py --env-id <环境ID> --service <产品>-web --port 3000 \
      --from-file backend/.env.secrets --keys PROXY_SHARED_SECRET --set BACKEND_URL=<后端服务地址>
"""
import argparse
import json
import subprocess
import sys
import time

API = ["tcb", "api", "tcbr"]
VERSION = ["--api-version", "2022-02-17"]


def tcbr(action, body, retries=3):
    """调用云托管接口；网络抖动（TLS 断开等）自动重试几次。"""
    for attempt in range(retries):
        try:
            return _tcbr_once(action, body)
        except SystemExit as e:
            if attempt == retries - 1 or "network" not in str(e).lower() and "socket" not in str(e).lower():
                raise
            time.sleep(5)


def _tcbr_once(action, body):
    out = subprocess.run(API + [action] + VERSION + ["--body", json.dumps(body, ensure_ascii=False), "--json"],
                         capture_output=True, text=True)
    text = out.stdout + out.stderr
    start = text.find("{")
    if start < 0:
        raise SystemExit(f"{action} 调用失败：{text[-300:]}")
    data = json.loads(text[start:])
    if "data" not in data:
        raise SystemExit(f"{action} 调用失败：{json.dumps(data, ensure_ascii=False)[:300]}")
    return data["data"]


def read_dotenv(path):
    vals = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    return vals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-id", required=True)
    ap.add_argument("--service", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--from-file", action="append", default=[], help="dotenv 文件，可多次")
    ap.add_argument("--keys", default="", help="从文件里取哪些变量，逗号分隔")
    ap.add_argument("--set", action="append", default=[], help="非密钥的固定值 KEY=VALUE，可多次")
    ap.add_argument("--cpu", type=float, default=0.25)
    ap.add_argument("--mem", type=float, default=0.5)
    ap.add_argument("--min", type=int, default=0)
    ap.add_argument("--max", type=int, default=1)
    a = ap.parse_args()

    file_vals = {}
    for f in a.from_file:
        file_vals.update(read_dotenv(f))
    params, secrets = {}, []
    for k in [k.strip() for k in a.keys.split(",") if k.strip()]:
        if not file_vals.get(k):
            raise SystemExit(f"本地文件里没有 {k} 或值为空")
        params[k] = file_vals[k]
        secrets.append(file_vals[k])
    for kv in a.set:
        k, _, v = kv.partition("=")
        params[k.strip()] = v.strip()

    records = tcbr("DescribeCloudRunDeployRecord", {"EnvId": a.env_id, "ServerName": a.service})["DeployRecords"]
    if not records:
        raise SystemExit("这个服务还没有部署记录，先用 tcb cloudrun deploy 部署一次")
    image = max(records, key=lambda r: r["DeployTime"])["ImageUrl"]

    body = {
        "EnvId": a.env_id,
        "ServerName": a.service,
        "DeployInfo": {"DeployType": "image", "ImageUrl": image, "ReleaseType": "FULL"},
        "Items": [
            {"Key": "EnvParam", "Value": json.dumps(params, ensure_ascii=False)},
            {"Key": "CpuSpecs", "FloatValue": a.cpu},
            {"Key": "MemSpecs", "FloatValue": a.mem},
            {"Key": "MinNum", "IntValue": a.min},
            {"Key": "MaxNum", "IntValue": a.max},
            {"Key": "Port", "IntValue": a.port},
        ],
    }
    task_id = tcbr("UpdateCloudRunServer", body)["TaskId"]
    print(f"已提交（任务 {task_id}）：服务 {a.service}，变量名 {', '.join(params)}，规格 {a.cpu} 核 / {a.mem} GB，实例 {a.min}~{a.max}")

    for _ in range(60):
        time.sleep(10)
        t = tcbr("DescribeServerManageTask", {"EnvId": a.env_id, "ServerName": a.service, "TaskId": task_id})
        t = t.get("Task") or t
        status = t.get("Status")
        if status in ("finished", "failed"):
            reason = t.get("FailReason", "")
            for s in secrets:
                reason = reason.replace(s, "<已隐藏>")
            print(f"发布结果：{status} {reason}")
            sys.exit(0 if status == "finished" else 1)
    raise SystemExit("等了 10 分钟还没结束，请用 DescribeServerManageTask 继续查看")


if __name__ == "__main__":
    main()

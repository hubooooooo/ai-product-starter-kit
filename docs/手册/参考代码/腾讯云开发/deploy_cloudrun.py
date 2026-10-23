"""把云托管服务的源码复制成一个干净的目录再部署（后端、前端通用；首次部署和更新版本都用它）。

为什么需要它：`tcb cloudrun deploy --source <目录>` 上传源码时只跳过 logs、.git、node_modules
（CloudBase CLI 3.8.7 源码确认），不读 .dockerignore。直接部署产品目录，会把 .env、.env.secrets、
.venv、本地 data/ 一起传到云端：密钥离开本机，包太大还容易报 socket hang up。

它做五件事：
1. 检查命令行登录是否有效、能否看到这个环境（登录约 30 天过期；收尾时 tcb logout 后也要重新授权）；
2. 按 .dockerignore 加一组固定排除项，把源码复制到临时目录（不带 / 的规则在任何层级都生效，比 Docker 更严）；
3. 检查临时目录里没有 .env 类文件，也没有出现本地密钥文件里的任何密钥值，有就停下不部署；
4. 用 `tcb --yes cloudrun deploy` 部署临时目录，输出里带签名的地址和密钥值一律打码，网络抖动自动重试；
5. 打印本月资源点用量，超过 70% 提醒。

用法（在工具包根目录执行；服务名用产品英文短名，见部署手册第八节）：
  python3 docs/手册/参考代码/腾讯云开发/deploy_cloudrun.py --env-id <环境ID> --service <短名>-api \
      --source projects/<产品名>/backend --port 8080
  python3 docs/手册/参考代码/腾讯云开发/deploy_cloudrun.py --env-id <环境ID> --service <短名>-web \
      --source projects/<产品名>/frontend --port 3000 --secret-file projects/<产品名>/backend/.env.secrets
只检查打包、不部署：加 --dry-run。
"""
import argparse
import fnmatch
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# 不管 .dockerignore 怎么写都排除；.env.example 除外
ALWAYS_EXCLUDE_NAMES = {".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
                        ".ruff_cache", ".next", "logs", "coverage", "htmlcov", ".DS_Store"}
ALWAYS_EXCLUDE_ROOT = {"data"}
# 云端按 Dockerfile 构建，即使 .dockerignore 里写了也要上传
ALWAYS_KEEP_ROOT = {"Dockerfile", ".dockerignore"}
SECRET_NAME = re.compile(r"KEY|SECRET|TOKEN|PASSWORD|INVITE|CODES", re.I)
SIGNED_URL = re.compile(r"https?://\S*?(q-sign|q-ak|signature|sign=|token=)\S*", re.I)
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def is_env_file(name):
    return name == ".env" or (name.startswith(".env.") and name != ".env.example")


def load_rules(src):
    rules = []
    p = src / ".dockerignore"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            neg = line.startswith("!")
            pat = (line[1:] if neg else line).strip().removeprefix("./").strip("/")
            if pat:
                rules.append((neg, pat))
    return rules


def match(pat, rel):
    pat = pat.removeprefix("**/")
    if "/" not in pat:
        return fnmatch.fnmatchcase(rel.rsplit("/", 1)[-1], pat)
    return fnmatch.fnmatchcase(rel, pat)


def excluded(rel, rules):
    name = rel.rsplit("/", 1)[-1]
    top = "/" not in rel
    if top and name in ALWAYS_KEEP_ROOT:
        return False
    if name in ALWAYS_EXCLUDE_NAMES or is_env_file(name) or (top and name in ALWAYS_EXCLUDE_ROOT):
        return True
    result = False
    for neg, pat in rules:  # 和 .dockerignore 一样：最后一条匹配的规则说了算
        if match(pat, rel):
            result = not neg
    return result


def stage(src, dst, rules):
    skipped, count, size = [], 0, 0
    for root, dirs, files in os.walk(src):
        rel_root = os.path.relpath(root, src).replace(os.sep, "/")
        rel_root = "" if rel_root == "." else rel_root
        keep = []
        for d in dirs:
            rel = f"{rel_root}/{d}" if rel_root else d
            (skipped.append(rel + "/") if excluded(rel, rules) else keep.append(d))
        dirs[:] = keep
        for f in files:
            rel = f"{rel_root}/{f}" if rel_root else f
            if excluded(rel, rules):
                skipped.append(rel)
                continue
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(root) / f, target)
            count += 1
            size += target.stat().st_size
    return skipped, count, size


def read_secret_values(paths):
    values = []
    for p in paths:
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                if SECRET_NAME.search(k) and len(v) >= 12:
                    values.append(v)
    return values


def check_staged(dst, secrets):
    problems = []
    for p in dst.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(dst).as_posix()
        if is_env_file(p.name):
            problems.append(f"{rel}（密钥文件）")
            continue
        data = p.read_bytes()
        if any(s.encode() in data for s in secrets):
            problems.append(f"{rel}（内容里出现了本地密钥文件中的密钥值）")
    return problems


def redact(text, secrets):
    text = SIGNED_URL.sub("<已隐藏带签名的地址>", text)
    for s in secrets:
        text = text.replace(s, "<已隐藏>")
    return text


def tcb(args):
    try:
        return subprocess.run(["tcb", *args], capture_output=True, text=True)
    except FileNotFoundError:
        raise SystemExit("找不到 tcb 命令：按部署手册第二节安装 CloudBase CLI")


def check_login(env_id):
    out = tcb(["env", "list", "--json"])
    if out.returncode != 0 or env_id not in out.stdout:
        raise SystemExit(
            f"看不到环境 {env_id}：命令行登录可能已失效（约 30 天过期，或收尾时执行过 tcb logout），"
            "也可能授权到了别的腾讯云账号。按部署手册第二节重新授权后再运行。")


def deploy(env_id, service, staged, port, secrets, retries):
    cmd = ["tcb", "--yes", "cloudrun", "deploy", "-e", env_id, "-s", service, "--source", str(staged),
           "--port", str(port), "--min-num", "0", "--max-num", "1", "--open-access-types", "PUBLIC",
           "--force", "--wait"]
    for attempt in range(retries + 1):
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        lines = []
        for line in p.stdout:
            line = redact(line, secrets)
            lines.append(line)
            print(line, end="", flush=True)
        if p.wait() == 0:
            return True
        flaky = any(k in "".join(lines) for k in ("socket hang up", "ECONNRESET", "ETIMEDOUT"))
        if not flaky or attempt == retries:
            return False
        print(f"\n网络抖动，第 {attempt + 2} 次尝试……")
    return False


def print_usage(env_id):
    out = tcb(["env", "usage", "-e", env_id, "--yes"])
    for line in ANSI.sub("", out.stdout).splitlines():
        if "resource points" in line.lower() or "资源点" in line:
            m = re.search(r"([\d.]+)\D+?([\d.]+)", line.split(":", 1)[-1].split("：", 1)[-1])
            note = ""
            if m and float(m.group(2)) > 0:
                pct = float(m.group(1)) / float(m.group(2)) * 100
                note = f"（{pct:.0f}%{'，已超过 70%，请告诉产品经理' if pct >= 70 else ''}）"
            print(f"本月资源点：{line.strip().lstrip('ℹ ')}{note}")
            return
    print("没读到资源点用量，请手动执行 tcb env usage -e <环境ID> --yes 查看")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-id", required=True)
    ap.add_argument("--service", required=True)
    ap.add_argument("--source", required=True, help="产品的 backend/ 或 frontend/ 目录")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--secret-file", action="append", default=[],
                    help="额外要防止上传的密钥文件，可多次；源码目录里的 .env、.env.secrets 总会检查")
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--dry-run", action="store_true", help="只打包和检查，不部署")
    a = ap.parse_args()

    src = Path(a.source).resolve()
    if not (src / "Dockerfile").exists():
        raise SystemExit(f"{src} 里没有 Dockerfile：云托管按 Dockerfile 构建，先按部署手册第七节写好")
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", a.service):
        raise SystemExit("服务名只用小写英文字母、数字和 -，字母开头，例如 xhs-api")
    secrets = read_secret_values([src / ".env", src / ".env.secrets", *map(Path, a.secret_file)])

    if not a.dry_run:
        check_login(a.env_id)

    tmp = Path(tempfile.mkdtemp(prefix="cloudrun-"))
    staged = tmp / src.name
    try:
        skipped, count, size = stage(src, staged, load_rules(src))
        problems = check_staged(staged, secrets)
        if problems:
            raise SystemExit("打包目录里有不该上传的内容，已停止部署：\n  " + "\n  ".join(problems))
        top_skipped = sorted({s for s in skipped if s.count("/") <= 1 and not s.startswith(".git")})
        print(f"已打包 {count} 个文件，共 {size / 1024 / 1024:.1f} MB；未上传：{', '.join(top_skipped[:15]) or '无'}")
        if size > 50 * 1024 * 1024:
            print("提醒：包超过 50 MB，上传容易失败。检查是不是有大文件或依赖目录没排除。")
        if a.dry_run:
            print("--dry-run：检查通过，未部署。")
            return
        ok = deploy(a.env_id, a.service, staged, a.port, secrets, a.retries)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print_usage(a.env_id)
    if not ok:
        raise SystemExit("部署失败：按部署手册第八节查构建日志和运行日志；不要把 CLI 原始报错贴进对话或文档")


if __name__ == "__main__":
    main()

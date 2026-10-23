"""把剪贴板里的密钥写进本地 .env，全程不显示密钥内容（macOS）。

为什么需要它：产品经理不用去 Finder 显示隐藏文件、用"文本编辑"改 .env（学生实测最容易卡在这步：
粘错行、多空格、多换行），密钥也不经过对话。

用法：产品经理在控制台点「复制」后，只回复"复制好了"（不要把密钥粘贴进对话），AI 在工具包根目录执行：
  python3 docs/手册/参考代码/腾讯云开发/save_secret_from_clipboard.py \
      --file projects/<产品名>/backend/.env --key CLOUDBASE_API_KEY
模型 Key 同理（--key MODEL_API_KEY）。输出只有变量名和长度；写完清空剪贴板。
文件必须已被 .gitignore 忽略，否则拒绝写入。
"""
import argparse
import os
import subprocess
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="要写入的 .env 文件")
    ap.add_argument("--key", required=True, help="变量名，如 CLOUDBASE_API_KEY")
    ap.add_argument("--min-length", type=int, default=20)
    a = ap.parse_args()

    path = Path(a.file).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    ignored = subprocess.run(["git", "-C", str(path.parent), "check-ignore", "-q", str(path)])
    if ignored.returncode == 128:
        raise SystemExit("工具包还不是 Git 仓库，无法确认文件会被忽略：先在工具包根目录 git init")
    if ignored.returncode != 0:
        raise SystemExit(f"{path.name} 没有被 .gitignore 忽略，拒绝写入密钥")

    value = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout.strip()
    value = value.removeprefix(f"{a.key}=").strip().strip('"').strip("'")
    if not value:
        raise SystemExit("剪贴板是空的：请产品经理在控制台重新点一次「复制」")
    if any(c.isspace() for c in value) or not value.isascii() or len(value) < a.min_length:
        raise SystemExit("剪贴板里的内容不像一把密钥（太短、含空格换行或中文），可能复制了别的东西：请重新点「复制」")

    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines = [ln for ln in lines if not ln.strip().startswith(f"{a.key}=")]
    lines.append(f"{a.key}={value}")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)

    subprocess.run(["pbcopy"], input="", text=True)
    print(f"已写入 {a.key}（长度 {len(value)}），剪贴板已清空。")


if __name__ == "__main__":
    main()

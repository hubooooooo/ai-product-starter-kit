#!/usr/bin/env bash
# 自检脚本：由脚本而不是 AI 判断四件事（mock 测试 / 密钥排除 / 重启恢复 / 前端构建）。
# 用法：./verify.sh [阶段目录名]     例：./verify.sh 阶段2-1   （提示"权限不够"时用 bash verify.sh 阶段2-1）
# 给了阶段目录名，会把完整输出写到 docs/evidence/<阶段目录名>/verify-输出.txt。
# 退出码：全部通过或 N/A 为 0；任一"不通过"或"未配置"为 1。
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
STAGE="${1:-}"
LOG="$(mktemp)"
log() { printf '%s\n' "$*" | tee -a "$LOG"; }
sect() { log ""; log "================ $* ================"; }

R1="未配置"; R2="未配置"; R3="未配置"; R4="N/A（本阶段无正式前端）"
D1=""; D2=""; D3=""; D4=""

log "verify.sh 自检  $(date '+%Y-%m-%d %H:%M:%S')  目录：$ROOT"

# ---------- 1. mock 自动化测试 ----------
sect "1. mock 自动化测试"
if [ -d backend/tests ]; then
  PY="$ROOT/backend/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
  T="$(mktemp)"
  (cd backend && MODEL_API_KEY="" "$PY" -m pytest -q 2>&1) > "$T"; RC=$?
  cat "$T" >> "$LOG"
  PASSED="$(grep -Eo '[0-9]+ passed' "$T" | tail -1 | grep -Eo '[0-9]+')"; PASSED="${PASSED:-0}"
  FAILED="$(grep -Eo '[0-9]+ (failed|error)' "$T" | grep -Eo '[0-9]+' | paste -sd+ - | bc 2>/dev/null)"; FAILED="${FAILED:-0}"
  TOTAL=$((PASSED + FAILED))
  if [ "$RC" -eq 0 ] && [ "$PASSED" -gt 0 ]; then R1="通过（${PASSED}/${TOTAL}）"; else R1="不通过（通过 $PASSED/$TOTAL，退出码 ${RC}）"; fi
  D1="后端 pytest"
  rm -f "$T"
else
  log "未找到 backend/tests，跳过后端测试。"
fi
if [ -f frontend/package.json ] && grep -q '"test"' frontend/package.json; then
  T="$(mktemp)"
  (cd frontend && npm test --silent -- --run 2>&1) > "$T"; RC=$?
  cat "$T" >> "$LOG"
  if [ "$RC" -eq 0 ]; then R1="$R1；前端测试通过"; else R1="不通过（前端测试退出码 ${RC}）"; fi
  rm -f "$T"
fi
log "结果：$R1"

# ---------- 2. 密钥排除 ----------
sect "2. 密钥排除（扫描 git 跟踪文件与构建产物）"
PAT='sk-[A-Za-z0-9]{20,}|AKLT[A-Za-z0-9]{10,}|AKIA[0-9A-Z]{16}|(api[_-]?key|secret|password|token)[[:space:]]*[=:][[:space:]]*["'"'"']?[A-Za-z0-9_-]{20,}'
HITS=0
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  log "问题：当前目录不是 Git 仓库，无法判断哪些文件会进仓库。请先让 AI 执行 git init 并配置 .gitignore。"
  HITS=$((HITS+1))
fi
# 扫描范围：已跟踪文件 + 未跟踪但没被 .gitignore 忽略的文件（即下次 git add 会进仓库的）
lsfiles() { git ls-files -z --cached --others --exclude-standard 2>/dev/null; }
# 2a. .env 类文件不得被跟踪
ENV_TRACKED="$(git ls-files | grep -E '(^|/)\.env(\.[A-Za-z0-9_-]+)?$' | grep -v '\.env\.example$' || true)"
if [ -n "$ENV_TRACKED" ]; then log "问题：以下 .env 文件被 git 跟踪："; log "$ENV_TRACKED"; HITS=$((HITS+1)); else log "通过：没有 .env 文件被 git 跟踪。"; fi
# 2b. 跟踪文件中的密钥样式
M="$(lsfiles | xargs -0 grep -InE --exclude=verify.sh "$PAT" 2>/dev/null | sed -E 's/([A-Za-z0-9_-]{6})[A-Za-z0-9_-]{8,}/\1******/g' || true)"
if [ -n "$M" ]; then log "问题：会进仓库的文件中发现疑似密钥（已打码）："; log "$M"; HITS=$((HITS+1)); else log "通过：会进仓库的文件中未发现密钥样式字符串。"; fi
# 2c. 构建产物中的密钥样式
for d in frontend/.next frontend/dist frontend/out backend/dist; do
  [ -d "$d" ] || continue
  M="$(grep -rIlE "$PAT" "$d" 2>/dev/null || true)"
  if [ -n "$M" ]; then log "问题：构建产物 $d 中发现疑似密钥，文件："; log "$M"; HITS=$((HITS+1)); else log "通过：构建产物 $d 未发现密钥样式字符串。"; fi
done
# 2d. 本机 .env 里的真实 Key 值不得出现在任何跟踪文件或构建产物里（值本身不打印）
for envf in backend/.env .env frontend/.env.local; do
  [ -f "$envf" ] || continue
  while IFS= read -r line; do
    case "$line" in \#*|"") continue;; esac
    name="${line%%=*}"
    # 只检查名字像密钥的变量（KEY / SECRET / TOKEN / PASSWORD / ACCESS），URL、模型名之类不算
    echo "$name" | grep -qiE 'key|secret|token|pass|access' || continue
    val="${line#*=}"; val="${val%\"}"; val="${val#\"}"
    [ "${#val}" -ge 12 ] || continue
    FOUND="$(lsfiles | xargs -0 grep -IlF -- "$val" 2>/dev/null || true)"
    for d in frontend/.next frontend/dist frontend/out backend/dist; do [ -d "$d" ] && FOUND="$FOUND $(grep -rIlF -- "$val" "$d" 2>/dev/null || true)"; done
    FOUND="$(echo "$FOUND" | xargs 2>/dev/null || true)"
    if [ -n "$FOUND" ]; then log "问题：$envf 中 ${line%%=*} 的值出现在：$FOUND"; HITS=$((HITS+1)); else log "通过：$envf 中 ${line%%=*} 的值未出现在任何跟踪文件或构建产物中。"; fi
  done < "$envf"
done
if [ "$HITS" -eq 0 ]; then R2="通过"; else R2="不通过（${HITS} 处问题，见输出）"; fi
log "结果：$R2"

# ---------- 3. 重启恢复 ----------
sect "3. 数据重启恢复（调用 scripts/restart-check.sh）"
if [ -x scripts/restart-check.sh ]; then
  T="$(mktemp)"; bash scripts/restart-check.sh > "$T" 2>&1; RC=$?
  tee -a "$LOG" < "$T"; rm -f "$T"
  if [ "$RC" -eq 0 ]; then R3="通过"; else R3="不通过（退出码 ${RC}，见输出）"; fi
else
  log "未找到 scripts/restart-check.sh。有可重启的服务时，AI 必须按项目写这个钩子。"
fi
log "结果：$R3"

# ---------- 4. 前端类型检查 / Lint / 生产构建 ----------
sect "4. 前端类型检查 / Lint / 生产构建"
if [ -f frontend/package.json ]; then
  FAIL=""
  T="$(mktemp)"
  if grep -q '"lint"' frontend/package.json; then (cd frontend && npm run lint 2>&1) >> "$T" || FAIL="$FAIL lint"; fi
  if [ -f frontend/tsconfig.json ]; then (cd frontend && npx tsc --noEmit 2>&1) >> "$T" || FAIL="$FAIL 类型检查"; fi
  if grep -q '"build"' frontend/package.json; then (cd frontend && npm run build 2>&1) >> "$T" || FAIL="$FAIL 生产构建"; fi
  cat "$T" >> "$LOG"; rm -f "$T"
  if [ -z "$FAIL" ]; then R4="通过"; else R4="不通过（失败项：${FAIL}）"; fi
else
  log "未找到 frontend/package.json，本阶段无正式前端。"
fi
log "结果：$R4"

# ---------- 汇总 ----------
sect "汇总（抄进是否表的就是这四行）"
log "是否表第 2 项  mock 测试：      $R1"
log "是否表第 4 项  前端检查与构建： $R4"
log "是否表第 5 项  密钥排除：       $R2"
log "是否表第 6 项  重启后数据恢复： $R3"
EXIT=0
for r in "$R1" "$R2" "$R3" "$R4"; do case "$r" in 不通过*|未配置*) EXIT=1;; esac; done
if [ "$EXIT" -eq 0 ]; then log "总判定：四项全部通过或不适用。"; else log "总判定：有不通过或未配置项，对应是否表只能填\"否\"。"; fi

if [ -n "$STAGE" ]; then
  mkdir -p "docs/evidence/$STAGE"
  cp "$LOG" "docs/evidence/$STAGE/verify-输出.txt"
  log "完整输出已写入：docs/evidence/$STAGE/verify-输出.txt"
fi
rm -f "$LOG"
exit "$EXIT"

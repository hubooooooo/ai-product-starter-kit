#!/usr/bin/env bash
# 自检脚本：由脚本而不是 AI 判断五件事（mock 测试 / 密钥排除 / 重启恢复 / 前端构建 / 文件齐全与位置）。
# 每个产品一个文件夹：projects/<产品名>/。脚本进到这个文件夹里检查。
# 用法：./verify.sh [产品名] [阶段目录名]     例：./verify.sh 我的第一个产品 阶段2-1   （提示"权限不够"时在前面加 bash）
# projects/ 下只有一个产品时，产品名可以省略：./verify.sh 阶段2-1
# 给了阶段目录名，会把完整输出写到 projects/<产品名>/docs/evidence/<阶段目录名>/verify-输出.txt。
# 退出码：全部通过或 N/A 为 0；任一"不通过"或"未配置"为 1；找不到产品为 2。
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# ---------- 选产品 ----------
PRODUCTS=()
for d in projects/*/; do [ -d "$d" ] && PRODUCTS+=("$(basename "$d")"); done
if [ $# -ge 1 ] && [ -d "projects/$1" ]; then
  PRODUCT="$1"; STAGE="${2:-}"
elif [ "${#PRODUCTS[@]}" -eq 1 ] && { [ $# -eq 0 ] || [[ "$1" == 阶段* ]]; }; then
  PRODUCT="${PRODUCTS[0]}"; STAGE="${1:-}"
else
  [ $# -ge 1 ] && echo "找不到产品\"$1\"，它也不是阶段名（阶段名以\"阶段\"开头，如 阶段2-1）。"
  echo "请指明检查哪个产品：./verify.sh <产品名> [阶段N]"
  echo "projects/ 下现有的产品：${PRODUCTS[*]:-（没有）}"
  exit 2
fi
P="projects/$PRODUCT"
LOG="$(mktemp)"
log() { printf '%s\n' "$*" | tee -a "$LOG"; }
sect() { log ""; log "================ $* ================"; }

R1="未配置"; R2="未配置"; R3="未配置"; R4="N/A（本阶段无正式前端）"; R5=""
NOCODE=0; case "$STAGE" in 阶段0|阶段1) NOCODE=1;; esac   # 无代码阶段：测试和重启检查不适用
D1=""; D2=""; D3=""; D4=""

log "verify.sh 自检  $(date '+%Y-%m-%d %H:%M:%S')  产品：${PRODUCT}（${ROOT}/${P}）"
cd "$P"

# ---------- 1. mock 自动化测试 ----------
sect "1. mock 自动化测试"
if [ "$NOCODE" -eq 1 ]; then
  R1="N/A（无代码阶段）"
elif [ -d backend/tests ]; then
  PY="$ROOT/$P/backend/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
  T="$(mktemp)"
  (cd backend && MODEL_API_KEY="" "$PY" -m pytest -q 2>&1) > "$T"; RC=$?
  cat "$T" >> "$LOG"
  PASSED="$(grep -Eo '[0-9]+ passed' "$T" | tail -1 | grep -Eo '[0-9]+')"; PASSED="${PASSED:-0}"
  FAILED="$(grep -Eo '[0-9]+ (failed|error)' "$T" | grep -Eo '[0-9]+' | paste -sd+ - | bc 2>/dev/null)"; FAILED="${FAILED:-0}"
  TOTAL=$((PASSED + FAILED))
  if [ "$RC" -eq 0 ] && [ "$PASSED" -gt 0 ]; then R1="通过（${PASSED}/${TOTAL}）"; else R1="不通过（通过 ${PASSED}/${TOTAL}，退出码 ${RC}）"; fi
  D1="后端 pytest"
  rm -f "$T"
else
  log "未找到 backend/tests，跳过后端测试。"
fi
if [ -f frontend/package.json ] && grep -q '"test"' frontend/package.json; then
  T="$(mktemp)"
  (cd frontend && npm test --silent -- --run 2>&1) > "$T"; RC=$?
  cat "$T" >> "$LOG"
  if [ "$RC" -eq 0 ]; then R1="${R1}；前端测试通过"; else R1="不通过（前端测试退出码 ${RC}）"; fi
  rm -f "$T"
fi
log "结果：$R1"

# ---------- 2. 密钥排除 ----------
sect "2. 密钥排除（扫描整个仓库会进 git 的文件，以及本产品的构建产物）"
cd "$ROOT"
PAT='sk-[A-Za-z0-9]{20,}|AKLT[A-Za-z0-9]{10,}|AKIA[0-9A-Z]{16}|(api[_-]?key|secret|password|token)[[:space:]]*[=:][[:space:]]*["'"'"']?[A-Za-z0-9_-]{20,}'
HITS=0
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  log "问题：工具包文件夹不是 Git 仓库，无法判断哪些文件会进仓库。请先让 AI 执行 git init 并配置 .gitignore。"
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
for d in "$P/frontend/.next" "$P/frontend/dist" "$P/frontend/out" "$P/backend/dist"; do
  [ -d "$d" ] || continue
  M="$(grep -rIlE "$PAT" "$d" 2>/dev/null || true)"
  if [ -n "$M" ]; then log "问题：构建产物 $d 中发现疑似密钥，文件："; log "$M"; HITS=$((HITS+1)); else log "通过：构建产物 $d 未发现密钥样式字符串。"; fi
done
# 2d. 本机 .env 里的真实 Key 值不得出现在任何跟踪文件或构建产物里（值本身不打印）
for envf in "$P/backend/.env" "$P/.env" "$P/frontend/.env.local" .env; do
  [ -f "$envf" ] || continue
  while IFS= read -r line; do
    case "$line" in \#*|"") continue;; esac
    name="${line%%=*}"
    # 只检查名字像密钥的变量（KEY / SECRET / TOKEN / PASSWORD / ACCESS），URL、模型名之类不算
    echo "$name" | grep -qiE 'key|secret|token|pass|access' || continue
    val="${line#*=}"; val="${val%\"}"; val="${val#\"}"
    [ "${#val}" -ge 12 ] || continue
    FOUND="$(lsfiles | xargs -0 grep -IlF -- "$val" 2>/dev/null || true)"
    for d in "$P/frontend/.next" "$P/frontend/dist" "$P/frontend/out" "$P/backend/dist"; do [ -d "$d" ] && FOUND="$FOUND $(grep -rIlF -- "$val" "$d" 2>/dev/null || true)"; done
    FOUND="$(echo "$FOUND" | xargs 2>/dev/null || true)"
    if [ -n "$FOUND" ]; then log "问题：$envf 中 ${line%%=*} 的值出现在：$FOUND"; HITS=$((HITS+1)); else log "通过：$envf 中 ${line%%=*} 的值未出现在任何跟踪文件或构建产物中。"; fi
  done < "$envf"
done
if [ "$HITS" -eq 0 ]; then R2="通过"; else R2="不通过（${HITS} 处问题，见输出）"; fi
log "结果：$R2"
cd "$P"

# ---------- 3. 重启恢复 ----------
sect "3. 数据重启恢复（调用 scripts/restart-check.sh）"
if [ "$NOCODE" -eq 1 ]; then
  R3="N/A（无代码阶段）"
elif [ -x scripts/restart-check.sh ]; then
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

# ---------- 5. 文件齐全与位置 ----------
sect "5. 文件齐全与位置（AGENTS.md 第 7 节的产出清单；根目录不放产品文件）"
MISS=0; STRAY=0
cd "$ROOT"
# 5a. 根目录只放工具包自己的文件，产品的代码、依赖、数据都应在 projects/<产品名>/ 里
for e in * .[!.]*; do
  [ -e "$e" ] || continue
  case "$e" in
    AGENTS.md|CLAUDE.md|README.md|开始看这里.md|LICENSE|verify.sh|.gitignore|assets|docs|projects|.git|.DS_Store) ;;
    scripts) for f in scripts/*; do [ "$f" = scripts/export-clean-kit.sh ] || { log "放错位置：${f}（应在产品文件夹里）"; STRAY=$((STRAY+1)); }; done ;;
    .venv|.env|.env.*|.next|.vefaas|.pytest_cache) log "放错位置：${e}（应在产品文件夹里）"; STRAY=$((STRAY+1)) ;;
    .*) ;;  # 其他隐藏文件夹多为编码工具自己的配置
    *) log "放错位置：${e}（应在产品文件夹里）"; STRAY=$((STRAY+1)) ;;
  esac
done
for e in docs/*; do
  case "$e" in docs/手册|docs/PRD模板.md) ;; *) log "放错位置：${e}（产品文档应在 ${P}/docs/ 里）"; STRAY=$((STRAY+1)) ;; esac
done
[ "$STRAY" -eq 0 ] && log "通过：根目录没有放错位置的文件。"
cd "$P"
# 5b. 本阶段必须产出的文件
NEED=(); EVI=0
case "$STAGE" in
  "") ;;
  阶段0) NEED=(docs/阶段文档/阶段0-PRD补全清单.md "docs/evidence/$STAGE/是否表.md") ;;
  阶段1) NEED=(docs/阶段文档/技术适配声明.md "docs/evidence/$STAGE/是否表.md") ;;
  阶段2*) NEED=("docs/阶段文档/${STAGE}技术开发文档.md"); EVI=1 ;;
  阶段3-0) NEED=(docs/阶段文档/前端适配声明.md "docs/evidence/$STAGE/是否表.md") ;;
  阶段3*) NEED=(docs/阶段文档/前端适配声明.md "docs/阶段文档/${STAGE}技术开发文档.md"); EVI=1 ;;
  阶段4) NEED=(docs/阶段文档/上线方案摘要.md); EVI=1 ;;
  阶段5) ;;
  *) log "问题：不认识的阶段名 ${STAGE}（应为 阶段0、阶段1、阶段2-1、阶段3-0、阶段3-1、阶段4、阶段5 这类）。"; MISS=$((MISS+1)) ;;
esac
if [ -n "$STAGE" ]; then
  NEED+=(docs/项目状态.md)
  [ "$EVI" -eq 1 ] && NEED+=(README.md "docs/evidence/$STAGE/照着做清单.md" "docs/evidence/$STAGE/是否表.md")
  for f in ${NEED[@]+"${NEED[@]}"}; do
    if [ -s "$f" ]; then log "有：$f"; else log "缺：$f"; MISS=$((MISS+1)); fi
  done
  if [ "$EVI" -eq 1 ]; then
    SHOTS="$(ls "docs/evidence/$STAGE" 2>/dev/null | grep -icE '\.(png|jpe?g)$')"
    if [ "$SHOTS" -gt 0 ]; then log "有：docs/evidence/$STAGE/ 下 $SHOTS 张截图"; else log "缺：docs/evidence/$STAGE/ 下至少一张截图（.png / .jpg）"; MISS=$((MISS+1)); fi
  fi
fi
if [ "$MISS" -gt 0 ] || [ "$STRAY" -gt 0 ]; then R5="不通过（缺 ${MISS} 个文件，${STRAY} 处放错位置）"
elif [ -z "$STAGE" ]; then R5="通过（只查了文件位置；给阶段名才查文件齐全）"
else R5="通过"; fi
log "结果：$R5"

# ---------- 汇总 ----------
sect "汇总（抄进是否表的就是这五行）"
log "是否表第 2 项  mock 测试：      $R1"
log "是否表第 4 项  前端检查与构建： $R4"
log "是否表第 5 项  密钥排除：       $R2"
log "是否表第 6 项  重启后数据恢复： $R3"
log "是否表第 10 项 文件齐全与位置： $R5"
EXIT=0
for r in "$R1" "$R2" "$R3" "$R4" "$R5"; do case "$r" in 不通过*|未配置*) EXIT=1;; esac; done
if [ "$EXIT" -eq 0 ]; then log "总判定：五项全部通过或不适用。"; else log "总判定：有不通过或未配置项，对应是否表只能填\"否\"。"; fi

if [ -n "$STAGE" ]; then
  mkdir -p "docs/evidence/$STAGE"
  cp "$LOG" "docs/evidence/$STAGE/verify-输出.txt"
  log "完整输出已写入：$P/docs/evidence/$STAGE/verify-输出.txt"
fi
rm -f "$LOG"
exit "$EXIT"

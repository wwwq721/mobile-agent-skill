#!/bin/sh
# 手机端 AI 操控技能包 · 安装脚本
# 用法：sh install.sh [--bin /usr/local/bin]
# 幂等：重复执行安全。
set -e

HERE=$(cd "$(dirname "$0")" && pwd)
BIN=${BIN_DIR:-/usr/local/bin}
PY=${PYTHON:-python3}

while [ $# -gt 0 ]; do
  case "$1" in
    --bin) BIN="$2"; shift 2 ;;
    *) echo "未知参数: $1"; exit 2 ;;
  esac
done

echo "== 1/3 检查依赖"
command -v "$PY" >/dev/null 2>&1 || { echo "缺少 python3（apk add python3 / apt install python3）"; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,7) else 1)' || { echo "python3 需要 >= 3.7"; exit 1; }
command -v android-a11y-cli >/dev/null 2>&1 || echo "   提示：没有 android-a11y-cli，screen 技能不可用（浏览器那半不受影响）"
echo "   ok"

echo "== 2/3 安装到 $BIN"
mkdir -p "$BIN"
chmod +x "$HERE/skills/screen/scr" "$HERE/skills/x-browser/bw" 2>/dev/null || true
ln -sf "$HERE/skills/screen/scr"   "$BIN/scr"
ln -sf "$HERE/skills/x-browser/bw" "$BIN/bw"
echo "   scr / bw"

echo "== 3/3 体检"
scr doctor 2>&1 | tail -5 || echo "   scr doctor 未通过（看上面的原因）"
bw state 2>&1 | head -3 || echo "   bw state 未通过（浏览器没开或无障碍没开）"

echo
echo "还需要人工一步："
echo "  手机 设置 → 无障碍 → 打开本 App（否则 scr 报 SERVICE_NOT_RUNNING / 退出码 69）"

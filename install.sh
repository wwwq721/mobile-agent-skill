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

echo "== 1/4 检查依赖"
command -v "$PY" >/dev/null 2>&1 || { echo "缺少 python3（apk add python3 / apt install python3）"; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,7) else 1)' || { echo "python3 需要 >= 3.7"; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "缺少 curl"; exit 1; }
echo "   ok"

echo "== 2/4 命令进 PATH（$BIN）"
mkdir -p "$BIN"
chmod +x "$HERE/skills/phone-browser/xb/xb.sh" \
         "$HERE/skills/phone-browser/bridge/restart.sh" \
         "$HERE/skills/mobile-ops/scripts/mshot.py" \
         "$HERE/skills/mobile-ops/scripts/mloc.py" 2>/dev/null || true
ln -sf "$HERE/skills/phone-browser/xb/xb.sh"      "$BIN/xb"
ln -sf "$HERE/skills/mobile-ops/scripts/mshot.py" "$BIN/mshot"
ln -sf "$HERE/skills/mobile-ops/scripts/mloc.py"  "$BIN/mloc"
echo "   xb / mshot / mloc"

echo "== 3/4 启动桥（127.0.0.1:8765）"
if curl -s -m 2 http://127.0.0.1:8765/status >/dev/null 2>&1; then
  echo "   已在运行"
else
  sh "$HERE/skills/phone-browser/bridge/restart.sh" >/tmp/phone-bridge.log 2>&1 \
    && echo "   已启动" || echo "   启动失败，看 /tmp/phone-bridge.log"
fi

echo "== 4/4 自检"
xb status 2>&1 | head -4
echo
echo "还需要人工两步："
echo "  1) 手机浏览器打开 http://127.0.0.1:8765/xb.user.js 装用户脚本（装前已开的标签要刷新）"
echo "  2) 设置 → 无障碍 → 打开本 App，然后：android-a11y-cli service ping"

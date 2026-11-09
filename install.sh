#!/bin/sh
# 手机端 AI 操控技能包 · 安装脚本
# 用法：sh install.sh [--bin /usr/local/bin] [--no-mcp]
# 只做幂等操作：重复执行安全。
set -e

HERE=$(cd "$(dirname "$0")" && pwd)
BIN=${BIN_DIR:-/usr/local/bin}
PY=${PYTHON:-python3}
DO_MCP=1

while [ $# -gt 0 ]; do
  case "$1" in
    --bin) BIN="$2"; shift 2 ;;
    --no-mcp) DO_MCP=0; shift ;;
    *) echo "未知参数: $1"; exit 2 ;;
  esac
done

echo "== 1/5 检查依赖"
command -v "$PY" >/dev/null 2>&1 || { echo "缺少 python3，先装：apk add python3 / apt install python3"; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 7) else 1)' || { echo "python3 需要 >= 3.7"; exit 1; }
echo "   python3: $(command -v "$PY")"

if [ "$DO_MCP" = 1 ]; then
  command -v minis-mcp-cli >/dev/null 2>&1 || echo "   提示：没找到 minis-mcp-cli，MCP 注册会被跳过（可稍后手动执行见 INSTALL.md）"
fi

echo "== 2/5 装 CLI 到 $BIN"
mkdir -p "$BIN"
chmod +x "$HERE/skills/phone-browser/edge/edge" \
         "$HERE/skills/mobile-ops/scripts/mshot.py" \
         "$HERE/skills/mobile-ops/scripts/mloc.py" 2>/dev/null || true
ln -sf "$HERE/skills/phone-browser/edge/edge"       "$BIN/edge"
ln -sf "$HERE/skills/mobile-ops/scripts/mshot.py"   "$BIN/mshot"
ln -sf "$HERE/skills/mobile-ops/scripts/mloc.py"    "$BIN/mloc"
echo "   edge / mshot / mloc -> $BIN"

echo "== 3/5 启动浏览器桥（127.0.0.1:8765）"
if curl -s -m 2 http://127.0.0.1:8765/status >/dev/null 2>&1; then
  echo "   已在运行"
else
  setsid "$PY" "$HERE/skills/phone-browser/edge/bridge.py" >/tmp/minis-bridge.log 2>&1 &
  sleep 1
  curl -s -m 3 http://127.0.0.1:8765/status >/dev/null 2>&1 \
    && echo "   已启动（日志 /tmp/minis-bridge.log）" \
    || echo "   启动失败，看 /tmp/minis-bridge.log"
fi

echo "== 4/5 注册 MCP（工具名 edge_js / edge_text / edge_click / edge_status）"
if [ "$DO_MCP" = 1 ] && command -v minis-mcp-cli >/dev/null 2>&1; then
  minis-mcp-cli add --name edge \
    --command "$PY" --args "$HERE/skills/phone-browser/edge/mcp_edge.py" \
    --note "Edge 桥：在手机浏览器页面内执行 JS" >/dev/null 2>&1 \
    && echo "   已注册 edge" \
    || echo "   注册失败或已存在，手动命令见 INSTALL.md"
else
  echo "   跳过"
fi

echo "== 5/5 自检"
curl -s -m 3 http://127.0.0.1:8765/status | head -c 200; echo
echo
echo "还需要人工做两件事："
echo "  1. 手机设置里打开本 App 的无障碍服务（设置 → 无障碍），然后跑：android-a11y-cli service ping"
echo "  2. 手机浏览器装篡改猴，访问 http://127.0.0.1:8765/minis.user.js 安装脚本并刷新要操作的标签页"

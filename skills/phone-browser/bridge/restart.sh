#!/bin/sh
# 重启桥：只认「解释器 + 本目录 bridge.py 的真实路径」，不误杀同名脚本或普通 shell。
# 退出码：0 成功；1 旧实例没停掉；2 新实例没起来。
TARGET="$(readlink -f /var/minis/skills/phone-browser/bridge/bridge.py)"
URL="http://127.0.0.1:8765/status"
SELF=$$

pids=$(python3 - "$TARGET" "$SELF" <<'PY'
import os, sys
target, self_pid = os.path.realpath(sys.argv[1]), sys.argv[2]
for pid in os.listdir('/proc'):
    if not pid.isdigit() or pid == self_pid:
        continue
    try:
        raw = open('/proc/%s/cmdline' % pid, 'rb').read().split(b'\0')
    except OSError:
        continue
    args = [p.decode('utf-8', 'ignore') for p in raw if p]
    if len(args) < 2:
        continue
    if 'python' not in os.path.basename(args[0]):
        continue
    if os.path.realpath(args[1]) != target:      # 精确匹配目标文件，不是字符串
        continue
    print(pid)
PY
)

for p in $pids; do
  kill "$p" 2>/dev/null
done

# 等端口真的空出来（最多 3 秒）
i=0
while [ $i -lt 15 ]; do
  if ! curl -s -m 1 -o /dev/null "$URL"; then break; fi
  i=$((i + 1)); sleep 0.2
done
if curl -s -m 1 -o /dev/null "$URL"; then
  echo "restart failed: old instance still owns port" >&2
  exit 1
fi

PYTHONDONTWRITEBYTECODE=1 setsid python3 "$TARGET" >> /tmp/bridge.log 2>&1 &
NEW=$!

i=0
while [ $i -lt 25 ]; do
  if curl -s -m 1 -o /dev/null "$URL"; then
    break
  fi
  i=$((i + 1)); sleep 0.2
done

if ! curl -s -m 1 -o /dev/null "$URL"; then
  echo "restart failed: new instance did not come up" >&2
  exit 2
fi
if ! kill -0 "$NEW" 2>/dev/null; then
  echo "restart failed: new process exited" >&2
  exit 2
fi

echo "restarted pid=$NEW"
curl -s -m 3 "$URL" | head -c 200
echo

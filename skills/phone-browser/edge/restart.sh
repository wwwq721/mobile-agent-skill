#!/bin/sh
# restart the Edge bridge safely (pidfile based, never kills the caller)
PIDF=/tmp/edge_bridge.pid
if [ -f "$PIDF" ]; then
  kill "$(cat $PIDF)" 2>/dev/null
  sleep 0.4
fi
setsid python3 /var/minis/skills/phone-browser/edge/bridge.py > /tmp/bridge.log 2>&1 &
echo $! > "$PIDF"
sleep 1
curl -s -m 3 http://127.0.0.1:8765/status | head -c 200
echo

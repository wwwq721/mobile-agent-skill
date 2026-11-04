#!/usr/bin/env python3
"""Soak test for the Edge bridge: repeated calls over several minutes."""
import json, os, sys, time, urllib.request
from importlib import import_module

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
mcp = import_module("mcp_edge")

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 12
GAP = int(sys.argv[2]) if len(sys.argv) > 2 else 20


def proc_stats():
    try:
        pid = open("/tmp/edge_bridge.pid").read().strip()
        st = open("/proc/%s/status" % pid).read()
        threads = [l.split()[1] for l in st.splitlines() if l.startswith("Threads")][0]
        rss = [l.split()[1] for l in st.splitlines() if l.startswith("VmRSS")][0]
        return int(threads), int(rss) // 1024
    except Exception as e:
        return -1, -1


rows = []
for i in range(1, ROUNDS + 1):
    if i in ():
        os.system("android-a11y-cli input key home >/dev/null 2>&1")
        time.sleep(1.5)
    t0 = time.time()
    r = mcp.call_bridge({"type": "eval", "code": "document.title + '|' + Date.now()"}, timeout=12)
    dt = time.time() - t0
    ok = bool(r.get("ok"))
    tabs = len((mcp.status() or {}).get("tabs") or [])
    th, rss = proc_stats()
    rows.append((i, ok, dt, tabs, th, rss, r.get("error", "")[:40]))
    print("%2d ok=%-5s %5.1fs tabs=%-2d thr=%-3d rss=%dMB %s"
          % (i, ok, dt, tabs, th, rss, "" if ok else r.get("error", "")[:40]), flush=True)
    sleep_for = GAP - (time.time() - t0)
    if sleep_for > 0 and i < ROUNDS:
        time.sleep(sleep_for)

okc = sum(1 for r in rows if r[1])
print("\n--- summary: %d/%d ok, avg %.1fs, max %.1fs, threads %d->%d, rss %d->%dMB"
      % (okc, len(rows), sum(r[2] for r in rows) / len(rows), max(r[2] for r in rows),
         rows[0][4], rows[-1][4], rows[0][5], rows[-1][5]))

#!/usr/bin/env python3
"""极简桥客户端：python3 xbjs.py '<js表达式>' [timeout]
绕开 CLI 的重试逻辑，直接打 /cmd。"""
import json, sys, urllib.error, urllib.request, uuid

BASE = "http://127.0.0.1:8765"


def js(code, timeout=8, target=None, url_contains=None):
    body = {"code": code, "op_id": "x" + uuid.uuid4().hex[:8], "timeout": timeout}
    if target:
        body["tab"] = target
    if url_contains:
        body["url_contains"] = url_contains
    req = urllib.request.Request(BASE + "/cmd", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout + 8) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return json.load(e)  # preserve delivered/acked on 504
        except ValueError:
            return {"ok": False, "error": "HTTP %d" % e.code}


if __name__ == "__main__":
    code = sys.argv[1]
    t = float(sys.argv[2]) if len(sys.argv) > 2 else 8
    d = js(code, t)
    print(d.get("value") if d.get("ok") else json.dumps(d, ensure_ascii=False)[:300])

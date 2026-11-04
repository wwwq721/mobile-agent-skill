#!/usr/bin/env python3
"""Minis <-> Edge bridge. Listens on 127.0.0.1:8765.

The Tampermonkey userscript in Edge long-polls POST /poll and executes jobs
inside the page (full DOM/JS, the user's own login state), posting back
POST /result. CLI/MCP clients submit via POST /cmd and wait for the answer.

Only a visible, waiting poll can take a job. A declared read may be sent a
second time to the same document; other jobs are never redispatched once sent.
"""
import json, math, os, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("BRIDGE_PORT", "8765"))
HERE = os.path.dirname(os.path.abspath(__file__))
TAB_TTL = 60          # forget tabs not seen for this long
PER_TRY = 2.5         # only a declared read may be sent a second time before ACK
CACHE_TTL = 600
MAX_JOBS = 2048
cv = threading.Condition()
pending, jobs, operations, tabs, polling = [], {}, {}, {}, {}


def live_tabs():
    with cv:
        now = time.time()
        for k in list(tabs):
            if k not in polling and now - tabs[k]["seen"] >= TAB_TTL:
                del tabs[k]
        return [dict(t, polling=k in polling) for k, t in tabs.items()]


def chosen(rec):
    w = rec["wire"]
    # A replay may not jump to a different document.
    wanted = w["target"] or rec["owner"]
    candidates = (tabs[t] for t in polling if t in tabs and tabs[t]["visible"]
                  and (not wanted or wanted == t)
                  and (not w["url_contains"] or w["url_contains"] in tabs[t]["url"]))
    best = max(candidates, key=lambda t: (t["seen"], t["focus"]), default=None)
    return best and best["tab"]


def drop(rec):
    jobs.pop(rec["wire"]["id"], None)
    op = rec["wire"]["op_id"]
    if op and operations.get(op) is rec:
        del operations[op]


def submit(b):
    try:
        timeout = float(b.get("timeout", 5))
        if not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ValueError()
    except (TypeError, ValueError):
        return {"ok": False, "error": "timeout must be in (0,120] seconds"}, 400
    end = time.monotonic() + timeout
    op = b.get("op_id")
    if op is not None and (not isinstance(op, str) or not 1 <= len(op) <= 128):
        return {"ok": False, "error": "invalid op_id"}, 400
    sig = (b.get("type", "eval"), b.get("code", ""), b.get("selector", ""),
           b.get("tab") or None, b.get("url_contains") or "", b.get("retry_safe") is True)
    with cv:
        now = time.monotonic()
        for old in list(jobs.values()):
            if old["until"] <= now:
                drop(old)
        r = operations.get(op) if op else None
        first = r is None
        if first:
            if len(jobs) >= MAX_JOBS:
                return {"ok": False, "delivered": False, "error": "bridge job cache full"}, 503
            jid = uuid.uuid4().hex
            w = dict(id=jid, op_id=op, type=sig[0], code=sig[1], selector=sig[2],
                     target=sig[3], url_contains=sig[4])
            r = dict(wire=w, sig=sig, owner=None, sent=0, last=0, ack=None, result=None,
                     closed=False, until=end + CACHE_TTL)
            jobs[jid] = r
            if op:
                operations[op] = r
            pending.append(r)
            cv.notify_all()
        elif sig != r["sig"]:
            return {"ok": False, "error": "op_id already belongs to a different command"}, 409
        while r["result"] is None and not r["closed"]:
            now = time.monotonic()
            if now >= end:
                break
            wait = end - now
            if (first and sig[0] == "eval" and sig[5] and r["sent"] == 1
                    and r["ack"] is None and r not in pending):
                retry_in = r["last"] + PER_TRY - now
                if retry_in <= 0:
                    pending.append(r)
                    cv.notify_all()
                else:
                    wait = min(wait, retry_in)
            cv.wait(wait)
        if r["result"] is not None:
            return r["result"], 200
        if first:
            if r in pending:
                pending.remove(r)
            if not r["sent"]:
                r["closed"] = True
                drop(r)  # nobody received it; the same op_id may safely be retried
            cv.notify_all()
        return {"ok": False, "id": r["wire"]["id"], "op_id": op, "delivered": bool(r["sent"]),
                "tab": r["owner"], "before": (r["ack"] or {}).get("before"),
                "acked": r["ack"] is not None, "ack_url": (r["ack"] or {}).get("url", ""),
                "error": ("result unknown: already dispatched; verify before retrying"
                          if r["sent"] else "timeout: no matching visible tab received this job")}, 504


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200, ctype="application/json"):
        body = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            pass

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def _local_host(self):
        return self.headers.get("Host", "") in ("127.0.0.1:%d" % self.server.server_port,
                                                "localhost:%d" % self.server.server_port)

    def do_GET(self):
        if not self._local_host() or (self.path.startswith("/status") and self.headers.get("Origin") is not None):
            self._send({"ok": False, "error": "local client required"}, 403)
            return
        if self.path.startswith("/xb.user.js"):
            with open(os.path.join(os.path.dirname(HERE), "xb", "minis-xb.user.js"), "rb") as f:
                self._send(f.read(), ctype="text/javascript; charset=utf-8")
        elif self.path.startswith("/minis.user.js"):
            with open(os.path.join(HERE, "minis.user.js"), "rb") as f:
                self._send(f.read(), ctype="text/javascript; charset=utf-8")
        elif self.path.startswith("/status"):
            with cv:
                snapshot = {"build": "xb-20261104-r1", "tabs": live_tabs(), "pending": len(pending)}
            self._send(snapshot)
        else:
            self._send({"ok": True, "hint": "POST /cmd {'code':..., 'url_contains':...}"})

    def do_POST(self):
        if (not self._local_host() or self.headers.get_content_type() != "application/json"
                or (self.path == "/cmd" and self.headers.get("Origin") is not None)):
            self.close_connection = True
            self._send({"ok": False, "error": "local JSON client required"}, 403)
            return
        if self.path == "/presence":
            b = self._body()
            with cv:
                t = tabs.get(b.get("tab"))
                if t:
                    t.update(visible=bool(b.get("visible")), focus=bool(b.get("focus")),
                             seen=time.time(), url=b.get("url", t["url"]), title=b.get("title", t["title"]))
                    cv.notify_all()
            self._send({"ok": bool(t)})
            return
        if self.path == "/poll":
            b = self._body()
            tid = b.get("tab") or "?"
            url = b.get("url", "")
            job = None
            lease = object()
            with cv:
                live_tabs()  # expire old document IDs even without a status reader
                tabs[tid] = {"tab": tid, "url": url, "title": b.get("title", ""), "seen": time.time(),
                             "visible": bool(b.get("visible")), "focus": bool(b.get("focus")), "v": b.get("v")}
                polling[tid] = lease
                cv.notify_all()
                try:
                    end = time.monotonic() + 20
                    while polling.get(tid) is lease and time.monotonic() < end:
                        r = next((item for item in pending if chosen(item) == tid), None)
                        if r is not None:
                            pending.remove(r)
                            wire_v = tabs[tid].get("v")
                            if (r["wire"]["type"] in ("click", "fill") and
                                    (not isinstance(wire_v, (int, float)) or wire_v < 12)):
                                r["result"] = {"ok": False, "delivered": False, "acked": False,
                                               "error": "script_update_required: update the X userscript to 3.1 and reload"}
                                drop(r)
                                cv.notify_all()
                                continue
                            r["owner"], r["last"] = tid, time.monotonic()
                            r["t0"] = time.monotonic()
                            r["sent"] += 1
                            job = r["wire"]
                            cv.notify_all()
                            break
                        cv.wait(max(0.001, end - time.monotonic()))
                finally:
                    if polling.get(tid) is lease:
                        del polling[tid]
                    cv.notify_all()
            if job:
                print("POLL %s got %s" % (tid, job["id"]), flush=True)
            self._send(job or {})
            return
        if self.path in ("/ack", "/result"):
            b = self._body()
            with cv:
                r = jobs.get(b.get("id", ""))
                accepted = r is not None and r["sent"] > 0 and (
                    not b.get("tab") or b["tab"] == r["owner"])
                if accepted:
                    if r in pending:
                        pending.remove(r)
                    if self.path == "/ack":
                        if r["ack"] is None:
                            print("ACK %s +%.0fms" % (b.get("id"), (time.monotonic()-r.get("t0",time.monotonic()))*1000), flush=True)
                            r["ack"] = {"url": b.get("url", ""), "before": b.get("before")}
                    elif r["result"] is None:
                        # The deployed userscript returns job.id, not op_id.
                        r["result"] = dict(b, op_id=r["wire"]["op_id"], tab=r["owner"])
                        print("RESULT %s +%.0fms" % (b.get("id"), (time.monotonic()-r.get("t0",time.monotonic()))*1000), flush=True)
                        r["until"] = time.monotonic() + CACHE_TTL
                    cv.notify_all()
            self._send({"ok": accepted}, 200 if accepted else 404)
            return
        if self.path == "/cmd":
            answer, code = submit(self._body())
            self._send(answer, code)
            return
        self._send({"ok": False, "error": "unknown endpoint"}, 404)


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    srv.daemon_threads = True
    print("bridge on http://127.0.0.1:%d" % PORT, flush=True)
    srv.serve_forever()

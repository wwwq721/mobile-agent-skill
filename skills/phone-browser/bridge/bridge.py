#!/usr/bin/env python3
"""Minis <-> X 浏览器 bridge. Listens on 127.0.0.1:8765.

The userscript inside X 浏览器 (com.mmbox.xbrowser) long-polls POST /poll and
executes jobs inside the page (full DOM/JS, the user's own login state), posting
back POST /result. Clients submit via POST /api/<op> and wait for the answer.

Only a visible, waiting poll can take a job. A declared read may be sent a
second time to the same document; other jobs are never redispatched once sent.
"""
import hashlib, json, math, os, sys, threading, time, uuid
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("BRIDGE_PORT", "8765"))
HERE = os.path.dirname(os.path.abspath(__file__))
TAB_TTL = 60          # forget tabs not seen for this long
PER_TRY = 2.5         # only a declared read may be sent a second time before ACK
CACHE_TTL = 600
MAX_JOBS = 2048
MAX_CACHE_BYTES = 16 * 1024 * 1024
MAX_RESULT_BYTES = 4 * 1024 * 1024
MAX_BODY_BYTES = 8 * 1024 * 1024
MAX_CONTROL_BYTES = 64 * 1024
BODY_READ_SECONDS = 10
RECORD_BYTES = 8192  # bounded bookkeeping, including a terminal error when full
CACHE_BYTES = 0
BODY_SLOTS = {"command": threading.BoundedSemaphore(2), "result": threading.BoundedSemaphore(2)}
cv = threading.Condition()
pending, jobs, operations, tabs, polling = [], {}, {}, {}, {}


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8", "backslashreplace")


class PackedJSON(Mapping):
    """Keep a result once as bytes; repeated HTTP replies share those bytes."""
    __slots__ = ("body", "ok", "status")

    def __init__(self, body, ok=None, status=200):
        self.body, self.ok, self.status = body, ok, status

    def as_dict(self):
        return json.loads(self.body)

    def __getitem__(self, key):
        if key == "ok" and self.ok is not None:
            return self.ok
        return self.as_dict()[key]

    def __iter__(self):
        return iter(self.as_dict())

    def __len__(self):
        return len(self.as_dict())


def account(rec):
    global CACHE_BYTES
    if not rec.get("tracked"):
        return
    charge = RECORD_BYTES + rec["wire_bytes"] + rec["ack_bytes"] + rec["result_bytes"] + rec["reserved"]
    CACHE_BYTES += charge - rec["charge"]
    rec["charge"] = charge


def trim_wire(rec):
    # The digest retains command identity after execution, without its large JS body.
    rec["wire"] = {k: v for k, v in rec["wire"].items()
                   if k not in ("code", "selector", "target", "url_contains")}
    rec["wire"].update(target=None, url_contains="")
    rec["wire_bytes"] = 0
    account(rec)


def terminal_error(rec, message):
    return {"ok": False, "id": rec["wire"]["id"], "op_id": rec["wire"]["op_id"],
            "delivered": bool(rec["sent"]), "acked": rec["acked"], "error": message}


def store_result(rec, value):
    body, status = json_bytes(value), 200
    if len(body) > MAX_RESULT_BYTES:
        value = terminal_error(rec, "result_too_large: response exceeds %d bytes; do not repeat the action" % MAX_RESULT_BYTES)
        body, status = json_bytes(value), 413
    trim_wire(rec)
    rec["reserved"] = 0
    account(rec)
    charge = len(body)
    if CACHE_BYTES + charge > MAX_CACHE_BYTES:
        # A late result may arrive after its waiter's reservation was released.
        # Retain a small terminal record rather than deleting the operation identity.
        value = terminal_error(rec, "result_not_cached: byte budget full; result was received, do not repeat the action")
        body, status, charge = json_bytes(value), 507, 0
    rec["result"] = PackedJSON(body, value.get("ok"), status)
    rec["result_bytes"] = charge
    rec["until"] = time.monotonic() + CACHE_TTL
    account(rec)


def script_version():
    """桥对外提供的用户脚本版本（解析 xb/minis-xb.user.js 的 @version）。"""
    try:
        path = os.path.join(os.path.dirname(HERE), "xb", "minis-xb.user.js")
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("// @version"):
                    return line.split()[-1].strip()
    except Exception:
        pass
    return "?"


LOG_PATH = "/tmp/bridge.log"
LOG_MAX = 4 * 1024 * 1024


def log(*a, **kw):
    """带轮转的日志：超过 4MB 就把当前文件挪到 .1，只留一份历史。"""
    try:
        if os.path.getsize(LOG_PATH) > LOG_MAX:
            os.replace(LOG_PATH, LOG_PATH + ".1")
    except OSError:
        pass
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            print(*a, file=f, **kw)
    except Exception:
        pass


def api_call(op, b, received_at=None):
    """高层操作入口：curl 直接调用（~0.1s）。语义与 MCP 路径保持一致。"""
    import json as _json
    import base64
    import xbops

    dumps = _json.dumps
    try:
        t = float(b.get("timeout", 8))
        if not math.isfinite(t) or not 0 < t <= 120:
            raise ValueError()
    except (ValueError, TypeError):
        return {"ok": False, "error": "timeout must be in (0,120] seconds"}, 400
    op_id = b["op_id"] if "op_id" in b else uuid.uuid4().hex
    if not isinstance(op_id, str) or not 1 <= len(op_id) <= 128:
        return {"ok": False, "error": "invalid op_id"}, 400
    deadline = int(((time.time() if received_at is None else received_at) + t) * 1000)

    def execute(code, retry_safe=False, kind="eval", selector=""):
        w = {"code": code, "timeout": t, "op_id": op_id, "deadline": deadline}
        if kind != "eval":
            w["type"] = kind
        if selector:
            w["selector"] = selector
        if retry_safe:
            w["retry_safe"] = True
        reply, status = submit(w, received_at)
        if status != 200:
            return reply, status
        if reply.get("ok") is not True:
            return reply, 422
        if op in ("click", "fill"):
            if isinstance(reply, PackedJSON):
                reply = reply.as_dict()
            try:
                action = _json.loads(reply.get("value", ""))
            except (TypeError, ValueError):
                action = None
            if isinstance(action, dict) and action.get("ok") is False:
                return dict(reply, ok=False, error=action.get("error") or "page rejected the action"), 422
        return reply, 200

    if op == "js":
        return execute(b["code"])
    if op == "text":
        sel = b.get("selector")
        code = ("(function(){var e=document.querySelector(%s);return e?(e.innerText||''):'no element';})()"
                % dumps(sel)) if sel else xbops.TEXT_JS
        return execute(code, retry_safe=True)
    if op == "snapshot":
        code = xbops.SNAPSHOT_JS.replace("__OFFSET__", str(int(b.get("offset") or 0))) \
                                 .replace("__PAGE__", str(int(b.get("limit") or 70)))
        return execute(code, retry_safe=True)
    if op in ("click", "fill"):
        sel = b.get("selector")
        if not isinstance(sel, str) or not sel:
            return {"ok": False, "error": "selector required"}, 400
        if op == "click":
            # 走页面侧点击：它会回 /ack，桥据此推断跳转是否落地（见 submit 尾部）
            return execute("", kind="click", selector=sel)
        val = b.get("value")
        if not isinstance(val, str):
            return {"ok": False, "error": "value must be a string"}, 400
        # 填表用 FILL_JS：checkbox/radio/select/contenteditable 的语义全在里面，页面侧那份没有
        return execute(xbops.FILL_JS % (dumps(sel), dumps(val)))
    return {"ok": False, "error": "unknown api: " + op}, 404

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
    # 用 rAF 帧率判“真前台”：后台标签被系统节流到 0–1 fps，前台 ~60。
    # document.hasFocus() 在 X 浏览器 WebView 里恒为 false，所以不能用它。
    best = max(candidates, key=lambda t: (t.get("raf", -1) >= 8, t.get("raf", -1), t["seen"]), default=None)
    return best and best["tab"]


def drop(rec):
    global CACHE_BYTES
    if rec.get("tracked"):
        CACHE_BYTES -= rec["charge"]
        rec["tracked"], rec["charge"] = False, 0
    jobs.pop(rec["wire"]["id"], None)
    try:
        if rec in pending:
            pending.remove(rec)
    except ValueError:
        pass
    op = rec["wire"]["op_id"]
    if op and operations.get(op) is rec:
        del operations[op]


def drop_expired_locked(now):
    for rec in list(jobs.values()):
        if rec["until"] <= now and not rec.get("waiters"):
            drop(rec)


class BridgeServer(ThreadingHTTPServer):
    next_cache_check = 0.0

    def service_actions(self):
        super().service_actions()
        now = time.monotonic()
        if now >= self.next_cache_check:
            self.next_cache_check = now + 15
            with cv:
                drop_expired_locked(now)


def submit(b, received_at=None):
    try:
        timeout = float(b.get("timeout", 5))
        if not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ValueError()
    except (TypeError, ValueError):
        return {"ok": False, "error": "timeout must be in (0,120] seconds"}, 400
    remaining = timeout if received_at is None else timeout - max(0, time.time() - received_at)
    end = time.monotonic() + max(0, remaining)
    op = b.get("op_id")
    if op is not None and (not isinstance(op, str) or not 1 <= len(op) <= 128):
        return {"ok": False, "error": "invalid op_id"}, 400
    kind, code, selector = b.get("type", "eval"), b.get("code", ""), b.get("selector", "")
    target, url = b.get("tab") or None, b.get("url_contains") or ""
    retry_safe = b.get("retry_safe") is True
    if (kind not in ("eval", "click", "fill") or not all(isinstance(v, str) for v in (code, selector, url))
            or (target is not None and (not isinstance(target, str) or len(target) > 256))):
        return {"ok": False, "error": "invalid command fields", "op_id": op, "delivered": False}, 400
    digest = hashlib.sha256()
    for chunk in json.JSONEncoder(ensure_ascii=False, separators=(",", ":")).iterencode(
            (kind, code, selector, target, url, retry_safe)):
        digest.update(chunk.encode("utf-8", "backslashreplace"))
    sig = digest.digest()
    with cv:
        now = time.monotonic()
        drop_expired_locked(now)
        r = operations.get(op) if op else None
        first = r is None
        if first:
            try:
                supplied_deadline = float(b.get("deadline") or 0) / 1000.0
            except (TypeError, ValueError):
                supplied_deadline = 0.0
            if remaining <= 0 or (supplied_deadline and time.time() >= supplied_deadline):
                return {"ok": False, "op_id": op, "delivered": False, "acked": False,
                        "error": "deadline_exceeded: request budget expired before admission"}, 504
            wall_now = time.time()
            recent = [t for t in live_tabs() if 0 <= wall_now - t["seen"] < 4
                      and (not target or t["tab"] == target)
                      and (not url or url in (t.get("url") or ""))]
            # Several fast polls can repeat the same frame sample. A visible page can still take work.
            if recent and all(not t["visible"] and t.get("bg", 0) >= 3 for t in recent):
                return {"ok": False, "delivered": False, "acked": False, "op_id": op,
                        "error": "needs_foreground: 匹配的页面最近均报告隐藏，请切回浏览器后重试",
                        "backgrounded_tabs": [t["tab"] for t in recent]}, 409
            if len(jobs) >= MAX_JOBS:
                return {"ok": False, "delivered": False, "error": "bridge job cache full"}, 503
            jid = uuid.uuid4().hex
            try:
                dl = float(b.get("deadline") or 0) / 1000.0
            except (TypeError, ValueError):
                dl = 0.0
            w = dict(id=jid, op_id=op, type=kind, code=code, selector=selector,
                     target=target, url_contains=url,
                     deadline=int(dl * 1000) if dl else int(((time.time() if received_at is None else received_at) + timeout) * 1000))
            wire_bytes = sum(sys.getsizeof(v) for v in w.values() if isinstance(v, str))
            if wire_bytes > MAX_BODY_BYTES:
                return {"ok": False, "op_id": op, "delivered": False,
                        "error": "command_too_large: cached command exceeds byte limit"}, 413
            reservation = MAX_RESULT_BYTES + MAX_CONTROL_BYTES
            charge = RECORD_BYTES + wire_bytes + reservation
            if CACHE_BYTES + charge > MAX_CACHE_BYTES:
                return {"ok": False, "op_id": op, "delivered": False, "acked": False,
                        "error": "bridge cache full: byte budget exhausted before dispatch"}, 503
            r = dict(wire=w, sig=sig, owner=None, sent=0, last=0, ack=None, result=None,
                     acked=False, closed=False, until=end + CACHE_TTL, waiters=0,
                     wire_bytes=wire_bytes, ack_bytes=0, result_bytes=0, reserved=reservation,
                     charge=0, tracked=True)
            account(r)
            jobs[jid] = r
            if op:
                operations[op] = r
            pending.append(r)
            cv.notify_all()
        elif sig != r["sig"]:
            return {"ok": False, "error": "op_id already belongs to a different command"}, 409
        if r["result"] is None and not first and not r["reserved"]:
            reservation = MAX_RESULT_BYTES + MAX_CONTROL_BYTES
            if CACHE_BYTES + reservation > MAX_CACHE_BYTES:
                return terminal_error(r, "cache_wait_full: action is already known; retry the same op_id later"), 503
            r["reserved"] = reservation
            account(r)
        r["waiters"] += 1
        try:
            while r["result"] is None and not r["closed"]:
                now = time.monotonic()
                if now >= end:
                    break
                wait = end - now
                if (first and kind == "eval" and retry_safe and r["sent"] == 1
                        and not r["acked"] and r not in pending):
                    retry_in = r["last"] + PER_TRY - now
                    if retry_in <= 0:
                        pending.append(r)
                        cv.notify_all()
                    else:
                        wait = min(wait, retry_in)
                cv.wait(wait)
        finally:
            r["waiters"] -= 1
            if not r["waiters"]:
                r["reserved"] = 0
                if r["result"] is None:
                    trim_wire(r)
                account(r)
        if r["result"] is not None:
            return r["result"], getattr(r["result"], "status", 200)
        if first:
            if r in pending:
                pending.remove(r)
            if not r["sent"]:
                r["closed"] = True
                drop(r)  # nobody received it; the same op_id may safely be retried
            cv.notify_all()
        if r.get("ack") and r["wire"]["type"] == "click":
            ack = r["ack"]
            before = ack.get("before")
            expected = before.get("expected_url") if isinstance(before, dict) else None
            owner = tabs.get(r["owner"])
            if (expected and owner and ack["url"] and expected != ack["url"]
                    and ack.get("owner_url") == ack["url"] and owner["url"] == expected):
                return {"ok": True, "inferred": True, "landed_url": expected, "acked_url": ack["url"],
                        "note": "the acknowledging document subsequently reported the expected URL",
                        "id": r["wire"]["id"], "op_id": op, "delivered": True, "acked": True}, 200
        return {"ok": False, "id": r["wire"]["id"], "op_id": op, "delivered": bool(r["sent"]),
                "tab": r["owner"], "before": (r["ack"] or {}).get("before"),
                "acked": r["acked"], "ack_url": (r["ack"] or {}).get("url", ""),
                "error": ("result unknown: already dispatched; verify before retrying"
                          if r["sent"] else "timeout: no matching visible tab received this job")}, 504


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200, ctype="application/json"):
        body = obj.body if isinstance(obj, PackedJSON) else (obj if isinstance(obj, bytes) else json_bytes(obj))
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            pass

    def _body(self, raw=False):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return "" if raw else {}
        data = bytearray()
        previous_timeout = self.connection.gettimeout()
        try:
            while len(data) < n:
                remaining = self._request_body_end - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("total request body budget expired")
                self.connection.settimeout(remaining)
                # read1 returns after one receive; read(n) resets its inactivity
                # timeout internally for every trickled byte and can wait forever.
                chunk = self.rfile.read1(min(64 * 1024, n - len(data)))
                if not chunk:
                    raise ValueError("incomplete request body")
                data.extend(chunk)
        finally:
            self.connection.settimeout(previous_timeout)
        if raw:
            return data.decode("utf-8", "replace")
        value = json.loads(data or b"{}")
        if not isinstance(value, dict):
            raise ValueError("expected a JSON object")
        return value

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
        elif self.path.startswith("/status"):
            with cv:
                ver = script_version()
                tl = live_tabs()
                stale = [t["tab"] for t in tl if (t.get("sv") or "") != ver]
                snapshot = {"build": "xb-20261104-r1", "script_version": ver,
                            "tabs": tl, "pending": len(pending),
                            "cache": {"used_bytes": CACHE_BYTES, "limit_bytes": MAX_CACHE_BYTES,
                                      "reserved_bytes": sum(r["reserved"] for r in jobs.values()),
                                      "jobs": len(jobs), "result_limit_bytes": MAX_RESULT_BYTES},
                            "stale_tabs": stale,
                            "hint": ("有标签跑的是旧脚本，打开 http://127.0.0.1:8765/xb.user.js 点安装" if stale else "")}
            self._send(snapshot)
        else:
            self._send({"ok": True, "hint": "POST /api/{js,text,snapshot,click,fill} ; GET /status"})

    def do_POST(self):
        self._request_started = time.time()
        self._request_body_end = time.monotonic() + BODY_READ_SECONDS
        raw_ok = self.path == "/api/raw"              # 原文 JS 端点：body 不是 JSON
        # 只接受"本地命令行"：网页发起的请求一定带 Origin（跨站时可能是 "null"），
        # 或者带 Sec-Fetch-Site != none。两者命中任一即拒绝，避免任意网页借 127.0.0.1 操控浏览器。
        origin = self.headers.get("Origin")
        site = (self.headers.get("Sec-Fetch-Site") or "").lower()
        from_web = origin is not None or (site and site != "none")
        if (from_web or not self._local_host()
                or (not raw_ok and self.headers.get_content_type() != "application/json")):
            self.close_connection = True
            self._send({"ok": False, "error": "local CLI only (web origins are rejected)"}, 403)
            return
        try:
            size = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            size = -1
        limit = MAX_CONTROL_BYTES if self.path in ("/poll", "/presence", "/ack") else MAX_BODY_BYTES
        if size < 0 or self.headers.get("Transfer-Encoding"):
            self.close_connection = True
            self._send({"ok": False, "error": "invalid request length"}, 400)
            return
        if size > limit:
            self.close_connection = True
            self._send({"ok": False, "error": "request_too_large: limit is %d bytes" % limit}, 413)
            return
        previous_timeout = self.connection.gettimeout()
        try:
            self.connection.settimeout(10)
            if size > MAX_CONTROL_BYTES:
                # Commands may wait for the page; results must use a separate lane.
                lane = "result" if self.path == "/result" else "command"
                slot = BODY_SLOTS[lane]
                if lane == "command" and not slot.acquire(blocking=False):
                    self.close_connection = True
                    error = {"ok": False, "error": "input_busy: request not admitted; retry only the same op_id"}
                    op = self.headers.get("X-Minis-Op-Id")
                    if op:
                        error["op_id"] = op
                        with cv:
                            known = operations.get(op)
                            error.update(delivered=bool(known and known["sent"]), acked=bool(known and known["acked"]))
                    self._send(error, 503)
                    return
                if lane == "result":
                    slot.acquire()
                try:
                    self._dispatch_post()
                finally:
                    slot.release()
            else:
                self._dispatch_post()
        except TimeoutError:
            self.close_connection = True
            self._send({"ok": False, "error": "request body timed out"}, 408)
        except (ValueError, UnicodeError, RecursionError) as error:
            self.close_connection = True
            self._send({"ok": False, "error": "invalid JSON request: %s" % error}, 400)
        finally:
            try:
                self.connection.settimeout(previous_timeout)
            except OSError:
                pass

    def _dispatch_post(self):
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
            if not isinstance(tid, str) or len(tid) > 256:
                self._send({"ok": False, "error": "invalid tab id"}, 400)
                return
            url = b.get("url", "")
            job = None
            lease = object()
            with cv:
                live_tabs()  # expire old document IDs even without a status reader
                tabs[tid] = {"tab": tid, "url": url, "title": b.get("title", ""), "seen": time.time(),
                             "visible": bool(b.get("visible")), "focus": bool(b.get("focus")), "v": b.get("v"), "sv": b.get("sv"),
                             "raf": b.get("raf") if isinstance(b.get("raf"), (int, float)) else -1,
                             "bg": (tabs.get(tid, {}).get("bg", 0) + 1) if (isinstance(b.get("raf"), (int, float)) and 0 <= b.get("raf") < 8) else 0}
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
                            if r["wire"].get("deadline") and time.time() * 1000 > r["wire"]["deadline"]:
                                r["result"] = {"ok": False, "delivered": False, "acked": False,
                                               "error": "deadline_exceeded: 任务在投递前就已过期，未执行"}
                                r["until"] = time.monotonic() + CACHE_TTL
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
                log("POLL %s got %s" % (tid, job["id"]), flush=True)
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
                        if not r["acked"]:
                            log("ACK %s +%.0fms" % (b.get("id"), (time.monotonic()-r.get("t0",time.monotonic()))*1000), flush=True)
                            owner = tabs.get(r["owner"]) or {}
                            r["acked"] = True
                            body = json_bytes({"url": b.get("url", ""), "before": b.get("before"),
                                               "owner_url": owner.get("url")})
                            if r["reserved"]:
                                r["reserved"] = max(0, r["reserved"] - MAX_CONTROL_BYTES)
                            account(r)
                            if len(body) <= MAX_CONTROL_BYTES and CACHE_BYTES + len(body) <= MAX_CACHE_BYTES:
                                r["ack"] = PackedJSON(body)
                                r["ack_bytes"] = len(body)
                                account(r)
                    elif r["result"] is None:
                        # The deployed userscript returns job.id, not op_id.
                        store_result(r, dict(b, op_id=r["wire"]["op_id"], tab=r["owner"]))
                        log("RESULT %s +%.0fms" % (b.get("id"), (time.monotonic()-r.get("t0",time.monotonic()))*1000), flush=True)
                        r["until"] = time.monotonic() + CACHE_TTL
                    cv.notify_all()
            self._send({"ok": accepted}, 200 if accepted else 404)
            return
        if self.path.startswith("/api/"):
            op = self.path[5:]
            if op == "raw":
                op = "js"
                b = {"code": self._body(raw=True), "timeout": self.headers.get("X-Minis-Timeout", 15)}
            else:
                b = self._body()
            if not isinstance(b, dict):
                self._send({"ok": False, "error": "expected a JSON object"}, 400)
                return
            header_id = self.headers.get("X-Minis-Op-Id")
            if header_id is not None:
                if "op_id" in b and b["op_id"] != header_id:
                    self._send({"ok": False, "error": "conflicting op_id"}, 400)
                    return
                b["op_id"] = header_id
            try:
                answer, code = api_call(op, b, self._request_started)
            except (KeyError, TypeError, ValueError) as e:
                answer, code = {"ok": False, "error": "invalid api input: %s" % e}, 400
            except Exception as e:
                answer, code = {"ok": False, "error": "api: %s" % e}, 500
            self._send(answer, code)
            return
        self._send({"ok": False, "error": "unknown endpoint"}, 404)


if __name__ == "__main__":
    srv = BridgeServer(("127.0.0.1", PORT), H)
    srv.daemon_threads = True
    log("bridge on http://127.0.0.1:%d" % PORT, flush=True)
    srv.serve_forever()

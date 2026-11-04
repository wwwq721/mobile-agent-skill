#!/usr/bin/env python3
"""MCP server: control the phone's Edge browser through the Tampermonkey bridge."""
import json, os, subprocess, sys, time, urllib.error, urllib.request, uuid

BRIDGE = "http://127.0.0.1:8765"
HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.environ.get("MINIS_BROWSER_PACKAGE", "com.mmbox.xbrowser")  # explicit edge_open only

TEXT_JS = r"""(function(){
  function walk(root){
    var s = root.innerText || '';
    var els = root.querySelectorAll('*');
    for (var i=0;i<els.length;i++){ if (els[i].shadowRoot) s += '\n' + walk(els[i].shadowRoot); }
    return s;
  }
  var out = document.body ? walk(document.body) : '';
  var fs = document.querySelectorAll('iframe');
  for (var i=0;i<fs.length;i++){ try { if (fs[i].contentDocument && fs[i].contentDocument.body) out += '\n' + walk(fs[i].contentDocument.body); } catch(e){} }
  return out.replace(/\n{3,}/g,'\n\n');
})()"""

SEL_FN = r"""
  function sel(el){
    function unique(q){ try { var a=document.querySelectorAll(q); return a.length===1 && a[0]===el; } catch(_){ return false; } }
    var tag=el.localName, esc=CSS.escape;
    if(el.id && unique('#'+esc(el.id))) return '#'+esc(el.id);
    for (var key of ['data-testid','data-test','name','aria-label','href','title']) {
      var v=el.getAttribute(key), q=v && tag+'['+key+'='+esc(v)+']';
      if(q && unique(q)) return q;
    }
    var parts=[], cur=el;
    while(cur && cur.nodeType===1 && parts.length<8){
      var i=1, p=cur; while((p=p.previousElementSibling)) if(p.localName===cur.localName) i++;
      parts.unshift(cur.localName+':nth-of-type('+i+')');
      var path=parts.join(' > '); if(unique(path)) return path;
      cur=cur.parentElement;
    }
    return null;
  }
  function label(el){
    return (el.getAttribute('aria-label') || el.innerText || el.getAttribute('title') ||
      el.placeholder || (/^(button|submit|reset)$/.test(el.type) ? el.value : '') || '').trim().slice(0,80);
  }
  function sig(el){
    return JSON.stringify([el.localName,el.getAttribute('role'),el.getAttribute('type'),el.getAttribute('name'),
      el.getAttribute('href'),el.getAttribute('formaction'),el.getAttribute('aria-label'),label(el)]);
  }
  function vis(el){ var r = el.getBoundingClientRect(); return r.width > 4 && r.height > 4 && r.bottom > 0 && r.top < innerHeight; }
"""

SNAPSHOT_JS = r"""(function(){
""" + SEL_FN + r"""
  var inter = [], serial=Array.from(crypto.getRandomValues(new Uint32Array(3)),function(x){return x.toString(36);}).join('-');
  var book={url:location.href,nodes:new Map(),signature:sig};
  document[Symbol.for('minis.snapshot.v1')]=book;
  var nodes = document.querySelectorAll('a,button,input,select,textarea,[role=button],[role=tab],[onclick]');
  for (var i = 0; i < nodes.length && inter.length < 70; i++) {
    var el = nodes[i]; if (!vis(el)) continue;
    var ref='minis-ref:'+serial+':'+inter.length;
    book.nodes.set(ref,{node:el,sig:sig(el)});
    inter.push({tag:el.localName,label:label(el).slice(0,40),index:inter.length,ref:ref,sel:sel(el)});
  }
  var ov = [];
  var cand = document.querySelectorAll('[role=dialog],dialog,[class*=modal],[class*=popup],[class*=drawer],[class*=dialog]');
  for (var j = 0; j < cand.length && ov.length < 6; j++) {
    var e = cand[j];
    if (getComputedStyle(e).display === 'none' || getComputedStyle(e).visibility === 'hidden' || !vis(e)) continue;
    var r = e.getBoundingClientRect();
    if (r.width < 30 || r.height < 80) continue;
    ov.push({sel: sel(e), text: (e.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 160)});
  }
  var txt = '';
  try { txt = document.body ? document.body.innerText.replace(/\n{3,}/g, '\n\n').slice(0, 4000) : ''; } catch (e) {}
  return JSON.stringify({url: location.href, title: document.title, snapshot_id:serial, overlays: ov, interactive: inter, text: txt});
})()"""

def ensure_bridge():
    try:
        urllib.request.urlopen(BRIDGE + "/status", timeout=1)
        return
    except Exception:
        pass
    log = open("/tmp/bridge.log", "a")
    subprocess.Popen([sys.executable, os.path.join(HERE, "bridge.py")],
                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    for _ in range(20):
        time.sleep(0.15)
        try:
            urllib.request.urlopen(BRIDGE + "/status", timeout=1)
            return
        except Exception:
            continue


ensure_bridge()


def _post(payload, timeout):
    req = urllib.request.Request(BRIDGE + "/cmd", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:          # 504 的响应体里有 delivered 标记，必须读出来
        try:
            return json.loads(e.read())
        except Exception:
            return {"ok": False, "error": "HTTP %d" % e.code}
    except Exception as e:
        return {"ok": False, "error": "%s" % e}


def call_bridge(payload, timeout=5):
    # Passive reads never wake another browser or reuse an implicit host filter.
    # The server deadline comes first so its delivered/acked detail reaches the tool.
    payload = dict(payload)
    try:
        budget = float(payload.get("timeout", timeout))
        if not 0 < budget <= 120:
            raise ValueError()
    except (TypeError, ValueError):
        return {"ok": False, "error": "timeout must be in (0,120] seconds"}
    payload["timeout"] = budget
    payload.setdefault("op_id", uuid.uuid4().hex)
    result = _post(payload, budget + 2)
    result.setdefault("op_id", payload["op_id"])
    return result


def status():
    try:
        with urllib.request.urlopen(BRIDGE + "/status", timeout=5) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


TOOLS = [
    {
        "name": "edge_open",
        "description": "按要求打开网址并切到前台（默认 X，可设置 MINIS_BROWSER_PACKAGE），可能会新建标签。已有页面直接读取。",
        "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
    },
    {
        "name": "edge_snapshot",
        "description": "页面快照：可见文字 + 可交互元素（带 CSS 选择器）+ 已弹出的浮层/对话框。找按钮、判断弹窗是否存在都用它，不要靠猜 innerText。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "edge_text",
        "description": "读取页面正文，含 shadow DOM 与同源 iframe。只返回文本，拿不到未挂载的弹层。",
        "inputSchema": {"type": "object", "properties": {"selector": {"type": "string", "description": "可选 CSS 选择器"}}},
    },
    {
        "name": "edge_js",
        "description": "在当前页面执行 JavaScript 表达式，返回结果（对象自动 JSON）。支持返回 Promise。",
        "inputSchema": {
            "type": "object",
            "properties": {"code": {"type": "string"}, "timeout": {"type": "number"}},
            "required": ["code"],
        },
    },
    {
        "name": "edge_click",
        "description": "优先把本次快照的 ref 填入 selector；也可用只匹配一个元素的 CSS。发出一次点击。若已送达但无结果，先核验当前页面；再次调用是新动作。",
        "inputSchema": {"type": "object", "properties": {"selector": {"type": "string"}, "snapshot_id": {"type": "string"}, "index": {"type": "integer", "minimum": 0}}, "oneOf": [{"required": ["selector"]}, {"required": ["snapshot_id", "index"]}]},
    },
    {
        "name": "edge_fill",
        "description": "用本次快照的 ref 或唯一 CSS 填写输入框并触发 input/change。",
        "inputSchema": {
            "type": "object",
            "properties": {"selector": {"type": "string"}, "value": {"type": "string"}, "snapshot_id": {"type": "string"}, "index": {"type": "integer", "minimum": 0}},
            "required": ["value"], "oneOf": [{"required": ["selector"]}, {"required": ["snapshot_id", "index"]}],
        },
    },
    {
        "name": "edge_status",
        "description": "桥接与标签页状态（判断 Edge 是否在前台、有无应答）。",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def run_tool(name, args):
    if name in ("edge_click", "edge_fill"):
        selector = args.get("selector")
        if "snapshot_id" in args or "index" in args:
            sid, idx = args.get("snapshot_id"), args.get("index")
            if selector is not None or not isinstance(sid, str) or not sid or type(idx) is not int or idx < 0:
                return {"ok": False, "error": "supply one selector/ref OR snapshot_id and nonnegative index"}
            selector = "minis-ref:%s:%d" % (sid, idx)
        if not isinstance(selector, str) or not selector:
            return {"ok": False, "error": "missing selector/ref"}
    if name == "edge_open":
        url = args["url"]
        scheme, rest = ("https", url) if "://" not in url else url.split("://", 1)
        subprocess.run(["android-open", "intent://%s#Intent;scheme=%s;package=%s;end"
                        % (rest.replace("#", "%23"), scheme, PKG)], capture_output=True, text=True)
        try:
            with open("/tmp/edge_target_url", "w") as f:
                f.write(url)
        except Exception:
            pass
        host = rest.split("/")[0].replace("%23", "#")
        for _ in range(40):                      # 等这一页的脚本真正连上，不是等任意标签
            time.sleep(0.25)
            st = status()
            if any(host in (t.get("url") or "") and time.time() - t.get("seen", 0) < 1.5
                   for t in (st.get("tabs") or [])):
                return {"ok": True, "tabs": len(st["tabs"]), "url": url}
        return {"ok": False, "error": "目标浏览器没有报告此页面；请核对前台和用户脚本。"}
    if name == "edge_snapshot":
        return call_bridge({"type": "eval", "code": SNAPSHOT_JS, "retry_safe": True})
    if name == "edge_text":
        code = TEXT_JS if not args.get("selector") else \
            "(function(){var e=document.querySelector(%s);return e?(e.innerText||''):'no element';})()" % json.dumps(args["selector"])
        return call_bridge({"type": "eval", "code": code, "retry_safe": True})
    if name == "edge_js":
        return call_bridge({"type": "eval", "code": args["code"], "timeout": args.get("timeout", 25)})
    if name == "edge_click":
        return call_bridge({"type": "click", "selector": selector})
    if name == "edge_fill":
        return call_bridge({"type": "fill", "selector": selector, "code": args["value"]})
    if name == "edge_status":
        return status()
    return {"ok": False, "error": "unknown tool " + name}


def send(msg):
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        mid, method = req.get("id"), req.get("method")
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                "serverInfo": {"name": "edge-bridge", "version": "1.4.0"}}})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            p = req.get("params") or {}
            res = run_tool(p.get("name"), p.get("arguments") or {})
            text = res.get("value") if (res.get("ok") and res.get("value") is not None) \
                else json.dumps(res, ensure_ascii=False)
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": text}], "isError": not res.get("ok", True)}})
        elif mid is not None:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "unknown method"}})


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""pb - drive the PHONE's own browser (existing login state) via AccessibilityService.

No adb / Shizuku / MCP needed. Reads the live UI tree of whatever browser the
VIEW intent resolves to (currently X浏览器 com.mmbox.xbrowser).

  pb open <url>            open in system browser, wait until it is foreground
  pb state                 package + page title + visible text lines
  pb text [--min-top N]    visible text lines (deduped, status bar dropped)
  pb collect [--swipes N]  scroll + accumulate unique lines => whole page
  pb tap <text|#id>        tap by text or nodeId (e.g. #000i)
  pb type <text>           type into focused input
  pb find <text>           locate node, print center coords
  pb back / pb key <name>  back / arbitrary input key
  pb info                  raw ui info (package, window count)
"""
import json, subprocess, sys, time, urllib.parse

CLI = "android-a11y-cli"
BROWSERISH = ("browser", "chrome", "mmbox", "microsoft", "mozilla", "brave", "vivaldi", "quark", "ucmobile", "tencent")


def call(*args):
    p = subprocess.run([CLI, *args], capture_output=True, text=True)
    try:
        return json.loads(p.stdout)
    except Exception:
        return {"ok": False, "error": {"message": (p.stdout + p.stderr).strip()[:300]}}


def ui_info():
    return call("ui", "info").get("data") or {}


def nodes():
    d = call("ui", "dump", "--compact")
    return (d.get("data") or {}).get("nodes", []) if d.get("ok") else []


def lines(ns, min_top=100):
    out = []
    for n in ns:
        t = (n.get("text") or "").strip()
        if not t:
            continue
        top = (n.get("bounds") or {}).get("top")
        if top is None:
            top = (n.get("center") or {}).get("y", 0)
        if top < min_top:
            continue
        if t not in out:
            out.append(t)
    return out


def is_browser(pkg):
    return any(k in (pkg or "").lower() for k in BROWSERISH)


def wait_browser(timeout=12):
    end = time.time() + timeout
    while time.time() < end:
        pkg = ui_info().get("packageName", "")
        if is_browser(pkg):
            return pkg
        time.sleep(0.6)
    return ui_info().get("packageName", "")


def swipe(direction="up", ms=350):
    if direction == "up":
        a, b = (540, 1850), (540, 650)
    else:
        a, b = (540, 650), (540, 1850)
    call("gesture", "swipe", str(a[0]), str(a[1]), str(b[0]), str(b[1]), str(ms))
    time.sleep(0.7)


def cmd_open(url):
    if "://" not in url and not url.startswith(("about:", "intent:")):
        url = "https://" + url
    p = subprocess.run(["android-open", url], capture_output=True, text=True)
    pkg = wait_browser()
    print(json.dumps({"ok": pkg and is_browser(pkg) or pkg.startswith("com.openminis"),
                      "package": pkg, "url": url,
                      "raw": (p.stdout + p.stderr).strip()[:200]}, ensure_ascii=False))


def cmd_state():
    i = ui_info()
    ns = nodes()
    ls = lines(ns)
    print(json.dumps({"package": i.get("packageName"), "title": (ls[0] if ls else ""),
                      "lines": len(ls), "preview": ls[:12]}, ensure_ascii=False, indent=1))


def cmd_text(min_top=100):
    for t in lines(nodes(), min_top):
        print(t)


def cmd_collect(swipes=6):
    seen, buf = set(), []
    stall = 0
    for _ in range(swipes + 1):
        fresh = [t for t in lines(nodes()) if t not in seen]
        for t in fresh:
            seen.add(t); buf.append(t)
        stall = stall + 1 if not fresh else 0
        if stall >= 2:
            break
        swipe("up")
    print("\n".join(buf))


def cmd_tap(target):
    if target.startswith("#"):
        r = call("tap", "node", target[1:])
    else:
        r = call("tap", "text", target)
    time.sleep(0.8)
    print(json.dumps(r, ensure_ascii=False)[:300])


def cmd_type(text):
    r = call("input", "text", text)
    print(json.dumps(r, ensure_ascii=False)[:300])


def cmd_find(text):
    hits = [n for n in nodes() if text in ((n.get("text") or "") + (n.get("contentDesc") or ""))]
    for n in hits[:10]:
        print(f'{n["nodeId"]}  {n.get("center")}  {n.get("text") or n.get("contentDesc")!r}  clickable={n.get("clickable")}')
    if not hits:
        print("no match")


def cmd_key(name):
    r = call("input", "key", name)
    print(json.dumps(r, ensure_ascii=False)[:200])


def main(argv):
    if not argv:
        print(__doc__); return
    cmd, *rest = argv
    opt = {}
    if "--min-top" in rest:
        i = rest.index("--min-top"); opt["min_top"] = int(rest[i + 1]); del rest[i:i + 2]
    if "--swipes" in rest:
        i = rest.index("--swipes"); opt["swipes"] = int(rest[i + 1]); del rest[i:i + 2]
    if cmd == "open":    cmd_open(rest[0])
    elif cmd == "state": cmd_state()
    elif cmd == "text":  cmd_text(opt.get("min_top", 100))
    elif cmd == "collect": cmd_collect(opt.get("swipes", 6))
    elif cmd == "tap":   cmd_tap(rest[0])
    elif cmd == "type":  cmd_type(" ".join(rest))
    elif cmd == "find":  cmd_find(rest[0])
    elif cmd == "back":  cmd_key("back")
    elif cmd == "key":   cmd_key(rest[0])
    elif cmd == "info":  print(json.dumps(ui_info(), ensure_ascii=False, indent=1))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])

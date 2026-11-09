#!/usr/bin/env python3
"""xb 的客户端格式化：把桥回的 JSON 压成给 AI 读的紧凑文本。

用法（由 xb.sh 调用，不直接手敲）：
    xbfmt.py snapshot [--sel] [--text] [--raw]
    xbfmt.py status   [--verbose]
    xbfmt.py text     [--all] [--sel 选择器]

为什么要它：桥回的 snapshot 信封里有二次转义，interactive 每条还带一段
全长 CSS 路径（sel），在真实页面上 70 条就是 1.7 万字符 —— 而点击只用 ref。
压缩后同页约 2.6K，正文/选择器按需另取。
"""
import json
import sys

TEXT_CAP = 3000


def load(stream):
    raw = stream.read()
    try:
        return json.loads(raw)
    except ValueError:
        return {"_raw": raw}


def body(env):
    """桥把页面结果放在 value 里，通常还是一层 JSON 字符串。"""
    v = env.get("value")
    if isinstance(v, str):
        s = v.strip()
        if s[:1] in "{[":
            try:
                return json.loads(s)
            except ValueError:
                pass
    return v


def one_line(s, limit):
    s = " ".join(str(s).split())
    return s[:limit] + ("…" if len(s) > limit else "")


def short_ref(ref):
    # 页面的 ref 固定以 minis-ref: 开头；xbm click 会自动补回，这里省掉它
    return ref[len("minis-ref:"):] if ref.startswith("minis-ref:") else ref


def cmd_snapshot(env, opts):
    if "_raw" in env:
        sys.stdout.write(env["_raw"])
        return 0
    if env.get("ok") is False:
        print("错误:", env.get("error"))
        return 1
    d = body(env) or {}
    items = d.get("interactive") or []
    total = d.get("total")
    offset = d.get("offset") or 0
    print("%s  |  %s  |  tab=%s" % (d.get("url", "?"), one_line(d.get("title", ""), 60), env.get("tab", "?")))
    tail = "共 %s 条，本次 %s 条" % (total, len(items))
    if offset:
        tail += "（offset %s）" % offset
    if total and total > len(items) + offset:
        tail += "（还有 %s 条，用 xb snapshot --all）" % (total - len(items) - offset)
    if d.get("roots") and d["roots"] > 1:
        tail += "，含 %s 个 shadow/frame 根" % d["roots"]
    print(tail)
    for it in items:
        ref = short_ref(it.get("ref", ""))
        scope = "~" if it.get("scope") else " "
        line = "%s%3s %-8s %-34s %s" % (scope, it.get("index", ""), it.get("tag", ""),
                                        one_line(it.get("label", ""), 34), ref)
        if opts.get("sel"):
            line += "  " + one_line(it.get("sel", ""), 90)
        print(line.rstrip())
    for ov in d.get("overlays") or []:
        print("~弹层 %s  %s" % (one_line(ov.get("text", ""), 60), one_line(ov.get("sel", ""), 60)))
    text = d.get("text") or ""
    if opts.get("text") and text:
        print("--- 正文 %s 字 ---" % len(text))
        print(text)
    elif text:
        print("正文 %s 字，要读用 xb text（这里不带）" % len(text))
    return 0


def cmd_text(env, opts):
    if "_raw" in env:
        sys.stdout.write(env["_raw"])
        return 0
    if env.get("ok") is False:
        print("错误:", env.get("error"))
        return 1
    v = body(env)
    if not isinstance(v, str):
        v = json.dumps(v, ensure_ascii=False) if v is not None else ""
    if v == "no element":
        print("错误: 没有匹配的元素（换个选择器，或用 xb snapshot 找 ref）")
        return 1
    n = len(v)
    if opts.get("all") or n <= TEXT_CAP:
        sys.stdout.write(v if v.endswith("\n") else v + "\n")
        return 0
    sys.stdout.write(v[:TEXT_CAP])
    print("\n… 已截断：共 %s 字，要看全文用 xb text all" % n)
    return 0


def trim_err(msg):
    """页面回的栈有 200 字符，AI 只需要第一行。"""
    s = str(msg or "?").split("\n")[0].strip()
    return s[:160]


def fail_line(env, hint=""):
    print("错误: %s" % trim_err(env.get("error")))
    if host := (hint or ""):
        print(host)
    if env.get("delivered") is False:
        print("没下发（多半是浏览器不在前台，看 xb status）")
    elif env.get("op_id"):
        print("op_id=%s（要重试就带 --op-id 复用它）" % env["op_id"])


def cmd_js(env, opts):
    """读一个值时只回值本身；出错才把信封摊开（AI 要看的就是它）。"""
    if "_raw" in env:
        sys.stdout.write(env["_raw"])
        return 0
    if env.get("ok") is not True:
        fail_line(env)
        return 1
    v = env.get("value")
    if isinstance(v, str):
        s = v.strip()
        if s[:1] in "{[":
            try:
                v = json.loads(s)
            except ValueError:
                pass
    if isinstance(v, (str, int, float, bool)) or v is None:
        print("" if v is None else v)
    else:
        print(json.dumps(v, ensure_ascii=False))
    return 0


def cmd_action(env, opts, kind):
    """click/fill 的紧凑回包：把「点了什么 / 落到哪」摊成一行。"""
    if "_raw" in env:
        sys.stdout.write(env["_raw"])
        return 0
    if env.get("ok") is not True:
        err = trim_err(env.get("error"))
        print("失败: %s" % err)
        if env.get("delivered") is False:
            print("（没下发：多半是浏览器不在前台，看 xb status）")
        elif "unknown" in err and env.get("op_id"):
            # 只有「可能已执行但结果丢了」才值得复用编号重试；页面明确拒绝时重试没用
            print("重试用: xb --op-id %s %s <同样的参数>" % (env["op_id"], kind))
        return 1
    a = body(env)
    if isinstance(a, str):
        print(a)
        return 0
    if not isinstance(a, dict):
        print(json.dumps(env, ensure_ascii=False))
        return 0
    if a.get("ok") is False:
        print("页面拒绝: %s" % a.get("error", "?"))
        return 1
    if kind == "click":
        b = a.get("before") or {}
        af = a.get("after") or {}
        exp = b.get("expected_url")
        print("点了 %s「%s」  %s → %s" % (b.get("tag", "?"), one_line(b.get("label", ""), 30),
                                         b.get("url", "?"), af.get("url", "?")))
        if exp and (af.get("url") == exp or env.get("inferred")):
            print("✓ 已落到 %s" % exp)
        elif exp:
            # 点击后跳转是异步的：ack 回包里的 after.url 常常还是旧地址，别据此判失败
            print("跳转中，预期 %s（要核验就 xb js 'location.href'）" % exp)
        return 0
    print("填好了: %s" % one_line(json.dumps({k: v for k, v in a.items() if k != "ok"}, ensure_ascii=False), 120))
    return 0


def cmd_status(env, opts):
    if "_raw" in env:
        sys.stdout.write(env["_raw"])
        return 0
    if opts.get("verbose"):          # 给机器/脚本用：只回 JSON，别掺人读的行
        print(json.dumps(env, ensure_ascii=False))
        return 0
    tabs = env.get("tabs") or []
    sv = env.get("script_version", "?")
    cache = env.get("cache") or {}
    used = cache.get("used_bytes") or 0
    print("ok  sv=%s  tabs=%s  pending=%s  cache=%sB" % (sv, len(tabs), env.get("pending", 0), used))
    warn = []
    for t in tabs:
        flags = []
        if not t.get("visible"):
            flags.append("后台")
        if (t.get("raf") or 0) < 8:
            flags.append("raf=%s" % t.get("raf"))
        if t.get("sv") and t.get("sv") != sv:
            flags.append("脚本旧(%s)" % t.get("sv"))
        if not t.get("polling"):
            flags.append("未轮询")
        print("  %s  %-6s %s" % (t.get("tab", "?"), ",".join(flags) or "就绪", one_line(t.get("url", ""), 70)))
        if not t.get("visible") or (t.get("raf") or 0) < 8:
            warn.append("页面被冻结")
    for s in env.get("stale_tabs") or []:
        warn.append("标签 %s 跑旧脚本，刷新一下" % s)
    if not tabs:
        print("  没有标签：浏览器没开，或已退到后台被杀")
    if warn:
        print("提示: " + "；".join(sorted(set(warn))) + " → 把浏览器切到前台再操作")
    return 0


def main(argv):
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    cmd, rest = argv[0].strip(), argv[1:]
    opts = {"sel": "--sel" in rest, "text": "--text" in rest,
            "all": "--all" in rest, "verbose": "--verbose" in rest}
    env = load(sys.stdin)
    if "--raw" in rest or "raw" in rest:
        sys.stdout.write(json.dumps(env, ensure_ascii=False) + "\n")
        return 0
    fn = {"snapshot": cmd_snapshot, "text": cmd_text, "status": cmd_status,
          "js": cmd_js, "click": lambda e, o: cmd_action(e, o, "click"),
          "fill": lambda e, o: cmd_action(e, o, "fill")}.get(cmd)
    if fn is None:
        print("xbfmt: 未知子命令 %r" % cmd, file=sys.stderr)
        return 2
    return fn(env, opts)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

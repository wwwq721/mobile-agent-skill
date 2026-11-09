#!/usr/bin/env python3
"""mloc — 常用入口库（本机用）

记的是「选择器」，不是 nodeId。nodeId 是某次 dump 里的临时序号，
界面一重绘就作废；选择器（文本/描述）每次重新解析成当次节点。

什么时候值得记：
  一个入口如果「位置固定 + 语义固定 + 每次都要点」（设置项、底部 tab、
  app 内固定按钮），就该记。展开/折叠这类点完就变的按钮别记，记了也是 stale。

子命令与参数见 mloc -h。
"""
import json
import os
import subprocess
import sys

DATA = "/var/minis/skills/mobile-ops/data"
STORE = os.path.join(DATA, "locators.json")


_LAST_ERROR = None      # 最近一次 a11y 调用的错误码，供 fail 时带上更准的诊断


def a11y(*args):
    """调内置命令，返回解析后的 JSON。失败给 {}，但把错误码记到 _LAST_ERROR。

    记录错误码不增加任何调用，只是不再把「无障碍没开」和「这屏没有目标」
    压成同一个空结果——上层据此能报出真正的原因。
    """
    global _LAST_ERROR
    try:
        out = subprocess.run(["android-a11y-cli", *args, "--compact"],
                             capture_output=True, text=True).stdout
        body = json.loads(out)
        err = body.get("error") or {}
        _LAST_ERROR = err.get("code") if isinstance(err, dict) else None
        return body
    except Exception:
        _LAST_ERROR = "CLI_UNAVAILABLE"
        return {}



def dump():
    """只取节点。包名一律由 node_pkg() 单点查询——dump 里查不到，靠 ui info 猜会拿到残留值。"""
    return a11y("ui", "dump").get("data", {}).get("nodes", [])

def fail(obj):
    """错误也走 stdout（非零退出码表示失败），这样 `mloc tap X | jq` 拿得到原因。"""
    print(json.dumps(obj, ensure_ascii=False))
    sys.exit(1)



def load():
    """读库。解析失败就重建——这个文件只有本工具在写，且是原子替换。"""
    if not os.path.exists(STORE):
        return {}
    try:
        raw = json.load(open(STORE, encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        print("警告: 定位库无法解析，已重建", file=sys.stderr)
        return {}


def save(db):
    """原子写：先写临时文件再 replace，避免半写把整库弄坏。"""
    os.makedirs(DATA, exist_ok=True)
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STORE)


def node_pkg(n):
    """节点所属应用。dump 的节点不带 packageName，必须单独查一次。"""
    return a11y("ui", "node", n["nodeId"]).get("data", {}).get("packageName", "")


def match(nodes, sel):
    """按稳定性优先级依次尝试：文本精确 > 描述 > 包含。"""
    if sel.get("text"):
        hit = [n for n in nodes if (n.get("text") or "") == sel["text"]]
        if hit:
            return hit
    if sel.get("desc"):
        hit = [n for n in nodes if (n.get("contentDesc") or "") == sel["desc"]]
        if hit:
            return hit
    if sel.get("contains"):
        return [n for n in nodes
                if sel["contains"] in ((n.get("text") or "") + (n.get("contentDesc") or ""))]
    return []


def learn(args):
    nodes = dump()
    if not nodes:
        # 节点为空一定是设备侧问题（授权/服务/空白页）。
        # 不能掉到后面报 no_match「先导航」——那是指错方向。
        err = _LAST_ERROR
        fail({"error": "no_nodes", "name": args.name, "a11y_error": err,
              "hint": "读不到界面节点；先查无障碍/授权，不是选择器的问题"})
    for k in ("text", "desc", "contains"):
        if getattr(args, k, None):
            sel = {k: getattr(args, k)}
            break
    else:
        fail({"error": "missing_selector", "hint": "需要 --text / --desc / --contains 之一"})

    hits = match(nodes, sel)
    if not hits:
        fail({"error": "no_match", "hint": "当前屏没有匹配项；先导航到目标所在的屏再 learn"})

    # 与 tap 判据一致：必须唯一可点，否则记下来也点不动
    clickable = [n for n in hits if n.get("clickable")]
    if len(clickable) != 1:
        fail({"error": "not_clickable" if not clickable else "ambiguous",
              "name": args.name, "matches": len(hits), "clickable": len(clickable),
              "hint": "目标不可点击，换 --desc 指向可点控件" if not clickable
                      else "目标匹配不唯一，用 --desc 收紧；分不开就别记"})

    # 包名以命中节点自己为准：桌面等场景 ui info 会残留上一个应用的包名，
    # 用错包名会写进一条永远点不动的条目。
    target = clickable[0] if clickable else hits[0]
    pkg = node_pkg(target)
    if pkg in ("?", ""):
        fail({"error": "unknown_package", "name": args.name,
              "a11y_error": _LAST_ERROR,
              "hint": "无法确定目标所属应用，未记录。若 a11y_error 是 "
                      "SERVICE_NOT_RUNNING / PERMISSION_DENIED，先修授权，不是库的问题"})

    db = load()
    db[pkg + "|" + args.name] = {"sel": sel}
    save(db)
    print(json.dumps({"learned": args.name, "pkg": pkg, "sel": sel,
                      "matched": len(hits)}, ensure_ascii=False))


def tap(args):
    """按名字在本屏定位，核对归属，再点。

    不先用 ui info 的包名筛库——桌面等场景它会残留上一个应用的包名，
    导致刚学好的入口报 no_locator。改为按名字找记录、用选择器定位、
    用节点真实包名核对归属。
    """
    db = load()
    nodes = dump()
    if not nodes:
        fail({"error": "no_nodes", "name": args.name, "a11y_error": _LAST_ERROR,
              "hint": "读不到界面节点；先修无障碍/授权，不是定位库的问题"})

    # 1. 按名字找记录（不同 app 可能有同名入口）
    cands = [(k, v) for k, v in db.items()
             if (k.split("|", 1) + [""])[1] == args.name]
    if not cands:
        fail({"error": "no_locator", "name": args.name,
              "hint": "没学过这个入口名；learn 一次再 tap"})

    # 2. 用这些记录的选择器在本屏定位
    hit_map = []
    for k, v in cands:
        sel = v.get("sel") or {}
        h = match(nodes, sel)
        if h:
            hit_map.append((k, v, h))
    if not hit_map:
        fail({"error": "stale", "name": args.name,
              "hint": "这屏没有该入口；先导航到那屏再 tap，重学只会得 no_match"})

    # 3. 用真实节点包名选定唯一一条记录
    chosen = None
    for k, v, h in hit_map:
        if k.split("|", 1)[0] == node_pkg(h[0]):
            chosen = (k, v, h)
            break
    if chosen is None:
        chosen = hit_map[0]            # 归属交给下面那道 wrong_app 校验

    key, rec, hits = chosen

    # 4. 唯一可点目标
    clickable = [n for n in hits if n.get("clickable")]
    if len(clickable) != 1:
        fail({"error": "not_clickable" if not clickable else "ambiguous",
              "name": args.name, "matches": len(hits), "clickable": len(clickable),
              "hint": "目标不可点击" if not clickable
                      else "多个同文案目标，用 --desc 收紧，或重新 dump 定位"})
    target = clickable[0]

    # 5. 归属校验：节点自带的包名最准，没有才查一次 ui node
    want = key.split("|", 1)[0]
    got = node_pkg(target)
    if not got:
        fail({"error": "unknown_target_package", "name": args.name,
              "a11y_error": _LAST_ERROR,
              "hint": "核对不到目标所属应用，未点击；重新 dump 定位，别复用这个 id"})
    if want not in ("?", "") and got != want:
        fail({"error": "wrong_app", "name": args.name, "want": want, "got": got,
              "hint": "目标属于别的应用，拒绝点击"})

    r = a11y("tap", "node", target["nodeId"])
    ok = bool(r.get("ok"))
    print(json.dumps({"ok": ok, "name": args.name, "node": target["nodeId"],
                      "error": None if ok else r.get("error")}, ensure_ascii=False))
    if not ok:
        sys.exit(1)


def show(_):
    db = load()
    if not db:
        print("（空）")
        return
    for k, v in sorted(db.items()):
        pkg, _, name = k.partition("|")
        print("%-28s %-12s %s" % (pkg[:28], name, v.get("sel") or {}))


def forget(args):
    db = load()
    gone = [k for k in db if (k.split("|", 1) + [""])[1] == args.name]
    for k in gone:
        del db[k]
    save(db)
    print("删除 %d 条" % len(gone))


def main():
    import argparse
    p = argparse.ArgumentParser(prog="mloc")
    sub = p.add_subparsers(dest="cmd")

    a = sub.add_parser("learn"); a.add_argument("name")
    a.add_argument("--text"); a.add_argument("--desc"); a.add_argument("--contains")
    a.set_defaults(fn=learn)

    a = sub.add_parser("tap"); a.add_argument("name"); a.set_defaults(fn=tap)
    sub.add_parser("list").set_defaults(fn=show)
    a = sub.add_parser("forget"); a.add_argument("name"); a.set_defaults(fn=forget)

    args = p.parse_args()
    if not getattr(args, "fn", None):
        p.print_help()
        sys.exit(2)      # 无子命令不是成功：`mloc && 下一步` 不能空跑
    args.fn(args)


if __name__ == "__main__":
    main()

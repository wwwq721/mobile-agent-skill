#!/usr/bin/env python3
"""mloc — 常用入口库（本机用）

记的是「选择器」，不是 nodeId。nodeId 是某次 dump 里的临时序号，
界面一重绘就作废；选择器（文本/描述）每次重新解析成当次节点。

什么时候值得记：
  一个入口如果「位置固定 + 语义固定 + 每次都要点」（设置项、底部 tab、
  app 内固定按钮），就该记。展开/折叠这类点完就变的按钮别记，记了也是 stale。

用法:
  mloc learn <名字> --text 文本     学一个入口（也可 --desc / --contains）
  mloc tap <名字>                  验证 + 点击（约 400ms，含一次 dump）
  mloc list                        看库，命中/失败次数会累积
  mloc check                       当前屏幕体检，失效的报 stale
  mloc forget <名字>               删掉
"""
import json
import os
import subprocess
import sys
import time

DATA = "/var/minis/skills/mobile-ops/data"
STORE = os.path.join(DATA, "locators.json")


def a11y(*args):
    """调内置命令，返回解析后的 JSON。失败给 {}。"""
    out = subprocess.run(["android-a11y-cli", *args, "--compact"],
                         capture_output=True, text=True).stdout
    try:
        return json.loads(out)
    except Exception:
        return {}


def dump():
    """ui dump 只给 count/nodes，包名要另问一次 ui info（+40ms）。"""
    nodes = a11y("ui", "dump").get("data", {}).get("nodes", [])
    pkg = a11y("ui", "info").get("data", {}).get("packageName", "?")
    return nodes, pkg


def load():
    db = {}
    if os.path.exists(STORE):
        try:
            db = json.load(open(STORE))
        except Exception:
            db = {}
    # 惰性淘汰：连续失手 5 次且一次没命中过的条目，留着只会误导下次点击
    for k in [k for k, v in db.items()
              if v.get("miss", 0) >= 5 and v.get("hits", 0) == 0]:
        del db[k]
    return db


def save(db):
    os.makedirs(DATA, exist_ok=True)
    json.dump(db, open(STORE, "w"), ensure_ascii=False, indent=1)


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
    nodes, pkg = dump()
    for k in ("text", "desc", "contains"):
        if getattr(args, k, None):
            sel = {k: getattr(args, k)}
            break
    else:
        sys.exit("需要 --text / --desc / --contains 之一")

    hits = match(nodes, sel)
    if not hits:
        sys.exit("当前屏幕没有匹配项，没学到东西")
    if len(hits) > 1:
        print("警告：匹配到 %d 个，点击时取第一个 clickable 的" % len(hits))

    db = load()
    db[pkg + "|" + args.name] = {
        "sel": sel, "hits": 0, "miss": 0,
        "added": time.strftime("%Y-%m-%d %H:%M"),
    }
    save(db)
    print(json.dumps({"learned": args.name, "pkg": pkg, "sel": sel,
                      "matched": len(hits)}, ensure_ascii=False))


def tap(args):
    db = load()
    nodes, pkg = dump()

    key = pkg + "|" + args.name
    if key not in db:                      # 换了个 app 也允许调用，只要名字唯一
        alt = [k for k in db if k.endswith("|" + args.name)]
        if len(alt) != 1:
            sys.exit(json.dumps({"error": "no_locator", "name": args.name,
                                 "pkg": pkg}, ensure_ascii=False))
        key = alt[0]
    rec = db[key]

    hits = match(nodes, rec["sel"])
    if not hits:
        rec["miss"] = rec.get("miss", 0) + 1
        save(db)
        sys.exit(json.dumps({"error": "stale", "name": args.name,
                             "miss": rec["miss"],
                             "hint": "入口不在这屏，或文案变了；重新 learn"},
                            ensure_ascii=False))

    target = next((n for n in hits if n.get("clickable")), hits[0])
    t0 = time.perf_counter()
    r = a11y("tap", "node", target["nodeId"])
    ms = (time.perf_counter() - t0) * 1000

    ok = bool(r.get("ok"))
    rec["hits" if ok else "miss"] = rec.get("hits" if ok else "miss", 0) + 1
    rec["last"] = time.strftime("%m-%d %H:%M")
    save(db)
    print(json.dumps({"ok": ok, "name": args.name, "node": target["nodeId"],
                      "ms": round(ms), "hits": rec["hits"], "miss": rec["miss"]},
                     ensure_ascii=False))


def show(_):
    db = load()
    if not db:
        print("（空）")
        return
    for k, v in sorted(db.items()):
        print("%-26s %-12s hits=%-3d miss=%-3d %s" %
              (k.split("|")[0][:26], k.split("|", 1)[1], v.get("hits", 0),
               v.get("miss", 0), v["sel"]))


def forget(args):
    db = load()
    gone = [k for k in db if k.endswith("|" + args.name)]
    for k in gone:
        del db[k]
    save(db)
    print("删除 %d 条" % len(gone))


def check(_):
    db = load()
    nodes, pkg = dump()
    alive, stale = [], []
    for k, v in db.items():
        if not k.startswith(pkg + "|"):
            continue
        (alive if match(nodes, v["sel"]) else stale).append(k.split("|", 1)[1])
    print(json.dumps({"pkg": pkg, "alive": alive, "stale": stale}, ensure_ascii=False))


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
    sub.add_parser("check").set_defaults(fn=check)

    args = p.parse_args()
    if not getattr(args, "fn", None):
        p.print_help()
        return
    args.fn(args)


if __name__ == "__main__":
    main()

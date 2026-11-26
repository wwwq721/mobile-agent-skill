#!/usr/bin/env python3
"""scr 全功能回归：每条命令跑一次并断言结果，失败即列出可读原因。

根本目的：修完必须自证没修坏——用户要的是"修完再测，直到测试成功"。
断言口径统一：命令自己吐出来的东西 vs 屏幕事实（前台包名、条目数、坐标是否在屏内）。
"""
import json
import re
import subprocess
import sys
import time

W, H = 1280, 2772
results = []


def run(*args, timeout=60):
    t0 = time.time()
    p = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or ""), int((time.time() - t0) * 1000)


def front():
    rc, out, _ = run("android-a11y-cli", "ui", "info")
    try:
        return json.loads(out)["data"]["packageName"]
    except Exception:
        return "?"


def case(name, fn):
    try:
        ok, detail = fn()
    except Exception as e:                                        # noqa: BLE001
        ok, detail = False, f"异常 {type(e).__name__}: {e}"
    results.append((name, ok, detail))
    print(f"{'✔' if ok else '✘'} {name} · {detail}")
    return ok


def items_of(out):
    """从 scr 输出里抽条目行 (序号, 标签, x, y)。"""
    rows = []
    for ln in out.splitlines():
        m = re.match(r"\s*s\d+\s+[·CE]*\s*(.*?)\s*@(\d+),(\d+)\s*$", ln)
        if m:
            rows.append((m.group(1), int(m.group(2)), int(m.group(3))))
    return rows


def home_bili():
    run("android-a11y-cli", "input", "key", "home")
    time.sleep(0.5)
    run("scr", "open", "哔哩哔哩")
    time.sleep(0.6)
    for _ in range(3):
        if "搜索栏" in (run("scr", "look")[1]):
            return True
        run("scr", "key", "back")
        time.sleep(0.5)
    return False


# ---------- 用例 ----------
def t_state():
    rc, out, ms = run("scr", "state")
    ok = rc == 0 and re.search(r"app \S+ · \d+ 项", out)
    return bool(ok), f"{ms}ms · {out.strip().splitlines()[0][:60] if out.strip() else '空'}"


def t_look():
    rc, out, ms = run("scr", "look")
    rows = items_of(out)
    oob = [(t, x, y) for t, x, y in rows if not (0 <= x < W and 0 <= y < H)]
    ok = rc == 0 and len(rows) >= 3 and not oob
    return ok, f"{ms}ms · {len(rows)} 项 · 越界 {len(oob)}" + (f" {oob[:2]}" if oob else "")


def t_xy():
    # 点「推荐」tab（B站 首页第二 tab），随后确认页面内容变了
    home_bili()
    _rc, before, _ = run("scr", "look")
    rc, out, ms = run("scr", "xy", "267", "353")
    _rc2, after, _ = run("scr", "look")
    changed = before.split("项", 1)[-1] != after.split("项", 1)[-1]
    return rc == 0 and changed, f"{ms}ms · 内容{'变了' if changed else '没变'}"


def t_tap():
    home_bili()
    rc, out, ms = run("scr", "tap", "热门")
    rows = items_of(out)
    hit = any("热门" in t for t, _x, _y in rows) or "综艺" in out or "番剧" in out
    return rc == 0 and hit, f"{ms}ms · {len(rows)} 项"


def t_search_flow():
    ok_home = home_bili()
    if not ok_home:
        return False, "回不到 B站 首页"
    # 搜索页有时要等一下才把输入框暴露出来：重试两次，别把"还没加载好"当失败
    ok_box = False
    for _ in range(3):
        rc1, o1, _ = run("scr", "tap", "搜索栏")
        if "搜索" not in o1:
            return False, f"点搜索栏后没进搜索页: {o1.splitlines()[0][:50]}"
        if re.search(r"^\s*s\d+\s+E\b", o1, re.M):
            ok_box = True
            break
        time.sleep(0.4)
    if not ok_box:
        return False, "搜索页没有暴露可写输入框"
    rc2, o2, ms2 = run("scr", "type", "测试")
    if "输入框当前文本" not in o2:
        return False, f"输入失败: {o2.splitlines()[0][:50]}"
    rc3, o3, _ = run("scr", "tap", "搜索")
    rc4, o4, ms4 = run("scr", "wait", "综合", "--timeout", "6000")
    rows = items_of(o4)
    ok = rc4 == 0 and len(rows) >= 5
    return ok, f"type {ms2}ms · 结果页 {len(rows)} 项 · wait {ms4}ms"


def t_wait_gone():
    # 用一个"肯定不在屏幕上"的串：等它消失永远等不到 → 必须超时（rc!=0）。
    # 以前拿"综合"，但不在结果页时它本来就不存在，会被判成立即成功。
    # 注意 --gone 的语义：串本来就不存在时，"等它消失"立刻成立（rc=0 是对的）。
    # 要测超时必须"等它出现"。
    rc, out, ms = run("scr", "wait", "zzz_不存在_zzz", "--timeout", "1200")
    return rc != 0 and "超时" in out, f"{ms}ms · 预期超时 · rc={rc}"


def t_swipe():
    _rc, before, _ = run("scr", "look")
    rc, out, ms = run("scr", "swipe", "up")
    _rc2, after, _ = run("scr", "look")
    b = set(t for t, _x, _y in items_of(before))
    a = set(t for t, _x, _y in items_of(after))
    moved = len(b ^ a) >= 2
    return rc == 0 and "内容动了" in out and moved, f"{ms}ms · 变化 {len(b ^ a)} 项"


def t_key_do():
    rc, out, ms = run("scr", "do", "key:back", "key:back")
    ok = rc == 0 and out.count("key:back") >= 1 and "✔" in out
    at_home = "搜索栏" in run("scr", "look")[1]
    return ok and at_home, f"{ms}ms · 回到首页={'是' if at_home else '否'}"


def t_shot():
    rc, out, ms = run("scr", "shot")
    m = re.search(r"(/var/minis/\S+\.(?:jpg|png))", out)
    import os
    ok = rc == 0 and bool(m) and os.path.exists(m.group(1))
    return ok, f"{ms}ms · {m.group(1) if m else out.strip()[:40]}"


def t_open_recents():
    run("android-a11y-cli", "input", "key", "home")
    time.sleep(0.8)
    rc, out, ms = run("scr", "open", "哔哩哔哩")
    f = front()
    return f == "tv.danmaku.bili", f"{ms}ms · 前台 {f}"


def t_open_icon():
    run("android-a11y-cli", "input", "key", "home")
    time.sleep(0.8)
    rc, out, ms = run("scr", "open", "哔哩哔哩")      # 用户要求：测试统一用 B 站
    f = front()
    run("android-a11y-cli", "input", "key", "back")
    time.sleep(0.4)
    return f == "tv.danmaku.bili", f"{ms}ms · 前台 {f}"


def t_grid():
    run("android-a11y-cli", "input", "key", "home")
    time.sleep(0.8)
    rc, out, ms = run("scr", "grid", "--all", timeout=180)
    pages = dict(re.findall(r"^页(\d+) · (\d+) 个图标", out, re.M))
    total = re.search(r"共 (\d+) 页", out)
    stop = re.search(r"当前停在第 (\d+) 页", out)
    ok = (rc == 0 and total and int(total.group(1)) >= 1 and len(pages) >= 1
          and int(pages.get("1", "0")) >= 15 and "小部件" in out and stop)
    return bool(ok), f"{ms}ms · {len(pages)} 页 · 页1 {pages.get('1','?')} 图标 · 停在第 {stop.group(1) if stop else '?'} 页"


def t_grid_tap():
    """grid 给的坐标必须点在同一个图标上（真点，验证完就退）。

    不写死格子：桌面会被用户重组（3-1 昨天是计算器，今天就成文件夹了），
    所以从 grid 输出里挑第一个"名字在已知映射里"的图标来点。
    """
    expect = {"设置": "com.android.settings", "计算器": "com.miui.calculator",
              "相机": "com.android.camera", "短信": "com.android.mms",
              "天气": "com.miui.weather2", "X浏览器": "com.mmbox.xbrowser",
              "企业微信": "com.tencent.wework", "某个 App": "com.migu.ring",
              "豌豆荚": "com.wandoujia.phoenix2", "应用商店": "com.xiaomi.market"}
    rc, out, _ = run("scr", "grid", timeout=180)
    if rc != 0:
        return False, "grid 失败"
    pick = None
    for m in re.finditer(r"^\s*(\d+-\d+)\s+(\S+)\s+(\d+),(\d+)$", out, re.M):
        if m.group(2) in expect:
            pick = (m.group(1), m.group(2), int(m.group(3)), int(m.group(4)),
                    expect[m.group(2)])
            break
    if not pick:
        return False, "grid 里没有已知图标可点"
    cell, name, x, y, pkg = pick
    run("scr", "xy", str(x), str(y))
    time.sleep(0.8)
    f = front()
    run("android-a11y-cli", "input", "key", "back")
    time.sleep(0.4)
    if f == pkg:
        return True, f"{cell} {name} {x},{y} → {f}"
    if f == "com.miui.securitycenter":             # 首启隐私页会顶掉包名
        return True, f"{cell} {name} {x},{y} → 首启隐私页"
    return False, f"{cell} {name} {x},{y} → 前台 {f}（期望 {pkg}）"


def t_doctor():
    rc, out, ms = run("scr", "doctor", timeout=120)
    return rc == 0, f"{ms}ms · {len(out.splitlines())} 行"


CASES = [
    ("state", t_state), ("look", t_look), ("xy", t_xy), ("tap", t_tap),
    ("type+search", t_search_flow), ("wait 超时", t_wait_gone), ("swipe", t_swipe),
    ("key/do", t_key_do), ("shot", t_shot), ("open 最近任务", t_open_recents),
    ("open 应用(B站)", t_open_icon), ("grid 读数", t_grid), ("grid 坐标可点", t_grid_tap),
    ("doctor", t_doctor),
]

if __name__ == "__main__":
    only = sys.argv[1:] or None
    for name, fn in CASES:
        if only and name not in only:
            continue
        case(name, fn)
    bad = [r for r in results if not r[1]]
    print(f"\n{'全部通过' if not bad else '失败 ' + str(len(bad)) + ' 项'}："
          f"{sum(1 for r in results if r[1])}/{len(results)}")
    sys.exit(1 if bad else 0)

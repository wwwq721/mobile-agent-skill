#!/usr/bin/env python3
"""mshot — 一条命令取屏（本机专用）

为什么不写坐标：
  截屏磁贴在通知栏第一屏的位置会被用户随时拖动（实测从 538 挪到
  916 只花了几分钟）。写死坐标必然失效，所以改成 tap text「截屏」——
  位置随便变，文字不变。代价是比 tap node 慢约 100ms（要遍历树）。

  WAIT = 0.21        点之前等 210ms。静置环境实测（HOME 重置成冷启动，
                     每档 4 次）：点击落在 182–224ms 只有 1/4 成功，
                     232ms 及以上 12 次全中。所以真闸门在 230ms 左右，
                     之前记的"180ms 是赌博线"是受人为操作干扰的假数据。
                     节点在 174ms 时还查不到，所以不能更早。
                     换机怎么重测：从 0.15 起每次 +0.03，连跑 4 次全成功
                     就取那个值。低于它时症状是"没报错、也没图"。

为什么不直接截图：
  本机 Android 10（SDK 29），AccessibilityService.takeScreenshot()
  是 API 30 才有的，调用报 NOT_SUPPORTED。所以走「通知栏磁贴 →
  系统截图进相册 → 从 MediaStore 导出」这条路，全链路约 1.5s，
  其中 1.1s 是系统自己合成+编码+落盘，无法压缩。

依赖：android-a11y-cli / android-photos（都是 Minis 内置，不需要装东西）
"""
import glob
import json
import os
import subprocess
import time

SHOT_DIR = "/var/minis/workspace/shots"   # 固定目录，配 KEEP 自动清理
KEEP = 5                                  # 只留最近 5 张，防止长期累积

WAIT = 0.21


def run(*args):
    """调内置命令，返回解析后的 JSON。失败给 {}，让调用方自己判断。"""
    out = subprocess.run([*args, "--compact"], capture_output=True, text=True).stdout
    try:
        return json.loads(out)
    except Exception:
        return {}


def latest():
    """相册最新一张图。用 id 而不是文件名判重，因为同一秒可能截两张。"""
    out = subprocess.run(
        ["android-photos", "list", "--days", "1", "--limit", "1"],
        capture_output=True, text=True).stdout
    try:
        return json.loads(out)["media"][0]
    except Exception:
        return {}


def capture():
    """点一次截屏磁贴。抢跑失败是静默的，所以重试一次并把等待拉长。

    用 tap text 而不是 tap xy：磁贴位置会被用户随时拖动（实测从
    538 挪到 916 只花几分钟），文字「截屏」不会变。
    """
    base = latest().get("id")
    for attempt in range(2):
        run("android-a11y-cli", "input", "key", "notifications")
        time.sleep(WAIT + attempt * 0.15)   # 第二次多等 150ms，避开竞态窗口
        hit = run("android-a11y-cli", "tap", "text", "截屏")
        if not hit.get("ok"):
            continue                         # 节点还没进无障碍树，下一轮再试
        for _ in range(15):                  # 轮询最多 3s，等系统编码落盘
            time.sleep(0.2)
            cur = latest()
            if cur.get("id") and cur["id"] != base:
                return cur
    return None


def relocate(path):
    """把图挪到固定目录，只留最近 KEEP 张。

    不留在 offloads 是因为那里由 Minis 管理、按会话划分，长期跑会越堆越多；
    固定目录 + 数量上限，才能保证半年后还是一样干净。
    """
    os.makedirs(SHOT_DIR, exist_ok=True)
    dst = os.path.join(SHOT_DIR, os.path.basename(path))
    os.replace(path, dst)
    old = sorted(glob.glob(os.path.join(SHOT_DIR, "*.jpg")), key=os.path.getmtime)
    for f in old[:-KEEP]:
        os.remove(f)
    return dst


def main():
    shot = capture()
    if not shot:
        # 失败时面板可能还挂着，滑上去；否则下一次 input key notifications 会无效
        run("android-a11y-cli", "gesture", "swipe", "540", "1500", "540", "300")
        raise SystemExit("取屏失败：通知栏没打开，或磁贴不在第一屏")

    # --size original 才拿得到全分辨率；thumb 会糊到看不清小字。
    raw = subprocess.run(
        ["android-photos", "export", "--id", str(shot["id"]), "--size", "original"],
        capture_output=True, text=True).stdout
    try:
        path = json.loads(raw).get("linux_path", "")
    except Exception:
        path = ""

    # 相册原件立刻删：每张 600KB，留着纯占空间（本机只剩 9.8G）。
    # 沙箱里那份由调用方用完自己删。
    subprocess.run(
        ["android-photos", "delete", "--ids", str(shot["id"]), "--confirm"],
        capture_output=True)

    if not path:
        raise SystemExit("导出失败：%s" % raw[:200])
    print(relocate(path))


if __name__ == "__main__":
    main()

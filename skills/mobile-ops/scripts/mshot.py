#!/usr/bin/env python3
"""mshot — 一条命令取屏，打印图片路径（本机专用）

前提（决定下面所有取舍）：
  * 用户自己操作手机时会把无障碍关掉，那时本工具跑不起来。
    所以不检测用户活跃、不推断"用户同时截图"，相关防御一律不做。
  * 单 AI 串行使用。
  * 真正的成本是模型往返，不是这里的毫秒数。

依赖：android-a11y-cli / android-photos（Minis 内置）
"""
import json
import os
import re
import subprocess
import sys
import time

SHOT_DIR = "/var/minis/workspace/shots/mshot"   # 工具独占目录
KEEP = 5                                        # 只留最近 5 张
SCAN_ID = 5                                     # 一次看 5 条相册记录
TILE_X, TILE_Y = 916, 363                         # 「截屏」磁贴中心；位置固定，变了就改这里

SHOT_RE = re.compile(r"^Screenshot_\d{8}_\d{6}", re.I)   # 系统截图命名


def a11y(*args):
    """调内置命令，返回解析后的 JSON；任何异常都返回 {}。"""
    try:
        out = subprocess.run(["android-a11y-cli", *args, "--compact"],
                             capture_output=True, text=True).stdout
        return json.loads(out)
    except Exception:
        return {}


def current_pkg():
    return (a11y("ui", "info").get("data") or {}).get("packageName", "")


def dismiss_shot_editor():
    """上一次截图可能留下编辑层（华为/荣耀是 com.huawei.HwMultiScreenShot）。

    它在最前时 input key notifications 打不开通知栏。按一次 back 退掉。

    两个判据都要满足才按 back：ui info 的包名会残留旧窗口，
    单看包名有可能把 back 打到用户正在用的 app 上（那会丢掉未保存的内容）。
    编辑层的节点数很少（实测 24），正常页面多得多。
    """
    if "MultiScreenShot" not in current_pkg():
        return False
    nodes = (a11y("ui", "dump").get("data") or {}).get("nodes") or []
    if len(nodes) >= 40:
        return False
    a11y("input", "key", "back")
    time.sleep(0.35)
    return True


def latest_many(n=SCAN_ID):
    """相册最近 n 条。查询失败返回 None（区别于"成功但为空"）。"""
    try:
        out = subprocess.run(["android-photos", "list", "--days", "1",
                              "--limit", str(n)],
                             capture_output=True, text=True).stdout
        media = json.loads(out)["media"]
        return media if isinstance(media, list) else []
    except Exception:
        return None


def claimed(base_id):
    """本次新产生的系统截图；认不出就 None。

    两条判据：id 比基线新（MediaStore id 单调递增）+ 文件名像系统截图
    （挡住相机/下载）。多张时取 id 最大的一张——这个窗口里出现的系统截图
    只可能是本次点击产生的，不是用户的数据。
    """
    media = latest_many()
    if not media:
        return None
    fresh = [m for m in media
             if int(m.get("id") or 0) > base_id
             and SHOT_RE.match(m.get("name") or "")]
    if not fresh:
        return None
    if len(fresh) > 1:
        print("提示: 本次出现 %d 张新截图，取最新一张" % len(fresh), file=sys.stderr)
    return max(fresh, key=lambda m: int(m.get("id") or 0))


def capture():
    """点一次「截屏」磁贴，等本次的新截图落盘。

    磁贴坐标固定（TILE_X/TILE_Y），直接点坐标，不 dump 找节点——省约 400ms。
    磁贴被拖走时这里会点空，报错里会提示改那两个常量。

    实测 1.95 秒（8 次，0 失败）的构成：
      Python 启动+import   170ms   ← 已是 Python 下限
      退截图编辑层          50ms   上次截图可能留下的预览层，会挡通知栏
      开通知栏+面板动画    300ms   ← 低于 230ms 点磁贴会被静默丢弃
      点磁贴                20ms
      系统截图管线        1210ms   ← 合成/编码/写盘/入相册，不可压缩
      查相册+导出           100ms
    能重叠的都重叠了：相册基线查询塞进面板动画窗口，删原件放后台，
    落盘用"固定等 0.95s + 60ms 轮询"兜住 1.2–3s 的长尾。
    再快只能换通道（Shizuku 的 screencap ≈0.5s），不在本 skill 范围内。
    """
    dismiss_shot_editor()

    # 第一次等 280ms 就点——低于 230ms 会被静默丢弃，280ms 是实测的可点闸门。
    # 仍偶发点空（面板动画抖动），所以失败后重来一次，成功路径不付这个代价。
    for attempt in range(2):
        a11y("input", "key", "notifications")
        time.sleep(0.30)             # 面板动画；加查询共约 370ms，实测点空率从 20% 降到接近 0

        # 基线查询塞进面板动画窗口里，不额外占时间（查询本身约 67ms）
        media = latest_many()
        if media is None:
            raise SystemExit("取屏失败：无法读取相册（查询失败），未触发截图")
        # 当天相册为空时基线取 0：之后的系统截图都只能是本次的
        base = int(media[0].get("id") or 0) if media else 0

        a11y("tap", "xy", str(TILE_X), str(TILE_Y))

        # 落盘时间实测在 1.0–1.6 秒间波动（相册越大越靠后）。先固定等 0.95 秒
        # 跳过必然为空的区间，再每 0.12 秒查一次兜住长尾——比死等 1.4 秒平均更快。
        time.sleep(0.95)
        for _ in range(10):
            cand = claimed(base)
            if cand:
                return cand
            time.sleep(0.06)
        if attempt == 0:
            time.sleep(0.4)          # 让残留面板先收起，免得下一次 toggle 把它关掉

    raise SystemExit("取屏失败：点了 (%d,%d) 两次都没出图。可能是屏幕熄了、无障碍/授权没开，"
                     "或磁贴被移走（改 TILE_X/TILE_Y）" % (TILE_X, TILE_Y))

def export_copy(shot):
    """导出到沙箱。任何可疑情况返回 ""，调用方据此保留相册原件。"""
    try:
        p = subprocess.run(
            ["android-photos", "export", "--id", str(shot["id"]),
             "--size", "original"],
            capture_output=True, text=True)
        if getattr(p, "returncode", 0) != 0:
            return ""
        path = json.loads(p.stdout).get("linux_path", "")
    except Exception:
        return ""
    if not path or not os.path.exists(path):
        return ""
    try:
        if os.path.getsize(path) == 0:      # 0 字节是导出中断的典型形态
            return ""
    except OSError:
        return ""
    return path


def relocate(path):
    """挪到 SHOT_DIR，只留最近 KEEP 张。这个目录是本工具独占的。"""
    try:
        os.makedirs(SHOT_DIR, exist_ok=True)
    except OSError as e:
        raise SystemExit("归档目录不可用：%s（%s）" % (SHOT_DIR, e))

    dst = os.path.join(SHOT_DIR, os.path.basename(path))
    os.replace(path, dst)

    shots = [os.path.join(SHOT_DIR, n) for n in os.listdir(SHOT_DIR)
             if os.path.isfile(os.path.join(SHOT_DIR, n))]
    shots.sort(key=os.path.getmtime)
    for f in shots[:-KEEP]:
        try:
            os.remove(f)
        except OSError:
            pass
    return dst


def main():
    shot = capture()
    if not shot:
        raise SystemExit("取屏失败：等不到新截图（磁贴点了但没出图？）")

    path = export_copy(shot)
    if not path:
        raise SystemExit("导出失败，相册原件已保留（id=%s）" % shot.get("id"))

    final = relocate(path)

    # 删相册原件放后台：交付不等它（实测 57ms），失败也只影响相册干净程度。
    # 不 detach 到孤儿进程，进程退出前 Python 会等子进程结束，所以不会半途丢。
    try:
        subprocess.Popen(
            ["android-photos", "delete", "--ids", str(shot["id"]), "--confirm"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print("警告: 删除相册原件失败 %s（图已保存在 %s）" % (e, final), file=sys.stderr)

    print(final)

if __name__ == "__main__":
    main()

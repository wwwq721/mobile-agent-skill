#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""learn_timing — 录一段"手动操作"的逐帧时序，用来校准 scr 的手势参数。

根本目的：手能拖、注入拖不动时，把"人到底怎么拖的"量出来——按住多久、什么时候开始移动、
移动多快、图标什么时候跟着手指走——再照这个改 `scr drag` 的三段参数，而不是靠猜。

录制结果**不清空**：每帧半尺寸 JPEG 留在 <out>/<时间戳>/ 下，index.json 记每帧的真实时间。
原图（1280×2772，约 700KB/张）缩完即删，只留半尺寸（约 100KB/张）。

用法：
    learn_timing                 # 默认每 0.25s 一帧，录 10s
    learn_timing -n 20           # 录 20s
    learn_timing --interval 0.2  # 更密的采样
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

DEFAULT_OUT = "/var/minis/workspace/shots/learn"
# 只认自己产出的文件名：f00_0.25s.jpg / index.json，且必须在 <MMDD-HHMMSS>/ 这种时间戳目录里。
# 为什么要有这条：--purge 以前是"把这个目录下所有文件都删掉"，一旦 --out 指错
# （比如指到 attachments 或 memory），会把用户的东西一起清掉——这类事故不该再有第二次。
OWN_FRAME = re.compile(r"^f\d{2,4}_\d+(?:\.\d+)?s\.jpg$")
RUN_DIR = re.compile(r"^\d{4}-\d{6}$")


def _mine(dirpath, name):
    return (name == "index.json" or OWN_FRAME.match(name)) and RUN_DIR.match(os.path.basename(dirpath))


def purge(root, dry=False):
    """只删自己产出的帧与索引；别的东西一律跳过并报出来。"""
    deleted, skipped, why = 0, 0, []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(dirpath, f)
            if not _mine(dirpath, f) or os.path.islink(p):
                skipped += 1
                if len(why) < 3:
                    why.append(p)
                continue
            if not dry:
                try:
                    os.remove(p)
                except OSError as e:
                    skipped += 1
                    if len(why) < 3:
                        why.append(f"{p}: {e}")
                    continue
            deleted += 1
        if not dry and RUN_DIR.match(os.path.basename(dirpath)):
            try:
                if not os.listdir(dirpath):
                    os.rmdir(dirpath)
            except OSError:
                pass
    return deleted, skipped, why


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--seconds", type=float, default=10)
    ap.add_argument("--interval", type=float, default=0.25)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--clean", action="store_true", help="录完就删掉这次录的帧")
    ap.add_argument("--purge", action="store_true", help="删掉历史录制帧后退出（只删自己产出的文件）")
    ap.add_argument("--dry-run", action="store_true", help="配合 --purge：只列出将删什么，不动手")
    ap.add_argument("--force", action="store_true", help="允许清理非默认目录（默认只清 workspace/shots/learn）")
    a = ap.parse_args()
    if a.purge:
        root = os.path.abspath(a.out)
        # dry-run 不删东西，任何目录都允许看
        if root != os.path.abspath(DEFAULT_OUT) and not (a.force or a.dry_run):
            print(f"✘ 拒绝清理 {root}：默认只允许 {DEFAULT_OUT}；确认要清别处请加 --force")
            sys.exit(3)
        if not os.path.isdir(root):
            print(f"✔ 没有可清理的目录（{root} 不存在）")
            return
        d, s, why = purge(root, dry=a.dry_run)
        verb = "将删除" if a.dry_run else "已删除"
        print(f"{verb} {d} 个自产文件；跳过 {s} 个不属于本脚本的文件（{root}）")
        for w in why:
            print(f"   跳过: {w}")
        return
    run = os.path.join(a.out, time.strftime("%m%d-%H%M%S"))
    os.makedirs(run, exist_ok=True)
    print(f"录制目录 {run}", flush=True)
    print(f"现在开始操作（录 {a.seconds:.0f}s，每 {a.interval}s 一帧）…", flush=True)

    from PIL import Image
    t0 = time.time()
    idx = []
    while time.time() - t0 < a.seconds:
        s = time.time()
        r = subprocess.run(["android-a11y-cli", "ui", "screenshot"],
                           capture_output=True, text=True)
        src = ""
        try:
            src = (json.loads(r.stdout).get("data") or {}).get("path", "")
        except Exception:                                      # noqa: BLE001
            pass
        if src and os.path.exists(src):
            t = time.time() - t0
            im = Image.open(src).convert("RGB")
            im = im.resize((im.width // 2, im.height // 2), Image.LANCZOS)
            name = f"f{len(idx):02d}_{t:05.2f}s.jpg"
            im.save(os.path.join(run, name), "JPEG", quality=85)
            idx.append({"frame": name, "t": round(t, 2)})
            try:
                os.remove(src)
            except OSError:
                pass
            print(f"  {name}", flush=True)
        dt = a.interval - (time.time() - s)
        if dt > 0:
            time.sleep(dt)

    json.dump(idx, open(os.path.join(run, "index.json"), "w"),
              ensure_ascii=False, indent=1)
    if a.clean:
        d, s, why = purge(run)          # 同一个删除口径：只删自己产出的
        print(f"共 {len(idx)} 帧，已按 --clean 删除 {d} 个（跳过 {s} 个不属于本脚本的文件）", flush=True)
        for w in why:
            print(f"   跳过: {w}", flush=True)
    else:
        print(f"共 {len(idx)} 帧 → {run}（用完记得 learn_timing --purge 清掉）", flush=True)


if __name__ == "__main__":
    sys.exit(main() or 0)

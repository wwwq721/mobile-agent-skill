#!/usr/bin/env python3
"""根本目的：文档改了结构（改名、换节号、删小节）后，防止别处还指着旧名字——
把"回扫"从靠记性变成一条命令。

检查三件事：
  1. 文中出现的 `某某.md` 路径是否真实存在（相对本技能目录解析）；
  2. 文中出现的 `某文件.md 第 N 节` 里的第 N 节是否在该文件中存在；
  3. 过时词（旧技法/旧结论/已删结构）是否还残留在不该出现的地方。

用法：python3 check_docs.py        # 有问题 exit 1，全绿 exit 0
"""
import os, re, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DOCS = ["SKILL.md", "迁移.md", "scenarios/desktop.md",
        "references/实测记录.md", "references/设备参数.md"]

# 旧词表：出现即提示（历史文件里允许，因为它就是记录历史）
STALE = ["抖动法", "shiver", "能力矩阵", "编辑模式搬运", "box = 3", "continueStroke 未发布"]
ALLOW_IN = {"references/实测记录.md"}          # 历史文件可提旧词

SECTION_RE = re.compile(r"第\s*([0-9]+)\s*节")
LINK_RE = re.compile(r"`([A-Za-z0-9_./\u4e00-\u9fa5-]+\.md)`")


def sections(path):
    out = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^##\s+([0-9]+)[.、]", line)
            if m:
                out.add(int(m.group(1)))
            m = re.match(r"^##\s+[一二三四五六七八九十]+、", line)
            if m:
                out.add(line.strip())
    return out


def main():
    bad = []
    for doc in DOCS:
        p = os.path.join(ROOT, doc)
        if not os.path.exists(p):
            bad.append(f"{doc}: 文件本身不存在")
            continue
        text = open(p, encoding="utf-8").read()

        for rel in set(LINK_RE.findall(text)):
            target = os.path.normpath(os.path.join(ROOT, os.path.dirname(doc), rel))
            if not os.path.exists(target):
                bad.append(f"{doc}: 引用 `{rel}` 不存在")

        # “某文件.md 第 N 节” —— 只在同一句里找，避免跨行误判
        for line in text.splitlines():
            for rel in LINK_RE.findall(line):
                target = os.path.normpath(os.path.join(ROOT, os.path.dirname(doc), rel))
                if not os.path.exists(target):
                    continue
                for num in SECTION_RE.findall(line):
                    if int(num) not in sections(target):
                        bad.append(f"{doc}: `{rel}` 没有第 {num} 节（该文件现只有 "
                                   f"{sorted(x for x in sections(target) if isinstance(x, int))}）")

        if doc not in ALLOW_IN:
            for w in STALE:
                if w in text:
                    bad.append(f"{doc}: 残留过时词「{w}」")

    if bad:
        print("✘ 文档一致性检查未通过：")
        for b in bad:
            print("  - " + b)
        sys.exit(1)
    print(f"✔ 文档一致性检查通过（{len(DOCS)} 份）")


if __name__ == "__main__":
    main()

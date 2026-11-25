# -*- coding: utf-8 -*-
"""删前核对：_工具脚本/tmp/cx4_ab 里那两个沙箱副本还有没有引用、里面有没有独有产物。"""
import os
import re
import hashlib

REPO = r"F:/开源掌机教程/_工具脚本"
DUMMY = r"F:/开源掌机教程/_工具脚本/tmp/cx4_ab/bizhawk_dummy"
CLEAN = r"F:/开源掌机教程/_工具脚本/tmp/cx4_ab/bizhawk_clean"
LIVE = r"F:/taspipe_scratch/cx4_ab/bizhawk"

print("=== 1. 哪些脚本提到 bizhawk_dummy / bizhawk_clean / tmp/cx4_ab")
hits = {}
for dp, dn, fn in os.walk(REPO):
    dn[:] = [x for x in dn if x not in ("tmp", "__pycache__", ".git", "node_modules")]
    for f in fn:
        if not f.endswith((".py", ".md", ".json", ".sh", ".ps1")):
            continue
        p = os.path.join(dp, f)
        try:
            t = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for kw in ("bizhawk_dummy", "bizhawk_clean"):
            if kw in t:
                hits.setdefault(kw, []).append((p, [i + 1 for i, l in enumerate(t.splitlines())
                                                    if kw in l][:6]))
for kw, v in hits.items():
    print("  %s:" % kw)
    for p, lines in v:
        print("     %s 行%s" % (p, lines))
if not hits:
    print("  （脚本正文零引用）")


def fingerprint(root):
    """只列非 dll/程序文件的独有内容：配置、固件、录像、状态、日志。"""
    uniq = []
    for dp, dn, fn in os.walk(root):
        rel = os.path.relpath(dp, root).replace("\\", "/")
        top = rel.split("/")[0]
        for f in fn:
            ext = os.path.splitext(f)[1].lower()
            if top == "dll" or ext in (".dll", ".pdb", ".xml", ".so", ".png", ".ico", ".ttf"):
                continue
            fp = os.path.join(dp, f)
            try:
                st = os.stat(fp)
            except OSError:
                continue
            uniq.append((rel + "/" + f, st.st_size, st.st_mtime))
    return uniq


for name, root in (("dummy", DUMMY), ("clean", CLEAN), ("live", LIVE)):
    if not os.path.isdir(root):
        print("\n%s 不存在" % root)
        continue
    u = fingerprint(root)
    print("\n=== 2. %s 非程序文件 %d 个" % (root, len(u)))
    for rel, sz, mt in sorted(u)[:40]:
        print("   %9d B  %s" % (sz, rel))

print("\n=== 3. 两份副本里 Firmware 目录")
for root in (DUMMY, CLEAN, LIVE):
    d = os.path.join(root, "Firmware")
    print("  ", root, "->", os.listdir(d) if os.path.isdir(d) else "无该目录")

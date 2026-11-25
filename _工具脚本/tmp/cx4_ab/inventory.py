# -*- coding: utf-8 -*-
"""盘点 cx4_ab 相关临时件：谁占盘、是否在 git 工作树里被忽略，只读不改。"""
import os
import subprocess

ROOTS = [r"F:/开源掌机教程/_工具脚本/tmp/cx4_ab", r"F:/taspipe_scratch/cx4_ab",
         r"F:/taspipe_scratch/cx4_probe_20261123", r"F:/taspipe_scratch/fw_channel_20261123",
         r"F:/taspipe_scratch/pip_zstd"]


def walk_size(d):
    tot = 0
    big = []
    for dirpath, dirnames, filenames in os.walk(d):
        dirnames[:] = [x for x in dirnames if x not in ("bizhawk", "r0_none", "r1_spec_dummy")]
        for f in filenames:
            try:
                n = os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                continue
            tot += n
            big.append((n, os.path.join(dirpath, f)))
    big.sort(reverse=True)
    return tot, big[:8]


for r in ROOTS:
    if not os.path.isdir(r):
        print(r, "不存在")
        continue
    tot, big = walk_size(r)
    print("\n%s  %.1f MB (bizhawk 沙箱树与两个 run 目录单列)" % (r, tot / 1048576.0))
    for n, p in big:
        print("   %9.1f KB  %s" % (n / 1024.0, p))
    for sub in ("bizhawk", "r0_none", "r1_spec_dummy"):
        p = os.path.join(r, sub)
        if os.path.isdir(p):
            s = sum(os.path.getsize(os.path.join(dp, f)) for dp, dn, fn in os.walk(p)
                    for f in fn if os.path.exists(os.path.join(dp, f)))
            print("   [子树 %-14s] %.1f MB" % (sub, s / 1048576.0))

print("\n--- git 里 _工具脚本/tmp 的跟踪情况")
o = subprocess.run(["git", "-C", r"F:/开源掌机教程", "status", "--porcelain", "--ignored",
                    "--", "_工具脚本/tmp"], capture_output=True, text=True, errors="replace")
lines = o.stdout.splitlines()
print("条目数=%d" % len(lines))
for l in lines[:12]:
    print("  ", l[:160])
o2 = subprocess.run(["git", "-C", r"F:/开源掌机教程", "ls-files", "_工具脚本/tmp"],
                    capture_output=True, text=True, errors="replace")
print("被 git 跟踪的文件数=%d" % len(o2.stdout.splitlines()))
for l in o2.stdout.splitlines()[:10]:
    print("  tracked:", l[:150])

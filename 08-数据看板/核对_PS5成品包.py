# -*- coding: utf-8 -*-
"""独立核对:获取台账的 asset 到底有几个在 成品包 里真存在(不走看板代码)。"""
import io
import os
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "06-资讯监控", "PS5移植商店", "成品包")

real = {}
for dp, dns, fns in os.walk(D):
    for fn in fns:
        real.setdefault(fn.lower(), []).append(os.path.relpath(os.path.join(dp, fn), ROOT))

rows = [ln.split("\t") for ln in io.open(os.path.join(ROOT, "06-资讯监控", "PS5移植商店", "获取台账.tsv"), encoding="utf-8").read().splitlines()[1:]]
hdr = io.open(os.path.join(ROOT, "06-资讯监控", "PS5移植商店", "获取台账.tsv"), encoding="utf-8").readline().rstrip("\n").split("\t")
ai = hdr.index("asset")
ni = hdr.index("name")

found = miss = blank = 0
blanks, missing = [], []
names = collections.Counter()
for r in rows:
    asset = r[ai] if len(r) > ai else ""
    names[asset] += 1
    if not asset:
        blank += 1
        blanks.append(r[ni][:40])
        continue
    if asset.lower() in real:
        found += 1
    else:
        miss += 1
        missing.append((r[ni][:30], asset[:44]))

print("台账行 %d | asset 命中本地 %d | 未命中 %d | 空 asset %d" % (len(rows), found, miss, blank))
dup = {k: v for k, v in names.items() if v > 1}
print("重复 asset:", dup)
print("空 asset 的行:", blanks)
print("未命中样例:", missing)
print("成品包文件总数:", sum(len(v) for v in real.values()), "唯一名:", len(real))
ext = collections.Counter(os.path.splitext(k)[1] for k in real)
print("成品包扩展名:", dict(ext))

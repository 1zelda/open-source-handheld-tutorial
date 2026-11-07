#!/usr/bin/env python3
"""把 ArkOS4Clone 的分卷 7z（.7z.001/002/003）合并解出 .img.xz，并记录派生哈希。
只处理命令行给定的前缀；已存在且哈希可算的目标文件会跳过（幂等）。
"""
import hashlib, os, subprocess, sys, py7zr

BASE = r"F:\开源掌机教程\02-模拟器库\已clone仓库\系统镜像"
PREFIXES = [
    r"ArkOS4Clone-20261008.img.xz.7z",
]

def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for blk in iter(lambda: f.read(16 * 1024 * 1024), b''):
            h.update(blk)
    return h.hexdigest()

for pre in PREFIXES:
    vols = [os.path.join(BASE, pre + '.%03d' % i) for i in (1, 2, 3)]
    missing = [v for v in vols if not os.path.exists(v)]
    if missing:
        print("SKIP(缺分卷)", os.path.basename(missing[0])); continue
    out = os.path.join(BASE, pre.replace('.7z', ''))   # ArkOS4Clone-20261008.img.xz
    if os.path.exists(out):
        print("已有", os.path.basename(out), os.path.getsize(out), sha256(out)); continue
    tmp = out + ".extracting"
    print("解卷 ->", os.path.basename(out), flush=True)
    with py7zr.SevenZipFile(vols[0], mode='r') as z:
        names = z.getnames()
        print("  归档内文件:", names, flush=True)
        z.extract(path=os.path.dirname(tmp) + "\\_ex_" + os.path.basename(pre))
    d = os.path.dirname(tmp) + "\\_ex_" + os.path.basename(pre)
    got = [os.path.join(d, n) for n in names]
    got = [g for g in got if os.path.isfile(g)]
    if len(got) != 1:
        print("!! 归档成员数不为 1，人工处理:", got); continue
    os.replace(got[0], out)
    print("OK", os.path.basename(out), os.path.getsize(out), "derived_sha256=" + sha256(out), flush=True)

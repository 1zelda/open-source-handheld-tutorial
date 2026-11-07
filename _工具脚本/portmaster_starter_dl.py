#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""下载 PortMaster 官方标注"自带完整游戏"的端口包, 逐个校验 MD5。

数据源: 02-模拟器库/已clone仓库/R36S专用/PortMaster-Info/ports.json
输出  : 04-游戏资源库/公版与开源游戏/ports起手包/*.zip

用法: py -3 _工具脚本/portmaster_starter_dl.py
"""
import hashlib
import io
import json
import os
import sys
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INFO = os.path.join(ROOT, "02-模拟器库", "已clone仓库", "R36S专用",
                    "PortMaster-Info", "ports.json")
DEST = os.path.join(ROOT, "04-游戏资源库", "公版与开源游戏", "ports起手包")

# 全部经 ports.json 确认为 r36s 可用 + 自带游戏数据 + <=20MB + 非 3D
PICKS = [
    "2048", "apotris", "spelunky", "cave.story-evo", "cave.story", "abuse",
    "sdlpop", "freegemas", "help.no.brake", "rick.dangerous", "opentyrian",
    "raptor", "akeyspath", "banana.duck", "gravitydefied", "nonny",
    "openmrac", "tiny-crate", "abes_adventure", "openblok", "simplesokoban",
    "blobby.volley2", "skifree", "blockout2", "icytower", "alienblaster",
    "wordlesdl", "nova_pinball", "mrrescue", "starcatcher",
]


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    with open(INFO, encoding="utf-8") as fh:
        ports = json.load(fh)["ports"]
    os.makedirs(DEST, exist_ok=True)

    ok = skip = bad = 0
    for name in PICKS:
        pkg = name + ".zip"
        rec = ports.get(pkg)
        if not rec:
            print("  ? 上游无此端口: %s" % pkg)
            bad += 1
            continue
        src = rec["source"]
        url, want = src["url"], src["md5"]
        out = os.path.join(DEST, pkg)
        if os.path.exists(out) and md5(out) == want:
            print("  = 已存在且校验通过: %s" % pkg)
            skip += 1
            continue
        tmp = out + ".part"
        try:
            urllib.request.urlretrieve(url, tmp)
        except Exception as exc:
            print("  x 下载失败 %s: %s" % (pkg, exc))
            bad += 1
            if os.path.exists(tmp):
                os.remove(tmp)
            continue
        got = md5(tmp)
        if got != want:
            print("  x MD5 不符 %s 期望=%s 实得=%s -> 删除" % (pkg, want, got))
            os.remove(tmp)
            bad += 1
            continue
        os.replace(tmp, out)
        print("  + %s  %.1f MB  md5 ok" % (pkg, os.path.getsize(out) / 1e6))
        ok += 1

    print("\n新下载 %d, 已存在 %d, 失败 %d" % (ok, skip, bad))
    total = sum(os.path.getsize(os.path.join(DEST, f)) for f in os.listdir(DEST)
                if f.endswith(".zip"))
    print("起手包合计: %.1f MB" % (total / 1e6))


if __name__ == "__main__":
    main()

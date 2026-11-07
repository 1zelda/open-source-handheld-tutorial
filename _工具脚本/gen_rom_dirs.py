#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从 ArkOS4Clone 的 es_systems.cfg 抽出"ROM 该放哪个目录 / 认什么扩展名"的权威表。

为什么不用网上抄的目录名: ArkOS 里 system 的 <name> 和实际 <path> 会不一致
(例: name=astrocade 但 path=/roms/astrocde/), 放错目录 = 前端里根本不会出现。

输出: 04-游戏资源库/自己ROM放这里/rom目录对照表.tsv

用法: py -3 _工具脚本/gen_rom_dirs.py
"""
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = {
    "ArkOS": os.path.join(ROOT, "02-模拟器库", "已clone仓库", "R36S专用",
                          "arkos4clone", "rootfs", "ArkOS", "etc", "emulationstation",
                          "es_systems.cfg"),
    "dArkOS": os.path.join(ROOT, "02-模拟器库", "已clone仓库", "R36S专用",
                           "arkos4clone", "rootfs", "dArkOS", "etc", "emulationstation",
                           "es_systems.cfg"),
}
DEST = os.path.join(ROOT, "04-游戏资源库", "自己ROM放这里", "rom目录对照表.tsv")

FIELD = re.compile(r"<(name|fullname|path|extension|command)>(.*?)</\1>", re.S)


def parse(cfg):
    txt = open(cfg, encoding="utf-8", errors="replace").read()
    out = []
    for block in re.findall(r"<system>(.*?)</system>", txt, re.S):
        f = {k: v.strip() for k, v in FIELD.findall(block)}
        path = f.get("path", "")
        if not path.startswith("/roms/"):
            continue  # /opt/system/ 之类是菜单项, 不是 ROM 目录
        rel = path.strip("/")[len("roms/"):]
        folder = rel
        exts = [e.lstrip(".").lower() for e in f.get("extension", "").split() if e]
        out.append({
            "folder": folder,
            "path": path.strip("/"),
            "name": f.get("name", ""),
            "fullname": f.get("fullname", ""),
            "exts": " ".join(sorted(set(exts))),
            "n_ext": len(set(exts)),
        })
    return out


def main():
    rows, flavours = [], {}
    for flavour, cfg in SRC.items():
        if not os.path.exists(cfg):
            print("x 缺文件: %s" % cfg)
            continue
        parsed = parse(cfg)
        flavours[flavour] = {r["folder"] for r in parsed}
        for r in parsed:
            r["flavour"] = flavour
        rows += parsed
        print("%-7s 解析出 %d 个 /roms/ 目录 (%s)" % (flavour, len(parsed), cfg.split("arkos4clone")[-1]))

    if "ArkOS" in flavours and "dArkOS" in flavours:
        only_ark = flavours["ArkOS"] - flavours["dArkOS"]
        only_dark = flavours["dArkOS"] - flavours["ArkOS"]
        print("两边差异: 仅 ArkOS=%s | 仅 dArkOS=%s" %
              (sorted(only_ark) or "无", sorted(only_dark) or "无"))

    with open(DEST, "w", encoding="utf-8", newline="") as fh:
        fh.write("flavour\tfolder\tpath\tname\tfullname\textensions\tn_ext\n")
        for r in sorted(rows, key=lambda x: (x["flavour"], x["folder"].lower())):
            fh.write("\t".join([r["flavour"], r["folder"], r["path"], r["name"],
                                r["fullname"], r["exts"], str(r["n_ext"])]) + "\n")

    ark = [r for r in rows if r["flavour"] == "ArkOS"]
    mismatch = [r for r in ark if r["folder"].lower() != r["name"].lower()]
    print("\n写入 %s (%d 行)" % (DEST, len(rows)))
    print("ArkOS 目录数: %d, 其中 folder != name 的有 %d 个(容易放错):" % (len(ark), len(mismatch)))
    for r in mismatch[:12]:
        print("   path 用 %-14s 而 name 是 %s" % (r["folder"], r["name"]))

    amb = {}
    for r in ark:
        for e in r["exts"].split():
            amb.setdefault(e, []).append(r["folder"])
    worst = sorted(((len(v), k, v) for k, v in amb.items() if k), reverse=True)[:8]
    print("\n扩展名归属最多的几个(单靠后缀判断会撞车, 需要看文件头):")
    for n, k, v in worst:
        print("   .%-5s -> %d 个目录: %s" % (k, n, ", ".join(v[:8])))


if __name__ == "__main__":
    main()

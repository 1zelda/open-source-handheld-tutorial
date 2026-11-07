#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""审计 ports全量合法池/ 里每个 zip 到底是不是"解压即玩"。

判定证据分两级:
  1) 上游权威字段 attr.availability。语义来自 PortMaster 官方表单
     (02-模拟器库/已clone仓库/R36S专用/PortMaster-Website/website/port-json.html:222-227):
       full  = Free game, all files included   -> 解压即玩
       demo  = Demo files included             -> 自带可玩的 demo, 完整版要另买
       free  = Free external assets needed     -> 需要自备"免费可得"的原始数据
       paid  = Paid external assets needed     -> 需要自备"已购买"的原始数据
     注意: free 不等于"免费包含", 上游原话是 external assets needed。
  2) 该字段为空时(老条目), 退回到 zip 内的占位文件标记 + attr.inst 文本 + 体积。

输出:
  04-游戏资源库/公版与开源游戏/portmaster_自备数据审计.tsv
  同目录 portmaster_仍需自备数据.txt   (可直接照着找素材的清单)
"""
import io
import json
import os
import re
import sys
import zipfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INFO = os.path.join(ROOT, "02-模拟器库", "已clone仓库", "R36S专用", "PortMaster-Info")
POOL = os.path.join(ROOT, "04-游戏资源库", "公版与开源游戏", "ports全量合法池")
OUT_DIR = os.path.join(ROOT, "04-游戏资源库", "公版与开源游戏")

# 占位/提示文件的两种形态: 名字里直接带"动词+here"; 或叫 *_here* / here.txt 且在放数据的目录里
MARKER_STRONG = re.compile(
    r"(?:place|put|add|copy|drop|insert|paste|move|extract|save|decompress|unzip)[ _\-\.]*here",
    re.I,
)
MARKER_WEAK = re.compile(r"here\.txt$|_here\b|_here\.", re.I)
DATADIR = re.compile(r"(?:game_?data|gamedir|data|games?|assets?|roms?|content|wads?|install)/", re.I)
# 上游 availability 为空的包, 退回读 inst 文本。
# 只认"安装动作 + 目的地"这类句子, 否则会把玩法描述(如 asteroludi 的
# "Extract minerals from asteroids")误判成要自备数据。
NEEDS_INST = re.compile(
    r"download .{0,60}(?:itch|steam|gog|https?://|\.zip|\.7z)"
    r"|(?:copy|extract|place|put|add|unzip|move) .{0,60}(?:into|to|in) "
    r"(?:the |this |your |its )?.{0,30}(?:folder|directory|\bdir\b|/|data|assets|gamedata|here)"
    r"|your own (?:copy|game|rom|wad|assets?|files?|data)|own copy|legally owned|purchase|buy the"
    r"|you (?:need to|must) (?:download|copy|place|provide|purchase|extract|own)",
    re.I,
)
SELF_RUN = re.compile(r"(ready to run|ready to go|all files (?:are )?included|"
                      r"comes with|already included)", re.I)
# "there is no need to download the game from itch.io" 这类否定句整句丢弃, 否则误判成要自备
NEGATION = re.compile(r"no need to|don'?t need|not need", re.I)


def inst_probe(text):
    return " ".join(s for s in re.split(r"(?<=[.!?])\s+", text or "")
                    if not NEGATION.search(s))


def cell(value):
    """TSV 一行一记录: 清掉制表符/换行, 双引号换成单引号(否则 csv 读取器会按引号配对吞行)。"""
    return (str(value).replace("\t", " ").replace("\r", " ")
            .replace("\n", " ").replace('"', "'"))


def norm_availability(value):
    v = (value or "").strip().lower()
    return v if v in ("full", "demo", "free", "paid") else ""


def marker_hits(pkg_path):
    hits = []
    try:
        with zipfile.ZipFile(pkg_path) as zf:
            for info in zf.infolist():
                name = info.filename.replace("\\", "/")
                base = name.rsplit("/", 1)[-1]
                if not base or info.is_dir():
                    continue
                if MARKER_STRONG.search(base) or (MARKER_WEAK.search(base) and DATADIR.search(name)):
                    hits.append(name)
    except zipfile.BadZipFile:
        hits.append("!BADZIP!")
    return hits


def main():
    ports = json.load(open(os.path.join(INFO, "ports.json"), encoding="utf-8"))["ports"]
    stats = json.load(open(os.path.join(INFO, "port_stats.json"), encoding="utf-8"))["ports"]

    zips = sorted(f for f in os.listdir(POOL) if f.endswith(".zip"))
    rows = []
    for pkg in zips:
        rec = ports.get(pkg) or {}
        attr = rec.get("attr") or {}
        src = rec.get("source") or {}
        av = norm_availability(attr.get("availability"))
        inst = (attr.get("inst") or "").replace("\t", " ").replace("\n", " ")
        size = os.path.getsize(os.path.join(POOL, pkg))
        hits = marker_hits(os.path.join(POOL, pkg))
        probe = inst_probe(inst)
        inst_needs = bool(NEEDS_INST.search(probe))

        if av == "full" and inst_needs:
            kind, why = "needs_conflict", "上游标 full 但 inst 要求自备数据"
        elif av == "full":
            kind, why = "self", "availability=full"
        elif av == "demo":
            kind, why = "demo", "availability=demo"
        elif av in ("free", "paid"):
            kind, why = "needs_" + av, "availability=%s(external assets needed)" % av
        elif hits:
            kind, why = "needs_unknown", "zip 内有放数据的占位文件"
        elif inst_needs:
            kind, why = "needs_unknown", "inst 说明要求自备"
        elif size < 150 * 1024 and not SELF_RUN.search(probe):
            kind, why = "suspect", "无标注、无说明且包体 <150KB"
        else:
            kind, why = "self_unmarked", "无标注, 未见自备要求"

        links = []
        for s in (attr.get("store") or []):
            url = s.get("url") or s.get("gameurl") or s.get("developerurl")
            if url:
                links.append("%s=%s" % (s.get("name") or "?", url))
        rows.append({
            "name": pkg[:-4],
            "title": attr.get("title") or pkg[:-4],
            "kind": kind,
            "evidence": why,
            "availability": av or "?",
            "mb": round(size / 1e6, 2),
            "markers": ";".join(hits[:3]),
            "downloads": stats.get(pkg, 0),
            "store": "+".join(links),
            "inst": inst[:260],
        })

    rows.sort(key=lambda r: (r["kind"], -r["mb"]))
    cols = ["name", "title", "kind", "evidence", "availability", "mb",
            "markers", "downloads", "store", "inst"]
    tsv = os.path.join(OUT_DIR, "portmaster_自备数据审计.tsv")
    with open(tsv, "w", encoding="utf-8", newline="") as fh:
        fh.write("\t".join(cols) + "\n")
        for r in rows:
            fh.write("\t".join(cell(r[c]) for c in cols) + "\n")

    need = [r for r in rows if r["kind"].startswith("needs_")]
    with open(os.path.join(OUT_DIR, "portmaster_仍需自备数据.txt"), "w",
              encoding="utf-8") as fh:
        fh.write("# 已下载但需要自备游戏数据才能玩的端口(限 r36s)\n")
        fh.write("# needs_free=免费素材可自行下载, needs_paid=需已购原版, "
                 "needs_conflict=官方标 full 但说明要求自备, needs_unknown=官方未标注但检测到要求\n")
        fh.write("# 列: 分组\t包名\t素材来源\t要做的事\n")
        for r in need:
            fh.write("%s\t%s\t%s\t%s\n" % (r["kind"], r["name"], r["store"] or "—",
                                           (r["inst"] or r["markers"])[:200]))

    from collections import Counter
    c = Counter(r["kind"] for r in rows)
    mb = {}
    for r in rows:
        mb[r["kind"]] = mb.get(r["kind"], 0) + r["mb"]
    print("池内包数: %d" % len(rows))
    for k in sorted(c):
        print("  %-14s %4d 个  %8.2f GB" % (k, c[k], mb[k] / 1024))
    print("写入 %s / portmaster_仍需自备数据.txt" % tsv)


if __name__ == "__main__":
    main()

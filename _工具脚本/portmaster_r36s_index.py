#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从 PortMaster-Info/ports.json 生成"我的 R36S 能装哪些 port"的权威清单。

数据源(本地, 无需联网):
  02-模拟器库/已clone仓库/R36S专用/PortMaster-Info/ports.json      上游端口元数据
  同目录 port_stats.json                                            各端口下载量

输出:
  04-游戏资源库/公版与开源游戏/portmaster_r36s_全清单.tsv   机器可读, 每个 port 一行
  04-游戏资源库/公版与开源游戏/portmaster_r36s_拿来即玩.txt  自包含、无需自备游戏的端口名

用法: py -3 _工具脚本/portmaster_r36s_index.py

说明: 上游 availability 字段大量为空, 所以"是否自带完整游戏"以 inst(安装说明)文本为准。
"""
import io
import json
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INFO = os.path.join(ROOT, "02-模拟器库", "已clone仓库", "R36S专用", "PortMaster-Info")
OUT_DIR = os.path.join(ROOT, "04-游戏资源库", "公版与开源游戏")
DEVICE = "r36s"

NEEDS = re.compile(
    r"download .{0,60}(?:itch|steam|gog|https?://|\.zip|\.7z)"
    r"|(?:copy|extract|place|put|add|unzip|move) .{0,60}(?:into|to|in) "
    r"(?:the |this |your |its )?.{0,30}(?:folder|directory|\bdir\b|/|data|assets|gamedata|here)"
    r"|your own (?:copy|game|rom|wad|assets?|files?|data)|own copy|legally owned|purchase|buy the"
    r"|you (?:need to|must) (?:download|copy|place|provide|purchase|extract|own)", re.I)
SELF_CONTAINED = re.compile(r"(ready to run|ready to go|all retail levels|"
                            r"included and ready|comes with|already included)", re.I)
NEGATION = re.compile(r"no need to|don'?t need|not need", re.I)


def cell(value):
    """一行一记录: 制表符/换行必须清掉。
    双引号也要换掉 —— 裸写的 TSV 被 csv 读取器按引号配对解析, 实测会吞掉 22 行
    (VVVVVV / doomengines / wolf3d 就是这样从"清单"里消失的)。
    """
    return (str(value).replace("\t", " ").replace("\r", " ")
            .replace("\n", " ").replace('"', "'"))


def classify(inst, availability, reqs):
    """返回 self / needs_data / unknown。

    availability 的官方语义见 PortMaster-Website/website/port-json.html:222-227:
      full=所有文件已包含, demo=自带 demo, free=需自备(免费可得的)外部素材,
      paid=需自备(已购买的)外部素材。
    reqs 是设备能力要求(lowres/power/opengl/...), 与"要不要自备游戏数据"无关, 不参与判定。
    """
    text = " ".join(s for s in re.split(r"(?<=[.!?])\s+", cell(inst))
                    if not NEGATION.search(s))
    if availability == "demo":
        return "self"          # 自带 demo, 开箱能玩(完整版另需)
    if availability in ("free", "paid") or NEEDS.search(text):
        return "needs_data"    # 官方要求自备, 或说明里出现"下载/拷贝/解压到…目录"
    if availability == "full" or SELF_CONTAINED.search(text):
        return "self"
    return "unknown"


def load(name):
    with open(os.path.join(INFO, name), encoding="utf-8") as fh:
        return json.load(fh)


def main():
    ports = load("ports.json")["ports"]
    stats = load("port_stats.json")["ports"]

    rows = []
    for pkg, rec in ports.items():
        attr = rec.get("attr") or {}
        avail = attr.get("avail") or []
        if not any(a.split(":")[0] == DEVICE for a in avail):
            continue
        cfw = sorted({a.split(":", 1)[1] for a in avail
                      if a.split(":")[0] == DEVICE and ":" in a and a.split(":", 1)[1] != "ALL"})
        src = rec.get("source") or {}
        kind = classify(attr.get("inst"), (attr.get("availability") or "").lower(),
                        attr.get("reqs"))
        rows.append({
            "name": pkg.replace(".zip", ""),
            "title": attr.get("title") or pkg,
            "mb": round((src.get("size") or 0) / 1e6, 1),
            "arch": "+".join(attr.get("arch") or []) or "any",
            "license": (attr.get("availability") or "").lower() or "?",
            "game_data": kind,
            "genres": "+".join(attr.get("genres") or []) or "",
            "downloads": stats.get(pkg, 0),
            "rtr": "yes" if attr.get("rtr") else "no",
            "cfw_only": ",".join(cfw),
            "porter": ",".join(attr.get("porter") or []),
            "desc": (attr.get("desc") or "").replace("\t", " ").replace("\n", " ")[:180],
            "inst": (attr.get("inst") or "").replace("\t", " ").replace("\n", " ")[:300],
            "md5": src.get("md5") or "",
            "url": src.get("url") or "",
        })

    rows.sort(key=lambda r: -r["downloads"])

    cols = ["name", "title", "mb", "arch", "license", "game_data", "genres",
            "downloads", "rtr", "cfw_only", "porter", "desc", "inst", "md5", "url"]
    tsv = os.path.join(OUT_DIR, "portmaster_r36s_全清单.tsv")
    with open(tsv, "w", encoding="utf-8", newline="") as fh:
        fh.write("\t".join(cols) + "\n")
        for r in rows:
            fh.write("\t".join(cell(r[c]) for c in cols) + "\n")

    selfs = [r for r in rows if r["game_data"] == "self"]
    with open(os.path.join(OUT_DIR, "portmaster_r36s_拿来即玩.txt"), "w", encoding="utf-8") as fh:
        fh.write("# 开箱能玩的 PortMaster 端口(限 r36s 档) —— 官方 availability=full, 或说明写明 ready to run\n")
        fh.write("# 判据来自 ports.json 的 attr.availability + attr.inst; free/paid 一律算\"需自备\", 见下一行\n")
        fh.write("# 逐包证据: ../公版与开源游戏/portmaster_自备数据审计.tsv (含 needs_free 的免费素材来源)\n")
        fh.write("# 按下载量降序。共 %d 个。\n" % len(selfs))
        for r in selfs:
            fh.write("%s\t%sMB\t%s\n" % (r["name"], r["mb"], r["title"]))

    def stat(label, sub):
        print("%-26s %5d 个  合计 %6.1f GB" % (label, len(sub), sum(x["mb"] for x in sub) / 1000))

    print("已写 %s —— %d 行" % (tsv, len(rows)))
    stat("总计", rows)
    stat("自带游戏解压即玩", selfs)
    stat("需自备原版数据", [r for r in rows if r["game_data"] == "needs_data"])
    stat("上游未说明", [r for r in rows if r["game_data"] == "unknown"])
    stat("即玩且 <=60MB", [r for r in selfs if r["mb"] <= 60])

    def table(sub, limit):
        print()
        print("| Port | 标题 | 体积 | 架构 | 类型 | 下载量 |")
        print("|---|---|---|---|---|---|")
        for r in sub[:limit]:
            print("| `%s` | %s | %sMB | %s | %s | %s |" % (
                r["name"], r["title"], r["mb"], r["arch"], r["genres"], r["downloads"]))

    print("\n### A. 按下载量前 40(不限授权, 含需自备游戏的商业作品兼容层)")
    table(rows, 40)

    pick = [r for r in selfs if r["mb"] <= 60]
    print("\n### B. 解压即玩 + <=60MB(共 %d 个), 按下载量前 45" % len(pick))
    table(pick, 45)

    light = [r for r in pick if r["mb"] <= 20 and "3d" not in (r["genres"] or "").lower()]
    print("\n### C. RK3326/1GB 稳妥区: 即玩 + <=20MB + 非 3D(共 %d 个), 前 45" % len(light))
    table(light, 45)
    print("\n起手包候选 = C 组前 12, 累计 %.0f MB" % sum(r["mb"] for r in light[:12]))


if __name__ == "__main__":
    main()

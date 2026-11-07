#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘点:从产物(台账/登记表/磁盘)重算本库的关键数字,不联网。"""
import collections
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)


def tsv(p):
    lines = open(p, encoding="utf-8").read().splitlines()
    head = lines[0].split("\t")
    rows = []
    for l in lines[1:]:
        if not l.strip() or l.startswith("#"):
            continue
        rows.append(dict(zip(head, l.split("\t") + [""] * (len(head) - len(l.split("\t"))))))
    return head, rows


head, rows = tsv("06-资讯监控/台账.tsv")
print("资讯台账:%d 列 / %d 条 | HOT %d | SUSPECT %d | ARR %d" % (
    len(head), len(rows),
    sum(1 for r in rows if r["flag_hot"] == "HOT"),
    sum(1 for r in rows if r["flag_note"]),
    sum(1 for r in rows if r["flag_arrival"].startswith("ARR|"))))
if "flag_focus" in head:
    fc = {}
    for r in rows:
        for tg in (r.get("flag_focus") or "").split("+"):
            if tg:
                fc[tg] = fc.get(tg, 0) + 1
    print("  聚焦分布:", "、".join("%s %d" % kv for kv in sorted(fc.items(), key=lambda x: -x[1])),
          "| 无主题 %d" % sum(1 for r in rows if not (r.get("flag_focus") or "")))

_, reg = tsv("06-资讯监控/源登记表.tsv")
print("资讯源登记表:%d 行 | 启用 %d" % (len(reg), sum(1 for r in reg if r.get("enabled") == "1")))

_, vr = tsv("06-资讯监控/大作判定.tsv")
print("大作判定表:%d 行 | %s" % (len(vr), dict(collections.Counter(r["verdict"] for r in vr))))

_, pool = tsv("04-游戏资源库/爆款收录/收录台账.tsv")
tot = sum(int(r["bytes"]) for r in pool)
print("爆款收录:%d 组 / %d payload / %d B = %.1f MB(十进制) = %.1f MiB" % (
    len({r["id"] for r in pool}), len(pool), tot, tot / 1e6, tot / 1048576))
print("  verify 分布:%s" % dict(collections.Counter(r["verify"] for r in pool)))

_, dl = tsv("06-资讯监控/合法收录登记表.tsv")
print("合法收录登记表:%d 行 | 启用 %d / 停用 %d" % (
    len(dl), sum(1 for r in dl if r["enabled"] == "1"), sum(1 for r in dl if r["enabled"] == "0")))

if os.path.exists("04-游戏资源库/下架抢救/收录台账.tsv"):
    _, rs = tsv("04-游戏资源库/下架抢救/收录台账.tsv")
    print("下架抢救台账:%d 行 | %s | 合计 %.1f MB" % (
        len(rs), dict(collections.Counter(r["status"] for r in rs)),
        sum(int(r["bytes"] or 0) for r in rs) / 1e6))
if os.path.exists("06-资讯监控/下架抢救登记表.tsv"):
    _, rr = tsv("06-资讯监控/下架抢救登记表.tsv")
    print("下架抢救登记表:%d 行 | %s | 按优先级 %s" % (
        len(rr), dict(collections.Counter(r.get("action", "") for r in rr)),
        dict(collections.Counter(r.get("priority", "") for r in rr))))

SKIP = {"收录台账.tsv", "复检.md", "readme.md", "_download.log"}
disk = set()
for dp, _, fs in os.walk("04-游戏资源库/爆款收录"):
    for fn in fs:
        if fn.lower() in SKIP:
            continue
        disk.add(os.path.relpath(os.path.join(dp, fn), ROOT).replace(os.sep, "/"))
led = {r["dest"] for r in pool}
print("磁盘 payload %d 个 | 磁盘有台账无 %s | 台账有磁盘无 %s" % (
    len(disk), sorted(disk - led) or "无", sorted(led - disk) or "无"))

md = 0
for dp, _, fs in os.walk("."):
    if ".git" in dp.split(os.sep):
        continue
    md += sum(1 for f in fs if f.lower().endswith(".md"))
print("全库 Markdown(含 clone 仓库自带):%d 篇" % md)

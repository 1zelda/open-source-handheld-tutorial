#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""weekly_digest.py —— 周报汇总(2026-10-21 新增)

为什么要有:日报是"今天发生了什么",周报是"这一周在往哪儿走"——
聚焦分布怎么移的、HOT 出了几条、新落了哪些 payload、失败源是不是天天同一批。
这些趋势日报里看不出来。

产物:06-资讯监控/周报/YYYY-Www.md(ISO 周编号,当周每天刷新,内容=本周至今)。
幂等:每天重跑生成同一个文件,daily_run 无条件调用,不加星期几判断。

数据源(全部本地,不联网):
  - 台账.tsv:first_seen_utc 在最近 7 天的条目(按本地日期算)
  - 04-游戏资源库/爆款收录/收录台账.tsv:fetched_utc 在最近 7 天的 payload
  - 04-游戏资源库/下架抢救/收录台账.tsv:最近 7 天新抓的
  - 06-资讯监控/日报/*.md:最近 7 天的失败源表(汇总"天天挂"的源)
"""
import datetime as dt
import json
import os
import re
import sys
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MON = os.path.join(ROOT, "06-资讯监控")
WEEK = os.path.join(MON, "周报")
LEDGER = os.path.join(MON, "台账.tsv")
BURST = os.path.join(ROOT, "04-游戏资源库", "爆款收录", "收录台账.tsv")
RESCUE = os.path.join(ROOT, "04-游戏资源库", "下架抢救", "收录台账.tsv")
DAILY = os.path.join(MON, "日报")


def local_day(s):
    try:
        return dt.datetime.strptime(s[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def rows_of(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        head = fh.readline().rstrip("\n").split("\t")
        out = []
        for line in fh:
            if not line.strip():
                continue
            p = line.rstrip("\n").split("\t")
            out.append(dict(zip(head, p + [""] * (len(head) - len(p)))))
        return out


def main():
    today = dt.date.today()
    week_ago = today - dt.timedelta(days=7)
    iso = today.isocalendar()
    wk_name = "%d-W%02d" % (iso[0], iso[1])

    led = rows_of(LEDGER)
    recent = [r for r in led if (local_day(r.get("first_seen_utc", "")) or today) >= week_ago]
    hot = [r for r in recent if r.get("flag_hot") == "HOT"]
    per_day = Counter((r.get("first_seen_utc") or "")[:10] for r in recent)
    focus = Counter()
    for r in recent:
        for f in (r.get("flag_focus") or "").split("+"):
            if f:
                focus[f] += 1
    arr = [r for r in recent if (r.get("flag_arrival") or "").startswith("ARR|")]
    by_source = Counter(r.get("source", "") for r in recent)

    burst = [r for r in rows_of(BURST)
             if (local_day((r.get("fetched_utc") or "")[:10]) or today) >= week_ago]
    rescue = [r for r in rows_of(RESCUE)
              if (local_day((r.get("fetched_utc") or "")[:10]) or today) >= week_ago]

    # 最近 7 天的日报失败表:汇总"天天挂"的源
    fail = Counter()
    for i in range(7):
        d = today - dt.timedelta(days=i)
        p = os.path.join(DAILY, "%s.md" % d.isoformat())
        if not os.path.exists(p):
            continue
        txt = open(p, encoding="utf-8", errors="replace").read()
        for m in re.finditer(r"^\| ([^|]+) \| (\d+|curl_err_\S+|000) \|", txt, re.M):
            fail[(m.group(1).strip(), m.group(2).strip())] += 1
    chronic = [(n, c, k) for (n, c), k in sorted(fail.items(), key=lambda x: -x[1]) if k >= 3]

    os.makedirs(WEEK, exist_ok=True)
    out = os.path.join(WEEK, "%s.md" % wk_name)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("# 周报 %s(本周至今:%s ~ %s)\n\n" % (wk_name, week_ago.isoformat(), today.isoformat()))
        fh.write("- 新入库 **%d** 条(日均 %.1f);HOT **%d** 条;大作登陆(ARR)**%d** 条\n"
                 % (len(recent), len(recent) / 7.0, len(hot), len(arr)))
        fh.write("- 台账累计 **%d** 条\n\n" % len(led))
        fh.write("## 每日入库量\n\n| 日期 | 条数 |\n|---|---|\n")
        for d, n in sorted(per_day.items()):
            fh.write("| %s | %d |\n" % (d, n))
        fh.write("\n## 聚焦分布(本周新条目)\n\n| 主题 | 条数 |\n|---|---|\n")
        for k, v in focus.most_common():
            fh.write("| %s | %d |\n" % (k, v))
        fh.write("\n## 高产源 TOP10\n\n| 源 | 条数 |\n|---|---|\n")
        for k, v in by_source.most_common(10):
            fh.write("| %s | %d |\n" % (k, v))
        if hot:
            fh.write("\n## 本周 HOT(最多 30 条)\n\n")
            for r in hot[:30]:
                fh.write("- %s [%s](%s) _%s_\n" % ((r.get("pub") or "")[:10], (r.get("title") or "")[:60],
                                                   r.get("url", ""), r.get("source", "")[:20]))
        fh.write("\n## 本周新落盘 payload(%d 个)\n\n" % len(burst))
        if burst:
            fh.write("| id | 资产 | 大小 | verify |\n|---|---|---|---|\n")
            for r in burst:
                fh.write("| %s | %s | %.1f MB | %s |\n" % (
                    r.get("id", ""), r.get("asset", ""), int(r.get("bytes") or 0) / 1048576, r.get("verify", "")))
        else:
            fh.write("(无)\n")
        fh.write("\n## 本周下架抢救新增(%d 个)\n\n" % len(rescue))
        if rescue:
            for r in rescue:
                fh.write("- %s — %s(%s)\n" % (r.get("id", ""), r.get("asset", ""), r.get("verify", "")))
        else:
            fh.write("(无)\n")
        fh.write("\n## 天天挂的源(7 天里失败 ≥3 次)\n\n")
        if chronic:
            fh.write("| 源 | 失败次数 | 典型状态 |\n|---|---|---|\n")
            for n, c, k in chronic:
                fh.write("| %s | %d | %s |\n" % (n, k, c))
        else:
            fh.write("(没有连续失败的源)\n")
    print("周报 %s -> %s" % (wk_name, out))
    print("  新入库 %d / HOT %d / ARR %d / 新 payload %d / 常败源 %d"
          % (len(recent), len(hot), len(arr), len(burst), len(chronic)))


if __name__ == "__main__":
    main()

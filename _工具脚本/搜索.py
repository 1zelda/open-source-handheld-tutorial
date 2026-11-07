#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""搜索.py —— 全库本地搜索(2026-10-21 新增)

为什么要有:台账 8900+ 条、判定/登记表 150+ 行、教程库 253 篇 Markdown,
之前只能靠 grep 手拼命令,且 TSV 的列含义记不住。这个工具按库内口径把
"搜什么、在哪搜、结果长什么样"固定下来。

用法:
  py -3 _工具脚本/搜索.py 关键词 [更多关键词...]      # 多个词是 AND(都要出现)
  py -3 _工具脚本/搜索.py 风之杖 --scope 台账           # 只搜一个范围
  py -3 _工具脚本/搜索.py mkw --scope 判定 --full       # 看整条 note
  py -3 _工具脚本/搜索.py ppsspp --scope 源             # 搜源登记表(找某站有没有源)

范围(scope):台账 / 判定 / 登记 / 源 / 教程 / 全部(默认)
  - 台账:搜 title/url/source 三列,输出 日期|来源|标题|链接|HOT|聚焦
  - 判定:搜 match/action/note,输出 判定|动作|payload
  - 登记:搜 id/name/repo/note,输出 id|名称|仓库|kind|tag
  - 源:  搜 name/url/note,输出 源名|URL|启用与否
  - 教程:搜文件名+正文(01-教程库),输出 文件|命中行
大小写不敏感;关键词里的正则元字符按字面处理。
"""
import argparse
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MON = os.path.join(ROOT, "06-资讯监控")
SCOPES = ("台账", "判定", "登记", "源", "教程")


def tsv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        head = fh.readline().rstrip("\n").split("\t")
        rows = []
        for line in fh:
            if not line.strip():
                continue
            p = line.rstrip("\n").split("\t")
            rows.append(dict(zip(head, p + [""] * (len(head) - len(p)))))
        return rows


def hit(haystack, pats):
    return all(p.search(haystack) for p in pats)


def show(row, cols, full=False, maxlen=150):
    out = []
    for label, val in cols:
        v = re.sub(r"\s+", " ", val or "").strip()
        if not v:
            continue
        if not full and len(v) > maxlen:
            v = v[:maxlen] + "…"
        out.append("%s=%s" % (label, v))
    return "  ".join(out)


def search_ledger(pats, limit, full):
    rows = tsv(os.path.join(MON, "台账.tsv"))
    n = 0
    for r in rows:
        blob = " ".join([r.get("title", ""), r.get("url", ""), r.get("source", "")])
        if not hit(blob, pats):
            continue
        n += 1
        if n > limit:
            break
        print("  %s | %-22s | %s" % ((r.get("first_seen_utc") or "")[:10],
                                     (r.get("source") or "")[:22], (r.get("title") or "")[:70]))
        if full:
            print("      url=%s  HOT=%s 聚焦=%s 判定=%s" % (
                r.get("url", ""), r.get("flag_hot", ""), r.get("flag_focus", ""), r.get("flag_arrival", "")))
    print("  (台账命中 %d 个%s)" % (n, ",已截断" if n > limit else ""))
    return n


def search_verdict(pats, limit, full):
    rows = tsv(os.path.join(MON, "大作判定.tsv"))
    n = 0
    for r in rows:
        if "match" not in r:
            continue
        blob = " ".join([r.get("match", ""), r.get("action", ""), r.get("note", ""), r.get("payload", "")])
        if not hit(blob, pats):
            continue
        n += 1
        if n > limit:
            break
        print("  [%s] %s" % (r.get("verdict", "?"), (r.get("action") or "")[:60]))
        if r.get("payload"):
            print("      payload=%s" % r["payload"])
        if full:
            print("      note=%s" % (r.get("note") or "")[:400])
    print("  (判定表命中 %d 个%s)" % (n, ",已截断" if n > limit else ""))
    return n


def search_registry(pats, limit, full):
    rows = tsv(os.path.join(MON, "合法收录登记表.tsv"))
    n = 0
    for r in rows:
        blob = " ".join([r.get("id", ""), r.get("name", ""), r.get("repo", ""), r.get("note", "")])
        if not hit(blob, pats):
            continue
        n += 1
        if n > limit:
            break
        print("  %-22s | %-9s | %s" % (r.get("id", ""), r.get("kind", ""), (r.get("name") or "")[:55]))
        if full:
            print("      repo=%s tag=%s needs_data=%s" % (r.get("repo", ""), r.get("tag", ""), r.get("needs_data", "")[:60]))
    print("  (登记表命中 %d 个%s)" % (n, ",已截断" if n > limit else ""))
    return n


def search_sources(pats, limit, full):
    rows = tsv(os.path.join(MON, "源登记表.tsv"))
    n = 0
    for r in rows:
        blob = " ".join([r.get("name", ""), r.get("url", ""), r.get("note", "")])
        if not hit(blob, pats):
            continue
        n += 1
        if n > limit:
            break
        print("  [%s] %s" % ("启用" if r.get("enabled") == "1" else "停用", (r.get("name") or "")[:44]))
        print("      %s" % (r.get("url") or "")[:110])
    print("  (源登记表命中 %d 个%s)" % (n, ",已截断" if n > limit else ""))
    return n


def search_tutorials(pats, limit, full):
    base = os.path.join(ROOT, "01-教程库")
    n = 0
    for dirpath, _, files in os.walk(base):
        for fn in files:
            if not fn.lower().endswith(".md"):
                continue
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, ROOT).replace("\\", "/")
            if hit(rel, pats):
                n += 1
                if n <= limit:
                    print("  (文件名命中) %s" % rel)
                continue
            try:
                txt = open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            if not hit(txt, pats):
                continue
            n += 1
            if n > limit:
                continue
            lines = [l.strip() for l in txt.splitlines() if l.strip()]
            first = next((l for l in lines if all(p.search(l) for p in pats)), lines[0] if lines else "")
            print("  %s" % rel)
            print("      %s" % first[:120])
    print("  (教程库命中 %d 个%s)" % (n, ",已截断" if n > limit else ""))
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("keywords", nargs="+")
    ap.add_argument("--scope", default="全部", help="范围:" + "/".join(SCOPES) + "/全部")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--full", action="store_true", help="输出整条(不截断)")
    args = ap.parse_args()
    pats = [re.compile(re.escape(k), re.I) for k in args.keywords]
    todo = SCOPES if args.scope == "全部" else (args.scope,)
    total = 0
    for s in todo:
        print("== %s ==" % s)
        fn = {"台账": search_ledger, "判定": search_verdict, "登记": search_registry,
              "源": search_sources, "教程": search_tutorials}[s]
        total += fn(pats, args.limit, args.full)
    print("\n合计命中 %d 条(每范围上限 %d)" % (total, args.limit))


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""P7 两臂逐格对比（P7 vs P6 基线）：评测 grades + 探针状态/hits 排序。"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path
ROOT = Path(__file__).resolve().parent


def cmp_eval(pre_fn, post_fn, label):
    pre = json.loads((ROOT / pre_fn).read_text(encoding="utf-8"))
    post = json.loads((ROOT / post_fn).read_text(encoding="utf-8"))
    gd = []
    for a, b in zip(pre["grades"], post["grades"]):
        for k in ("ok", "status", "gold_pos", "condition", "refusal", "retrieval"):
            if a.get(k) != b.get(k):
                gd.append(f"{a['id']}.{k}: {a.get(k)}->{b.get(k)}")
    print(f"{label}评测grades逐字段: {len(gd)} 差异")
    for d in gd:
        print(f"  {d}")
    if not gd:
        print("  零差异 OK")
    print(f"  summary: {post['summary']['ok']}/{post['summary']['total']} "
          f"fail={post['summary']['failed_ids']}")
    return len(gd)


def cmp_probe(pre_fn, post_fn, label):
    pre = json.loads((ROOT / pre_fn).read_text(encoding="utf-8"))
    post = json.loads((ROOT / post_fn).read_text(encoding="utf-8"))
    pd = []
    for a, b in zip(pre, post):
        assert a["id"] == b["id"]
        for w in ("w3", "w5"):
            if a[w]["status"] != b[w]["status"]:
                pd.append(f"{a['id']} {w}: {a[w]['status']}->{b[w]['status']}")
            ah = [h.get("chunk_id") for h in a[w].get("hits", [])]
            bh = [h.get("chunk_id") for h in b[w].get("hits", [])]
            if ah != bh:
                pd.append(f"{a['id']} {w}: hits排序变化")
    print(f"{label}探针逐格(状态+hits排序): {len(pd)} 差异")
    for d in pd:
        print(f"  {d}")
    if not pd:
        print("  零差异 OK")
    return len(pd)


total = 0
total += cmp_eval("p6_prod_bm25.json", "p7_prod_bm25.json", "bm25")
total += cmp_probe("p6_probe_bm25", "p7_probe_bm25", "bm25")
total += cmp_eval("p6_prod_hybrid.json", "p7_prod_hybrid.json", "hybrid")
total += cmp_probe("p6_probe_hybrid", "p7_probe_hybrid", "hybrid")
print(f"\n两臂总差异: {total}（应 0）")
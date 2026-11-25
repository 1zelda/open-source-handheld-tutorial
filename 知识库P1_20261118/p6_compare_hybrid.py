# -*- coding: utf-8 -*-
"""P6 hybrid 臂逐格对比（评测 grades + 探针状态/hits 排序）。"""
import json, sys
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path
ROOT = Path(__file__).resolve().parent

pre_e = json.loads((ROOT / "p23_revert_prod_hybrid.json").read_text(encoding="utf-8"))
post_e = json.loads((ROOT / "p6_prod_hybrid.json").read_text(encoding="utf-8"))
gd = []
for a, b in zip(pre_e["grades"], post_e["grades"]):
    for k in ("ok", "status", "gold_pos", "condition", "refusal", "retrieval"):
        if a.get(k) != b.get(k):
            gd.append(f"{a['id']}.{k}: {a.get(k)}->{b.get(k)}")
print(f"hybrid评测grades逐字段: {len(gd)} 差异")
for d in gd:
    print(f"  {d}")
if not gd:
    print("  零差异 OK")
print(f"  summary: {post_e['summary']}")

pre_p = json.loads((ROOT / "p23_revert_probe_hybrid.json").read_text(encoding="utf-8"))
post_p = json.loads((ROOT / "p6_probe_hybrid").read_text(encoding="utf-8"))
pd = []
for a, b in zip(pre_p, post_p):
    assert a["id"] == b["id"]
    for w in ("w3", "w5"):
        if a[w]["status"] != b[w]["status"]:
            pd.append(f"{a['id']} {w}: {a[w]['status']}->{b[w]['status']}")
        ah = [h.get("chunk_id") for h in a[w].get("hits", [])]
        bh = [h.get("chunk_id") for h in b[w].get("hits", [])]
        if ah != bh:
            pd.append(f"{a['id']} {w}: hits排序变化")
print(f"hybrid探针逐格(状态+hits排序): {len(pd)} 差异")
for d in pd:
    print(f"  {d}")
if not pd:
    print("  零差异 OK")
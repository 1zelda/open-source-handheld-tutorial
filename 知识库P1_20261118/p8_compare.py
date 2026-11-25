# -*- coding: utf-8 -*-
"""P8 再索引逐格对比生产基线（p7_prod_* / p7_probe_*）。

与 P7 对比不同：再索引预期有差异，本脚本如实列出每一处，并按跑前规则分类：
- 评测 grades 逐字段差异（ok/status/gold_pos/condition/refusal/retrieval）
- 探针 w3/w5 状态翻转（标明方向：救回 inconclusive->pass / 回归 pass->非pass）
- 探针 hits 排序变化计数
- 焦点格全文 dump：W03/W09/X18/X16/X26/X17（真阳/假阳判定要看放行块原文）
用法：py -3 -u p8_compare.py bm25
"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path
ROOT = Path(__file__).resolve().parent
FOCUS = {"W03", "W09", "X18", "X16", "X26", "X17", "W14", "X23", "X28"}


def cmp_eval(arm):
    pre = json.loads((ROOT / f"p7_prod_{arm}.json").read_text(encoding="utf-8"))
    post = json.loads((ROOT / f"p8_reindex_{arm}_eval.json").read_text(encoding="utf-8"))
    gd = []
    for a, b in zip(pre["grades"], post["grades"]):
        for k in ("ok", "status", "gold_pos", "condition", "refusal", "retrieval"):
            if a.get(k) != b.get(k):
                gd.append(f"{a['id']}.{k}: {a.get(k)}->{b.get(k)}")
    print(f"[{arm}] 评测 grades 逐字段: {len(gd)} 差异")
    for d in gd:
        print(f"  {d}")
    ok_reg = [a['id'] for a, b in zip(pre['grades'], post['grades'])
              if a['ok'] and not b['ok']]
    ok_gain = [a['id'] for a, b in zip(pre['grades'], post['grades'])
               if not a['ok'] and b['ok']]
    print(f"  ok 回归(pass->fail): {ok_reg}  ok 新增(fail->pass): {ok_gain}")
    print(f"  summary 基线 {pre['summary']['ok']}/{pre['summary']['total']} "
          f"-> 再索引 {post['summary']['ok']}/{post['summary']['total']} "
          f"fail={post['summary']['failed_ids']}")
    return ok_reg


def cmp_probe(arm):
    pre = json.loads((ROOT / f"p7_probe_{arm}").read_text(encoding="utf-8"))
    post = json.loads((ROOT / f"p8_reindex_{arm}_probe.json").read_text(encoding="utf-8"))
    flips, hits_chg, reg = [], [], []
    for a, b in zip(pre, post):
        assert a["id"] == b["id"]
        for w in ("w3", "w5"):
            if a[w]["status"] != b[w]["status"]:
                flips.append(f"{a['id']} {w}: {a[w]['status']}->{b[w]['status']}")
                if a[w]["status"] == "pass" and b[w]["status"] != "pass":
                    reg.append(f"{a['id']} {w}")
            ah = [h.get("chunk_id") for h in a[w].get("hits", [])]
            bh = [h.get("chunk_id") for h in b[w].get("hits", [])]
            if ah != bh:
                hits_chg.append(f"{a['id']} {w}")
    print(f"\n[{arm}] 探针状态翻转: {len(flips)} 处")
    for d in flips:
        print(f"  {d}")
    print(f"  其中回归(pass->非pass): {reg}")
    print(f"  hits 排序变化: {len(hits_chg)} 处 {hits_chg}")
    print(f"\n[{arm}] 焦点格 w3 放行块原文（判真阳/假阳）:")
    for b in post:
        if b["id"] in FOCUS:
            w3 = b["w3"]
            print(f"  --- {b['id']} [{b['kind']}] w3={w3['status']} "
                  f"refusal={w3.get('refusal')} cond={w3.get('condition')}")
            print(f"      q: {b['q']}")
            for h in w3.get("hits", [])[:5]:
                print(f"      rank{h['rank']} {h['chunk_id']} auth={h['authority']} "
                      f"ans={h['answerable']} {h['locator'].split('/')[-1]}")
                print(f"         {h['snippet'][:120]}")
    return reg, flips


def main():
    arm = sys.argv[1] if len(sys.argv) > 1 else "bm25"
    ok_reg = cmp_eval(arm)
    probe_reg, flips = cmp_probe(arm)
    print(f"\n==== [{arm}] 跑前规则判定 ====")
    print(f"R2 评测 ok 回归: {len(ok_reg)}  探针 pass 回归: {len(probe_reg)}")
    print(f"R3 探针 inconclusive->pass 救回: "
          f"{[f for f in flips if 'inconclusive->pass' in f]}")


if __name__ == "__main__":
    main()
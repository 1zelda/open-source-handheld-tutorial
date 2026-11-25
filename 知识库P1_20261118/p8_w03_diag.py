# -*- coding: utf-8 -*-
"""P8 W03 专项只读诊断：再索引后 W03 pass 的证据到底对不对。

查三件：
1. W03 全部 hits 的逐事实可答性分解（focus_hit/intent_ok/pattern_ok）+ 放行块全文。
2. 真答案必杀技节（含『守门员专用必杀技为龙卷风拳』）在 W03 排第几、是否可答。
3. X12（trap）基线 w5=pass 的放行块 vs 再索引 w5=inconclusive —— 分清是回归还是修掉假阳。
走生产 kb.query 指向临时索引。
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import kb as K  # noqa: E402

HERE = Path(__file__).resolve().parent
SCRATCH = HERE / "p8_scratch"
TI = str(SCRATCH / "index_reindex.json")
TM = str(SCRATCH / "corpus_map_reindex.json")
IDX = json.loads(Path(TI).read_text(encoding="utf-8"))
BY_ID = {c["chunk_id"]: c for c in IDX["chunks"]}


def dump(q, label, topn=12):
    print(f"\n==== {label}: {q} ====")
    res = K.query(q, top_window=3, index_path=TI, map_path=TM)
    print(f"status={res['status']} refusal={res.get('refusal')} cond={res.get('condition')}")
    print(f"reason={res.get('reason')}")
    for i, h in enumerate(res.get("hits", [])[:topn], 1):
        c = BY_ID[h["chunk_id"]]
        a = h.get("answerability", {})
        print(f"  rank{i} {h['chunk_id']} auth={h['authority']} ans={a.get('answerable')} "
              f"{c['path'].split('/')[-1]}#L{c['line_start']}-{c['line_end']} lang={c['lang']}")
        print(f"     intent={a.get('intent')} focus_ok={a.get('focus_ok')} "
              f"intent_ok={a.get('intent_ok')} pattern_ok={a.get('pattern_ok')} "
              f"focus_hit={a.get('focus_hit')} url_list={a.get('url_list')} "
              f"anchor_ok={a.get('topic_anchor_ok')}")
    # 真答案必杀技节排名
    for cid, c in BY_ID.items():
        if "守门员专用必杀技" in c["text"] or "龙卷风拳" in c["text"]:
            rank = next((i for i, h in enumerate(res.get("hits", []), 1)
                         if h["chunk_id"] == cid), None)
            print(f"  [真答案块] {cid} {c['path'].split('/')[-1]}#L{c['line_start']}-{c['line_end']} "
                  f"auth={c['authority']} 在W03排名={rank}")
            print(f"     全文: {c['text']}")
            ann = K.annotate(q, c["text"], K.tokens, lang=c["lang"])
            print(f"     生产annotate: {ann}")
    return res


def main():
    r = dump("热血足球2 守门员能不能用必杀？", "W03")
    # rank1 放行块全文
    if r.get("hits"):
        c = BY_ID[r["hits"][0]["chunk_id"]]
        print(f"\n  [W03 rank1 放行块全文] {c['path'].split('/')[-1]}#L{c['line_start']}-{c['line_end']}")
        print(f"     {c['text']}")
    # X12 trap：基线 vs 再索引 w5
    print("\n==== X12 trap 基线 w5 vs 再索引 w5 ====")
    base = json.loads((HERE / "p7_probe_bm25").read_text(encoding="utf-8"))
    post = json.loads((HERE / "p8_reindex_bm25_probe.json").read_text(encoding="utf-8"))
    bx = next(x for x in base if x["id"] == "X12")
    px = next(x for x in post if x["id"] == "X12")
    print(f"  X12 q: {bx['q']} kind={bx['kind']}")
    for tag, x in (("基线", bx), ("再索引", px)):
        w5 = x["w5"]
        print(f"  [{tag} w5] status={w5['status']} refusal={w5.get('refusal')}")
        for h in w5.get("hits", [])[:5]:
            print(f"     rank{h['rank']} {h['chunk_id']} auth={h['authority']} "
                  f"ans={h['answerable']} {h['locator'].split('/')[-1]}")
            print(f"        {h['snippet'][:100]}")


if __name__ == "__main__":
    main()
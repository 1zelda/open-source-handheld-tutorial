# -*- coding: utf-8 -*-
"""P4 排序诊断（只读）：Q08/Q10 的 gold 在 BM25/稠密/RRF池/重排各步的真实位次。

复算 kb.query 同款 BM25（同常数同扩展），稠密/重排用 kb_dense 同款模型与池口径。
不改任何生产文件。用法：venv python -u p4_rank_diag.py
"""
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import kb as K  # noqa: E402
from taspipe import kb_dense as D  # noqa: E402
from taspipe.kb_route import route, in_scope, expand_terms  # noqa: E402
import numpy as np  # noqa: E402

CASES = [
    ("Q08", "双人合作模式下二号玩家操作什么位置？",
     {"revision": "nekketsu_soccer2_fc_jp"}, ("setsumei", 47, 47)),
    ("Q10", "KOF98 ECK 能不能关掉队友改成 1v1？",
     {"revision": "kof98eck"}, ("素材生产规范", 185, 190)),
]


def main():
    idx = K.load_index(K.INDEX_JSON)
    chunks = idx["chunks"]
    m = K.load_map(None)
    z = np.load(D.npz_path(K.INDEX_JSON))
    vecs = z["vecs"]
    from sentence_transformers import SentenceTransformer, CrossEncoder
    dev = D._device()
    emb = SentenceTransformer(D.EMBED_MODEL, device=dev, revision=D.EMBED_REV,
                              local_files_only=True, model_kwargs={"low_cpu_mem_usage": True})
    rk = CrossEncoder(D.RERANK_MODEL, device=dev, revision=D.RERANK_REV,
                      max_length=1024, local_files_only=True,
                      model_kwargs={"low_cpu_mem_usage": True})
    N, avgdl = idx["stats"]["N"], idx["stats"]["avgdl"] or 1.0
    for qid, q, f, (gpath, ga, gb) in CASES:
        print("=" * 72)
        print(qid, q, f)
        revision = f.get("revision")
        rev_game = m["revisions"][revision]["game_id"] if revision else None
        r = route(q)
        cand = [i for i, c in enumerate(chunks)
                if in_scope(c, r) and K._filters(c, None, revision, None, None, rev_game)]
        gold = [i for i in cand if gpath in chunks[i]["path"]
                and chunks[i]["line_start"] <= gb and chunks[i]["line_end"] >= ga]
        print(f"候选 {len(cand)}；gold 块下标 {gold}")
        qt = set(K.tokens(q))
        extra = expand_terms(q, K.tokens)
        qt |= extra
        print(f"查询词 {sorted(qt)}")
        scores, matched = {}, {}
        for term in qt:
            post = idx["postings"].get(term)
            if not post:
                continue
            df = len(post)
            idf = math.log(1 + (N - df + 0.5) / (df + 0.5))
            for ci, tf in post:
                if ci not in set(cand):
                    continue
                dl = chunks[ci]["dl"] or 1
                scores[ci] = scores.get(ci, 0.0) + idf * tf * (K.K1 + 1) / (
                    tf + K.K1 * (1 - K.B + K.B * dl / avgdl))
                matched.setdefault(ci, []).append(term)
        bm25_order = sorted(scores, key=lambda ci: (-scores[ci], ci))
        print("-- BM25 top10（gold 位次见 *）")
        for rank, ci in enumerate(bm25_order[:10], 1):
            mark = "*" if ci in gold else " "
            print(f" {mark}{rank:2d} score={scores[ci]:7.3f} "
                  f"{chunks[ci]['path'].split('/')[-1]} L{chunks[ci]['line_start']}-"
                  f"{chunks[ci]['line_end']} matched={sorted(matched.get(ci, []))}")
        for gi in gold:
            pos = bm25_order.index(gi) + 1 if gi in scores else None
            print(f"  gold L{chunks[gi]['line_start']}-{chunks[gi]['line_end']} "
                  f"BM25 位次={pos} score={scores.get(gi)} matched={sorted(matched.get(gi, []))}")
        qv = emb.encode(q, normalize_embeddings=True)
        sims = vecs[cand] @ qv
        dense_order = [cand[i] for i in np.argsort(-sims)[:D.POOL]]
        for gi in gold:
            pos = dense_order.index(gi) + 1 if gi in dense_order else ">50"
            print(f"  gold 稠密位次={pos}")
        print("-- 稠密 top5")
        for rank, ci in enumerate(dense_order[:5], 1):
            mark = "*" if ci in gold else " "
            print(f" {mark}{rank:2d} sim={sims[cand.index(ci)]:.3f} "
                  f"{chunks[ci]['path'].split('/')[-1]} L{chunks[ci]['line_start']}-"
                  f"{chunks[ci]['line_end']}")
        fused = D._rrf([bm25_order[:D.POOL], dense_order])
        pool = list(dict.fromkeys(fused + dense_order[:D.DENSE_CUT]
                                  + bm25_order[:D.BM25_CUT]))
        print(f"池大小 {len(pool)}；gold 在池内：{[gi in pool for gi in gold]}")
        pairs = [(q, chunks[ci]["text"]) for ci in pool]
        rs = rk.predict(pairs)
        ranked = [ci for _, ci in sorted(zip(rs, pool), key=lambda x: -float(x[0]))]
        print("-- 重排 top10（分数）")
        for rank, ci in enumerate(ranked[:10], 1):
            mark = "*" if ci in gold else " "
            sc = float(rs[pool.index(ci)])
            print(f" {mark}{rank:2d} rerank={sc:7.3f} "
                  f"{chunks[ci]['path'].split('/')[-1]} L{chunks[ci]['line_start']}-"
                  f"{chunks[ci]['line_end']}")
        for gi in gold:
            if gi in pool:
                pos = ranked.index(gi) + 1
                print(f"  gold 重排位次={pos} rerank={float(rs[pool.index(gi)]):.3f}")
            else:
                print("  gold 不在池内（重排前就已出局）")


if __name__ == "__main__":
    main()
# -*- coding: utf-8 -*-
"""候选臂：Haystack 编排 + Qdrant local mode 稠密检索 + BGE-M3 + 可选重排。

公平性闸门：
  * 语料 = frozen_corpus/index.json 的 562 块，与基线逐字节同源（sha 断言）。
  * 每题候选集用生产 kb._filters 计算，稠密臂用 HasIdCondition 限定同一候选集。
  * BM25 文本用生产 kb.tokens 预分词（中文 bigram 同源），避免英文分词器吃亏。
  * 状态闸门逐行镜像 kb.py query 的 _strong/warns/top1 规则（不改生产代码）。
变体：bm25_only / rrf / rrf_rerank。不调任何外部 LLM API。
"""
import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
sys.path.insert(0, str(HERE))
from taspipe import kb  # noqa: E402
import eval_common as E  # noqa: E402

import numpy as np  # noqa: E402
from haystack import Document  # noqa: E402
from haystack.document_stores.in_memory import InMemoryDocumentStore  # noqa: E402
from haystack.components.retrievers.in_memory import InMemoryBM25Retriever  # noqa: E402
from qdrant_client import QdrantClient  # noqa: E402
from qdrant_client import models as qm  # noqa: E402
from sentence_transformers import SentenceTransformer, CrossEncoder  # noqa: E402

EMBED_REV = "5617a9f61b028005a4858fdac845db406aefb181"   # BAAI/bge-m3, MIT（本轮 API 核实）
RERANK_REV = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"  # BAAI/bge-reranker-v2-m3, Apache-2.0
RRF_K = 60
POOL = 50


def load_frozen():
    spec = E.load_questions()
    fp = HERE / "frozen_corpus"
    ip, mp = fp / "index.json", fp / "corpus_map.json"
    sha = hashlib.sha256(ip.read_bytes()).hexdigest()
    assert sha == spec["corpus_fingerprint"]["index_sha256"], "冻结副本指纹漂移"
    idx = json.loads(ip.read_text(encoding="utf-8"))
    cmap = json.loads(mp.read_text(encoding="utf-8"))
    return spec, idx, cmap, sha


def build_dense(idx, sha):
    cache = HERE / f"embeddings_{sha[:12]}.npz"
    chunks = idx["chunks"]
    if cache.exists():
        z = np.load(cache)
        vecs = z["vecs"]
        assert len(vecs) == len(chunks)
        print(f"嵌入缓存命中 {cache.name}")
    else:
        model = SentenceTransformer("BAAI/bge-m3", device="cuda", revision=EMBED_REV)
        texts = [c["text"] for c in chunks]
        t0 = time.perf_counter()
        vecs = model.encode(texts, batch_size=16, normalize_embeddings=True,
                            show_progress_bar=True, convert_to_numpy=True)
        print(f"嵌入 {len(texts)} 块耗时 {time.perf_counter()-t0:.1f}s (CUDA)")
        np.savez_compressed(cache, vecs=vecs)
        del model
    client = QdrantClient(path=str(HERE / "qdrant_local"))
    coll = f"kb_pilot_{sha[:12]}"
    if not client.collection_exists(coll):
        client.create_collection(coll, vectors_config=qm.VectorParams(
            size=vecs.shape[1], distance=qm.Distance.COSINE))
        client.upsert(coll, points=[
            qm.PointStruct(id=i, vector=vecs[i].tolist(), payload={
                "chunk_id": c["chunk_id"], "path": c["path"],
                "revision": c["revision"], "game_id": c["game_id"],
                "authority": c["authority"], "status": c["status"]})
            for i, c in enumerate(chunks)])
    return client, vecs, coll


def hay_filter(game, revision, platform, rev_game):
    conds = []
    if game:
        conds.append({"field": "meta.game_id", "operator": "==", "value": game})
    if revision:
        conds.append({"operator": "OR", "conditions": [
            {"field": "meta.revision", "operator": "==", "value": revision},
            {"field": "meta.game_id", "operator": "==", "value": rev_game}]})
    if platform:
        conds.append({"operator": "OR", "conditions": [
            {"field": "meta.platform", "operator": "==", "value": platform},
            {"field": "meta.platform", "operator": "==", "value": "ANY"}]})
    if not conds:
        return None
    return {"operator": "AND", "conditions": conds} if len(conds) > 1 else conds[0]


def mirror_gate(qtext, hits, chunks_by_id, revision, rev_game, candidates_n):
    """逐行镜像 kb.py query 的判定段（L441-481），输入同构 hits。"""
    base = {"counts": {"candidates": candidates_n, "hits": len(hits)}}
    if not hits:
        return {**base, "status": "miss", "hits": [],
                "reason": "候选块内两路检索均无命中"}
    qt = set(kb.tokens(qtext))
    content_terms = {t for t in qt if len(t) >= 2}
    for h in hits:
        c = chunks_by_id[h["chunk_id"]]
        h["revision_match"] = (revision is None or c["revision"] == revision
                               or (c["revision"].endswith("_multi") and rev_game is not None
                                   and c["game_id"] == rev_game))
        h["_content"] = content_terms & set(kb.tokens(c["text"]))

    def _strong(h):
        if h["status"] != "verified_read" or not h["revision_match"]:
            return False
        if h["authority"] == "authoritative":
            return True
        return (h["authority"] == "cross_version" and revision is not None
                and h["revision"] == revision)

    strong = [h for h in hits if _strong(h) and h["_content"]]
    warns = []
    for h in hits:
        if h["authority"] == "cross_version" and not (revision and h["revision"] == revision):
            warns.append(f"{h['source_id']} 是 {h['revision']} 的跨版本参考件，不得当权威依据")
        elif not h["revision_match"]:
            warns.append(f"{h['source_id']} 属 {h['revision']}，与所问 {revision} 不是同一版本")
        elif h["authority"] == "reference_only":
            warns.append(f"{h['source_id']} 是二手件（reference_only），须交叉核对")
    base["authority_warnings"] = warns
    base["counts"]["strong"] = len(strong)
    for h in hits:
        h.pop("_content", None)
    if not strong:
        return {**base, "status": "inconclusive", "hits": hits,
                "reason": "命中只有快照/二手/跨版本支撑或仅单字噪声"}
    if hits[0]["chunk_id"] not in {h["chunk_id"] for h in strong}:
        return {**base, "status": "inconclusive", "hits": hits,
                "reason": f"最高分命中 {hits[0]['source_id']} 非本版本权威，权威件在低分位"}
    return {**base, "status": "pass", "hits": hits,
            "reason": f"{len(strong)} 条 verified_read+authoritative 内容词命中且最高分即权威"}


def to_hit(c, score):
    return {"chunk_id": c["chunk_id"], "score": round(float(score), 4),
            "source_id": c["source_id"], "status": c["status"],
            "authority": c["authority"], "revision": c["revision"],
            "game_id": c["game_id"], "platform": c["platform"],
            "locator": f"{c['path']}#L{c['line_start']}-L{c['line_end']}",
            "heading": c.get("heading", ""), "snippet": c["text"][:240]}


def rrf(lists, topk=8):
    scores, first = {}, {}
    for lst in lists:
        for rank, cid in enumerate(lst):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
            first.setdefault(cid, rank)
    return sorted(scores, key=lambda c: (-scores[c], first[c]))[:topk], scores


def main():
    spec, idx, cmap, sha = load_frozen()
    chunks = idx["chunks"]
    by_id = {c["chunk_id"]: c for c in chunks}
    pos_of = {c["chunk_id"]: i for i, c in enumerate(chunks)}
    client, vecs, coll = build_dense(idx, sha)
    embedder = SentenceTransformer("BAAI/bge-m3", device="cuda", revision=EMBED_REV)

    store = InMemoryDocumentStore()
    docs = [Document(id=c["chunk_id"],
                     content=" ".join(kb.tokens(c["text"])),
                     meta={"game_id": c["game_id"], "revision": c["revision"],
                           "platform": c["platform"], "authority": c["authority"]})
            for c in chunks]
    store.write_documents(docs)
    bm25 = InMemoryBM25Retriever(document_store=store, top_k=POOL)
    # Haystack 3.5 核心包已移除 TransformersSimilarityRanker，用 CrossEncoder 等价实现
    ranker = CrossEncoder("BAAI/bge-reranker-v2-m3", device="cuda",
                          revision=RERANK_REV, max_length=1024)

    variants = {"bm25_only": [], "rrf": [], "rrf_rerank": []}
    grades = {k: [] for k in variants}
    for q in spec["questions"]:
        f = q["filters"]
        game, revision, platform = f.get("game"), f.get("revision"), f.get("platform")
        rev_game = cmap["revisions"][revision]["game_id"] if revision else None
        cand = [i for i, c in enumerate(chunks)
                if kb._filters(c, game, revision, platform, None, rev_game)]
        cand_ids = {chunks[i]["chunk_id"] for i in cand}
        hf = hay_filter(game, revision, platform, rev_game)
        bres = bm25.run(query=" ".join(kb.tokens(q["q"])), filters=hf)
        bm25_ids = [d.id for d in bres["documents"]]
        assert set(bm25_ids) <= cand_ids, f"{q['id']} Haystack过滤与生产候选集不一致"
        qv = embedder.encode(q["q"], normalize_embeddings=True).tolist()
        dres = client.query_points(coll, query=qv, limit=POOL,
                                   query_filter=qm.Filter(must=[
                                       qm.HasIdCondition(has_id=list(cand))]))
        dense_ids = [by_id_key(p.id, chunks) for p in dres.points]
        assert set(dense_ids) <= cand_ids

        fused, fscores = rrf([bm25_ids, dense_ids])
        pairs = [(q["q"], by_id[cid]["text"]) for cid in fused]
        rs = ranker.predict(pairs) if pairs else []
        reranked = [cid for _, cid in sorted(zip(rs, fused), key=lambda x: -float(x[0]))]

        picks = {"bm25_only": bm25_ids[:8], "rrf": fused, "rrf_rerank": reranked}
        for name, ids in picks.items():
            hits = [to_hit(by_id[cid], fscores.get(cid, 0.0)) for cid in ids]
            res = mirror_gate(q["q"], hits, by_id, revision, rev_game, len(cand))
            res = {"q": q["q"], **res}
            g = E.grade(q, res)
            variants[name].append({"id": q["id"], "result": res})
            grades[name].append(g)
        print(q["id"], {k: ("OK" if grades[k][-1]["ok"] else "FAIL") + "/" + grades[k][-1]["status"]
                        for k in variants})

    out = {"arm": "haystack_qdrant_bge_m3", "index_sha256": sha, "chunks": len(chunks),
           "embed_model": {"name": "BAAI/bge-m3", "revision": EMBED_REV, "license": "MIT"},
           "rerank_model": {"name": "BAAI/bge-reranker-v2-m3", "revision": RERANK_REV,
                            "license": "Apache-2.0"},
           "variants": {}}
    for name in variants:
        out["variants"][name] = {"summary": E.summarize(grades[name]),
                                 "grades": grades[name], "results": variants[name]}
        print(name, json.dumps(out["variants"][name]["summary"], ensure_ascii=False))
    (HERE / "candidate_results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


def by_id_key(point_id, chunks):
    return chunks[point_id]["chunk_id"]


if __name__ == "__main__":
    main()
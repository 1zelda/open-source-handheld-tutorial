# -*- coding: utf-8 -*-
"""P1 完整检索臂：域路由 → 硬过滤 → v3 BM25+BGE-M3 RRF → 重排 → 可答性 → 权威闸门。

与 pilot 候选臂的差异（全部来自小样报告 §6 的四件事）：
  1. 域路由：域外零语料 → not_found_within_scope（治 Q12-14）
  2. 逐事实可答性：全命中不可答 → insufficient_evidence（治 Q09/Q15 类假阳性）
  3. v3 语言同质小段（治 Q06-08 跨语）
  4. 权威策略双轨：strict_top1（默认，与生产同规则）/ top3_conditional（备选，
     只测数字供用户选，不改默认）
零外部 LLM。生产代码只读引用。判定段逐行镜像 kb.py L441-481 再叠加可答性层。
"""
import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PILOT = HERE.parent / "知识库小样_20261118"
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
sys.path.insert(0, str(PILOT))
sys.path.insert(0, str(HERE))

from taspipe import kb  # noqa: E402
import eval_common as E  # noqa: E402
import run_candidate as RC  # noqa: E402
from p1_router import route  # noqa: E402
from p1_answerability import annotate  # noqa: E402
import p1_status as S  # noqa: E402

import numpy as np  # noqa: E402
from haystack import Document  # noqa: E402
from haystack.document_stores.in_memory import InMemoryDocumentStore  # noqa: E402
from haystack.components.retrievers.in_memory import InMemoryBM25Retriever  # noqa: E402
from qdrant_client import QdrantClient  # noqa: E402
from qdrant_client import models as qm  # noqa: E402
from sentence_transformers import SentenceTransformer, CrossEncoder  # noqa: E402

POOL = 50


def load_embedder():
    return SentenceTransformer("BAAI/bge-m3", device="cuda",
                               revision=RC.EMBED_REV, local_files_only=True,
                               model_kwargs={"low_cpu_mem_usage": True})


def build_dense_v3(chunks, sha, embedder):
    """embedder 由调用方传入并负责释放；本函数只产缓存与 qdrant 集合。"""
    cache = HERE / f"embeddings_v3_{sha[:12]}.npz"
    if cache.exists():
        vecs = np.load(cache)["vecs"]
        assert len(vecs) == len(chunks)
        print(f"嵌入缓存命中 {cache.name}")
    else:
        t0 = time.perf_counter()
        vecs = embedder.encode([c["text"] for c in chunks], batch_size=16,
                               normalize_embeddings=True, show_progress_bar=True,
                               convert_to_numpy=True)
        print(f"嵌入 {len(chunks)} 块耗时 {time.perf_counter()-t0:.1f}s (CUDA)")
        np.savez_compressed(cache, vecs=vecs)
    client = QdrantClient(path=str(HERE / "qdrant_local"))
    coll = f"kb_p1_{sha[:12]}"
    if not client.collection_exists(coll):
        client.create_collection(coll, vectors_config=qm.VectorParams(
            size=vecs.shape[1], distance=qm.Distance.COSINE))
        client.upsert(coll, points=[
            qm.PointStruct(id=i, vector=vecs[i].tolist(), payload={
                "chunk_id": c["chunk_id"], "game_id": c["game_id"],
                "revision": c["revision"]})
            for i, c in enumerate(chunks)])
    return client, vecs, coll


def in_scope(c, r):
    if r["game_ids"] is None:      # unrouted：查全部
        return True
    if r["game_ids"] and c["game_id"] not in r["game_ids"]:
        return False
    if r["revisions"] and c["revision"] not in r["revisions"]:
        return False
    return True


def p1_gate(qtext, hits, by_id, revision, rev_game, n_cand, policy):
    """镜像 kb.py 判定段 + 可答性层。policy: strict_top1 / top3_conditional。"""
    base = {"counts": {"candidates": n_cand, "hits": len(hits)}, "policy": policy}
    if not hits:
        return {**base, "status": S.MISS, "hits": [],
                "reason": "候选块内两路检索均无命中"}
    qt = set(kb.tokens(qtext))
    content_terms = {t for t in qt if len(t) >= 2}
    for h in hits:
        c = by_id[h["chunk_id"]]
        h["revision_match"] = (revision is None or c["revision"] == revision
                               or (c["revision"].endswith("_multi") and rev_game is not None
                                   and c["game_id"] == rev_game))
        h["_content"] = content_terms & set(kb.tokens(c["text"]))
        h["answerability"] = annotate(qtext, c["text"], kb.tokens)

    def _strong(h):
        if h["status"] != "verified_read" or not h["revision_match"]:
            return False
        if h["authority"] == "authoritative":
            return True
        return (h["authority"] == "cross_version" and revision is not None
                and h["revision"] == revision)

    warns = []
    for h in hits:
        if h["authority"] == "cross_version" and not (revision and h["revision"] == revision):
            warns.append(f"{h['source_id']} 是 {h['revision']} 的跨版本参考件，不得当权威依据")
        elif not h["revision_match"]:
            warns.append(f"{h['source_id']} 属 {h['revision']}，与所问 {revision} 不是同一版本")
        elif h["authority"] == "reference_only":
            warns.append(f"{h['source_id']} 是二手件（reference_only），须交叉核对")
    base["authority_warnings"] = warns

    answerable = [h for h in hits if h["answerability"]["answerable"]]
    base["counts"]["answerable"] = len(answerable)
    for h in hits:
        h.pop("_content", None)
    if not answerable:
        return {**base, "status": S.INSUFFICIENT, "hits": hits,
                "reason": "命中全部未过逐事实可答性核查（词命中≠回答问题）"}
    strong = [h for h in answerable
              if _strong(h) and (content_terms & set(kb.tokens(by_id[h["chunk_id"]]["text"])))]
    base["counts"]["strong"] = len(strong)
    if not strong:
        return {**base, "status": S.INCONCLUSIVE, "hits": hits,
                "reason": "可答命中只有快照/二手/跨版本支撑或仅单字噪声"}
    strong_ids = {h["chunk_id"] for h in strong}
    if policy == "strict_top1":
        if hits[0]["chunk_id"] not in strong_ids:
            return {**base, "status": S.INCONCLUSIVE, "hits": hits,
                    "reason": f"最高分命中 {hits[0]['source_id']} 非本版本权威可答件，权威件在低分位"}
        return {**base, "status": S.PASS, "hits": hits,
                "reason": f"{len(strong)} 条 verified_read+authoritative 可答命中且最高分即权威"}
    # top3_conditional：top3 内有权威可答件即附条件出证（备选策略，只测数字）
    for rank, h in enumerate(hits[:3], 1):
        if h["chunk_id"] in strong_ids:
            return {**base, "status": S.PASS, "hits": hits,
                    "condition": f"权威可答件在第{rank}位，非最高分；出证须附此条件",
                    "reason": f"top3 附条件：第{rank}位为 verified_read+authoritative 可答件"}
    return {**base, "status": S.INCONCLUSIVE, "hits": hits,
            "reason": "top3 内无本版本权威可答件"}


def p1_grade(q, res):
    if q["expect"] == "refuse" and res.get("status") in (S.NOT_FOUND, S.INSUFFICIENT):
        return {"id": q["id"], "tier": "refuse", "ok": True,
                "why": f"status={res['status']}（结构性拒答，缺证据不冒充事实）",
                "status": res["status"], "n_hits": len(res.get("hits", [])),
                "top1": res["hits"][0]["locator"] if res.get("hits") else None}
    return E.grade(q, res)


def main():
    spec_path = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "p1_questions.json"
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "p1_results.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    idx = json.loads((HERE / "v3_index.json").read_text(encoding="utf-8"))
    cmap = json.loads((PILOT / "frozen_corpus" / "corpus_map.json").read_text(encoding="utf-8"))
    sha = hashlib.sha256((HERE / "v3_index.json").read_bytes()).hexdigest()
    chunks = idx["chunks"]
    by_id = {c["chunk_id"]: c for c in chunks}
    # 阶段A：嵌入（语料+全部问句），完成后立即释放模型压内存峰值
    # 问句向量有缓存则直接复用，整个嵌入模型都不用加载
    qcache = HERE / "qvecs_ext.npz"
    qvecs = None
    if qcache.exists():
        z = np.load(qcache, allow_pickle=True)
        cached = {str(i): z["vecs"][k].tolist() for k, i in enumerate(z["ids"])}
        if all(q["id"] in cached for q in spec["questions"]):
            qvecs = {q["id"]: cached[q["id"]] for q in spec["questions"]}
            print("问句向量缓存命中 qvecs_ext.npz", flush=True)
    embedder = None
    if qvecs is None:
        embedder = load_embedder()
    client, vecs, coll = build_dense_v3(chunks, sha, embedder)
    if qvecs is None:
        qvecs = {q["id"]: embedder.encode(q["q"], normalize_embeddings=True).tolist()
                 for q in spec["questions"]}
        np.savez_compressed(qcache, ids=np.array([q["id"] for q in spec["questions"]]),
                            vecs=np.array([qvecs[q["id"]] for q in spec["questions"]]))
        del embedder
        import torch
        torch.cuda.empty_cache()
    print("阶段A完成", flush=True)
    store = InMemoryDocumentStore()
    store.write_documents([
        Document(id=c["chunk_id"], content=" ".join(kb.tokens(c["text"])),
                 meta={"game_id": c["game_id"], "revision": c["revision"],
                       "platform": c["platform"], "authority": c["authority"]})
        for c in chunks])
    bm25 = InMemoryBM25Retriever(document_store=store, top_k=POOL)
    # 阶段B：重排器单独加载（不与嵌入模型同时驻留）
    ranker = CrossEncoder("BAAI/bge-reranker-v2-m3", device="cuda",
                          revision=RC.RERANK_REV, max_length=1024,
                          local_files_only=True,
                          automodel_args={"low_cpu_mem_usage": True})
    print("阶段B：重排器就绪", flush=True)

    policies = ["strict_top1", "top3_conditional"]
    pools = ["fused8", "union", "union12"]
    results = {f"{pl}/{po}": [] for pl in pools for po in policies}
    grades = {k: [] for k in results}
    for q in spec["questions"]:
        f = q.get("filters", {})
        game, revision, platform = f.get("game"), f.get("revision"), f.get("platform")
        rev_game = cmap["revisions"][revision]["game_id"] if revision else None
        r = route(q["q"])
        has_filters = bool(game or revision or platform)
        # 域外零语料拒答：仅在无显式过滤时成立（显式 game/revision 是权威意图）
        if not r["corpus_available"] and not has_filters:
            res = {"q": q["q"], "route": r, "status": S.NOT_FOUND, "hits": [],
                   "counts": {"candidates": 0, "hits": 0},
                   "reason": f"路由到 {r['domain']}（命中 {r['matched']}），该域库内零语料"}
            for k in results:
                results[k].append({"id": q["id"], "result": res})
                grades[k].append(p1_grade(q, res))
            print(q["id"], "NOT_FOUND", r["domain"])
            continue
        cand = [i for i, c in enumerate(chunks)
                if (has_filters or in_scope(c, r))
                and kb._filters(c, game, revision, platform, None, rev_game)]
        cand_ids = {chunks[i]["chunk_id"] for i in cand}
        hf = RC.hay_filter(game, revision, platform, rev_game)
        bres = bm25.run(query=" ".join(kb.tokens(q["q"])), filters=hf)
        bm25_ids = [d.id for d in bres["documents"] if d.id in cand_ids]
        qv = qvecs[q["id"]]
        dres = client.query_points(coll, query=qv, limit=POOL,
                                   query_filter=qm.Filter(must=[
                                       qm.HasIdCondition(has_id=list(cand))])) if cand else None
        dense_ids = [chunks[p.id]["chunk_id"] for p in dres.points] if dres else []
        assert set(bm25_ids) <= cand_ids and set(dense_ids) <= cand_ids
        fused, fscores = RC.rrf([bm25_ids, dense_ids])
        # 联合池：融合top8 ∪ 稠密topN ∪ BM25top6——治"单路命中被RRF埋没"
        # （日文金标BM25近零分，纯融合top8永远进不了重排器视野）
        # union12 把稠密截断从6扩到12（诊断：Q02稠密12/P22稠密9/P23稠密12）
        pool6 = list(dict.fromkeys(fused + dense_ids[:6] + bm25_ids[:6]))
        pool12 = list(dict.fromkeys(fused + dense_ids[:12] + bm25_ids[:6]))
        pairs = [(q["q"], by_id[cid]["text"]) for cid in pool12]
        rs = ranker.predict(pairs) if pairs else []
        score_of = {cid: float(s) for cid, s in zip(pool12, rs)}
        pick = {"fused8": sorted(fused, key=lambda c: -score_of[c]),
                "union": sorted(pool6, key=lambda c: -score_of[c])[:8],
                "union12": sorted(pool12, key=lambda c: -score_of[c])[:8]}
        line = [q["id"], r["domain"], f"pool={len(pool12)}"]
        for pl in pools:
            hits = [RC.to_hit(by_id[cid], fscores.get(cid, 0.0)) for cid in pick[pl]]
            for po in policies:
                res = p1_gate(q["q"], [dict(h) for h in hits], by_id, revision, rev_game,
                              len(cand), po)
                res = {"q": q["q"], "route": r, "pool_size": len(pool12), **res}
                g = p1_grade(q, res)
                k = f"{pl}/{po}"
                results[k].append({"id": q["id"], "result": res})
                grades[k].append(g)
                line.append(("OK" if g["ok"] else "FAIL") + "/" + g["status"])
        print(*line)

    out = {"arm": "p1_route_v3_answerability", "v3_sha256": sha, "chunks": len(chunks),
           "spec": spec_path.name, "variants": {}}
    for k in results:
        out["variants"][k] = {"summary": E.summarize(grades[k]),
                              "grades": grades[k], "results": results[k]}
        print(k, json.dumps(out["variants"][k]["summary"], ensure_ascii=False))
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
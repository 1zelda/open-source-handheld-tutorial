# -*- coding: utf-8 -*-
"""追加变体 rrf_rerank_pool30：融合池扩到30再重排取8（治单路命中被RRF埋掉）。"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_candidate as RC  # noqa: E402
import eval_common as E  # noqa: E402
from taspipe import kb  # noqa: E402
from haystack import Document  # noqa: E402
from haystack.document_stores.in_memory import InMemoryDocumentStore  # noqa: E402
from haystack.components.retrievers.in_memory import InMemoryBM25Retriever  # noqa: E402
from qdrant_client import models as qm  # noqa: E402
from sentence_transformers import SentenceTransformer, CrossEncoder  # noqa: E402


def main():
    spec, idx, cmap, sha = RC.load_frozen()
    chunks = idx["chunks"]
    by_id = {c["chunk_id"]: c for c in chunks}
    client, vecs, coll = RC.build_dense(idx, sha)
    embedder = SentenceTransformer("BAAI/bge-m3", device="cuda", local_files_only=True)
    store = InMemoryDocumentStore()
    store.write_documents([Document(id=c["chunk_id"],
                                    content=" ".join(kb.tokens(c["text"])),
                                    meta={"game_id": c["game_id"], "revision": c["revision"],
                                          "platform": c["platform"], "authority": c["authority"]})
                           for c in chunks])
    bm25 = InMemoryBM25Retriever(document_store=store, top_k=RC.POOL)
    ranker = CrossEncoder("BAAI/bge-reranker-v2-m3", device="cuda",
                          revision=RC.RERANK_REV, max_length=1024, local_files_only=True)
    results, grades = [], []
    for q in spec["questions"]:
        f = q["filters"]
        game, revision, platform = f.get("game"), f.get("revision"), f.get("platform")
        rev_game = cmap["revisions"][revision]["game_id"] if revision else None
        cand = [i for i, c in enumerate(chunks)
                if kb._filters(c, game, revision, platform, None, rev_game)]
        hf = RC.hay_filter(game, revision, platform, rev_game)
        bm25_ids = [d.id for d in bm25.run(query=" ".join(kb.tokens(q["q"])),
                                           filters=hf)["documents"]]
        qv = embedder.encode(q["q"], normalize_embeddings=True).tolist()
        dres = client.query_points(coll, query=qv, limit=RC.POOL,
                                   query_filter=qm.Filter(must=[
                                       qm.HasIdCondition(has_id=list(cand))]))
        dense_ids = [chunks[p.id]["chunk_id"] for p in dres.points]
        fused, fscores = RC.rrf([bm25_ids, dense_ids], topk=30)
        pairs = [(q["q"], by_id[cid]["text"]) for cid in fused]
        rs = ranker.predict(pairs) if pairs else []
        reranked = [cid for _, cid in sorted(zip(rs, fused), key=lambda x: -float(x[0]))][:8]
        hits = [RC.to_hit(by_id[cid], fscores.get(cid, 0.0)) for cid in reranked]
        res = {"q": q["q"], **RC.mirror_gate(q["q"], hits, by_id, revision, rev_game, len(cand))}
        g = E.grade(q, res)
        results.append({"id": q["id"], "result": res})
        grades.append(g)
        print(q["id"], "OK" if g["ok"] else "FAIL", g["status"], g["why"][:60])
    out = {"variant": "rrf_rerank_pool30", "index_sha256": sha,
           "summary": E.summarize(grades), "grades": grades, "results": results}
    (HERE / "pool30_results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
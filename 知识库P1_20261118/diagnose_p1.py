# -*- coding: utf-8 -*-
"""诊断残留失败题：金标在 BM25/稠密两路的真实排名（候选集内）。"""
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PILOT = HERE.parent / "知识库小样_20261118"
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
sys.path.insert(0, str(PILOT))
sys.path.insert(0, str(HERE))
from taspipe import kb  # noqa: E402
import run_candidate as RC  # noqa: E402
from p1_router import route  # noqa: E402
from p1_arm import in_scope, load_embedder  # noqa: E402

import numpy as np  # noqa: E402
from haystack import Document  # noqa: E402
from haystack.document_stores.in_memory import InMemoryDocumentStore  # noqa: E402
from haystack.components.retrievers.in_memory import InMemoryBM25Retriever  # noqa: E402
from qdrant_client import QdrantClient  # noqa: E402
from qdrant_client import models as qm  # noqa: E402

FAILS = ["Q02", "Q08", "P19", "P22", "P23"]

spec = json.loads((HERE / "p1_questions_ext.json").read_text(encoding="utf-8"))
idx = json.loads((HERE / "v3_index.json").read_text(encoding="utf-8"))
cmap = json.loads((PILOT / "frozen_corpus" / "corpus_map.json").read_text(encoding="utf-8"))
sha = hashlib.sha256((HERE / "v3_index.json").read_bytes()).hexdigest()
chunks = idx["chunks"]
by_id = {c["chunk_id"]: c for c in chunks}
client = QdrantClient(path=str(HERE / "qdrant_local"))
coll = f"kb_p1_{sha[:12]}"
vecs = np.load(HERE / f"embeddings_v3_{sha[:12]}.npz")["vecs"]

store = InMemoryDocumentStore()
store.write_documents([
    Document(id=c["chunk_id"], content=" ".join(kb.tokens(c["text"])),
             meta={"game_id": c["game_id"], "revision": c["revision"],
                   "platform": c["platform"], "authority": c["authority"]})
    for c in chunks])
bm25 = InMemoryBM25Retriever(document_store=store, top_k=500)

emb = load_embedder()
qcache = HERE / "qvecs_ext.npz"
allq = {q["id"]: q["q"] for q in spec["questions"]}
qv = emb.encode([allq[i] for i in sorted(allq)], normalize_embeddings=True)
np.savez_compressed(qcache, ids=np.array(sorted(allq)), vecs=qv)
qmap = {i: qv[k].tolist() for k, i in enumerate(sorted(allq))}
del emb
print("问句向量已缓存 qvecs_ext.npz", flush=True)

for q in spec["questions"]:
    if q["id"] not in FAILS:
        continue
    f = q.get("filters", {})
    game, revision, platform = f.get("game"), f.get("revision"), f.get("platform")
    rev_game = cmap["revisions"][revision]["game_id"] if revision else None
    r = route(q["q"])
    has_filters = bool(game or revision or platform)
    cand = [i for i, c in enumerate(chunks)
            if (has_filters or in_scope(c, r))
            and kb._filters(c, game, revision, platform, None, rev_game)]
    cand_ids = {chunks[i]["chunk_id"] for i in cand}
    gold = q.get("gold") or {}
    gcid = gold.get("anchor_chunk")
    hf = RC.hay_filter(game, revision, platform, rev_game)
    bres = bm25.run(query=" ".join(kb.tokens(q["q"])), filters=hf)
    bm25_ids = [d.id for d in bres["documents"] if d.id in cand_ids]
    dres = client.query_points(coll, query=qmap[q["id"]], limit=len(cand),
                               query_filter=qm.Filter(must=[
                                   qm.HasIdCondition(has_id=list(cand))]))
    dense_ids = [chunks[p.id]["chunk_id"] for p in dres.points]
    br = bm25_ids.index(gcid) + 1 if gcid in bm25_ids else None
    dr = dense_ids.index(gcid) + 1 if gcid in dense_ids else None
    print(f"== {q['id']} 候选{len(cand)} 金标{gcid} BM25排名={br} 稠密排名={dr}")
    print("   稠密top3:", [by_id[c]["path"].split("/")[-1][:26] + f"#L{by_id[c]['line_start']}"
                          for c in dense_ids[:3]])
    if gcid and gcid in by_id:
        print("   金标块:", by_id[gcid]["path"].split("/")[-1][:30],
              f"L{by_id[gcid]['line_start']}-{by_id[gcid]['line_end']}",
              by_id[gcid]["text"][:60].replace("\n", " "))
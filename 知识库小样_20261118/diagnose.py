# -*- coding: utf-8 -*-
"""诊断：跨语题金标在稠密路的真实排名 + 关键题 top1 是谁。"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
sys.path.insert(0, str(HERE))
from taspipe import kb  # noqa: E402
import eval_common as E  # noqa: E402
import numpy as np  # noqa: E402
from qdrant_client import QdrantClient  # noqa: E402
from qdrant_client import models as qm  # noqa: E402
from sentence_transformers import SentenceTransformer  # noqa: E402

spec = E.load_questions()
idx = json.loads((HERE / "frozen_corpus" / "index.json").read_text(encoding="utf-8"))
cmap = json.loads((HERE / "frozen_corpus" / "corpus_map.json").read_text(encoding="utf-8"))
chunks = idx["chunks"]
sha = spec["corpus_fingerprint"]["index_sha256"]
vecs = np.load(HERE / f"embeddings_{sha[:12]}.npz")["vecs"]
client = QdrantClient(path=str(HERE / "qdrant_local"))
coll = f"kb_pilot_{sha[:12]}"
model = SentenceTransformer("BAAI/bge-m3", device="cuda", local_files_only=True)

cand_res = json.loads((HERE / "candidate_results.json").read_text(encoding="utf-8"))
rr = {r["id"]: r["result"] for r in cand_res["variants"]["rrf_rerank"]["results"]}

print("== 跨语题：金标块在稠密路（候选集内）的排名 ==")
for q in spec["questions"]:
    if q["id"] not in ("Q06", "Q07", "Q08"):
        continue
    rev = q["filters"]["revision"]
    rev_game = cmap["revisions"][rev]["game_id"]
    cand = [i for i, c in enumerate(chunks)
            if kb._filters(c, None, rev, None, None, rev_game)]
    qv = model.encode(q["q"], normalize_embeddings=True).tolist()
    dres = client.query_points(coll, query=qv, limit=len(cand),
                               query_filter=qm.Filter(must=[
                                   qm.HasIdCondition(has_id=list(cand))]))
    gold = q["gold"]
    rank = None
    for r, p in enumerate(dres.points, 1):
        c = chunks[p.id]
        if gold["path_contains"] in c["path"] and \
           c["line_start"] <= gold["line_end"] and c["line_end"] >= gold["line_start"]:
            rank = r
            break
    print(f"{q['id']} 候选{len(cand)} 金标稠密排名={rank} "
          f"稠密top3={[chunks[p.id]['path'].split('/')[-1][:22] for p in dres.points[:3]]}")

print("== 关键题 rrf_rerank top3 ==")
for qid in ("Q01", "Q02", "Q03", "Q09", "Q11", "Q12", "Q18"):
    res = rr[qid]
    print(qid, res["status"])
    for h in res["hits"][:3]:
        print("   ", h["score"], h["authority"], h["locator"].split("/")[-1][:60])
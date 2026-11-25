# -*- coding: utf-8 -*-
"""可选稠密增强层：BGE-M3 向量 + RRF 融合 + bge-reranker-v2-m3 重排（union12 池）。

主干仍是 kb.py 的 BM25；本模块只在「嵌入指纹件存在 + 与当前索引 sha 一致 +
sentence_transformers 可导入」时启用。任何一条不满足 => 退回 BM25 主干，
query 结果的 retrieval/retrieval_note 字段明示走的哪条路（不许静默顶包）。

建指纹件（需要 sentence_transformers/torch，优先 CUDA）：
  py -3 -m taspipe.kb dense
环境：HF_HUB_CACHE 指向本地模型缓存、HF_HUB_OFFLINE=1、NO_PROXY 含 localhost。
模型：BAAI/bge-m3（MIT）rev 5617a9f6…；BAAI/bge-reranker-v2-m3（Apache-2.0）rev 953dc6f6…
池口径（P1 实测 26 题 23/26 的那套）：RRF top8 ∪ 稠密 top12 ∪ BM25 top6 进重排取 top8。
"""
import hashlib
import json
import time
from pathlib import Path

EMBED_MODEL = "BAAI/bge-m3"
EMBED_REV = "5617a9f61b028005a4858fdac845db406aefb181"
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
RERANK_REV = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
RRF_K = 60
POOL = 50
DENSE_CUT = 12
BM25_CUT = 6
TOPK = 8

_embedder = None
_ranker = None


def _sha256(b):
    return hashlib.sha256(b).hexdigest()


def npz_path(index_path):
    p = Path(index_path)
    return p.with_name(f"embeddings_{_sha256(p.read_bytes())[:12]}.npz")


def _device():
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def build_dense(index_path, device=None):
    """给当前索引全量块嵌入，落指纹件（vecs 与 chunks 顺序对齐 + index_sha）。"""
    import json
    import numpy as np
    from sentence_transformers import SentenceTransformer
    p = Path(index_path)
    sha = _sha256(p.read_bytes())
    idx = json.loads(p.read_text(encoding="utf-8"))
    texts = [c["text"] for c in idx["chunks"]]
    dev = device or _device()
    model = SentenceTransformer(EMBED_MODEL, device=dev, revision=EMBED_REV,
                                local_files_only=True,
                                model_kwargs={"low_cpu_mem_usage": True})
    t0 = time.perf_counter()
    vecs = model.encode(texts, batch_size=16, normalize_embeddings=True,
                        show_progress_bar=True, convert_to_numpy=True)
    out = p.with_name(f"embeddings_{sha[:12]}.npz")
    np.savez_compressed(out, vecs=vecs, index_sha=np.array(sha))
    return {"status": "built", "npz": str(out), "chunks": len(texts),
            "device": dev, "seconds": round(time.perf_counter() - t0, 1)}


def _rrf(lists):
    scores, first = {}, {}
    for lst in lists:
        for rank, ci in enumerate(lst):
            scores[ci] = scores.get(ci, 0.0) + 1.0 / (RRF_K + rank + 1)
            first.setdefault(ci, rank)
    return sorted(scores, key=lambda c: (-scores[c], first[c]))


def anchor_top8(ranked, bm25_order):
    """词法锚：BM25 top1 保最终 top8 末位席位（P4，治重排推翻主干）。

    只保席位不抬名次：top1 仍是重排的选择，锚件追加在第 8 位。
    bm25_order 为空或 top1 已在榜内 => 原样返回（不重复占位）。
    """
    top = ranked[:TOPK]
    if bm25_order and bm25_order[0] not in top:
        top = top[:TOPK - 1] + [bm25_order[0]]
    return top


_ready_cache = {}


def ready(index_path):
    """稠密增强是否就绪（不加载模型、不碰 GPU）：索引存在 + 指纹件存在 + sha 一致
    + 块数对齐 + sentence_transformers 可导入。返回 (bool, reason)。

    供 kb.query 决定是否切到 hybrid 富集索引；enhance 内部仍各自复核（不静默顶包）。
    按 (路径, mtime_ns) 缓存：索引未重建则复用，重建后 mtime 变 => 自动失效。
    可选依赖缺席（numpy/sentence_transformers）=> (False, 原因)，不抛异常：
    兜底臂必须在缺依赖环境里也能走通（阶段1契约）。
    """
    try:
        import numpy as np
    except ImportError:
        return False, "当前环境缺 numpy（稠密增强不可用，走 BM25 兜底）"
    p = Path(index_path)
    if not p.is_file():
        return False, "索引文件不存在"
    key = (str(p), p.stat().st_mtime_ns)
    if key in _ready_cache:
        return _ready_cache[key]
    sha = _sha256(p.read_bytes())
    npz = p.with_name(f"embeddings_{sha[:12]}.npz")
    if not npz.is_file():
        res = (False, "稠密指纹件未建（py -3 -m taspipe.kb dense）")
    else:
        z = np.load(npz)
        if str(z["index_sha"]) != sha:
            res = (False, "稠密指纹与当前索引不一致（重跑 kb dense）")
        else:
            nchunks = len(json.loads(p.read_text(encoding="utf-8"))["chunks"])
            if len(z["vecs"]) != nchunks:
                res = (False, "稠密指纹块数与索引不符（重跑 kb dense）")
            else:
                try:
                    import sentence_transformers  # noqa: F401
                    res = (True, None)
                except ImportError:
                    res = (False, "当前环境缺 sentence_transformers（用带依赖的 venv）")
    _ready_cache[key] = res
    return res


def enhance(q, chunks, cand, bm25_order, index_path):
    """返回 (top8块下标, 设备, None) 或 (None, None, 退回原因)。

    指纹/依赖检查在重模型导入之前——漂移或缺件时不加载模型、不碰 GPU。
    bm25_order 是 kb.query 的候选内 BM25 排序（块下标，已截断与否均可）。
    任何失败（缺依赖/模型加载/推理异常）=> (None, None, 原因)，由 kb.query
    完整退回 base+全局 BM25；不许抛异常打断兜底臂（阶段1契约）。
    """
    try:
        import numpy as np
    except ImportError:
        return None, None, "当前环境缺 numpy（稠密增强不可用，走 BM25 兜底）"
    p = Path(index_path)
    if not p.is_file():
        return None, None, "索引文件不存在"
    sha = _sha256(p.read_bytes())
    npz = p.with_name(f"embeddings_{sha[:12]}.npz")
    if not npz.is_file():
        return None, None, "稠密指纹件未建（py -3 -m taspipe.kb dense）"
    z = np.load(npz)
    if str(z["index_sha"]) != sha:
        return None, None, "稠密指纹与当前索引不一致（重跑 kb dense）"
    vecs = z["vecs"]
    if len(vecs) != len(chunks):
        return None, None, "稠密指纹块数与索引不符（重跑 kb dense）"
    try:
        from sentence_transformers import SentenceTransformer, CrossEncoder
    except ImportError:
        return None, None, "当前环境缺 sentence_transformers（用带依赖的 venv 或装依赖）"
    global _embedder, _ranker
    try:
        dev = _device()
        if _embedder is None:
            _embedder = SentenceTransformer(EMBED_MODEL, device=dev, revision=EMBED_REV,
                                            local_files_only=True,
                                            model_kwargs={"low_cpu_mem_usage": True})
        if _ranker is None:
            _ranker = CrossEncoder(RERANK_MODEL, device=dev, revision=RERANK_REV,
                                   max_length=1024, local_files_only=True,
                                   model_kwargs={"low_cpu_mem_usage": True})
        qv = _embedder.encode(q, normalize_embeddings=True)
        sims = vecs[cand] @ qv
        dense_order = [cand[i] for i in np.argsort(-sims)[:POOL]]
        bm25_list = bm25_order[:POOL]
        fused = _rrf([bm25_list, dense_order])
        pool = list(dict.fromkeys(fused + dense_order[:DENSE_CUT] + bm25_list[:BM25_CUT]))
        pairs = [(q, chunks[ci]["text"]) for ci in pool]
        rs = _ranker.predict(pairs)
        ranked = [ci for _, ci in sorted(zip(rs, pool), key=lambda x: -float(x[0]))]
        return anchor_top8(ranked, bm25_list), dev, None
    except Exception as e:
        # 模型加载/推理失败 => 显式退回原因，kb.query 完整重跑 base（不静默顶包）
        return None, None, f"稠密增强运行失败（{type(e).__name__}: {e}），退回 BM25"
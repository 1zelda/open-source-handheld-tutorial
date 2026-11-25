# -*- coding: utf-8 -*-
"""26 题走生产 kb.query 判分（零 LLM，只读检索）。

用法：py -3 -u prod_eval.py <输出json> [top_window] [题集json]
top_window 缺省 3（用户批准口径）；显式传 5 只作测量变体，不改生产默认。
题集缺省 p1_questions_ext.json；阶段2 传 p2_questions_ext.json（Q02 补范围）。
判分器与臂侧同一份 eval_common：v1 grade 保留基线口径，v2 grade_v2 绑定实际出证。
hybrid 与否由环境决定：带依赖 venv + 稠密指纹件 => hybrid_union12，否则明示 bm25_only。
阶段2：输出带指纹（题集/代码/参数/索引/模型身份），供四分类对账与复现。
"""
import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
sys.path.insert(0, str(HERE.parent / "知识库小样_20261118"))

from taspipe import kb  # noqa: E402
from taspipe import kb_dense as KD  # noqa: E402
from taspipe import kb_route as KR  # noqa: E402
import eval_common as E  # noqa: E402


def _sha(p):
    p = Path(p)
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.is_file() else None


def fingerprints(qpath, window):
    base = kb.INDEX_JSON
    hybrid = base.parent / "index_hybrid.json"
    idx = {}
    for name, p in (("base", base), ("hybrid", hybrid)):
        if p.is_file():
            d = json.loads(p.read_text(encoding="utf-8"))
            idx[name] = {"sha256_16": _sha(p), "chunks": len(d["chunks"]),
                         "bytes": p.stat().st_size}
    return {
        "taken_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "question_file": {"name": Path(qpath).name, "sha256_16": _sha(qpath)},
        "code_sha256_16": {"kb.py": _sha(kb.__file__), "kb_route.py": _sha(KR.__file__),
                           "kb_dense.py": _sha(KD.__file__), "eval_common.py": _sha(E.__file__),
                           "prod_eval.py": _sha(__file__)},
        "params": {"top_window": window},
        "indexes": idx,
        "models": {"embed": KD.EMBED_MODEL, "embed_rev": KD.EMBED_REV,
                   "rerank": KD.RERANK_MODEL, "rerank_rev": KD.RERANK_REV,
                   "rrf_k": KD.RRF_K, "pool": KD.POOL, "dense_cut": KD.DENSE_CUT,
                   "bm25_cut": KD.BM25_CUT, "topk": KD.TOPK},
    }


def main():
    out_path = Path(sys.argv[1])
    window = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    qname = sys.argv[3] if len(sys.argv) > 3 else "p1_questions_ext.json"
    qpath = HERE / qname
    spec = json.loads(qpath.read_text(encoding="utf-8"))
    results, grades, grades2 = [], [], []
    for q in spec["questions"]:
        f = q.get("filters", {})
        res = kb.query(q["q"], game=f.get("game"), revision=f.get("revision"),
                       platform=f.get("platform"), top_window=window)
        g = E.grade(q, res)
        g2 = E.grade_v2(q, res)
        gold = q.get("gold")
        pos = None
        if gold:
            for i, h in enumerate(res.get("hits", []), 1):
                if E._gold_hit(h, gold):
                    pos = i
                    break
        g["gold_pos"] = pos
        g["retrieval"] = res.get("retrieval")
        g["condition"] = res.get("condition")
        g["refusal"] = res.get("refusal")
        g["v2"] = g2
        grades.append(g)
        grades2.append(g2)
        results.append({"id": q["id"], "q": q["q"], "res": res})
        print(f"{q['id']:4s} {'OK ' if g['ok'] else 'FAIL'} {g['tier']:14s} "
              f"status={res['status']:12s} retrieval={res.get('retrieval', '?'):14s} "
              f"gold_pos={pos} v2={'OK ' if g2['ok'] else 'FAIL'} "
              f"sel_gold={g2['selected_locator'] is not None and g2['correct_evidence']} "
              f"refusal={res.get('refusal', '-')}", flush=True)
    summ = E.summarize(grades)
    summ2 = E.summarize_v2(grades2)
    print("v1:", json.dumps(summ, ensure_ascii=False), flush=True)
    print("v2:", json.dumps(summ2, ensure_ascii=False), flush=True)
    out_path.write_text(json.dumps({"summary": summ, "summary_v2": summ2,
                                    "fingerprints": fingerprints(qpath, window),
                                    "top_window": window, "question_file": qname,
                                    "grades": grades, "results": results},
                                   ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
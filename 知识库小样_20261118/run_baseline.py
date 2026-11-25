# -*- coding: utf-8 -*-
"""基线臂：只读调用生产 kb.query，不重建索引、不写生产目录。"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from taspipe import kb  # noqa: E402
import eval_common as E  # noqa: E402


def main():
    spec = E.load_questions()
    frozen = Path(__file__).resolve().parent / "frozen_corpus"
    ip, mp = frozen / "index.json", frozen / "corpus_map.json"
    idx = kb.load_index(ip)
    assert idx is not None, "冻结索引不存在，先跑 freeze_corpus.py"
    import hashlib
    sha = hashlib.sha256(ip.read_bytes()).hexdigest()
    assert sha == spec["corpus_fingerprint"]["index_sha256"], \
        f"冻结副本指纹漂移 {sha}，两臂必须同料"
    results, grades = [], []
    for q in spec["questions"]:
        t0 = time.perf_counter()
        res = kb.query(q["q"], topk=8, index_path=ip, map_path=mp, **q["filters"])
        dt = time.perf_counter() - t0
        g = E.grade(q, res)
        g["latency_ms"] = round(dt * 1000, 1)
        results.append({"id": q["id"], "q": q["q"], "filters": q["filters"],
                        "result": res})
        grades.append(g)
        print(f"{q['id']} [{'OK' if g['ok'] else 'FAIL'}] {g['tier']} "
              f"{g['why']} {g['latency_ms']}ms")
    out = {"arm": "baseline_bm25", "index_sha256": sha,
           "chunks": idx["stats"]["N"],
           "summary": E.summarize(grades), "grades": grades, "results": results}
    p = Path(__file__).resolve().parent / "baseline_results.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
# -*- coding: utf-8 -*-
"""P8 再索引诊断：26 题评测 + 60 题双窗口探针，走生产 kb.query 但指向临时索引。

用法：py -3 -u p8_eval.py bm25      （系统 py -3，无依赖 ⇒ bm25_only）
      venv  -u p8_eval.py hybrid    （venv + 临时 npz ⇒ hybrid_union12）
判分器/探针 brief 与生产 prod_eval.py / p23_probe.py 同一份（eval_common.grade / probe_window.brief）。
唯一差别：kb.query 传 index_path/map_path 指向 p8_scratch 临时件，生产默认路径不被读改。
输出：p8_reindex_{arm}_eval.json（同 prod_eval 结构）+ p8_reindex_{arm}_probe.json（同 p23_probe 结构）。
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
sys.path.insert(0, str(HERE.parent / "知识库小样_20261118"))
from taspipe import kb  # noqa: E402
import eval_common as E  # noqa: E402
from probe_window import brief  # noqa: E402

SCRATCH = HERE / "p8_scratch"
TEMP_INDEX = str(SCRATCH / "index_reindex.json")
TEMP_MAP = str(SCRATCH / "corpus_map_reindex.json")


def run_eval(arm):
    spec = json.loads((HERE / "p1_questions_ext.json").read_text(encoding="utf-8"))
    results, grades = [], []
    for q in spec["questions"]:
        f = q.get("filters", {})
        res = kb.query(q["q"], game=f.get("game"), revision=f.get("revision"),
                       platform=f.get("platform"), top_window=3,
                       index_path=TEMP_INDEX, map_path=TEMP_MAP)
        g = E.grade(q, res)
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
        grades.append(g)
        results.append({"id": q["id"], "q": q["q"], "res": res})
        print(f"{q['id']:4s} {'OK ' if g['ok'] else 'FAIL'} {g['tier']:14s} "
              f"status={res['status']:12s} retrieval={res.get('retrieval', '?'):14s} "
              f"gold_pos={pos} cond={'Y' if res.get('condition') else '-'} "
              f"refusal={res.get('refusal', '-')}", flush=True)
    summ = E.summarize(grades)
    print(json.dumps(summ, ensure_ascii=False), flush=True)
    out = HERE / f"p8_reindex_{arm}_eval.json"
    out.write_text(json.dumps({"summary": summ, "top_window": 3,
                               "grades": grades, "results": results},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print("written", out, flush=True)


def run_probe(arm):
    base = json.loads((HERE / "probe_questions.json").read_text(encoding="utf-8"))
    ext = json.loads((HERE / "probe_questions_ext.json").read_text(encoding="utf-8"))
    questions = [dict(q, kind="regression") for q in base["questions"]] + ext["questions"]
    rows = []
    for q in questions:
        f = q.get("filters", {})
        kw = dict(game=f.get("game"), revision=f.get("revision"), platform=f.get("platform"),
                  index_path=TEMP_INDEX, map_path=TEMP_MAP)
        r3 = kb.query(q["q"], top_window=3, **kw)
        r5 = kb.query(q["q"], top_window=5, **kw)
        flip = "SAME" if r3["status"] == r5["status"] else f"{r3['status']}->{r5['status']}"
        rows.append({"id": q["id"], "q": q["q"], "kind": q["kind"], "filters": f,
                     "flip": flip, "w3": brief(r3), "w5": brief(r5)})
        print(f"{q['id']} [{q['kind'][:10]:10s}] {flip:24s} w3={r3['status']:12s} "
              f"w5={r5['status']:12s} | {q['q']}", flush=True)
    out = HERE / f"p8_reindex_{arm}_probe.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    flips = [r for r in rows if r["flip"] != "SAME"]
    worse = [r for r in rows if r["w3"]["status"] == "pass" and r["w5"]["status"] != "pass"]
    trap_pass = [r["id"] for r in rows if r["kind"] == "trap"
                 and (r["w3"]["status"] == "pass" or r["w5"]["status"] == "pass")]
    print(f"\n共 {len(rows)} 题；翻转 {len(flips)} 条：{[r['id'] + ':' + r['flip'] for r in flips]}",
          flush=True)
    print(f"变差 {len(worse)} 条；trap格放行 {trap_pass}", flush=True)
    print("written", out, flush=True)


def main():
    arm = sys.argv[1] if len(sys.argv) > 1 else "bm25"
    assert arm in ("bm25", "hybrid"), arm
    print(f"==== P8 再索引评测 arm={arm} ====", flush=True)
    run_eval(arm)
    print(f"\n==== P8 再索引探针 arm={arm} ====", flush=True)
    run_probe(arm)


if __name__ == "__main__":
    main()
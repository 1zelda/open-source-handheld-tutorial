# -*- coding: utf-8 -*-
"""#23 中文对照落地后探针复测：60 条双窗口，生产 kb.query。
输出名由 argv[1] 指定（臂专属，绝不覆盖 P5 的 p5_probe_ext_results*.json）。
臂由环境决定：系统 py -3 = bm25_only；venv = hybrid。
用法：py -3 -u p23_probe.py p23_probe_results_bm25.json
      venv -u p23_probe.py p23_probe_results_hybrid.json
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import kb  # noqa: E402
from probe_window import brief  # noqa: E402


def main():
    outname = sys.argv[1] if len(sys.argv) > 1 else "p23_probe_results.json"
    base = json.loads((HERE / "probe_questions.json").read_text(encoding="utf-8"))
    ext = json.loads((HERE / "probe_questions_ext.json").read_text(encoding="utf-8"))
    questions = [dict(q, kind="regression") for q in base["questions"]] + ext["questions"]
    rows = []
    for q in questions:
        f = q.get("filters", {})
        kw = dict(game=f.get("game"), revision=f.get("revision"), platform=f.get("platform"))
        r3 = kb.query(q["q"], top_window=3, **kw)
        r5 = kb.query(q["q"], top_window=5, **kw)
        flip = "SAME" if r3["status"] == r5["status"] else f"{r3['status']}->{r5['status']}"

        def w(r):
            b = brief(r)
            b["selected_evidence"] = [{"chunk_id": h["chunk_id"], "locator": h["locator"]}
                                      for h in r.get("selected_evidence", [])]
            b["index_used"] = r.get("index_used")
            return b

        rows.append({"id": q["id"], "q": q["q"], "kind": q["kind"], "filters": f,
                     "flip": flip, "w3": w(r3), "w5": w(r5)})
        print(f"{q['id']} [{q['kind'][:10]:10s}] {flip:24s} w3={r3['status']:12s} "
              f"w5={r5['status']:12s} | {q['q']}", flush=True)
    out = HERE / outname
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    flips = [r for r in rows if r["flip"] != "SAME"]
    worse = [r for r in rows if r["w3"]["status"] == "pass" and r["w5"]["status"] != "pass"]
    trap_pass = [r["id"] for r in rows if r["kind"] == "trap"
                 and (r["w3"]["status"] == "pass" or r["w5"]["status"] == "pass")]
    # 阶段2分类：应拒答档（真负例/来源不足）放行 = 假阳候选；歧义档放行单列
    refuse_kinds = ("true_negative", "insufficient_source")
    fp_pass = [r["id"] for r in rows if r["kind"] in refuse_kinds
               and (r["w3"]["status"] == "pass" or r["w5"]["status"] == "pass")]
    amb_pass = [r["id"] for r in rows if r["kind"] == "ambiguous"
                and (r["w3"]["status"] == "pass" or r["w5"]["status"] == "pass")]
    print(f"\n共 {len(rows)} 题；翻转 {len(flips)} 条：{[r['id'] + ':' + r['flip'] for r in flips]}",
          flush=True)
    print(f"变差 {len(worse)} 条；trap格放行 {trap_pass}", flush=True)
    print(f"应拒答档放行(假阳候选) {fp_pass}；歧义档放行 {amb_pass}", flush=True)
    print(f"written {out}", flush=True)


if __name__ == "__main__":
    main()
# -*- coding: utf-8 -*-
"""窗口边界探针：30 条人工问句，同一问句跑 top_window=3 与 5（生产 kb.query 真实入口）。

判定规则（跑前定死）：保留 window5 当默认，当且仅当——
  1) 每条 inconclusive→pass 翻转的第4/5位权威件经人工核对确实回答了问题；
  2) 拒答/域外档零回归（top3 拒的 top5 也必须拒）；
  3) 没有任何题变差（pass→非pass）。
任一不满足 ⇒ 维持 top3。
用法（venv）：python -u probe_window.py  → probe_window_results.json + 控制台逐条
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import kb  # noqa: E402


def brief(res):
    return {
        "status": res["status"],
        "reason": res.get("reason"),
        "condition": res.get("condition"),
        "refusal": res.get("refusal"),
        "retrieval": res.get("retrieval"),
        "query_expansion": res.get("query_expansion"),
        "hits": [{"rank": i, "chunk_id": h["chunk_id"], "locator": h["locator"],
                  "authority": h.get("authority"),
                  "answerable": h.get("answerability", {}).get("answerable"),
                  "snippet": h.get("snippet", "")}
                 for i, h in enumerate(res.get("hits", []), 1)],
    }


def main():
    spec = json.loads((HERE / "probe_questions.json").read_text(encoding="utf-8"))
    rows = []
    for q in spec["questions"]:
        f = q.get("filters", {})
        kw = dict(game=f.get("game"), revision=f.get("revision"), platform=f.get("platform"))
        r3 = kb.query(q["q"], top_window=3, **kw)
        r5 = kb.query(q["q"], top_window=5, **kw)
        flip = "SAME"
        if r3["status"] != r5["status"]:
            flip = f"{r3['status']}->{r5['status']}"
        rows.append({"id": q["id"], "q": q["q"], "filters": f, "flip": flip,
                     "w3": brief(r3), "w5": brief(r5)})
        print(f"{q['id']} {flip:24s} w3={r3['status']:12s} w5={r5['status']:12s} "
              f"cond5={'Y' if r5.get('condition') else '-'} | {q['q']}", flush=True)
        if flip != "SAME":
            for h in brief(r5)["hits"][2:5]:
                print(f"    rank{h['rank']} auth={h['authority']} ans={h['answerable']} "
                      f"{h['locator']}", flush=True)
                print(f"      {h['snippet'][:200]}", flush=True)
    out = HERE / "probe_window_results.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    flips = [r for r in rows if r["flip"] != "SAME"]
    worse = [r for r in rows if r["w3"]["status"] == "pass" and r["w5"]["status"] != "pass"]
    refuse_reg = [r for r in rows if r["w3"]["status"] != "pass" and r["w5"]["status"] == "pass"
                  and r["w3"].get("refusal") == "out_of_scope"]
    print(f"\n共 {len(rows)} 题；翻转 {len(flips)} 条：{[r['id'] + ':' + r['flip'] for r in flips]}",
          flush=True)
    print(f"变差 {len(worse)} 条；域外误放行 {len(refuse_reg)} 条", flush=True)
    print(f"written {out}", flush=True)


if __name__ == "__main__":
    main()
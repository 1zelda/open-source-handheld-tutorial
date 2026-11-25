# -*- coding: utf-8 -*-
"""窗口扩集复测：60 条（W01-W30 回归基线 + X01-X30 新格），生产 kb.query 双窗口。
跑前规则见 窗口扩集决策_2026-11-19.md（假阳性一票否决/回归零容忍/真救回≥1才翻默认）。
用法（venv）：python -u p5_probe_ext.py → p5_probe_ext_results.json（不碰窗口决策轮原件）
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import kb  # noqa: E402
from probe_window import brief  # noqa: E402


def main():
    base = json.loads((HERE / "probe_questions.json").read_text(encoding="utf-8"))
    ext = json.loads((HERE / "probe_questions_ext.json").read_text(encoding="utf-8"))
    questions = [dict(q, kind="regression") for q in base["questions"]] + ext["questions"]
    rows = []
    for q in questions:
        f = q.get("filters", {})
        kw = dict(game=f.get("game"), revision=f.get("revision"), platform=f.get("platform"))
        r3 = kb.query(q["q"], top_window=3, **kw)
        r5 = kb.query(q["q"], top_window=5, **kw)
        flip = "SAME"
        if r3["status"] != r5["status"]:
            flip = f"{r3['status']}->{r5['status']}"
        rows.append({"id": q["id"], "q": q["q"], "kind": q["kind"], "filters": f,
                     "flip": flip, "w3": brief(r3), "w5": brief(r5)})
        print(f"{q['id']} [{q['kind'][:10]:10s}] {flip:24s} w3={r3['status']:12s} "
              f"w5={r5['status']:12s} cond5={'Y' if r5.get('condition') else '-'} | {q['q']}",
              flush=True)
        if flip != "SAME":
            for h in brief(r5)["hits"][2:5]:
                print(f"    rank{h['rank']} auth={h['authority']} ans={h['answerable']} "
                      f"{h['locator']}", flush=True)
                print(f"      {h['snippet'][:200]}", flush=True)
    out = HERE / "p5_probe_ext_results.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    flips = [r for r in rows if r["flip"] != "SAME"]
    worse = [r for r in rows if r["w3"]["status"] == "pass" and r["w5"]["status"] != "pass"]
    refuse_reg = [r for r in rows if r["w3"]["status"] != "pass" and r["w5"]["status"] == "pass"
                  and r["w3"].get("refusal") == "out_of_scope"]
    trap_pass = [r["id"] for r in rows if r["kind"] == "trap"
                 and (r["w3"]["status"] == "pass" or r["w5"]["status"] == "pass")]
    print(f"\n共 {len(rows)} 题；翻转 {len(flips)} 条：{[r['id'] + ':' + r['flip'] for r in flips]}",
          flush=True)
    print(f"变差 {len(worse)} 条；域外误放行 {len(refuse_reg)} 条；trap格放行 {trap_pass}",
          flush=True)
    print(f"written {out}", flush=True)


if __name__ == "__main__":
    main()
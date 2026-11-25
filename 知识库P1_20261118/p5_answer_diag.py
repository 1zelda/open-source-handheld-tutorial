# -*- coding: utf-8 -*-
"""P5 只读诊断：7 个疑似假阳性格的可答性五关分解，不写任何生产状态。

对象：翻转假阳性 X01/X06/X07/X24 + w3 已放行疑似假阳性 X25/X26/X28/X30。
对每题取 top5 内全部 answerable 块，打印五关分解 + 焦点词/锚词命中，
定位是哪一关放行了"含焦点词但不含答案事实"的块。
用法（venv）：python -u p5_answer_diag.py > p5_answer_diag_out.txt
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import kb  # noqa: E402
from taspipe.kb_route import classify_intent, focus_terms, focus_pattern, expand_terms  # noqa: E402

SUSPECTS = ["X01", "X06", "X07", "X24", "X25", "X26", "X28", "X30"]


def main():
    spec = json.loads((HERE / "probe_questions_ext.json").read_text(encoding="utf-8"))
    qs = {q["id"]: q for q in spec["questions"]}
    tok = kb._tokens if hasattr(kb, "_tokens") else None
    for qid in SUSPECTS:
        q = qs[qid]
        f = q.get("filters", {})
        res = kb.query(q["q"], top_window=5, game=f.get("game"),
                       revision=f.get("revision"), platform=f.get("platform"))
        print(f"== {qid} {q['q']}  status={res['status']} intent={classify_intent(q['q'])}")
        fp = focus_pattern(q["q"])
        print(f"   focus_pattern={fp.pattern if fp else None}")
        for i, h in enumerate(res.get("hits", [])[:5], 1):
            a = h.get("answerability", {})
            if not a.get("answerable"):
                continue
            print(f"   rank{i} {h['locator'].split('/')[-1]} auth={h.get('authority')}")
            print(f"     intent={a.get('intent')} focus_ok={a.get('focus_ok')} "
                  f"pattern_ok={a.get('pattern_ok')} intent_ok={a.get('intent_ok')} "
                  f"url_list={a.get('url_list')} anchor_ok={a.get('topic_anchor_ok')}")
            print(f"     focus_hit={a.get('focus_hit')}")
            print(f"     snippet={h.get('snippet', '')[:180]}")
        print(flush=True)


if __name__ == "__main__":
    main()
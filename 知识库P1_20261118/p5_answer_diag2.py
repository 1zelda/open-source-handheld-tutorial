# -*- coding: utf-8 -*-
"""P5 只读诊断 v2：直接 annotate 嫌疑块（不加载模型、不跑 query、不写任何状态）。

可答性五关是纯 Python，与检索臂无关。对每个疑似假阳性格，取嫌疑 locator 行段
内的真实索引块，打印五关分解 + 焦点/锚词命中，定位是哪一关放行了
"含焦点词但不含答案事实"的块。同时打印真答案所在块作对照。
用法（系统 py -3 即可，无需 venv）：python -u p5_answer_diag2.py > p5_answer_diag2_out.txt
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import kb as K  # noqa: E402
from taspipe import kb_route as KR  # noqa: E402
from taspipe.kb_answer import annotate  # noqa: E402

# (id, 问句, 嫌疑块 path_part, 行段) —— 嫌疑块=探针里放行但疑不答问句的块
SUSPECT = [
    ("X01", "热血足球 1P 得分的内存地址是多少？", "必杀全清单", 194, 210),
    ("X06", "热血足球 应援曲一共有几首？", "必杀全清单", 262, 264),
    ("X07", "热血足球 海月是什么射门？", "必杀全清单", 229, 231),
    ("X24", "热血足球 怎么存档进度？", "必杀全清单", 101, 119),
    ("X25", "热血足球 球员受伤了怎么治疗？", "必杀全清单", 137, 158),
    ("X26", "热血足球 雨天场地对射门有什么影响？", "必杀全清单", 137, 158),
    ("X28", "拳皇98 ECK 金手指怎么用？", "素材生产规范", 18, 31),
    ("X30", "热血足球 合体技有哪些发动方法？", "必杀全清单", 3, 7),
]
# 真答案块对照（必须仍可答）
TRUE_ANS = [
    ("X01真", "热血足球 1P 得分的内存地址是多少？", "必杀全清单", 216, 225),
    ("X06真", "热血足球 应援曲一共有几首？", "必杀全清单", 216, 225),
    ("X07真", "热血足球 海月是什么射门？", "必杀全清单", 36, 49),
    ("X24真", "热血足球 怎么存档进度？", "必杀全清单", 234, 239),
]


def show(chunks, qid, q, pp, a, b):
    cs = [c for c in chunks if pp in c["path"]
          and c["line_start"] <= b and c["line_end"] >= a]
    if not cs:
        print(f"  {qid} 无块 {pp} L{a}-{b}")
        return
    for c in cs:
        r = annotate(q, c["text"], K.tokens, c.get("lang", "zh"))
        focus = KR.focus_terms(q, K.tokens)
        anchor = focus | KR.expand_terms(q, K.tokens)
        tt = set(K.tokens(c["text"]))
        print(f"  {qid} L{c['line_start']}-{c['line_end']} lang={c.get('lang')} "
              f"ans={r['answerable']} intent={r['intent']}")
        print(f"    focus_ok={r['focus_ok']} pattern_ok={r['pattern_ok']} "
              f"intent_ok={r['intent_ok']} url_list={r['url_list']} "
              f"anchor_ok={r['topic_anchor_ok']}")
        print(f"    focus={sorted(focus)}")
        print(f"    focus_hit={r['focus_hit']} anchor_hit={sorted(anchor & tt)[:8]}")
        fp = KR.focus_pattern(q)
        print(f"    focus_pattern={fp.pattern if fp else None}")


def main():
    idx = K.load_index(K.INDEX_JSON)
    chunks = idx["chunks"]
    print("=== 嫌疑块（疑假阳性：放行但不答问句）===")
    for qid, q, pp, a, b in SUSPECT:
        print(f"== {qid} {q}")
        show(chunks, qid, q, pp, a, b)
        print()
    print("=== 真答案块对照（必须仍可答）===")
    for qid, q, pp, a, b in TRUE_ANS:
        print(f"== {qid} {q}")
        show(chunks, qid, q, pp, a, b)
        print()


if __name__ == "__main__":
    main()
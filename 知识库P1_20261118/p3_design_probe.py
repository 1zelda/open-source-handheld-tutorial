# -*- coding: utf-8 -*-
"""P3 设计诊断（只读，不改生产）：在真实索引上模拟候选规则，量误杀面。

候选规则：
  R1 结构关：块含 >=2 个 http(s) 网址 => 来源清单不是答案正文 => 不可答
  R2 话题锚：howto/existence 意图也硬性要求焦点词重叠（焦点集并入跨语扩展词）
核对对象：3 假阳性块必须变不可答；26 题金标块 + 探针真阳性块必须仍可答。
用法：venv python -u p3_design_probe.py
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import kb as K  # noqa: E402
from taspipe import kb_route as KR  # noqa: E402
from taspipe.kb_answer import annotate  # noqa: E402

URL_RE = re.compile(r"https?://")


def sim(q, text, lang="zh"):
    """现状 + 候选规则后的可答性。R2 只对中文主导块生效（跨语块焦点天然不重叠，
    由形态关/意图校验器把关；三个假阳性全是中文块）。"""
    cur = annotate(q, text, K.tokens)
    focus = KR.focus_terms(q, K.tokens) | KR.expand_terms(q, K.tokens)
    tt = set(K.tokens(text))
    hit = sorted(focus & tt)
    r1 = len(URL_RE.findall(text)) >= 2
    r2 = lang == "zh" and cur["intent"] in ("howto", "existence") and not hit
    new = cur["answerable"] and not r1 and not r2
    return cur, new, hit, r1, r2


def main():
    idx = K.load_index(K.INDEX_JSON)
    chunks = idx["chunks"]

    def find(path_part, ls, le):
        return [c for c in chunks if path_part in c["path"]
                and c["line_start"] <= le and c["line_end"] >= ls]

    print("=== 假阳性块（必须变不可答）===")
    fp = [("W11 一直输球会怎么样？", "必杀全清单", 137, 158),
          ("W14 禁区高空球怎么顶？", "必杀全清单", 216, 225),
          ("W27 有没有隐藏结局？", "必杀全清单", 216, 225)]
    for q, pp, a, b in fp:
        for c in find(pp, a, b):
            cur, new, hit, r1, r2 = sim(q, c["text"], c.get("lang", "zh"))
            print(f"{q[:12]} L{c['line_start']}-{c['line_end']} "
                  f"intent={cur['intent']} 现={cur['answerable']} 新={new} "
                  f"R1={r1} R2={r2} focus_hit={hit[:6]}")

    print("\n=== 26 题金标块（必须保持可答；refuse/无gold题跳过）===")
    spec = json.loads((HERE / "p1_questions_ext.json").read_text(encoding="utf-8"))
    bad = 0
    for q in spec["questions"]:
        g = q.get("gold")
        if not g:
            continue
        cs = find(g["path_contains"], g["line_start"], g["line_end"])
        if not cs:
            print(f"{q['id']} 金标无块！")
            bad += 1
            continue
        states = []
        for c in cs:
            cur, new, hit, r1, r2 = sim(q["q"], c["text"], c.get("lang", "zh"))
            states.append((c["line_start"], cur["answerable"], new, r1, r2, hit[:4]))
        any_new = any(s[2] for s in states)
        flag = "OK" if any_new else "KILLED"
        if not any_new:
            bad += 1
        print(f"{q['id']} {flag} {q['q'][:24]}")
        for ls, ca, na, r1, r2, hit in states:
            print(f"    L{ls} 现={ca} 新={na} R1={r1} R2={r2} hit={hit}")

    print("\n=== 探针真阳性/现状pass题的代表块（抽查不误杀）===")
    spot = [("W02 热血足球联盟 必杀射门有几种？", "必杀全清单", 3, 7),
            ("W01 热血足球2 燕返怎么触发？", "必杀全清单", 70, 85),
            ("W07 热血足球2 暂停秘技的签名是什么？", "必杀全清单", 251, 259),
            ("W29 拳皇98 ECK 能不能关掉队战？", "素材生产规范", 185, 190),
            ("P22 说明书里的 PK 战模式怎么玩？", "setsumei", 329, 329),
            ("P23 说明书里状态（ステータス）一节讲了哪些参数？", "setsumei", 269, 269),
            ("Q05 我想控制队长以外的队员，该怎么换人？", "必杀全清单", 24, 33),
            ("Q16 怎么射门才能让守门员扑不到？", "必杀全清单", 3, 7)]
    for q, pp, a, b in spot:
        for c in find(pp, a, b):
            cur, new, hit, r1, r2 = sim(q, c["text"], c.get("lang", "zh"))
            print(f"{q[:14]} L{c['line_start']}-{c['line_end']} "
                  f"intent={cur['intent']} 现={cur['answerable']} 新={new} "
                  f"R1={r1} R2={r2} hit={hit[:6]}")
    print(f"\n金标误杀数：{bad}")


if __name__ == "__main__":
    main()
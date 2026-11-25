# -*- coding: utf-8 -*-
"""P5 候选规则模拟（只读，不改生产）：量误杀面，数据决定落哪条。

候选：
  C1 count 量词补「首」（几首/多少首→首），治 X06「11条」串答。
  C2 焦点形态补「什么射门→射门」，治 X07 只命中主语「海月」缺属性「射门」。
  R3 zh 块且问句无焦点形态(fp=None)时，要求 >=2 个焦点词命中（焦点内容词>=2 才施），
     治 X01/X24/X25/X26/X28 只命中一个 peripheral 词。ja 块豁免（跨语焦点天然不重叠）。

核对：8 嫌疑块须变不可答(X30 除外，语料层)；26 题金标块须仍可答；
      26+60 逐题域内"现状可答的权威块"候选后不得清零（pass→inconclusive 回归）。
用法（系统 py -3）：python -u p5_fix_sim.py > p5_fix_sim_out.txt
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import kb as K  # noqa: E402
from taspipe import kb_route as KR  # noqa: E402
from taspipe import kb_answer as KA  # noqa: E402

COUNT_ASK_C1 = KA.COUNT_ASK + [(re.compile(r"几首|多少首"), ["首"])]
FOCUS_PATTERNS_C2 = KR.FOCUS_PATTERNS + [(re.compile(r"什么射门"), re.compile(r"射门"))]


def focus_pattern_c2(q):
    for qrx, arx in FOCUS_PATTERNS_C2:
        if qrx.search(q):
            return arx
    return None


def count_ok_c1(q, text):
    t = KA._norm(text)
    for qrx, units in COUNT_ASK_C1:
        if qrx.search(q):
            return any(re.search(r"\d+\s*" + re.escape(u), t) for u in units)
    return bool(KA.COUNT_RE.search(t))


def intent_ok_c1(intent, q, text):
    if intent == "count":
        return count_ok_c1(q, text)
    return KA._intent_ok(intent, q, text)


def cand(q, text, lang, use_r3):
    """返回 (现状ans, 候选ans, 分解)。C1+C2 恒在；R3 由 use_r3 控制。"""
    cur = KA.annotate(q, text, K.tokens, lang)
    intent = KR.classify_intent(q)
    focus = KR.focus_terms(q, K.tokens)
    tt = set(K.tokens(text))
    focus_hit = sorted(focus & tt)
    fp = focus_pattern_c2(q)
    pattern_ok = bool(fp.search(text)) if fp else True
    intent_ok = intent_ok_c1(intent, q, text)
    focus_required = intent == "topic" or (intent == "identity" and fp is None)
    focus_ok = bool(focus_hit) if focus else True
    url_list = len(KA.URL_RE.findall(text)) >= 2
    anchor_focus = focus | KR.expand_terms(q, K.tokens)
    anchor_ok = bool(anchor_focus & tt) if anchor_focus else True
    anchor_required = lang == "zh" and intent in ("howto", "existence")
    new = (pattern_ok and intent_ok and (focus_ok or not focus_required)
           and not url_list and (anchor_ok or not anchor_required))
    r3_kill = False
    if use_r3 and lang == "zh" and fp is None and len(focus) >= 2:
        if len(focus_hit) < 2:
            r3_kill = True
            new = False
    return cur["answerable"], bool(new), r3_kill, focus_hit


def find(chunks, pp, a, b):
    return [c for c in chunks if pp in c["path"]
            and c["line_start"] <= b and c["line_end"] >= a]


def main():
    idx = K.load_index(K.INDEX_JSON)
    chunks = idx["chunks"]
    ext = json.loads((HERE / "probe_questions_ext.json").read_text(encoding="utf-8"))
    old = json.loads((HERE / "probe_questions.json").read_text(encoding="utf-8"))
    frozen = json.loads((HERE / "p1_questions_ext.json").read_text(encoding="utf-8"))
    probes = ext["questions"] + [dict(q, kind="regression") for q in old["questions"]]

    suspect = [("X01", "必杀全清单", 194, 210), ("X06", "必杀全清单", 262, 264),
               ("X07", "必杀全清单", 229, 231), ("X24", "必杀全清单", 101, 119),
               ("X25", "必杀全清单", 137, 158), ("X26", "必杀全清单", 137, 158),
               ("X28", "素材生产规范", 18, 31), ("X30", "必杀全清单", 3, 7)]
    pmap = {q["id"]: q["q"] for q in probes}

    for use_r3 in (False, True):
        tag = "C1+C2+R3" if use_r3 else "C1+C2"
        print(f"\n########## 候选 {tag} ##########")
        print("=== 嫌疑块（须变不可答，X30 除外）===")
        for qid, pp, a, b in suspect:
            q = pmap[qid]
            for c in find(chunks, pp, a, b):
                ca, na, r3, hit = cand(q, c["text"], c.get("lang", "zh"), use_r3)
                print(f"  {qid} L{c['line_start']}-{c['line_end']} 现={ca} 新={na} "
                      f"r3_kill={r3} hit={hit[:5]}")

        print("=== 26 题金标块（须仍可答）===")
        killed = 0
        for q in frozen["questions"]:
            g = q.get("gold")
            if not g:
                continue
            cs = find(chunks, g["path_contains"], g["line_start"], g["line_end"])
            states = [cand(q["q"], c["text"], c.get("lang", "zh"), use_r3) for c in cs]
            any_new = any(s[1] for s in states)
            any_cur = any(s[0] for s in states)
            if any_cur and not any_new:
                killed += 1
                print(f"  {q['id']} KILLED {q['q'][:26]}")
                for c, s in zip(cs, states):
                    print(f"     L{c['line_start']} 现={s[0]} 新={s[1]} r3={s[2]} hit={s[3][:5]}")
        print(f"  金标误杀数：{killed}")

        print("=== 26+60 逐题域内可答权威块清零回归（pass→inconclusive）===")
        reg = 0
        allq = frozen["questions"] + probes
        for q in allq:
            f = q.get("filters", {})
            r = KR.route(q["q"])
            if f.get("game"):
                r["game_ids"] = [f["game"]]
            if f.get("revision"):
                r["revisions"] = [f["revision"]]
            scope = [c for c in chunks if KR.in_scope(c, r)]
            cur_auth = [c for c in scope
                        if c.get("authority") == "authoritative"
                        and KA.annotate(q["q"], c["text"], K.tokens, c.get("lang", "zh"))["answerable"]]
            new_auth = [c for c in scope
                        if c.get("authority") == "authoritative"
                        and cand(q["q"], c["text"], c.get("lang", "zh"), use_r3)[1]]
            if cur_auth and not new_auth:
                reg += 1
                print(f"  {q['id']:5s} REGRESS {q['q'][:30]} 现可答权威{len(cur_auth)}→0")
        print(f"  清零回归题数：{reg}")


if __name__ == "__main__":
    main()
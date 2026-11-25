# -*- coding: utf-8 -*-
"""P4 修复模拟第二轮（只读）：F1 整词扩展被数据否决（Q07 3->23、P22 1->8 回归，
Q08 仍 11 名救不回）。本轮试「扩展词降权」原则性变体：
  A: 扩展词全部 0.5 权重
  B: 扩展词全部 0.3 权重
  C: 扩展整词 1.0、扩展 bigram 0.5
自家问句词恒 1.0。扩展是猜测、原词是确定——降权是原则不是逐题调参。
用法：venv python -u p4_fix_sim2.py
"""
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
sys.path.insert(0, str(HERE.parent / "知识库小样_20261118"))
from taspipe import kb as K  # noqa: E402
from taspipe import kb_route as KR  # noqa: E402


def bm25_rank_w(idx, chunks, cand, own, extra, weight_fn):
    N, avgdl = idx["stats"]["N"], idx["stats"]["avgdl"] or 1.0
    cand_set = set(cand)
    scores = {}
    for term in own | extra:
        post = idx["postings"].get(term)
        if not post:
            continue
        w = 1.0 if term in own else weight_fn(term, extra)
        df = len(post)
        idf = math.log(1 + (N - df + 0.5) / (df + 0.5))
        for ci, tf in post:
            if ci not in cand_set:
                continue
            dl = chunks[ci]["dl"] or 1
            scores[ci] = scores.get(ci, 0.0) + w * idf * tf * (K.K1 + 1) / (
                tf + K.K1 * (1 - K.B + K.B * dl / avgdl))
    return sorted(scores, key=lambda ci: (-scores[ci], ci))


def cand_of(chunks, m, q, f):
    from taspipe.kb_route import route, in_scope
    revision = f.get("revision")
    game = f.get("game")
    platform = f.get("platform")
    rev_game = m["revisions"][revision]["game_id"] if revision else None
    r = route(q)
    has_filters = bool(game or revision or platform)
    return [i for i, c in enumerate(chunks)
            if (has_filters or in_scope(c, r))
            and K._filters(c, game, revision, platform, None, rev_game)]


def gold_pos(order, chunks, gold):
    if not gold:
        return None
    for rank, ci in enumerate(order, 1):
        c = chunks[ci]
        if gold["path_contains"] in c["path"] \
                and c["line_start"] <= gold["line_end"] \
                and c["line_end"] >= gold["line_start"]:
            return rank
    return None


def main():
    idx = K.load_index(K.INDEX_JSON)
    chunks = idx["chunks"]
    m = K.load_map(None)
    spec = json.loads((HERE / "p1_questions_ext.json").read_text(encoding="utf-8"))
    probe = json.loads((HERE / "probe_questions.json").read_text(encoding="utf-8"))

    def wA(t, extra):
        return 0.5

    def wB(t, extra):
        return 0.3

    whole_forms = {form for forms in KR.JA_SYNONYMS.values() for form in forms}

    def wC(t, extra):
        return 1.0 if t in whole_forms else 0.5

    variants = [("A0.5", wA), ("B0.3", wB), ("C整1半0.5", wC)]
    print("=== 26 题：gold BM25 位次  现 | A | B | C（<=8 才进得了池/窗）===")
    for q in spec["questions"]:
        f = q.get("filters", {})
        cand = cand_of(chunks, m, q["q"], f)
        if not cand:
            continue
        own = set(K.tokens(q["q"]))
        extra = KR.expand_terms(q["q"], K.tokens) - own
        o0 = bm25_rank_w(idx, chunks, cand, own, extra, lambda t, e: 1.0)
        row = [gold_pos(o0, chunks, q.get("gold"))]
        tops = [o0[:1]]
        for name, fn in variants:
            o = bm25_rank_w(idx, chunks, cand, own, extra, fn)
            row.append(gold_pos(o, chunks, q.get("gold")))
            tops.append(o[:1])
        chg = "".join("变" if t != tops[0] else "同" for t in tops[1:])
        print(f"{q['id']:4s} " + " | ".join(f"{str(p):>4s}" for p in row)
              + f"  top1:{chg}  {q['q'][:24]}")
    print("\n=== 30 探针：top1 变化（现 vs A/B/C）===")
    for q in probe["questions"]:
        f = q.get("filters", {})
        cand = cand_of(chunks, m, q["q"], f)
        if not cand:
            continue
        own = set(K.tokens(q["q"]))
        extra = KR.expand_terms(q["q"], K.tokens) - own
        o0 = bm25_rank_w(idx, chunks, cand, own, extra, lambda t, e: 1.0)
        chg = []
        for name, fn in variants:
            o = bm25_rank_w(idx, chunks, cand, own, extra, fn)
            chg.append("同" if o[:1] == o0[:1] else "变")
        if any(c == "变" for c in chg):
            c = chunks[o0[0]]
            print(f"{q['id']} {'/'.join(chg)}  现top1={c['path'].split('/')[-1][:24]} L{c['line_start']}")
    print("（未打印的探针 = 三变体 top1 全同）")


if __name__ == "__main__":
    main()
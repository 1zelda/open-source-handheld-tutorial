# -*- coding: utf-8 -*-
"""P4 修复模拟（只读，不改生产）：
  F1 跨语扩展只取整词（去 bigram 噪声）——治 Q08 的メンバー紹介段刷分
  F2 词法锚：BM25 top1 保最终 top8 席位——治 Q10 重排推翻主干
模拟 26 题冻结集 + 30 探针的 BM25 排序变化与 gold 位次；hybrid 全链真跑由后续验证承担。
用法：venv python -u p4_fix_sim.py
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
import eval_common as E  # noqa: E402


def whole_forms(q):
    extra = set()
    for zh, forms in KR.JA_SYNONYMS.items():
        if zh in q:
            for form in forms:
                extra.update(t for t in K.tokens(form) if len(t) == len(form))
    return extra


def bm25_rank(idx, chunks, cand, qt):
    N, avgdl = idx["stats"]["N"], idx["stats"]["avgdl"] or 1.0
    cand_set = set(cand)
    scores, matched = {}, {}
    for term in qt:
        post = idx["postings"].get(term)
        if not post:
            continue
        df = len(post)
        idf = math.log(1 + (N - df + 0.5) / (df + 0.5))
        for ci, tf in post:
            if ci not in cand_set:
                continue
            dl = chunks[ci]["dl"] or 1
            scores[ci] = scores.get(ci, 0.0) + idf * tf * (K.K1 + 1) / (
                tf + K.K1 * (1 - K.B + K.B * dl / avgdl))
            matched.setdefault(ci, []).append(term)
    order = sorted(scores, key=lambda ci: (-scores[ci], ci))
    return order, scores, matched


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
    print("=== 26 题冻结集：BM25 排序 gold 位次（现扩展 vs 整词扩展）===")
    for q in spec["questions"]:
        f = q.get("filters", {})
        cand = cand_of(chunks, m, q["q"], f)
        if not cand:
            print(f"{q['id']:4s} 无候选（域外/miss）")
            continue
        qt0 = set(K.tokens(q["q"])) | KR.expand_terms(q["q"], K.tokens)
        qt1 = set(K.tokens(q["q"])) | whole_forms(q["q"])
        o0, s0, _ = bm25_rank(idx, chunks, cand, qt0)
        o1, s1, _ = bm25_rank(idx, chunks, cand, qt1)
        g = q.get("gold")
        p0, p1 = gold_pos(o0, chunks, g), gold_pos(o1, chunks, g)
        top1_same = (o0[:1] == o1[:1])
        print(f"{q['id']:4s} gold {str(p0):>4s} -> {str(p1):>4s}  "
              f"top1{'同' if top1_same else '变'}  {q['q'][:26]}")
    print("\n=== 30 探针：BM25 top1 变化（F2 锚的对象）与整词扩展影响 ===")
    for q in probe["questions"]:
        f = q.get("filters", {})
        cand = cand_of(chunks, m, q["q"], f)
        if not cand:
            print(f"{q['id']} 无候选")
            continue
        qt0 = set(K.tokens(q["q"])) | KR.expand_terms(q["q"], K.tokens)
        qt1 = set(K.tokens(q["q"])) | whole_forms(q["q"])
        o0, _, _ = bm25_rank(idx, chunks, cand, qt0)
        o1, _, _ = bm25_rank(idx, chunks, cand, qt1)
        t0 = chunks[o0[0]] if o0 else None
        t1 = chunks[o1[0]] if o1 else None
        same = o0[:1] == o1[:1]
        lab = lambda c: f"{c['path'].split('/')[-1][:22]} L{c['line_start']}" if c else "-"
        print(f"{q['id']} top1{'同' if same else '变'} {lab(t0)}"
              + ("" if same else f" -> {lab(t1)}"))


if __name__ == "__main__":
    main()
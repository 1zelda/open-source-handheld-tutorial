# -*- coding: utf-8 -*-
"""小样共用判分器：两臂输出同构 hits，逐格直接计数，不许倒推。"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOC_RE = re.compile(r"#L(\d+)-L(\d+)$")


def load_questions():
    return json.loads((HERE / "pilot_questions.json").read_text(encoding="utf-8"))


def _loc(hit):
    m = LOC_RE.search(hit["locator"])
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def _gold_hit(hit, gold):
    if gold is None:
        return False
    if gold["path_contains"] not in hit["locator"]:
        return False
    s, e = _loc(hit)
    return s <= gold["line_end"] and e >= gold["line_start"]


def grade(q, res):
    tier = q["expect"]
    hits = res.get("hits", [])
    status = res.get("status")
    if tier == "strict_pass":
        ok = status == "pass" and any(_gold_hit(h, q["gold"]) for h in hits)
        why = f"status={status}, gold_overlap={any(_gold_hit(h, q['gold']) for h in hits)}"
    elif tier == "gold_in_topk":
        ok = any(_gold_hit(h, q["gold"]) for h in hits)
        why = f"status={status}, gold_in_top{len(hits)}={ok}"
    elif tier == "refuse":
        ok = status in ("miss", "inconclusive")
        why = f"status={status}（pass 即失败：缺证据不许冒充事实）"
    elif tier == "version_guard":
        um = [h for h in hits if "gamersky" in h["locator"]]
        top1_um = bool(hits) and "gamersky" in hits[0]["locator"]
        warned = bool(res.get("authority_warnings"))
        ok = (not (status == "pass" and top1_um)) and (not um or warned)
        why = f"status={status}, um_hits={len(um)}, top1_um={top1_um}, warned={warned}"
    else:
        raise ValueError(tier)
    return {"id": q["id"], "tier": tier, "ok": bool(ok), "why": why,
            "status": status, "n_hits": len(hits),
            "top1": hits[0]["locator"] if hits else None}


def summarize(grades):
    by_tier = {}
    for g in grades:
        t = by_tier.setdefault(g["tier"], {"total": 0, "ok": 0})
        t["total"] += 1
        t["ok"] += int(g["ok"])
    return {"total": len(grades), "ok": sum(g["ok"] for g in grades),
            "by_tier": by_tier,
            "failed_ids": [g["id"] for g in grades if not g["ok"]]}


def grade_v2(q, res):
    """阶段2尺子：strict_pass 绑定 selected_evidence（实际放行块）与金标重叠，
    不再"任意命中含金标即过"。v1 grade() 字节不动，供四分类对账。
    分表字段逐题记录：直接召回/正确出证/错误出证/漏答/引用有效性/版本条件错误。
    等价证据召回（equivalent_recall）保留位，阶段4跨语对齐落地后才计分。"""
    tier = q["expect"]
    hits = res.get("hits", [])
    status = res.get("status")
    sel = res.get("selected_evidence") or []
    gold = q.get("gold")
    direct = any(_gold_hit(h, gold) for h in hits)
    sel_gold = bool(sel) and _gold_hit(sel[0], gold)
    cit = True
    if sel:
        s, e = _loc(sel[0])
        cit = s > 0 and e >= s
    um = [h for h in hits if "gamersky" in h["locator"]]
    top1_um = bool(hits) and "gamersky" in hits[0]["locator"]
    sel_um = bool(sel) and "gamersky" in sel[0]["locator"]
    warned = bool(res.get("authority_warnings"))
    ver_err = status == "pass" and (top1_um or sel_um or (bool(um) and not warned))
    if tier == "strict_pass":
        ok = status == "pass" and sel_gold
        why = f"status={status}, selected_gold={sel_gold}, direct_recall={direct}"
        correct = ok
        wrong = status == "pass" and not sel_gold
        missed = direct and status != "pass"
    elif tier == "gold_in_topk":
        ok = direct
        why = f"status={status}, gold_in_top{len(hits)}={ok}"
        correct = status == "pass" and sel_gold
        wrong = status == "pass" and bool(sel) and not sel_gold
        missed = direct and status != "pass"
    elif tier == "refuse":
        ok = status in ("miss", "inconclusive")
        why = f"status={status}（pass 即失败：缺证据不许冒充事实）"
        correct = ok
        wrong = status == "pass"
        missed = False
    elif tier == "version_guard":
        ok = (not (status == "pass" and (top1_um or sel_um))) and (not um or warned)
        why = (f"status={status}, um_hits={len(um)}, top1_um={top1_um}, "
               f"sel_um={sel_um}, warned={warned}")
        correct = ok and status == "pass"
        wrong = status == "pass" and (top1_um or sel_um)
        missed = False
    else:
        raise ValueError(tier)
    return {"id": q["id"], "tier": tier, "ok": bool(ok), "why": why,
            "status": status, "n_hits": len(hits),
            "top1": hits[0]["locator"] if hits else None,
            "direct_recall": bool(direct), "equivalent_recall": None,
            "correct_evidence": bool(correct), "wrong_evidence": bool(wrong),
            "missed_answer": bool(missed), "citation_valid": bool(cit),
            "version_condition_error": bool(ver_err),
            "selected_locator": sel[0]["locator"] if sel else None}


def summarize_v2(grades):
    base = summarize(grades)
    split = {}
    for k in ("direct_recall", "correct_evidence", "wrong_evidence",
              "missed_answer", "citation_valid", "version_condition_error"):
        split[k] = sum(int(g.get(k, False)) for g in grades)
    split["equivalent_recall"] = "reserved_phase4"
    base["split_table"] = split
    base["wrong_evidence_ids"] = [g["id"] for g in grades if g.get("wrong_evidence")]
    base["missed_answer_ids"] = [g["id"] for g in grades if g.get("missed_answer")]
    return base
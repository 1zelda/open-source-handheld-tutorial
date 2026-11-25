# -*- coding: utf-8 -*-
"""选题卡落盘：五队列MD+全量JSON+运行记录，原子写（tmp+replace）。"""
import json
import os
from pathlib import Path

MODDIR = Path(__file__).resolve().parent
OUT_ROOT = MODDIR / "产出"
QUEUES = ["今日优先", "潜力待验证", "长期选题", "系列跟踪", "低优先归档"]


def _atomic_write(p, text):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)


def render_card_md(c):
    lines = [f"### {c['core_hook']}",
             f"- event_id: `{c['event_id']}` ｜ 受众: {c['profile_id']}",
             f"- 关注等级: **{c['attention']}** ｜ 证据状态: **{c['evidence_status']}** ｜ 队列: {c['queue']}",
             f"- 来源: {', '.join(c['sources'])}（独立来源{c['source_count']}个/条目{c['item_count']}条；{c['evidence_note']}）",
             f"- 首见: {c['first_seen'] or '未知'} ｜ pub: {c['pub_latest'] or '未知'}",
             f"- {c['title_only_note']}；{c['core_hook_note']}"]
    if c.get("body_snippet"):
        lines.append(f"- 正文片段（{c.get('body_locator')}）:")
        lines.append(f"    > {c['body_snippet'][:240]}")
    lines.append("- 八维分解:")
    for name, d in c["dims"].items():
        lines.append(f"  - {name}: {d['level']} —— {d['reason']}")
    if c.get("series_timeline"):
        lines.append(f"- 系列时间线（{len(c.get('series_members', []))}个成员，最近{len(c['series_timeline'])}条）:")
        for it in c["series_timeline"]:
            lines.append(f"  - {it['date'] or '未知'} ｜ {it['title']} ｜ `{it['event_id']}`")
    kb = c.get("kb") or {}
    sel = kb.get("selected_evidence") or []
    if kb.get("status") == "pass" and kb.get("hits"):
        if sel:
            lines.append("- KB出证（放行依据块，只有这些算证据）:")
            for h in sel:
                lines.append(f"  - [{h.get('authority')}/{h.get('status')}] {h.get('locator')}")
                lines.append(f"    > {h.get('snippet', '')[:160]}")
            sel_locs = {h.get("locator") for h in sel}
            rest = [h for h in kb["hits"] if h.get("locator") not in sel_locs]
            if rest:
                lines.append("- KB相关命中（非出证，供人工复核）:")
                for h in rest:
                    lines.append(f"  - [{h.get('authority')}/{h.get('status')}] {h.get('locator')}")
        else:
            # 旧结果/mock 无放行依据块记录：整组降为相关命中，不冒充证据
            lines.append("- KB相关命中（无放行依据块记录，不得当证据；供人工复核）:")
            for h in kb["hits"]:
                lines.append(f"  - [{h.get('authority')}/{h.get('status')}] {h.get('locator')}")
    elif kb.get("status") == "mined" and kb.get("hits"):
        lines.append("- KB挖题权威块（来源级已读证，未经问句对照，非出证）:")
        for h in kb["hits"]:
            lines.append(f"  - [{h.get('authority')}/{h.get('status')}] {h.get('locator')}")
            lines.append(f"    > {h.get('snippet', '')[:160]}")
    else:
        lines.append(f"- KB对照: {kb.get('status', '未执行')}"
                     + (f" —— {kb['reason']}" if kb.get("reason") else "")
                     + "（命中块留在JSON供人工复核，不上卡冒充证据）")
    if kb.get("retrieval_note"):
        lines.append(f"- 检索路径: {kb.get('retrieval')}（{kb['retrieval_note']}）")
    if c.get("evidence_scope"):
        lines.append(f"- 证据口径: {c['evidence_scope']}")
    if c.get("evidence_detail"):
        lines.append(f"- 证据备注: {c['evidence_detail']}")
    lines.append(f"- 必须交代: {c['must_mention']}")
    if c["urls"]:
        lines.append(f"- 链接: {c['urls'][0]}")
    lines.append(f"- 判断: {c['judged_at']} ｜ {c['rule_version']}")
    return "\n".join(lines)


def write_cards(cards, runinfo, outdir=None):
    d = Path(outdir) if outdir else OUT_ROOT / runinfo["date"]
    written = []
    _atomic_write(d / "选题卡.json", json.dumps(cards, ensure_ascii=False, indent=1))
    written.append(d / "选题卡.json")
    counts = {}
    for q in QUEUES:
        subset = [c for c in cards if c["queue"] == q]
        counts[q] = len(subset)
        body = [f"# {q}（{len(subset)} 条）", "",
                f"> 规则版本 {runinfo['rule_version']}；仅标题判断，语义槽位未接线。", ""]
        body += [render_card_md(c) + "\n" for c in subset]
        _atomic_write(d / f"{q}.md", "\n".join(body))
        written.append(d / f"{q}.md")
    runinfo = {**runinfo, "queue_counts": counts, "cards_total": len(cards)}
    _atomic_write(d / "运行记录.json", json.dumps(runinfo, ensure_ascii=False, indent=1))
    written.append(d / "运行记录.json")
    return written, counts
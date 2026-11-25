# -*- coding: utf-8 -*-
"""入口A 新闻筛选 生产入口：完整台账→事件→窗口→KB对照→分层→五队列选题卡。
P2a 零LLM三件接线：热度时序快照(每轮追加+需求信号)、入口B挖题(--entry-b)、
定向正文采集(--collect-body N)。只读台账与共享KB文件；产出全落本层目录。
语义槽位仍未接线，运行记录点名，不静默跳过。
用法：py -3 跑一轮.py [--kb bm25|hybrid|off] [--limit 40] [--entry-b] [--collect-body N]
"""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import 台账读取
import 事件归并
import 知识对照
import 关注分层
import 系列归并
import 选题卡
import 反馈台账
import 热度时序
import 入口B挖题
import 正文采集
import 需求回流

MODDIR = Path(__file__).resolve().parent
UNWIRED = ["语义分析槽位（拆主次/找角度/反差确认，须用户批准外部模型）",
           "入口B子槽：差异/冲突的语义判定、观众问题挖题",
           "正文子槽：语义拆主次/找角度（当前只做动词级精修）",
           "发布效果回流（原P3自家后台performances；B站需求探针回流已接线--bili-demand）",
           "B站回流子槽：扩词表自动取大盘候选词已接线(§11.11,--bili-demand)；角度词最终选择/语义消歧须人工；候选词实测+card→keyword全自动闭环须批准联网探针run"]
ATT_RANK = {"高": 2, "中": 1, "低": 0}
TIME_RANK = {"高": 2, "中": 1, "未知": 0, "低": -1}


def run(kb_mode="bm25", limit=40, days=14, outdir=None, profile_id=None, ledger_path=None,
        entry_b=False, collect_body=0, snapshot=True, bili_demand=False, bili_probe=None):
    today = datetime.now(timezone.utc)
    rows = 台账读取.read_ledger(ledger_path)
    sha = 台账读取.ledger_sha(ledger_path)
    events = 事件归并.merge_events(rows)
    cutoff = today - timedelta(days=days)

    def in_window(ev):
        for s in (ev["first_seen"], ev["pub_latest"]):
            try:
                d = datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if d >= cutoff:
                    return True
            except (ValueError, TypeError):
                continue
        return False

    candidates = [ev for ev in events if in_window(ev)]
    profiles = 关注分层.load_profiles()
    profile = next((p for p in profiles if p["id"] == profile_id), profiles[0])
    adopted = 反馈台账.adopted_titles()
    rejected = 反馈台账.rejected_decisions()  # §3.1 编辑拒绝→制作动作轴降队（仅editorial_judgment）

    # 热度时序：追加本轮观测，再按历史算需求信号（<2次恒未知）
    snap_info, demand_map = None, {}
    if snapshot:
        snap_info = 热度时序.record(candidates, ts=today.strftime("%Y-%m-%dT%H:%M:%SZ"))
        for ev in candidates:
            demand_map[ev["event_id"]] = 热度时序.demand_signal(ev, 热度时序.history(ev["event_id"]))

    # B站需求回流（--bili-demand）：只读探针结果，ip_name→实测词映射，可靠档优先于热度时序。
    # demand_override 仅信息维，不进关注/队列（§3）。不可靠/未映射显式退回热度时序。
    bili_info = None
    probe_map = None
    if bili_demand:
        probe_map = 需求回流.load_probe(bili_probe)
        demand_map, bili_info = 需求回流.build_demand_map(candidates, probe_map, demand_map)

    pre = [关注分层.score_event(ev, profile, None, today, adopted, rejected=rejected) for ev in candidates]
    order = sorted(range(len(candidates)),
                   key=lambda i: (-ATT_RANK[pre[i]["attention"]],
                                  -TIME_RANK[pre[i]["dims"]["时机与供给"]["level"]],
                                  -candidates[i]["source_count"]))
    ordered = [candidates[i] for i in order]
    kb_map, kb_info = 知识对照.crosscheck(ordered, mode=kb_mode, limit=limit)
    cards = [关注分层.score_event(ev, profile, kb_map.get(ev["event_id"]), today, adopted,
                                  demand_override=demand_map.get(ev["event_id"]), rejected=rejected)
             for ev in ordered]
    cards, series_count = 系列归并.fold(cards)

    # 定向正文采集：top N 卡取正文后按 body 重算（关注/队列一致重derive）
    body_info = None
    if collect_body > 0:
        targets = 正文采集.select_targets(cards, collect_body)
        target_ids = {c["event_id"] for c in targets}
        ev_by_id = {ev["event_id"]: ev for ev in ordered}
        ok = empty = err = 0
        for i, c in enumerate(cards):
            if c["event_id"] not in target_ids:
                continue
            ev = ev_by_id.get(c["event_id"])
            if not ev or not ev["urls"]:
                continue
            body = 正文采集.fetch(ev["urls"][0])
            cards[i] = 关注分层.score_event(ev, profile, kb_map.get(ev["event_id"]), today, adopted,
                                            demand_override=demand_map.get(ev["event_id"]), body=body,
                                            rejected=rejected)
            if body.get("status") == "ok":
                ok += 1
            elif body.get("status") == "empty":
                empty += 1
            else:
                err += 1
        body_info = {"attempted": len(targets), "ok": ok, "empty": empty, "error": err,
                     "snippet_max": 正文采集.SNIPPET_MAX}

    # 入口B：KB主动挖题（无时效长期选题，entry=B），与新闻标题/已采纳去重
    b_info = None
    if entry_b:
        news_titles = {事件归并.norm_title(t) for ev in candidates for t in ev["titles"]}
        b_cards, b_info = 入口B挖题.mine(profile, news_titles=news_titles, adopted=adopted, today=today,
                                         probe_map=probe_map)
        cards = cards + b_cards

    # 扩词表（card→keyword 零LLM prep，§11.11）：surface 高/中关注未探针IP→draft候选词。
    # 只读reporting，不改demand/queue，不联网；实测须另批探针run。
    exp_list, exp_info = (None, None)
    if bili_demand:
        exp_list, exp_info = 需求回流.build_expansion_list(cards, probe_map)

    # 编辑拒绝回流统计（§3.1，从最终卡现查，不写死）
    rej_cards = [c for c in cards if c.get("editorial_rejected")]
    rej_series_full = [c for c in rej_cards if str(c.get("event_id", "")).startswith("series:")]
    rej_series_partial = [c for c in cards if c.get("series_rejected_count")]
    fb_rejection = {
        "rejected_decisions": len(rejected),
        "cards_demoted": len(rej_cards),
        "direct_demoted": len(rej_cards) - len(rej_series_full),
        "series_fully_rejected": len(rej_series_full),
        "series_partial_flagged": len(rej_series_partial),
        "axis": "拒绝只改制作动作轴(queue→低优先归档)，关注/证据/八维/需求不动；仅editorial_judgment，没时间永不降",
    }

    demand_wired = sum(1 for d in demand_map.values() if d["level"] != "未知")
    runinfo = {
        "date": today.strftime("%Y-%m-%d"),
        "generated_at": today.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ledger_sha256": sha, "ledger_rows": len(rows),
        "events_total": len(events), "candidates_in_window": len(candidates),
        "window_days": days, "kb_limit": limit,
        "kb": kb_info, "profile_id": profile["id"],
        "profile_basis": profile["basis"],
        "rule_version": 关注分层.RULE_VERSION,
        "ip_table_version": 关注分层.load_ip_table()["version"],
        "series_count": series_count,
        "snapshot": snap_info, "demand_wired": demand_wired,
        "entry_b": b_info, "body": body_info, "bili_demand": bili_info, "bili_expansion": exp_info,
        "feedback_rejection": fb_rejection,
        "unwired_slots": UNWIRED,
        "entry": "A 新闻筛选" + ("+B KB挖题" if entry_b else "（B未跑，--entry-b开启）"),
    }
    written, counts = 选题卡.write_cards(cards, runinfo, outdir)
    if exp_list is not None:
        d = written[0].parent
        选题卡._atomic_write(d / "扩词表候选.json", json.dumps(exp_list, ensure_ascii=False, indent=1))
        选题卡._atomic_write(d / "扩词表候选.md", 需求回流.render_expansion_md(exp_list, exp_info))
        written += [d / "扩词表候选.json", d / "扩词表候选.md"]
    print(f"台账 {len(rows)} 行(sha {sha[:12]}…) → 事件 {len(events)} → 窗口{days}天候选 {len(candidates)}")
    print(f"KB模式 {kb_info['mode']}" + (f"（{kb_info['downgrade']}）" if kb_info.get("downgrade") else "")
          + f"，查询 {kb_info.get('queried', 0)} 条")
    if kb_info.get("routing") == "auto_multi":
        print(f"KB自动路由: 多域问题 {kb_info.get('multi_domain_queries', 0)} 条；"
              f"查询日志 {kb_info.get('query_log')}（本轮留痕 {kb_info.get('logged_queries', 0)} 条）")
    if snap_info:
        print(f"热度快照: {snap_info['ts']} 追加 {snap_info['recorded']} 条观测；需求信号非未知 {demand_wired} 条（<2次观测恒未知）")
    if bili_info:
        print(f"B站需求回流: 探针词{bili_info['probe_words']} 映射卡{bili_info['mapped_cards']}"
              f"（可靠提权{bili_info['reliable_override']}/不可靠退回{bili_info['contaminated_fallback']}）"
              f" 未映射退回{bili_info['unmapped_fallback']}；{bili_info['precedence']}")
    if exp_info:
        print(f"扩词表候选: {exp_info['candidate_ips']} 个高/中关注未探针IP"
              f"（高关注{exp_info['high_attention_ips']}/覆盖卡{exp_info['cards_covered']}）；"
              f"draft候选词须人工核+批准联网才测，不改demand/queue")
    if fb_rejection["rejected_decisions"]:
        print(f"编辑拒绝回流: {fb_rejection['rejected_decisions']}条拒绝决策→降队{fb_rejection['cards_demoted']}张"
              f"(直接{fb_rejection['direct_demoted']}/系列全拒{fb_rejection['series_fully_rejected']})，"
              f"部分拒系列标志{fb_rejection['series_partial_flagged']}张；只改制作动作轴，关注/证据/需求不动")
    for q, n in counts.items():
        print(f"  {q}: {n}")
    print(f"系列归并: {series_count} 张系列跟踪卡（同项目≥2常规事件合并，重大事件不折叠）")
    if b_info:
        print(f"入口B挖题: {b_info['mined']} 张（权威块{b_info['authoritative_chunks']}/组{b_info['groups']}，跳过{b_info['skipped']}）")
        if b_info.get("bili_probe_on"):
            print(f"  入口B回流: {b_info['bili_demand_wired']} 张B挖卡带实测B站需求档（仅信息维，queue恒长期选题）")
    if body_info:
        print(f"正文采集: 试{body_info['attempted']} 成{body_info['ok']} 空{body_info['empty']} 败{body_info['error']}（snippet≤{body_info['snippet_max']}字；空=HTTP200但JS壳/反爬无正文）")
    print("产出:")
    for p in written:
        print(f"  {p}")
    print("未接线槽位（不静默跳过）:")
    for s in UNWIRED:
        print(f"  - {s}")
    return cards, runinfo, written


def main():
    ap = argparse.ArgumentParser(description="选题决策层 入口A(+B/正文/热度)")
    ap.add_argument("--kb", choices=["bm25", "hybrid", "off"], default="bm25")
    ap.add_argument("--limit", type=int, default=40, help="本轮KB对照查询上限")
    ap.add_argument("--days", type=int, default=14, help="候选窗口天数")
    ap.add_argument("--out", default=None, help="产出目录（默认 产出/<日期>）")
    ap.add_argument("--profile", default=None)
    ap.add_argument("--ledger", default=None, help="台账路径覆盖（试跑合成台账用）")
    ap.add_argument("--entry-b", action="store_true", help="开启入口B KB主动挖题")
    ap.add_argument("--collect-body", type=int, default=0, help="定向采正文的top卡数（0=不采）")
    ap.add_argument("--no-snapshot", action="store_true", help="不追加热度观测（默认追加）")
    ap.add_argument("--bili-demand", action="store_true",
                    help="开启B站需求回流（只读探针结果，ip_name→实测词映射，可靠档优先于热度时序）")
    ap.add_argument("--bili-probe", default=None, help="探针结果.json路径覆盖（默认 B站热度实验/探针结果.json）")
    a = ap.parse_args()
    run(a.kb, a.limit, a.days, a.out, a.profile, a.ledger,
        entry_b=a.entry_b, collect_body=a.collect_body, snapshot=not a.no_snapshot,
        bili_demand=a.bili_demand, bili_probe=a.bili_probe)


if __name__ == "__main__":
    main()
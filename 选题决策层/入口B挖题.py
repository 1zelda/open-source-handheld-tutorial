# -*- coding: utf-8 -*-
"""入口B 知识库主动挖题（说明书§10.1）：扫KB权威verified块，按game/revision分组，
受众匹配+知名度过滤，生成无时效长期选题挖题卡(entry=B)。同game≥2 revision给版本差异
对比（结构信号，非语义）。与新闻标题/已采纳去重。差异/冲突语义判定、观众问题挖题仍未接线。
只读KB快照，产出落本层。"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import 关注分层
import 知识对照
import 需求回流
from 事件归并 import norm_title

MODDIR = Path(__file__).resolve().parent
# 编辑假设映射：game_id/platform → 显示名（KB索引只带id，不带中文名）
GAME_NAMES = {"nekketsu_soccer2": "热血足球", "nekketsu_soccer_mobile": "热血足球手游",
              "kof98": "拳皇98", "multi": "街机/多游戏"}
PLATFORM_NAMES = {"NES": "FC/NES", "ARCADE": "街机", "MOBILE": "手游", "ANY": "跨平台"}


def mine(profile, news_titles=frozenset(), adopted=frozenset(), today=None, index_path=None,
         probe_map=None):
    today = today or datetime.now(timezone.utc)
    ip = Path(index_path) if index_path else 知识对照.SNAP / "index.json"
    d = json.loads(ip.read_text(encoding="utf-8"))
    chunks = d.get("chunks", [])
    auth_all = [c for c in chunks
                if c.get("authority") == "authoritative" and c.get("status") == "verified_read"]
    # 域过滤：只挖锚定游戏内容域的块；meta域(project_docs/tooling内部文档)排除，与域锚点闸门同源。
    auth = [c for c in auth_all if 知识对照.content_block(c.get("game_id"), c.get("revision"))]
    meta_excluded = len(auth_all) - len(auth)
    groups = {}
    for c in auth:
        groups.setdefault((c.get("game_id"), c.get("revision")), []).append(c)
    revs = {}
    for (g, r) in groups:
        revs.setdefault(g, set()).add(r)

    interests = [w.lower() for w in profile["interests"]]
    cards, skipped = [], 0
    for (g, r), cs in sorted(groups.items()):
        gname = GAME_NAMES.get(g, g or "未知游戏")
        plat = PLATFORM_NAMES.get(cs[0].get("platform"), cs[0].get("platform") or "")
        ets = sorted({e for c in cs for e in (c.get("element_types") or [])})
        headings = [c.get("heading") for c in cs if c.get("heading")]
        sample = " ".join((c.get("text") or "")[:200] for c in cs[:3])
        text = f"{gname} {plat} {' '.join(ets)} {' '.join(headings)} {sample}".lower()
        hits = [w for w in interests if w in text]
        rec_level, rec_reason, rec_ev, major, ip_name = 关注分层.recognition(text)
        if not hits and rec_level == "低":
            skipped += 1
            continue
        core = f"{gname}[{r}] {plat} {'/'.join(ets[:4]) or '机制'} 已验证攻略（KB挖题，无时效）"
        nrev = len(revs.get(g, set()))
        if nrev >= 2:
            contrast = 关注分层._dim("中", f"同game有{nrev}个revision权威块——版本结构差异，非语义判定", [])
            core = f"{gname} 版本对照选题（{nrev}个revision）：{core}"
        else:
            contrast = 关注分层._dim("未知", "单revision，无版本差异结构信号；语义反差未接线", [])
        nt = norm_title(core)
        if nt in news_titles or nt in adopted:
            skipped += 1
            continue
        hits_kb = [{"locator": f"{c.get('path')}#L{c.get('line_start')}",
                    "snippet": (c.get("text") or "")[:240],
                    "authority": c.get("authority"), "status": c.get("status")}
                   for c in cs[:3]]
        match = 关注分层._dim("高" if len(hits) >= 2 else "中",
                              f"KB块命中受众词{hits[:6]}（KB挖题，非新闻）", [])
        recog = 关注分层._dim(rec_level, rec_reason + "（编辑假设表）", rec_ev)
        express = 关注分层._dim("高", "KB权威verified块（来源级已读证），可引证演示；未做问句级可答性对照",
                                [h["locator"] for h in hits_kb])
        # 需求信号：--bili-demand 时接 B站实测档（ip_name 已由 recognition 算出）；默认关仍未知。
        # 仅信息维，不改 attention/queue（queue 恒长期选题）。未映射/未探针/不可靠显式退回未知。
        kb_ts = 关注分层._dim("未知", "KB挖题无热度时序，不编造需求", [])
        demand = 需求回流.demand_for_ip(ip_name, probe_map, kb_ts) if probe_map is not None else kb_ts
        dims = {"受众匹配": match,
                "实际影响": 关注分层._dim("未知", "KB挖题无新闻影响动词；已验证机制本身即看点", []),
                "信息增量": 关注分层._dim("中", "KB已验证存量知识，无时效；是否讲过查反馈台账", []),
                "反差与故事性": contrast,
                "需求信号": demand,
                "表达与素材": express,
                "时机与供给": 关注分层._dim("未知", "无时效（KB存量知识，非新闻）", []),
                "知名度与重大性": recog}
        attention = "中" if (match["level"] in ("高", "中") and rec_level in ("高", "中")) else "低"
        cards.append({
            "event_id": "kbmine:" + hashlib.sha1(f"{g}|{r}".encode("utf-8")).hexdigest()[:12],
            "entry": "B", "source": "kb_mine",
            "titles": [core], "urls": [], "sources": [cs[0].get("source_id") or "kb"],
            "source_count": 1, "item_count": len(cs),
            "evidence_note": "KB权威verified块；挖题非新闻，无转载计数",
            "first_seen": "", "pub_latest": "",
            "profile_id": profile["id"], "attention": attention,
            "major_event": False, "ip_name": ip_name, "dims": dims,
            "evidence_status": "库内权威块（挖题）",
            "evidence_detail": f"game={g} revision={r} 权威块{len(cs)}个",
            "evidence_scope": ("挖题=来源级权威verified块盘点，未做问句级可答性对照，"
                               "不是pass、不得当'已证实对照'出证；制作前须按问句走KB对照"),
            # 挖题不硬编码pass（阶段1）：没有问句就没有可答性判定。
            # status=mined 与检索 pass 显式区分；selected_evidence 恒空。
            "kb": {"status": "mined", "mode": "bm25", "retrieval": "kb_mine",
                   "reason": "权威verified块盘点（来源级），未做问句级可答性对照",
                   "selected_evidence": [], "hits": hits_kb},
            "queue": "长期选题",
            "core_hook": core,
            "core_hook_note": "KB挖题核心看点=已验证机制/攻略本身；语义拆主次/找角度未接线",
            "must_mention": "版本/适用条件须人工核（KB块带revision身份，同名异版不可混喂）",
            "title_only": False,
            "title_only_note": "KB挖题（非新闻正文，有权威块片段）；语义层未接线",
            "rule_version": 关注分层.RULE_VERSION,
            "judged_at": today.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    info = {"mined": len(cards), "skipped": skipped, "authoritative_chunks": len(auth_all),
            "meta_blocks_excluded": meta_excluded, "content_chunks": len(auth),
            "groups": len(groups), "index_path": str(ip),
            "bili_demand_wired": sum(1 for c in cards
                                     if "B站已有视频热度代理" in c["dims"]["需求信号"]["reason"]),
            "bili_probe_on": probe_map is not None,
            "unwired_subslots": ["差异/冲突的语义判定", "观众问题挖题"]}
    return cards, info
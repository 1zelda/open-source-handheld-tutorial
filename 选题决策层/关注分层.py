# -*- coding: utf-8 -*-
"""规则版关注分层（说明书§3）：八维各给 高/中/低/未知+理由+依据，不加权求和。
需求信号无时序恒=未知；反差只给「中(假设)」；正文未采集必标「仅标题判断」。
知名度与重大性：知名IP/重大事件→高，小众IP/知名项目→中，无→低；关注高须知名度≥中。"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

MODDIR = Path(__file__).resolve().parent
PROFILES = MODDIR / "受众档案.json"
IP_TABLE = MODDIR / "知名IP表.json"
RULE_VERSION = "rules-2026-11-19-v2"

IMPACT_WORDS = ["发布", "上线", "发售", "官宣", "公布", "公开", "发表", "宣布", "确认",
                "破解", "移植", "重制", "复刻", "停运", "下架", "泄露", "修复", "夺冠",
                "冠军", "推出", "开源", "免费", "登陆", "release", "launch", "exploit",
                "port", "remake", "support", "announces", "reveals", "unveils", "confirmed"]
MAINT_WORDS = ["commit", "typo", "bump", "merge", "docs", "readme", "cleanup",
               "refactor", "提交", "格式", "拼写", "翻译", "add game + game files"]
STORY_WORDS = ["首次", "终于", "隐藏", "彩蛋", "争议", "翻车", "逆袭", "对比",
               "冷知识", "秘密", "真相", "first", "hidden", "secret"]
OFFICIAL_KINDS = {"github_atom"}


def load_profiles(path=None):
    return json.loads(Path(path or PROFILES).read_text(encoding="utf-8"))["profiles"]


_IP_CACHE = None


def load_ip_table(path=None):
    global _IP_CACHE
    if path is None and _IP_CACHE is not None:
        return _IP_CACHE
    t = json.loads(Path(path or IP_TABLE).read_text(encoding="utf-8"))
    if path is None:
        _IP_CACHE = t
    return t


def _has_cjk(s):
    return any("一" <= c <= "鿿" for c in s)


def _alias_hit(alias, text_lower):
    a = alias.strip().lower()
    if not a:
        return False
    if _has_cjk(a):
        return a in text_lower
    return re.search(r"(?<![a-z0-9])" + re.escape(a) + r"(?![a-z0-9])", text_lower) is not None


def recognition(text_lower, table=None):
    """返回 (level, reason, evidence, major_event, ip_name)。
    高=知名IP或重大事件；中=小众IP或知名项目；低=无。拉丁词边界、中文子串。"""
    t = table or load_ip_table()
    mass = niche = proj = major = None
    for grp in t["mass"]:
        if any(_alias_hit(a, text_lower) for a in grp):
            mass = grp[0]
            break
    for grp in t["niche"]:
        if any(_alias_hit(a, text_lower) for a in grp):
            niche = grp[0]
            break
    for p in t["projects"]:
        if _alias_hit(p, text_lower):
            proj = p
            break
    if proj is None:
        for p in t.get("platforms", []):
            if _alias_hit(p, text_lower):
                proj = p
                break
    for w in t["major_events"]:
        if _alias_hit(w, text_lower):
            major = w
            break
    parts = []
    if mass:
        parts.append(f"知名IP「{mass}」")
    if major:
        parts.append(f"重大事件词「{major}」")
    if niche:
        parts.append(f"小众IP「{niche}」")
    if proj:
        parts.append(f"知名项目「{proj}」")
    if mass or major:
        level = "高"
    elif niche or proj:
        level = "中"
    else:
        level = "低"
    reason = ("；".join(parts) if parts else "标题未含知名IP/项目/重大事件词（编辑假设表，非观众实测）")
    ip_name = mass or niche or proj
    return level, reason, parts, bool(major), ip_name


def _days_since(datestr, today):
    try:
        d = datetime.strptime(datestr[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return (today - d).days
    except (ValueError, TypeError):
        return None


def _dim(level, reason, evidence=None):
    return {"level": level, "reason": reason, "evidence": evidence or []}


def score_event(ev, profile, kb_info, today, adopted_titles=frozenset(), demand_override=None, body=None,
                rejected=None):
    from 事件归并 import norm_title
    text = (" ".join(ev["titles"]) + " " + " ".join(ev["focus"])).lower()
    body_ok = bool(body and body.get("status") == "ok" and (body.get("main_text") or body.get("snippet")))
    body_text = ((body.get("main_text") or body.get("snippet") or "").lower()) if body_ok else ""
    body_loc = [body["locator"]] if body_ok and body.get("locator") else []
    hits = [w for w in profile["interests"] if w.lower() in text]
    focus_hit = sorted(set(ev["focus"]) & set(profile.get("focus_domains") or []))
    urls = ev["urls"][:3]

    if focus_hit or len(hits) >= 2:
        match = _dim("高", f"受众词命中{hits[:6]} 聚焦域命中{focus_hit}", urls)
    elif len(hits) == 1:
        match = _dim("中", f"受众词仅命中{hits}", urls)
    else:
        match = _dim("低", "标题/聚焦标签无该受众兴趣词（词命中只是假设，非观众实测）", urls)

    if body_ok:
        b_imp = [w for w in IMPACT_WORDS if w.lower() in body_text]
        b_maint = [w for w in MAINT_WORDS if w.lower() in body_text]
        if b_imp:
            impact = _dim("高", f"正文影响动词命中{b_imp[:5]}（已采正文）", body_loc)
        elif b_maint:
            impact = _dim("低", f"正文维护动词命中{b_maint[:5]}，无影响动词（已采正文）", body_loc)
        else:
            impact = _dim("未知", "正文未含影响/维护动词（已采正文）", body_loc)
    else:
        imp = [w for w in IMPACT_WORDS if w.lower() in text]
        maint = [w for w in MAINT_WORDS if w.lower() in text]
        if imp:
            impact = _dim("高", f"影响动词命中{imp[:5]}（仅标题，正文未采集）", urls)
        elif maint:
            impact = _dim("低", f"维护性动词命中{maint[:5]}，无影响动词", urls)
        else:
            impact = _dim("未知", "标题未含影响/维护动词，待正文采集", urls)

    nt = norm_title(ev["titles"][0] if ev["titles"] else "")
    age = _days_since(ev["pub_latest"], today)
    if nt and nt in adopted_titles:
        novelty = _dim("低", "反馈台账显示已采纳讲过", [])
    elif age is not None and age > 30:
        novelty = _dim("低", f"pub距今{age}天，旧闻（我库第一次见≠世界首次）", urls)
    else:
        novelty = _dim("高" if age is not None and age <= 14 else "中",
                       f"事件首见{ev['first_seen'] or '未知'}，pub距今{age if age is not None else '未知'}天", urls)

    story_src = body_text if body_ok else text
    story = [w for w in STORY_WORDS if w.lower() in story_src]
    story_tag = "正文" if body_ok else "标题"
    contrast = (_dim("中", f"{story_tag}反差标记词{story[:4]}——假设，语义槽位未接线，须人工/模型确认",
                     body_loc if body_ok else urls)
                if story else _dim("未知", f"规则看不出反差（{story_tag}），语义槽位未接线", []))

    if demand_override is not None:
        demand = demand_override
    else:
        demand_reason = "无热度时序数据，不编造需求信号"
        if ev["flag_hot_any"]:
            demand_reason += "；旧资源HOT规则命中（仅参考，非受众热度）"
        demand = _dim("未知", demand_reason, [])

    kb_status = (kb_info or {}).get("status")
    official = bool(set(ev["kinds"]) & OFFICIAL_KINDS) and any(
        "releases/tag/" in u for u in ev["urls"])
    if kb_status == "pass":
        express = _dim("高", "KB问句级可答对照pass（有放行依据块，可引证演示；非标题说法逐事实核实）",
                       [h["locator"] for h in kb_info.get("hits", []) if h.get("locator")])
    elif official:
        express = _dim("中", "官方release件，可演示但需真机/实测验证", urls)
    else:
        express = _dim("未知", "论坛/提交类，素材可得性未知", urls)

    if age is None:
        # 无pub用first_seen代理（显式注明）；两者皆无才未知。无日期≠长尾冷知识
        age = _days_since(ev["first_seen"], today)
        timing_src = "first_seen代理"
    else:
        timing_src = "pub"
    if age is None:
        timing = _dim("未知", "无pub也无first_seen", [])
    elif age <= 7:
        timing = _dim("高", f"{timing_src}距今{age}天", [])
    elif age <= 30:
        timing = _dim("中", f"{timing_src}距今{age}天", [])
    else:
        timing = _dim("低", f"{timing_src}距今{age}天，时效已过", [])

    rec_level, rec_reason, rec_ev, major_event, ip_name = recognition(text)
    recog = _dim(rec_level, rec_reason + "（编辑假设表，仅标题）", rec_ev)

    dims = {"受众匹配": match, "实际影响": impact, "信息增量": novelty,
            "反差与故事性": contrast, "需求信号": demand, "表达与素材": express,
            "时机与供给": timing, "知名度与重大性": recog}

    if match["level"] == "低":
        attention = "低"
    elif impact["level"] == "高" and match["level"] in ("高", "中") and rec_level in ("高", "中"):
        attention = "高"  # 不知名项目常规发布不许进今日优先：关注高须知名度≥中
    elif match["level"] == "高" and (impact["level"] in ("中", "未知") or contrast["level"] == "中"):
        attention = "中"
    elif match["level"] == "中" and contrast["level"] == "中":
        attention = "中"  # 部分匹配+反差假设：冷知识不许因词命中少被埋
    else:
        attention = "低"

    if kb_status == "pass":
        evidence = "库内已证实对照"
    elif official:
        evidence = "官方发布件"
    elif kb_status in ("miss", "inconclusive", "not_built"):
        evidence = "仅说法（库内无对照）"
    elif kb_status in ("off", "未执行", "not_queried", None):
        evidence = "库内未对照"
    else:
        evidence = "待核实"
    evidence_detail = (kb_info or {}).get("reason") or (kb_info or {}).get("retrieval_note") or ""
    # pass 口径注记（阶段1）：标签与队列机制不动（HARD/今日优先依赖现值），
    # 但必须显式说清 pass 的证明范围——问句级可答对照 ≠ 标题说法逐事实证实。
    evidence_scope = None
    if kb_status == "pass":
        evidence_scope = ("KB pass=问句窗口内有权威可答块（问句级对照），非标题说法逐事实证实；"
                          "出证只认 selected_evidence，其余命中是相关资料")

    hard = evidence in ("官方发布件", "库内已证实对照")
    if attention == "低":
        queue = "低优先归档"
    elif attention == "高" and hard and timing["level"] == "高":
        queue = "今日优先"
    elif timing["level"] in ("低", "未知") and (
            kb_status == "pass" or contrast["level"] == "中" or match["level"] == "高"):
        queue = "长期选题"  # 冷知识不因无热度/过时效被埋
    elif attention == "高" and hard:
        queue = "潜力待验证"  # 证据硬但时间窗中档，待人工确认时机
    elif not hard:
        queue = "潜力待验证"
    else:
        queue = "低优先归档"

    # 编辑拒绝回流（§3.1）：只改制作动作轴(queue)，关注/证据/八维/需求一律不动。
    # 仅 editorial_judgment 拒绝（rejected_decisions 已滤掉 editor_capacity）；最新 wins。
    editorial_rejected = bool(rejected and ev["event_id"] in rejected)
    if editorial_rejected:
        queue = "低优先归档"

    card = {
        "event_id": ev["event_id"],
        "titles": ev["titles"],
        "urls": ev["urls"],
        "sources": ev["sources"],
        "source_count": ev["source_count"],
        "item_count": ev["item_count"],
        "evidence_note": ev["evidence_note"],
        "first_seen": ev["first_seen"],
        "pub_latest": ev["pub_latest"],
        "profile_id": profile["id"],
        "attention": attention,
        "major_event": major_event,
        "ip_name": ip_name,
        "dims": dims,
        "evidence_status": evidence,
        "evidence_detail": evidence_detail,
        "evidence_scope": evidence_scope,
        "kb": kb_info or {"status": "未执行", "hits": []},
        "queue": queue,
        "core_hook": ev["titles"][0] if ev["titles"] else "",
        "core_hook_note": "规则版核心看点=影响事实本身；拆主次/找角度的语义槽位未接线",
        "must_mention": "限制条件/适用版本槽位未接线（语义层），发布前人工补",
        "title_only": not body_ok,
        "title_only_note": ("已采正文片段（≤240字snippet+locator，不整篇搬运）" if body_ok
                            else (f"正文采集失败:{body.get('error', '无')}（仍仅标题判断）"
                                  if body else "仅标题判断（正文未采集）")),
        "body_status": ("ok" if body_ok else ("error" if body else "not_collected")),
        "body_snippet": (body.get("snippet", "")[:240] if body_ok else ""),
        "body_locator": (body.get("locator") if body_ok else None),
        "rule_version": RULE_VERSION,
        "judged_at": today.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if editorial_rejected:
        card["editorial_rejected"] = True
        card["rejection_reason"] = rejected.get(ev["event_id"], "")
    return card
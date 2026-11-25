# -*- coding: utf-8 -*-
"""持续更新系列归并（说明书§3）：同一项目窗口内≥2个常规事件→1张系列跟踪卡。
项目身份=GitHub repo名（小写）否则标题里的知名项目名；重大事件不折叠（新闻≠常规更新）；
单事件项目不折叠；不同repo不许误并。成员event_id与时间线保留供人工回溯。"""
import hashlib
import re
from datetime import datetime

import 关注分层

ATT_RANK = {"高": 2, "中": 1, "低": 0}
HARD = ("官方发布件", "库内已证实对照")
_GH = re.compile(r"github\.com/([^/]+)/([^/?#]+)", re.I)


def project_key(card, table=None):
    for u in card.get("urls", []):
        m = _GH.search(u)
        if m:
            repo = m.group(2).lower().removesuffix(".git")
            if repo:
                return "gh:" + repo
    text = " ".join(card.get("titles", [])).lower()
    t = table or 关注分层.load_ip_table()
    # 只用软件项目名作系列身份；平台/硬件名(platforms)不作key，防"PS5/Switch 2"吞并无关新闻
    for p in t["projects"]:
        if 关注分层._alias_hit(p, text):
            return "name:" + p.lower()
    return None


def _date_key(c):
    s = c.get("pub_latest") or c.get("first_seen") or ""
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return datetime.min


def _best_member(members):
    return max(members, key=lambda c: (ATT_RANK.get(c["attention"], 0),
                                       c["evidence_status"] in HARD,
                                       c.get("source_count", 0)))


def fold(cards, table=None):
    """返回 (归并后卡列表, 系列卡数)。重大事件卡与无项目身份卡原样保留。"""
    t = table or 关注分层.load_ip_table()
    groups = {}
    passthrough = []
    for c in cards:
        if c.get("major_event"):
            passthrough.append(c)  # 重大事件不折叠
            continue
        key = project_key(c, t)
        if key is None:
            passthrough.append(c)
            continue
        groups.setdefault(key, []).append(c)

    series_cards = []
    for key, members in groups.items():
        if len(members) < 2:
            passthrough.extend(members)  # 单事件不折叠
            continue
        wanted = [m for m in members if not m.get("editorial_rejected")]
        best = _best_member(wanted or members)  # 优先未被拒成员代表系列（§3.1）
        ordered = sorted(members, key=_date_key, reverse=True)
        timeline = [{"date": (m.get("pub_latest") or m.get("first_seen") or "")[:10],
                     "title": m["titles"][0] if m.get("titles") else "",
                     "event_id": m["event_id"]} for m in ordered[:10]]
        proj = key.split(":", 1)[1]
        sc = dict(best)
        sc["event_id"] = "series:" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
        sc["queue"] = "系列跟踪"
        # 编辑拒绝回流（§3.1）：全成员被拒→降整系列；部分被拒→只标志不降（拒一事件≠拒整项目）。
        rej_n = sum(1 for m in members if m.get("editorial_rejected"))
        if rej_n == len(members):
            sc["queue"] = "低优先归档"
            sc["editorial_rejected"] = True
            sc["rejection_reason"] = "系列全部成员已被编辑拒绝"
        elif rej_n:
            sc["series_rejected_count"] = rej_n
        sc["core_hook"] = f"{proj} 持续更新跟踪（{len(members)}个事件）"
        sc["core_hook_note"] = "系列卡=同项目常规更新合并；拆主次/找角度语义槽位未接线"
        sc["series_key"] = key
        sc["series_members"] = [m["event_id"] for m in ordered]
        sc["series_timeline"] = timeline
        sc["title_only_note"] = "仅标题判断（正文未采集）；系列时间线供人工回溯"
        series_cards.append(sc)

    return passthrough + series_cards, len(series_cards)
# -*- coding: utf-8 -*-
"""B站需求回流（说明书§11.8，P3 主动版，零LLM）。只读 B站热度实验/探针结果.json，
把实测「词→需求档」经编辑映射表(ip_name→实测词)接进 关注分层.score_event 的 demand_override。
**不联网、不重跑探针**。优先级：B站可靠档(高/中/低)＞热度时序(媒体覆盖代理)＞未知；
不可靠/未映射/未探针**显式退回**热度时序，不拿不可靠播放冒充需求、不拿未测冒充已测。
demand_override 仅「需求信号」信息维，**不进关注合成/队列**(§3，T31h 反证)。
探针/试跑只读，不写真实探针结果。"""
import json
from pathlib import Path

import B站热度探针
import 关注分层

MODDIR = Path(__file__).resolve().parent
PROBE_RESULTS = MODDIR / "B站热度实验" / "探针结果.json"
MAP_VERSION = "bili-map-2026-11-19-v1"
RELIABLE = ("高", "中", "低")

# ip_name(关注分层.recognition 产出的身份：mass/niche 组首别名 或 projects/platforms 原样)
# → (实测探针词, 粒度标注)。编辑映射，**只连真测过的词**；消歧/粒度选择须人工核。
# 未列入的 ip_name(多数无名项目)→未探针，显式退回热度时序/未知，不静默冒充。
IP_TO_KEYWORD = {
    "zelda": ("塞尔达传说", "大盘"),
    "kirby": ("星之卡比", "大盘"),
    "pikmin": ("皮克敏", "大盘"),
    "xenoblade": ("异度之刃", "大盘"),
    "dragon ball": ("龙珠", "大盘"),
    "stellar blade": ("剑星", "大盘·消歧(不用星刃)"),
    "sea of stars": ("Sea of Stars", "大盘·消歧(中文星之海歧义,用英文原名)"),
    "king of fighters": ("拳皇98", "细分(拳皇98版本,非整拳皇IP大盘)"),
    "热血系列": ("热血足球", "细分(热血足球,非整热血系列)"),
    "shadps4": ("shadPS4", "大盘"),
    "dolphin": ("Dolphin模拟器", "大盘"),
    "batocera": ("Batocera", "大盘"),
    "switch 2": ("Switch2 破解", "角度(破解角度,非整平台大盘)"),
    "ns2": ("Switch2 破解", "角度(破解角度,非整平台大盘)"),
}


def _dim(level, reason, evidence=None):
    return {"level": level, "reason": reason, "evidence": evidence or []}


def load_probe(path=None):
    """读探针结果.json → {keyword: rec}。**只读**；不存在/损坏返回空dict(不冒充已测)。"""
    p = Path(path or PROBE_RESULTS)
    if not p.is_file():
        return {}
    try:
        recs = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(recs, list):
        return {}
    return {r["keyword"]: r for r in recs if isinstance(r, dict) and r.get("keyword")}


def _channel_fit(rec):
    """频道适配标签：委托 B站热度探针.channel_fit 单一权威（track-aware，§11.10）。
    信息性，不改需求档/队列。怀旧供给缺口机会/新游热度消退/工具中性/跨代待核。"""
    return B站热度探针.channel_fit(rec)


def _fallback(ts_dim, note):
    """B站不可用/不可靠/未映射→退回热度时序。显式留痕，不静默。"""
    if ts_dim and ts_dim.get("level") in RELIABLE:
        return _dim(ts_dim["level"],
                    ts_dim.get("reason", "") + "；B站回流退回:" + note,
                    ts_dim.get("evidence", []))
    base = ts_dim.get("reason", "") if ts_dim else "无热度时序数据"
    return _dim("未知", base + "；B站回流:" + note + "；需求未知(不冒充)", [])


def _resolve(ip_name, probe_map, ts_dim):
    """身份→需求维。返回 (dim, status)；status∈reliable/contaminated/unmapped。
    B站可靠档优先于热度时序；不可靠(核心命中<闸门)/未映射/未探针退回热度时序。"""
    if not ip_name:
        return _fallback(ts_dim, "无知名IP/项目身份,未映射B站探针词(未探针)"), "unmapped"
    entry = IP_TO_KEYWORD.get(ip_name)
    if not entry:
        return _fallback(ts_dim, f"ip「{ip_name}」不在编辑映射表(未探针,须先扩词表)"), "unmapped"
    kw, gran = entry
    rec = probe_map.get(kw)
    if rec is None:
        return _fallback(ts_dim, f"映射词「{kw}」不在本轮探针结果(未探针)"), "unmapped"
    lvl = rec.get("demand_level")
    if lvl not in RELIABLE:
        chr_ = rec.get("core_hit_rate", 0) or 0
        return _fallback(ts_dim, f"B站词「{kw}」需求{lvl}(核心命中{chr_:.2f}不可靠/未知),不冒充"), "contaminated"
    pm = rec.get("relevant_play_median", 0) or 0
    chr_ = rec.get("core_hit_rate", 0) or 0
    eng = rec.get("engagement_median", 0) or 0
    rc = rec.get("recent_count", 0) or 0
    rpm = rec.get("recent_play_median", 0) or 0
    fit = _channel_fit(rec)
    reason = (f"B站已有视频热度代理(非本选题实测)；ip「{ip_name}」→实测词「{kw}」(粒度:{gran})；"
              f"需求{lvl}:去污染播放中位{pm:.0f}(核心命中{chr_:.2f})；"
              f"互动率{eng:.3f}·近90天{rc}条近期播放{rpm:.0f}(track:{B站热度探针.word_track(kw)}·{fit})；"
              f"优先于热度时序媒体覆盖代理；高命中≠语义相关,歧义词须人工核top3")
    evidence = [f"B站探针 {kw} @{rec.get('ts', '')}"]
    for t in (rec.get("top3") or [])[:3]:
        if t.get("bvid"):
            evidence.append(f"{t['bvid']}｜{(t.get('title') or '')[:60]}｜播放{t.get('play', 0)}")
    return _dim(lvl, reason, evidence), "reliable"


def _ip_name_of(ev):
    text = (" ".join(ev.get("titles") or []) + " " + " ".join(ev.get("focus") or [])).lower()
    return 关注分层.recognition(text)[4]


def demand_for_ip(ip_name, probe_map, ts_dim=None):
    """给定身份 ip_name→需求维。供已算出 ip_name 的链（入口B挖题）复用，避免重复 recognition。"""
    return _resolve(ip_name, probe_map, ts_dim)[0]


def demand_for_event(ev, probe_map, ts_dim=None):
    """单事件需求维(demand_override)。走 recognition 生产路径取 ip_name→映射实测词。"""
    return demand_for_ip(_ip_name_of(ev), probe_map, ts_dim)


def build_demand_map(events, probe_map, ts_map=None):
    """批量 {event_id: demand_override dim}＋info(逐格计数供 runinfo)。
    ts_map={event_id: 热度时序 dim}。每事件 recognition 只调一次。"""
    ts_map = ts_map or {}
    demand_map = {}
    reliable = contaminated = unmapped = 0
    for ev in events:
        dim, status = _resolve(_ip_name_of(ev), probe_map, ts_map.get(ev["event_id"]))
        demand_map[ev["event_id"]] = dim
        if status == "reliable":
            reliable += 1
        elif status == "contaminated":
            contaminated += 1
        else:
            unmapped += 1
    info = {
        "map_version": MAP_VERSION,
        "track_version": B站热度探针.TRACK_VERSION,
        "probe_words": len(probe_map),
        "mapped_cards": reliable + contaminated,
        "reliable_override": reliable,
        "contaminated_fallback": contaminated,
        "unmapped_fallback": unmapped,
        "precedence": "B站可靠(高/中/低)>热度时序>未知；不可靠/未映射/未探针退回热度时序",
        "informational_only": "demand_override仅信息维,不进关注合成/队列(§3,T31h反证)",
        "count_basis": "候选事件级(系列归并前)；卡片级B站reason数≤此(系列卡取最强成员维,非best映射成员折叠不单独成卡)",
    }
    return demand_map, info


def _candidate_word(ip_name):
    """零LLM自动取词(§11.2/§11.11)：mass/niche组首个中文别名作大盘候选；项目/平台名原样。
    返回 (word, kind, note)。draft候选，须人工消歧/粒度/角度核＋批准联网探针后才测。"""
    t = 关注分层.load_ip_table()
    for grp in t.get("mass", []) + t.get("niche", []):
        if grp and grp[0] == ip_name:
            cjk = next((a for a in grp if 关注分层._has_cjk(a)), None)
            if cjk:
                return cjk, "IP大盘", "首个中文别名(§11.2)；粒度/角度/消歧须人工核"
            return grp[0], "IP大盘", "组内无中文别名，用首别名；中文探针词须人工核"
    return ip_name, "项目/平台", "项目名原样；中文品类词(开源掌机/PS4模拟器等)须人工补"


def _preflight(word):
    """探针就绪度结构预检(§11.12,零LLM/不联网)：复用探针单一权威 _kw_cores 暴露该词将被
    如何匹配(词元/字符类),引用已实测先例提示风险类别。**不预测命中率(须联网)、不判语义歧义、
    不自动改词**——只 surface 结构供人工核。纯拉丁≠必兜底(Batocera/shadPS4反例),
    2字子词≠必假阳(街机改版反例),风险类别是结构提示非定论,不据此定阈值。"""
    lat, cjk = B站热度探针._kw_cores(word)
    if lat and cjk:
        sc = "混合"
    elif cjk:
        sc = "含CJK"
    elif lat:
        sc = "纯拉丁"
    else:
        sc = "无核心词元"
    sub2 = [c for c in cjk if len(c) == 2]
    if sc == "纯拉丁":
        note = ("纯拉丁词:B站易词元级模糊兜底(model2-nx→NX CAD先例),须核top3/考虑补中文品类词;"
                "纯拉丁≠必兜底(Batocera/shadPS4纯拉丁但实测可靠);命中率须联网实测,不预测,不自动改词")
    elif sc == "混合":
        note = ("混合词:拉丁词元易兜底(model2-nx先例)+2字CJK词元易假阳(街机改版先例),须人工核top3;"
                "不预测命中率/不判语义/不自动改词")
    elif sc == "含CJK":
        note = ("含2字CJK词元[" + "/".join(sub2) + "]:放宽匹配(街机改版先例),若词元泛易假阳须人工核top3;"
                "2字子词≠必假阳(街机改版真相关);语义歧义零LLM治不了须人工,不预测命中率,不自动改词")
    else:
        note = "无核心词元(探针无法匹配),须人工换词;不自动改词"
    return {"script_class": sc, "cores_lat": lat, "cores_cjk": cjk,
            "cjk_sub2": sub2, "match_note": note}


def build_expansion_list(cards, probe_map):
    """零LLM扩词表(card→keyword全自动的prep半段，§11.11)：从已scoring卡surface
    高/中关注但B站未探针的已识别IP→候选探针词。只报覆盖缺口，**不改demand/queue**；
    编辑映射表仍权威(已映射词用编辑词，未映射IP自动取大盘候选)；候选是draft须人工核＋批准联网才测。
    **不联网、不mutate卡**。返回 (ranked_list, info)。"""
    probe_map = probe_map or {}
    groups = {}
    for c in cards:
        ip = c.get("ip_name")
        att = c.get("attention")
        if not ip or att not in ("高", "中"):
            continue
        entry = IP_TO_KEYWORD.get(ip)
        if entry is not None and entry[0] in probe_map:
            continue  # 已映射且词已探针→非覆盖缺口(污染属消歧问题,另列,不混入扩词表)
        if entry is not None:
            word, kind, note = entry[0], "编辑映射", f"编辑表已定词「{entry[0]}」，本轮未探针"
            gap = f"映射词「{entry[0]}」未探针"
        else:
            word, kind, note = _candidate_word(ip)
            gap = "不在编辑映射表"
        g = groups.get(ip)
        if g is None:
            g = groups[ip] = {"ip_name": ip, "candidate_word": word, "word_kind": kind,
                              "gap_kind": gap, "note": note, "cards": 0, "attention_max": "中",
                              "major_event_cards": 0, "queues": set(), "entries": set(), "samples": [],
                              "preflight": _preflight(word)}
        g["cards"] += 1
        if att == "高":
            g["attention_max"] = "高"
        if c.get("major_event"):
            g["major_event_cards"] += 1
        g["queues"].add(c.get("queue", ""))
        g["entries"].add(c.get("entry", "A"))
        if len(g["samples"]) < 3:
            g["samples"].append({"event_id": c.get("event_id"), "attention": att,
                                 "core_hook": (c.get("core_hook") or "")[:60]})
    lst = sorted(groups.values(),
                 key=lambda g: (0 if g["attention_max"] == "高" else 1, -g["cards"], g["candidate_word"]))
    for g in lst:
        g["queues"] = sorted(g["queues"])
        g["entries"] = sorted(g["entries"])
    info = {"version": MAP_VERSION, "track_version": B站热度探针.TRACK_VERSION,
            "candidate_ips": len(lst),
            "high_attention_ips": sum(1 for g in lst if g["attention_max"] == "高"),
            "cards_covered": sum(g["cards"] for g in lst),
            "basis": "高/中关注且B站未探针的已识别IP；候选词=编辑映射词或recognition组首个中文别名(§11.2)",
            "informational_only": "扩词表只surface覆盖缺口，不改demand/queue；编辑映射表仍权威",
            "human_review": "候选词是draft，须人工消歧/粒度/角度核＋批准联网探针后才测；零LLM不做语义消歧/角度词最终选择",
            "no_network": "本步不联网，只从已scoring卡派生候选；实测须另批探针run"}
    sc_counts = {}
    for g in lst:
        sc = g["preflight"]["script_class"]
        sc_counts[sc] = sc_counts.get(sc, 0) + 1
    info["preflight"] = {
        "script_class_counts": sc_counts,
        "pure_latin": sc_counts.get("纯拉丁", 0),
        "cjk_with_sub2": sum(1 for g in lst if g["preflight"]["cjk_sub2"]),
        "basis": "复用探针_kw_cores单一权威暴露词元/字符类(§11.12)；结构预检非命中率预测",
        "honest": "纯拉丁≠必兜底(Batocera/shadPS4反例),2字子词≠必假阳(街机改版反例)；不预测core_hit_rate(须联网),不判语义歧义/不自动改词(须人工)"}
    return lst, info


def render_expansion_md(lst, info):
    """扩词表候选.md：人工可读 ranked 清单＋draft/人工核/批准联网/不改队列 flags。版权只给指针＋短hook≤60。"""
    lines = ["# B站探针扩词表候选（零LLM自动取词，§11.11）", "",
             f"> 版本 {info['version']}；候选IP {info['candidate_ips']} 个"
             f"（高关注 {info['high_attention_ips']}／覆盖卡 {info['cards_covered']}）。",
             f"> **{info['informational_only']}**。",
             f"> **{info['human_review']}**。",
             f"> **{info['no_network']}**。", "",
             "这些是「已识别、关注高/中、但 B站需求未探针」的覆盖缺口——系统对它们的需求判断退回未知/热度时序。",
             "候选词是 draft（编辑映射词或 IP 表首个中文别名），**消歧/粒度/角度词最终选择须人工核**，",
             "核完并**批准联网探针 run** 后才测；测得可靠档再经编辑映射表回流（§11.8）。本表不改任何卡的 demand/queue。", "",
             "| IP身份 | 候选探针词(draft) | 词类型 | 就绪度 | 关注max | 卡数 | 重大事件卡 | 队列分布 | 缺口 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for g in lst:
        lines.append(f"| {g['ip_name']} | {g['candidate_word']} | {g['word_kind']} | {g['preflight']['script_class']} "
                     f"| {g['attention_max']} | {g['cards']} | {g['major_event_cards']} | {'/'.join(g['queues'])} | {g['gap_kind']} |")
    pf = info.get("preflight", {})
    sc = pf.get("script_class_counts", {})
    lines += ["", "## 探针就绪度结构预检（§11.12，零LLM/不联网，复用探针 _kw_cores 单一权威）", "",
              "> 暴露每个候选词将被探针如何匹配（词元/字符类），引用已实测先例提示风险类别。",
              "> **不预测命中率（须联网实测）、不判语义歧义、不自动改词**——只供人工核优先级。",
              "> 纯拉丁≠必兜底（Batocera/shadPS4 纯拉丁但实测可靠）；2字子词≠必假阳（街机改版2字子词真相关）。", "",
              f"脚本类分布：纯拉丁 {sc.get('纯拉丁', 0)}／含CJK {sc.get('含CJK', 0)}／混合 {sc.get('混合', 0)}／无核心词元 {sc.get('无核心词元', 0)}。", "",
              f"- **纯拉丁词 {pf.get('pure_latin', 0)} 个**（词元兜底风险类，model2-nx→NX CAD 先例）：须核 top3／考虑补中文品类词；逐词词元见下。",
              f"- **含 2 字 CJK 词元 {pf.get('cjk_with_sub2', 0)} 个**（假旗风险类，街机改版先例）：词元泛易假阳，须人工核 top3；逐词词元见下。", "",
              "## 样本看点（≤60字，版权只给指针）＋角度线索", ""]
    for g in lst:
        lines.append(f"### {g['ip_name']} → 候选「{g['candidate_word']}」")
        lines.append(f"- {g['note']}")
        pf_g = g["preflight"]
        lines.append(f"- 探针词元：拉丁{pf_g['cores_lat']}／CJK{pf_g['cores_cjk']}（{pf_g['script_class']}）")
        if g["major_event_cards"]:
            lines.append(f"- 角度线索：{g['major_event_cards']} 张卡含重大事件词(破解/下架/越狱等)，"
                         f"可考虑角度词(§11.2 粒度两档)，最终选择须人工")
        for s in g["samples"]:
            lines.append(f"- [{s['attention']}] {s['core_hook']} ｜ `{s['event_id']}`")
        lines.append("")
    return "\n".join(lines)
# -*- coding: utf-8 -*-
"""最小证据选择器（评审路线阶段3，候选层，零生成式LLM）。

权威规格 = 根目录 知识库评审结论与实施路线_2026-11-20.md §阶段3。
五类事实：角色归属 / 玩家分工 / 数量 / 精确值 / 能否。
现有 kb_answer 五关降为初筛；本层加七项核查：
  主体一致 / 属性一致 / 条件覆盖 / 数值归属 / 肯否 / 来源资格 / 反证。
复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论。

**候选层纪律**：本模块不改 kb.query 默认判定/窗口。合格证据在低分位被选中
属策略调整，须作为候选验证后再由用户批准翻默认，不许偷偷改口径。
"""
import re
import unicodedata

from .kb_answer import COUNT_ASK, VALUE_SUBTYPES, _norm
from .kb_route import classify_intent, focus_terms


def _fw(t):
    """全角latin/数字归一到半角（２Ｐ→2P、ＧＫ→GK、ＭＦ→MF），喂给ASCII正则。"""
    return unicodedata.normalize("NFKC", t)

EXCL_Q = re.compile(r"只有|仅|唯一")
SCOPE_TEAM = re.compile(r"队内|队里|队伍内|热血队")
SCOPE_ALL = re.compile(r"全游戏|整个游戏|全部角色|所有角色")
STATE_NATIVE = re.compile(r"原生")
MODE_COOP = re.compile(r"合作|協力|协力")
MODE_VS = re.compile(r"对战|対戦")
PLAYER_Q = re.compile(r"([12一二])\s*[P号]|玩家([12一二])|([12一二])号玩家")
ATTR_Q = re.compile(r"哪个角色|谁会|谁会使|哪个.*会|谁原生|只有.*会|唯一.*会|角色是谁|会使.*是谁")
PLAYER_ROLE_Q = re.compile(r"操作什么位置|玩家操作|操作.*位置|[12]P.*位置")
NEG_Q = re.compile(r"不能|无法|不可以|会不会不")

# 归属行标志：把技能/属性绑到角色或数量。单含"原生"不算（方法学段也谈原生）。
ATTR_LINE = re.compile(r"仅|只有|唯一|全员|多人会|\d+\s*人会")
# 方法学/生产测量词汇：密集出现且无归属行 ⇒ 不得承担归属出证（Q02 病假）。
METHOD_MARKERS = re.compile(
    r"实测|探针|闸门|采集|宏|签名|像素|测量|复现|标定|正对照|反例|ramdump|OAM|sprite")
POSITION_RE = re.compile(r"GK|MF|FW|DF|门将|中场|前锋|后卫|位置|キーパー|ゴールキーパー|ポジション|役目")
PLAYER_REF = re.compile(r"1P|2P|一号|二号|1号|2号")
OTHER_TEAM = re.compile(r"巴西|阿根廷|德国|意大利|墨西哥|对手|ぶらじる|あるぜんちん|どいつ")
USE_VERB = re.compile(r"使用|会使|会|发动|拥有")
# 数值类问句的泛词（指纹/哈希/ROM 等）不算对象词，防"同哈希错文件"。
VALUE_GENERIC = re.compile(r"指纹|哈希|校验和|字节|文件大小|地址|sha1|SHA1|多少|多大|ROM|rom")
PLAYER_PAT = {"1": r"1P|一号|1号", "一": r"1P|一号|1号",
              "2": r"2P|二号|2号", "二": r"2P|二号|2号"}
# 归属/能否类主体核：剔除条件词与疑问/功能碎片，留下被问的技能/对象名词。
# 治"同角色错技能"：块含"原生"等条件词不算主体命中，须含技能词本身。
ATTR_FUNC = re.compile(r"原生|秘技|队|热血|只有|仅|唯一|会|角色|哪|什么|多少|操作|位置|模式|合作|对战|玩家|角|色")


def parse_question(q, tokens_fn):
    """问句 → 事实类 + 主体焦点 + 条件。无法归类 ⇒ fact_class=None（复杂问题）。"""
    focus = focus_terms(q, tokens_fn)
    intent = classify_intent(q)
    if PLAYER_ROLE_Q.search(q):
        fc = "player_role"
    elif any(rx.search(q) for rx, _ in COUNT_ASK):
        fc = "count"
    elif any(rx.search(q) for rx, _ in VALUE_SUBTYPES):
        fc = "exact_value"
    elif ATTR_Q.search(q):
        fc = "role_attribution"
    elif intent == "yesno" or (re.search(r"吗[？?]?\s*$", q)
                               and re.search(r"能|会|可以|无法|不能", q)):
        fc = "capability"
    else:
        fc = None
    pm = PLAYER_Q.search(q)
    player = None
    if pm:
        player = next(g for g in pm.groups() if g)
    return {"fact_class": fc, "focus": sorted(focus), "intent": intent,
            "exclusivity": bool(EXCL_Q.search(q)),
            "scope": "all" if SCOPE_ALL.search(q) else ("team" if SCOPE_TEAM.search(q) else None),
            "state_native": bool(STATE_NATIVE.search(q)),
            "mode": "coop" if MODE_COOP.search(q) else ("vs" if MODE_VS.search(q) else None),
            "player": player, "negative": bool(NEG_Q.search(q))}


def _attr_lines(text, focus):
    """含焦点词且含归属标志的行（技能→角色/数量绑定）。"""
    out = []
    for ln in text.splitlines():
        if ATTR_LINE.search(ln) and (not focus or any(f in ln for f in focus)):
            out.append(ln)
    return out


def check_block(parsed, text, meta, tokens_fn):
    """七项核查。meta 需带 authority/status/revision_match。返回逐项 bool+原因。"""
    t = _norm(text)
    tt = set(tokens_fn(text))
    focus = set(parsed["focus"])
    fc = parsed["fact_class"]
    c = {}
    if fc in ("role_attribution", "capability"):
        core = {f for f in focus if not ATTR_FUNC.fullmatch(f)}
        c["subject_match"] = (not core) or bool(core & tt)
    else:
        c["subject_match"] = (not focus) or bool(focus & tt)
    attr_lines = _attr_lines(text, focus)
    method_n = len(METHOD_MARKERS.findall(t))
    if fc == "role_attribution":
        c["attribute_match"] = bool(attr_lines) and method_n < 3
        c["attribute_reason"] = (
            f"归属行{len(attr_lines)}条/方法学词{method_n}个"
            + ("" if attr_lines else "；无技能→角色归属行，方法学段不得承担归属出证"))
    elif fc == "player_role":
        ok = any(PLAYER_REF.search(_fw(ln)) and POSITION_RE.search(_fw(ln))
                 for ln in text.splitlines())
        c["attribute_match"] = ok
        c["attribute_reason"] = "需同一行含玩家编号+位置（全角日文归一后判）"
    elif fc in ("count", "exact_value"):
        c["attribute_match"] = True  # 数值归属关单独查
        c["attribute_reason"] = "数值类由 value_attribution 把关"
    elif fc == "capability":
        c["attribute_match"] = bool(re.search(r"可以|不能|无法|不可|能|会|支持|限制|专用", t))
        c["attribute_reason"] = "肯否形态词（含无法/不能）"
    else:
        c["attribute_match"] = False
        c["attribute_reason"] = "复杂问题不强行归类"
    ans = attr_lines[0] if attr_lines else t
    cond_ok, cond_why = True, []
    if parsed["state_native"]:
        ok = "原生" in t
        cond_ok &= ok
        cond_why.append("原生" + ("✓" if ok else "✗"))
    if parsed["mode"] == "coop":
        ok = bool(MODE_COOP.search(t))
        cond_ok &= ok
        cond_why.append("合作" + ("✓" if ok else "✗"))
    if parsed["player"]:
        rx = PLAYER_PAT.get(parsed["player"], PLAYER_REF.pattern)
        ok = bool(re.search(rx, _fw(t)))
        cond_ok &= ok
        cond_why.append("玩家编号" + ("✓" if ok else "✗"))
    if parsed["scope"] == "team":
        # 范围只看归属行（回答本问的行），不看整块：金表别行提他队不算越界。
        scope_text = "\n".join(attr_lines) if attr_lines else t
        ok = not (OTHER_TEAM.search(scope_text) and "热血" not in scope_text)
        cond_ok &= ok
        cond_why.append("队内范围" + ("✓" if ok else "✗（归属行属他队，不在问句范围）"))
    c["condition_coverage"] = cond_ok
    c["condition_reason"] = "；".join(cond_why) or "无额外条件"
    if fc in ("count", "exact_value"):
        ok = False
        focus_specific = {f for f in focus if not VALUE_GENERIC.search(f)}
        for ln in text.splitlines():
            if focus_specific and not any(f in ln for f in focus_specific):
                continue
            if fc == "count" and any(re.search(r"\d+\s*" + re.escape(u), _norm(ln))
                                     for _, units in COUNT_ASK for u in units):
                ok = True
            if fc == "exact_value" and any(arx.search(ln) for _, arx in VALUE_SUBTYPES):
                ok = True
        c["value_attribution"] = ok
        c["value_reason"] = "数值须与对象词同 line" if not ok else "数值与对象词同行"
    else:
        c["value_attribution"] = True
        c["value_reason"] = "非数值类，不适用"
    pol_ok, pol_why = True, ""
    if parsed["exclusivity"]:
        pol_ok = bool(EXCL_Q.search(ans))
        pol_why = "排他问须归属行含仅/只有/唯一" + ("✓" if pol_ok else "✗（『会使』≠『只有他会』）")
    if parsed["negative"]:
        ok = bool(re.search(r"不能|无法|不可|全否", t))
        pol_ok &= ok
        pol_why += "；否定问须否定证据" + ("✓" if ok else "✗")
    c["polarity"] = pol_ok
    c["polarity_reason"] = pol_why or "无肯否/排他要求"
    source_ok = (meta.get("authority") == "authoritative"
                 and meta.get("status") == "verified_read"
                 and bool(meta.get("revision_match")))
    if meta.get("fragment_policy") == "strict":
        source_ok = source_ok and bool(meta.get("fragment_provenance", {}).get("eligible"))
    c["source_eligibility"] = source_ok
    c["source_reason"] = (f"authority={meta.get('authority')}/"
                          f"status={meta.get('status')}/rev_match={meta.get('revision_match')}"
                          + (f"/fragment={meta.get('fragment_provenance', {}).get('reason')}"
                             if meta.get("fragment_policy") == "strict" else ""))
    c["counter_evidence"] = True  # select() 层跨块计算
    c["counter_reason"] = "见 select 跨块反证"
    c["eligible"] = all(c[k] for k in ("subject_match", "attribute_match",
                        "condition_coverage", "value_attribution", "polarity",
                        "source_eligibility", "counter_evidence"))
    return c


def select(q, hits, texts, tokens_fn, production_window=3, preferred_chunk_id=None):
    """候选选择。hits=kb.query 的命中（含 answerability 初筛），texts=chunk_id→全文。
    返回 selected/verdict/beyond_window；**不改生产默认**。
    已有 selected_evidence 通过七项核查时保留，避免无理由换证。"""
    parsed = parse_question(q, tokens_fn)
    if parsed["fact_class"] is None:
        return {"fact_class": None, "parsed": parsed, "verdict": "inconclusive",
                "selected": None, "selected_rank": None, "beyond_window": False,
                "counterexample_blocks": [],
                "reason": "复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论",
                "per_block": []}
    per = []
    for rank, h in enumerate(hits, 1):
        text = texts.get(h["chunk_id"], h.get("snippet", ""))
        meta = {"authority": h.get("authority"), "status": h.get("status"),
                "revision_match": h.get("revision_match", True),
                "fragment_policy": h.get("fragment_provenance", {}).get("policy"),
                "fragment_provenance": h.get("fragment_provenance")}
        checks = check_block(parsed, text, meta, tokens_fn)
        if h.get("answerability", {}).get("answerable") is False:
            checks["initial_screen"] = False
            checks["initial_reason"] = "生产可答性初筛已拒，选择器不得单独救活"
            checks["eligible"] = False
        per.append({"rank": rank, "chunk_id": h["chunk_id"], "checks": checks})
    # 跨块反证：排他归属问，问全游戏范围时，他队使用块构成反例；
    # 问队内范围时，他队块不在同一范围，不构成反例（Q02 巴西 Bûnyo）。
    counters = []
    if parsed["fact_class"] == "role_attribution" and parsed["exclusivity"]:
        for p in per:
            text = texts.get(p["chunk_id"], "")
            if (OTHER_TEAM.search(text) and USE_VERB.search(text)
                    and set(parsed["focus"]) & set(tokens_fn(text))):
                if parsed["scope"] == "all":
                    counters.append(p["chunk_id"])
                    p["checks"]["counter_evidence"] = False
                    p["checks"]["counter_reason"] = "全游戏排他问存在他队使用反例"
                    p["checks"]["eligible"] = False
    preferred = next((p for p in per if preferred_chunk_id
                      and p["chunk_id"] == preferred_chunk_id
                      and p["checks"]["eligible"]), None)
    selected = preferred or next((p for p in per if p["checks"]["eligible"]), None)
    if counters and parsed["scope"] == "all":
        selected = None  # 全游戏排他主张已被他队使用反证推翻，整问拒答
    rank = selected["rank"] if selected else None
    return {"fact_class": parsed["fact_class"], "parsed": parsed,
            "verdict": "pass" if selected else "inconclusive",
            "selected": selected["chunk_id"] if selected else None,
            "selected_rank": rank,
            "beyond_window": bool(rank and rank > production_window),
            "counterexample_blocks": counters,
            "reason": (f"第{rank}位块过七项核查" if selected else
                       ("全游戏排他问存在他队使用反证，主张被推翻" if counters else
                        "无块同时过七项核查（初筛可答≠合格证据）")),
            "per_block": per}
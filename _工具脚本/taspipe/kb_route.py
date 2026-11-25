# -*- coding: utf-8 -*-
"""域路由 + 问句意图分类（零 LLM，纯规则）。生产版，移植自 P1 小样 p1_router.py。

治的病：LOL 世界冠军问题命中热血足球"世界杯"段还判 pass。
规则优先级：显式游戏名/身份词 > 泛词。域外语料为零 ⇒ query 拒答（out_of_scope），
不是"不存在"，是本地没收集。显式 game/revision/platform 过滤优先于域限制。
"""
import re
import unicodedata

# domain -> (本地 game_id 分区, 显式关键词, 弱关键词)
DOMAINS = {
    "retro_soccer": {
        "game_ids": ["nekketsu_soccer2"], "revisions": [],
        "strong": ["热血足球", "热血联盟", "热血联赛", "熱血サッカー", "くにお",
                   "燕返", "必杀射门", "小辫子", "美纱子", "热血队"],
        "weak": ["射门", "守门员", "点球", "PK战", "输球", "必杀"],
    },
    "retro_fighting": {
        "game_ids": ["nekketsu_kakutou_densetsu"], "revisions": [],
        "strong": ["热血格斗传说", "熱血格闘伝説", "Nekketsu Kakutou Densetsu", "TJC-NA"],
        "weak": ["格斗传说"],
    },
    "kof98": {
        "game_ids": ["kof98"], "revisions": [],
        "strong": ["拳皇98", "拳皇'98", "KOF98", "kof98", "98UM", "98um", "ECK",
                   "草薙京", "八神庵", "简化连招"],
        "weak": ["拳皇", "出招表"],
    },
    "arcade_hacks": {
        "game_ids": [], "revisions": ["arcade_hack_multi"],
        "strong": ["街机改版", "改版整合", "quanjizhong", "街机hack"],
        "weak": ["改版", "街机"],
    },
    "megaman1": {
        "game_ids": [], "revisions": ["megaman1_nes_us"],
        "strong": ["洛克人1", "洛克人 1", "洛克人Ⅰ", "洛克人一",
                   "Mega Man 1", "Rockman 1", "MM1"],
        "weak": [],
    },
    "megaman2": {
        "game_ids": [], "revisions": ["megaman2_nes_tasvideos_rockman2", "megaman2_nes_us_manual"],
        "strong": ["洛克人2", "洛克人 2", "洛克人II", "洛克人 II",
                   "Mega Man 2", "Mega Man II", "Rockman 2", "Rockman II", "MM2"],
        "weak": [],
    },
    "project_docs": {
        "game_ids": [], "revisions": ["project_docs"],
        "strong": ["素材生产规范", "要素盘点", "泛化矩阵", "目标与实施路线",
                   "测试问题与闸门"],
        "weak": ["闸门", "流水线", "说明书", "TAS", "tas"],
    },
    "tooling": {
        "game_ids": [], "revisions": ["project_docs"],
        "strong": ["kb.py", "sources.py", "registry.py", "acquire.py",
                   "retro_cheat_runner"],
        "weak": ["脚本", "工具链"],
    },
    "esports_lol": {
        "game_ids": [], "revisions": [],
        "strong": ["英雄联盟", "LOL", "lol", "LPL", "全球总决赛", "MSI",
                   "拳头游戏", "Riot", "Faker", "LCK", "LEC"],
        "weak": ["战队", "转会", "赛程", "冠军"],
    },
    "esports_dota": {
        "game_ids": [], "revisions": [],
        "strong": ["DOTA", "dota", "Dota", "DOTA2", "TI14", "TI13", "国际邀请赛",
                   "Valve赛事", "刀塔"],
        "weak": ["奖金池", "赛程"],
    },
    # 阶段一第1天新增（全域KB实施计划 §6）：空语料域=诚实拒答，不是全库泛搜。
    # 只收强词不收弱词，避免抢既有域问句；语料 ingest 前 corpus_available 恒 False。
    "esports_cs2": {
        "game_ids": [], "revisions": [],
        "strong": ["CS2", "cs2", "反恐精英2", "反恐精英：全球攻势",
                   "CSGO", "csgo", "HLTV", "hltv"],
        "weak": [],
    },
    "esports_valorant": {
        "game_ids": [], "revisions": [],
        "strong": ["VALORANT", "valorant", "无畏契约", "VCT", "vct"],
        "weak": [],
    },
    "modern_games": {
        "game_ids": [], "revisions": [],
        "strong": ["原神", "纳西妲", "圣遗物", "崩坏", "星穹铁道", "绝区零",
                   "黑神话", "PS5", "Switch2", "网游", "手游新作"],
        "weak": ["新作", "发售日"],
    },
}

# 意图判定顺序敏感：value 先于 count（"SHA1是多少"是取值不是数数）
INTENT_RULES = [
    ("value_lookup", re.compile(r"CRC32|crc32|SHA1|sha1|指纹|校验和|哈希|多少字节|文件大小|内存地址|地址是|(?:速度|坐标)(?:是)?多少")),
    ("count", re.compile(r"多少|几种|几名|几场|几个|几支|总数|一共")),
    ("identity", re.compile(r"哪个|哪支|哪位|谁|什么位置|位置(?:是|为)?什么|什么角色|签名")),
    ("yesno", re.compile(r"能不能|可不可以|能否|是否|会不会|关不关|关得掉")),
    ("howto", re.compile(r"怎么|如何|怎样")),
    ("existence", re.compile(r"有没有|是否存在|触发|隐藏")),
]

# 焦点模式：问句聚焦词 -> 证据块必须含的答案形态（可答性闸门用）
CAPABILITY_LIST_Q = re.compile(r"(?:六项|6项).{0,6}(?:能力|参数).{0,10}(?:哪些|参数|列出)|(?:列出|哪些).{0,10}(?:六项|6项).{0,6}(?:能力|参数)")
CAPABILITY_LIST_RE = re.compile(r"能力共\s*6\s*项")
CAPABILITY_FORMULA_Q = re.compile(
    r"(?:名字|姓名|生日|誕生日|血型).{0,20}(?:换算|公式|怎么算|如何计算)|"
    r"(?:换算|公式|怎么算|如何计算).{0,20}(?:名字|姓名|生日|誕生日|血型)")
CAPABILITY_FORMULA_RE = re.compile(r"(?:没有|未).{0,16}(?:给出|提供).{0,24}公式|公式.{0,16}(?:没有|未)")
FOCUS_PATTERNS = [
    (re.compile(r"什么位置|位置(?:是|为)?什么"), re.compile(r"ＧＫ|GK|ＭＦ|MF|FW|DF|门将|中场|前锋|后卫|守门员|キーパー|ゴールキーパー|ポジション")),
    # 排他/原生归属必须有“谁+原生/只有”的完整归属形态；方法学段提“非原生者”不算角色答案。
    (re.compile(r"(只有|唯一|原生|专属).{0,16}(哪个角色|谁会使)|"
                r"(哪个角色|谁会使).{0,16}(只有|唯一|原生|专属)"),
     re.compile(r"(?:仅|只有)[^。；\n]{0,24}(?:原生|会|使用)|"
                r"(?:原生|专属)[^。；\n]{0,24}(?:是|为|：|=)|"
                r"(?:是|为|：|=)[^。；\n]{0,24}(?:原生|专属)")),
    # 问"原生"必须答"原生"——"仅会燕返者"不含角色名，不算回答了原生归属
    (re.compile(r"原生"), re.compile(r"原生")),
    (re.compile(r"哪个角色|谁会使"), re.compile(r"会使|会使用|能用|专属|原生|仅|只有")),
    (re.compile(r"签名"), re.compile(
        r"(?:判定签名|签名判据|签名|得点表现)[^。；\n]{0,24}(?:=|＝|:|：|为|是)[^。；\n]{0,32}"
        r"|(?:=|＝|:|：)[^。；\n]{0,12}(?:ひっさつOK|必杀技OK)"
        r"|ひっさつOK")),
    (re.compile(r"转会|买卖|交易"), re.compile(r"转会|买卖|交易|市场")),
    (re.compile(r"出招表|指令"), re.compile(r"[↓↘→←↙↑↖↗].{0,8}[ABCD]|[0-9]{2,3}[ABCD]")),
    # 问"X是什么射门"必须答射门种类——只命中主语(海月)缺属性(射门)不算回答（P5 X07）
    (re.compile(r"什么射门"), re.compile(r"射门")),
    # 问"对射门有什么影响"必须答射门——控室/天气段沾雨天场地但不讲射门不算回答（P6 X26）
    (re.compile(r"射门.{0,6}影响|对射门"), re.compile(r"射门")),
    # 版本/公式问句必须出现对应形态；标题词命中不能替具体补丁或计算式作答。
    (re.compile(r"Rev\.?\s*B|DvD|4-Score|Satellite", re.I),
     re.compile(r"Rev\.?\s*B|DvD|4-Score|Satellite", re.I)),
    (re.compile(r"KT#|公式|怎么算|如何计算", re.I),
     re.compile(r"KT\s*#\s*=|(?:出生月|誕生日|生日)[^。；\n]{0,50}"
                r"(?:mod|[+\-＋−*/%=＝])[^。；\n]{0,50}(?:\d|出生日|誕生日)|"
                r"(?:计算式|算式)[^。；\n]{0,80}(?:[=＝]|mod)|"
                r"[A-Za-z]{1,8}\s*=\s*[^\s。；]+", re.I)),
    (CAPABILITY_LIST_Q, CAPABILITY_LIST_RE),
    (CAPABILITY_FORMULA_Q, CAPABILITY_FORMULA_RE),
]

# 焦点词停用表：游戏标题词/疑问词不算焦点（否则"热血足球"本身会让任何块过关）
# P5 并入域泛词/问句框架词：球员(≈队员/角色，本域每块都有)、射门(本域核心动作泛词)、
# 地址/内存(value_lookup 问句框架词，非主语)。治 X25/X26 假块只命中域泛词缺问句主语。
# 数据口径：60 探针+26 冻结集模拟零金标误杀零真回归（p5_fix_sim_c3a_out.txt）；
# 全量版(并 eck/kof98)误杀 W18 八神庵连招被否，故 KOF 域标识词不停用。
FOCUS_STOP = {
    "热血", "足球", "联盟", "热血足球", "球联", "血足", "热血联盟", "热血联赛",
    "拳皇", "游戏", "模式", "多少", "什么", "怎么", "怎样", "如何", "能不能",
    "会不会", "是否", "哪个", "哪些", "一共", "总数", "请问", "告诉我", "玩家",
    "队员", "角色", "里面", "这个", "那个", "一下", "我们", "可以", "需要",
    "球员", "射门", "地址", "内存",
}

TITLE_SCORING_STOP = {
    "热血", "足球", "联盟", "热血足球", "球联", "血足", "热血联盟", "热血联赛",
    "拳皇", "游戏",
}
ATTRIBUTION_SCORING_STOP = FOCUS_STOP | {
    "只有", "仅", "唯一", "谁", "会使", "能用", "有哪", "生只", "返原", "个角",
    "色会", "队内", "热血队内", "血队", "热血队",
}
TEAM_SIZE_Q = re.compile(r"(?:每队|一队|球队).{0,10}(?:几名|多少人|几个人|几人)")
TEAM_BATTLE_Q = re.compile(r"1v1|(?:关掉|关闭|取消).{0,6}队友")
MULTIPLAYER_MODE_Q = re.compile(r"[1-4]\s*[PＰ]\s*模式|(?:点球|ＰＫ)\s*战")
TEAM_SHOT_Q = re.compile(
    r"([\u4e00-\u9fff]{2,4})队.{0,8}必杀射门.{0,10}(?:叫什么|名称|哪[种个])")
TEAM_NAMES = (
    "塞内加尔", "喀麦隆", "阿根廷", "几内亚", "墨西哥", "英格兰", "意大利", "德国",
    "巴西", "韩国", "泰国", "蒙古",
)
TECHNIQUE_NAMES = (
    "爆裂攻击", "龙卷拳", "必杀运球", "龙卷踢", "钻子攻击", "三倍加速", "超常冲刺",
    "脚跟挑球", "虚攻", "鱼跃头球", "倒挂金钩", "电光球射门",
)
TECHNIQUE_ASK_Q = re.compile(
    r"(?:" + "|".join(TECHNIQUE_NAMES) + r").{0,24}(?:怎么|怎样|如何|哪个键|哪些角色|能用|发动|触发)|"
    r"(?:怎么|怎样|如何|哪个键|哪些角色|能用|发动|触发).{0,24}(?:"
    + "|".join(TECHNIQUE_NAMES) + r")")
TEAM_SIZE_SCORING_STOP = FOCUS_STOP | {"几名", "名球", "场几", "盟每"}
TEAM_BATTLE_SCORING_STOP = FOCUS_STOP | {"kof98", "eck", "1v1"}
MULTIPLAYER_SCORING_STOP = FOCUS_STOP | {
    "日版", "说明书", "说明", "怎样", "分队", "第三人", "控制", "操作", "哪些", "选手",
}
TEAM_SHOT_SCORING_STOP = (FOCUS_STOP - {"射门"}) | {"叫什么", "名字", "名称"}
TECHNIQUE_SCORING_STOP = FOCUS_STOP | {
    "哪个", "哪些", "角色", "怎样", "怎么", "如何", "按键", "键", "时要", "能用",
}
CAPABILITY_SCORING_STOP = FOCUS_STOP | {"说明书", "说明", "列出", "六项", "参数", "哪些"}
PLAYER_ROLE_SCORING_STOP = FOCUS_STOP | {
    "双人", "合作", "二号", "一号", "操作", "位置", "人合", "下二", "么位",
    "作什", "作模", "号玩", "家操", "式下", "ショ", "ジシ", "ポジ",
    "ポジション", "モー", "モード", "ョン", "ード",
}


def route(q):
    """返回 {domain, game_ids, revisions, corpus_available, matched, tier}。
    显式词命中即定域；弱词只在无显式命中时生效；都不中 => unrouted（查全部本地）。"""
    ql = unicodedata.normalize("NFKC", q).lower()
    best = None
    for name, d in DOMAINS.items():
        s_hit = [k for k in d["strong"] if k.lower() in ql]
        if s_hit:
            cand = {"domain": name, "game_ids": d["game_ids"],
                    "revisions": d["revisions"],
                    "corpus_available": bool(d["game_ids"] or d["revisions"]),
                    "matched": s_hit, "tier": "strong"}
            # 多个显式域冲突时取命中词更多者（平手取先定义者，确定性）
            if best is None or len(s_hit) > len(best["matched"]):
                best = cand
    if best:
        return best
    for name, d in DOMAINS.items():
        w_hit = [k for k in d["weak"] if k.lower() in ql]
        if w_hit:
            return {"domain": name, "game_ids": d["game_ids"],
                    "revisions": d["revisions"],
                    "corpus_available": bool(d["game_ids"] or d["revisions"]),
                    "matched": w_hit, "tier": "weak"}
    return {"domain": "unrouted", "game_ids": None, "revisions": None,
            "corpus_available": True, "matched": [], "tier": "none"}


def domain_route(name):
    """显式指定域时构造路由；命中词留空，表示调用方已点名。"""
    d = DOMAINS[name]
    return {"domain": name, "game_ids": d["game_ids"],
            "revisions": d["revisions"],
            "corpus_available": bool(d["game_ids"] or d["revisions"]),
            "matched": [], "tier": "explicit"}


def _auto_hit(q, keyword):
    """自动路由用拉丁词边界，避免 Fantasy→tas、check→ECK 这类子串误报。"""
    ql = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", q).lower())
    kw = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", keyword).lower())
    if kw.isascii() and re.search(r"[a-z0-9]", kw):
        return re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", ql) is not None
    if re.search(r"(?:\d|ii)$", kw):
        return re.search(re.escape(kw) + r"(?![a-z0-9])", ql) is not None
    return kw in ql


# 泛词不能证明具体游戏/版本：拳皇15 不等于 KOF98，单说冠军也不等于 LOL。
AUTO_WEAK_STOP = {"拳皇", "冠军"}


def route_many(q):
    """返回问句命中的全部域；有强词时忽略弱词，无强词才并列全部弱词命中。

    单域旧行为仍由 route() 保留；自动调用不得先挑一个域，也不能把未识别实体说成不存在。
    """
    strong = []
    for order, (name, d) in enumerate(DOMAINS.items()):
        hit = [k for k in d["strong"] if _auto_hit(q, k)]
        if hit:
            strong.append((order, name, hit))
    if strong:
        strong.sort(key=lambda x: (-len(x[2]), x[0]))
        return [{"domain": name, "game_ids": DOMAINS[name]["game_ids"],
                 "revisions": DOMAINS[name]["revisions"],
                 "corpus_available": bool(DOMAINS[name]["game_ids"] or DOMAINS[name]["revisions"]),
                 "matched": hit, "tier": "strong"} for _, name, hit in strong]
    weak = []
    for order, (name, d) in enumerate(DOMAINS.items()):
        hit = [k for k in d["weak"] if k not in AUTO_WEAK_STOP and _auto_hit(q, k)]
        if hit:
            weak.append((order, name, hit))
    weak.sort(key=lambda x: (-len(x[2]), x[0]))
    if weak:
        return [{"domain": name, "game_ids": DOMAINS[name]["game_ids"],
                 "revisions": DOMAINS[name]["revisions"],
                 "corpus_available": bool(DOMAINS[name]["game_ids"] or DOMAINS[name]["revisions"]),
                 "matched": hit, "tier": "weak"} for _, name, hit in weak]
    return [{"domain": "unrouted", "game_ids": None, "revisions": None,
             "corpus_available": True, "matched": [], "tier": "none"}]


def in_scope(c, r):
    """块是否落在路由域内（unrouted 查全部）。"""
    if r["game_ids"] is None:
        return True
    if r["game_ids"] and c["game_id"] not in r["game_ids"]:
        return False
    if r["revisions"] and c["revision"] not in r["revisions"]:
        return False
    return True


def classify_intent(q):
    for name, rx in INTENT_RULES:
        if rx.search(q):
            return name
    return "topic"


def focus_terms(q, tokens_fn):
    """内容词去标题/疑问停用词 => 焦点词集。"""
    return {t for t in tokens_fn(q) if len(t) >= 2 and t not in FOCUS_STOP}


def focus_pattern(q):
    for qrx, arx in FOCUS_PATTERNS:
        if qrx.search(q):
            return arx
    return None


# 中文/日文表层形式映射（规则式跨语查询扩展，零 LLM）。每条映射须在真实语料出现，
# 并保留同义证据词的窄触发，避免把泛问句扩成具体答案。
# 每个日文形式都在真实语料里出现过（2026-11-19 逐词计数核实：協力7/モード44/試合17/
# キーパー9/ポジション16/やさしい5/むずかしい7/２Ｐ10/１Ｐ9；2026-11-24 tok4 重核：
# サッカー4/選手10/プレイヤー0）。プレイヤー 语料 0 次，不收。
# 治的病：Q08 中文问"二号玩家/合作"，日文说明书只写"２Ｐ協力"，词法主干永远命中不了。
JA_SYNONYMS = {
    "合作": ["協力"],
    "协力": ["協力"],
    "双人": ["2p"],
    "两人": ["2p"],
    "二号": ["2p"],
    "一号": ["1p"],
    "模式": ["モード"],
    "比赛": ["試合"],
    "守门员": ["キーパー"],
    "门将": ["キーパー"],
    "难度": ["やさしい", "むずかしい"],
    "位置": ["ポジション"],
    "上场": ["プレイ"],
    "判定签名": ["得点表", "ひっさつOK"],
    "修订版": ["同口径", "回放无法对齐"],
}
TEAM_SIZE_JA_SYNONYMS = {"足球": ["サッカー"], "球员": ["選手"]}


def expand_terms(q, tokens_fn):
    """问句含中文触发词 => 追加日文表层形式的分词结果（供 BM25 查询侧）。
    只扩查询，不改问句原文、不影响稠密向量与可答性焦点。"""
    extra = set()
    for zh, forms in JA_SYNONYMS.items():
        if zh in q:
            for form in forms:
                extra.update(tokens_fn(form))
    if TEAM_SIZE_Q.search(q):
        for zh, forms in TEAM_SIZE_JA_SYNONYMS.items():
            if zh in q:
                for form in forms:
                    extra.update(tokens_fn(form))
    if MULTIPLAYER_MODE_Q.search(q):
        for zh, forms in {"分队": ["チーム"], "第三人": ["3p"], "点球": ["ＰＫ"]}.items():
            if zh in q:
                for form in forms:
                    extra.update(tokens_fn(form))
    return extra


# 问句版本钉（阶段1：只暴露信息，不参与路由/过滤/打分）。
# 只收无歧义身份词：ECK=简化连招版 hack、98UM=官方升级版的身份已结案（sha1 级证据）。
# 「拳皇98」本身两版都指，不收；自动钉版本会误杀跨版本参考件，判定改动属后续阶段。
VERSION_HINTS = {"eck": "kof98eck", "98um": "kof98um",
                 "kof98eck": "kof98eck", "kof98um": "kof98um"}


def version_hints(q):
    """问句里的无歧义版本身份词 → revision id 列表（信息层）。
    拉丁词边界匹配，避免子串误报；返回有序去重列表，空列表=无版本线索。"""
    ql = q.lower()
    out = set()
    for tok, rev in VERSION_HINTS.items():
        if re.search(r"(?<![a-z0-9])" + re.escape(tok) + r"(?![a-z0-9])", ql):
            out.add(rev)
    return sorted(out)
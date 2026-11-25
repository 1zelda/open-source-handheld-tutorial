# -*- coding: utf-8 -*-
"""P1 域路由 + 问句意图分类（零 LLM，纯规则，可自检）。

治的病：pilot Q12——LOL 世界冠军问题命中热血足球"世界杯"段还判 pass。
规则优先级：显式游戏名/身份词 > 泛词。域外语料为零 ⇒ not_found_within_scope，
不是"不存在"，是本地没收集（与生产 kb 的 miss 语义区分开）。
"""
import re

# domain -> (本地 game_id 分区, 显式关键词, 弱关键词)
DOMAINS = {
    "retro_soccer": {
        "game_ids": ["nekketsu_soccer2"], "revisions": [],
        "strong": ["热血足球", "热血联盟", "热血联赛", "熱血サッカー", "くにお",
                   "燕返", "必杀射门", "小辫子", "美纱子", "热血队"],
        "weak": ["射门", "守门员", "点球", "PK战", "输球", "必杀"],
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
        "strong": ["DOTA", "dota", "Dota", "TI14", "TI13", "国际邀请赛",
                   "Valve赛事", "刀塔"],
        "weak": ["奖金池", "赛程"],
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
    ("value_lookup", re.compile(r"SHA1|sha1|指纹|校验和|哈希|多少字节|文件大小|内存地址|地址是")),
    ("count", re.compile(r"多少|几种|几名|几场|几个|几支|总数|一共")),
    ("identity", re.compile(r"哪个|哪支|哪位|谁|什么位置|什么角色|签名")),
    ("yesno", re.compile(r"能不能|可不可以|能否|是否|会不会|关不关|关得掉")),
    ("howto", re.compile(r"怎么|如何|怎样")),
    ("existence", re.compile(r"有没有|是否存在|触发|隐藏")),
]

# 焦点模式：问句聚焦词 -> 证据块必须含的答案形态（可答性闸门用）
FOCUS_PATTERNS = [
    (re.compile(r"什么位置"), re.compile(r"ＧＫ|GK|ＭＦ|MF|门将|中场|前锋|后卫|守门员")),
    # 问"原生"必须答"原生"——"仅会燕返者"不含角色名，不算回答了原生归属
    (re.compile(r"原生"), re.compile(r"原生")),
    (re.compile(r"哪个角色|谁会使"), re.compile(r"仅|只有|原生|专属")),
    (re.compile(r"签名"), re.compile(r"「[^」]+」|签名.{0,16}(=|＝|:|：)")),
    (re.compile(r"转会|买卖|交易"), re.compile(r"转会|买卖|交易|市场")),
    (re.compile(r"出招表|指令"), re.compile(r"[↓↘→←↙↑↖↗].{0,8}[ABCD]|[0-9]{2,3}[ABCD]")),
]

# 焦点词停用表：游戏标题词/疑问词不算焦点（否则"热血足球"本身会让任何块过关）
FOCUS_STOP = {
    "热血", "足球", "联盟", "热血足球", "球联", "血足", "热血联盟", "热血联赛",
    "拳皇", "游戏", "模式", "多少", "什么", "怎么", "怎样", "如何", "能不能",
    "会不会", "是否", "哪个", "哪些", "一共", "总数", "请问", "告诉我", "玩家",
    "队员", "角色", "里面", "这个", "那个", "一下", "我们", "可以", "需要",
}


def route(q):
    """返回 {domain, game_ids, corpus_available, matched, tier}。
    显式词命中即定域；弱词只在无显式命中时生效；都不中 => unrouted（查全部本地）。"""
    ql = q.lower()
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
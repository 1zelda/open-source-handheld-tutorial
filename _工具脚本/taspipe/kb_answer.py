# -*- coding: utf-8 -*-
"""逐事实可答性闸门（零 LLM）。生产版，移植自 P1 小样 p1_answerability.py。

治的病："指纹/sha1"命中视频指纹规则就判 pass，库里根本没有 ROM SHA1。
原则：词命中 ≠ 回答了问题。每个命中块按问句意图校验答案形态，
全部块不可答 ⇒ query 判 inconclusive（refusal=unanswerable），绝不 pass。
可答性只影响判定，不影响 hits 列表（检索召回与判定分开计）。
"""
import re
import unicodedata

from .kb_route import (classify_intent, focus_terms, focus_pattern, expand_terms,
                       MULTIPLAYER_MODE_Q, TEAM_SHOT_Q, TEAM_NAMES, TECHNIQUE_NAMES, TECHNIQUE_ASK_Q,
                       CAPABILITY_FORMULA_Q, CAPABILITY_FORMULA_RE)

FULLWIDTH = str.maketrans("０１２３４５６７８９", "0123456789")


def _norm(t):
    return t.translate(FULLWIDTH)


VALUE_SUBTYPES = [
    (re.compile(r"CRC32|crc32"), re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{8}(?![0-9A-Fa-f])")),
    (re.compile(r"SHA1|sha1|指纹|哈希|校验和"), re.compile(r"[0-9a-fA-F]{40}")),
    (re.compile(r"字节|文件大小|多大"), re.compile(r"\d[\d,]*\s*(B|字节|KB|MB|GB)")),
    (re.compile(r"地址"), re.compile(r"(0x|\$)[0-9A-Fa-f]{2,4}")),
    (re.compile(r"速度|坐标"), re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{2}\.[0-9A-Fa-f]{2}(?![0-9A-Fa-f])")),
]

COUNT_RE = re.compile(r"[0-9一二三四五六七八九十两]+\s*(种|名|人|场|个|支|条|回|試合)")
# 问句量词 → 可接受的文本量词（含日文映射：场↔試合、名↔人）
COUNT_ASK = [
    (re.compile(r"几种|多少种"), ["种"]),
    (re.compile(r"几名|多少人|几个人|几人"), ["名", "人"]),
    (re.compile(r"几场|多少场"), ["场", "試合"]),
    (re.compile(r"几个|多少个"), ["个"]),
    (re.compile(r"几支|多少支"), ["支"]),
    (re.compile(r"几条|多少条"), ["条"]),
    (re.compile(r"几首|多少首"), ["首"]),
    (re.compile(r"几帧|多少帧"), ["帧", "frames"]),
]
# P7 补「专用必杀技/专用技」隐性肯定形态：W03 真答案「守门员专用必杀技为龙卷风拳」
# 不含 不能/可以/支持 等显性是非词，旧 YESNO_RE 判 intent_ok=False 把真答案挡在门外。
# 「专属必杀技」即肯定「能用必杀」。只收 专用必杀技/专用技（窄），不收 才能/持有/专用
# 泛词——模拟证 才能 会让 X16 球员数据块冒充答案（p7_yesno_sim_out.txt E4 引 2 假阳被否）。
YESNO_RE = re.compile(r"不能|可以|不可|能触发|就能|会触发|限制|关不掉|全否|支持|ROM ?侧|专用必杀技|专用技")
HOWTO_RE = re.compile(r"按键|步骤|→|菜单|作战会议|输入|暂停|Start|start|A×|B×|选择|换到|操作|按"
                      r"|セレクト|プレイ|方法|遊び方|やり方|開始")
EXIST_RE = re.compile(r"触发|条件|结局|彩蛋|隐藏|存在")
URL_RE = re.compile(r"https?://")
EXCLUSIVE_ATTRIBUTION_Q = re.compile(
    r"(?:只有|仅|唯一).*(?:哪个角色|谁会使|谁.*会)|"
    r"(?:哪个角色|谁会使|谁.*会).*(?:只有|仅|唯一)")
EXCLUSIVE_LINE = re.compile(r"只有|仅|唯一")
POSITION_SUBJECT_Q = (
    re.compile(r"(?:^|[\s，,、])([^，。！？?,\s]{1,16}?)"
               r"(?:在(?:队里|队伍|热血足球|游戏里))?"
               r"(?:打|踢|守|司职|处于|站)(?:的)?(?:是)?什么位置"),
    re.compile(r"([^，。！？?,\s]{1,16}?)(?:的)?(?:司职位置|位置)(?:是|为)?什么"),
    re.compile(r"([^，。！？?,\s]{1,16}?)的场上位置(?:是|为)?什么"),
)
POSITION_SUBJECT_ALIASES = {
    "国夫": ["くにお"], "赖常": ["よりつね"], "卡洛斯": ["かるろす"],
    "佐治": ["さじ"], "九门": ["くもん"], "海月": ["かいずき"],
    "宇贺神": ["うがじん"], "鬼武": ["おにたけ"], "岩壁": ["いわかべ"],
    "堀端": ["ほりばた"], "津根": ["つねを"], "元永": ["げんえい"],
}
POSITION_SUBJECT_STOP = {"玩家", "队员", "角色", "球员", "门将", "中场", "前锋", "后卫",
                         "1P", "2P", "1号", "2号", "一号", "二号"}
SHOT_METHOD_Q = re.compile(
    r"(?:怎么|如何|怎样).{0,8}射门|射门.{0,16}(?:怎么|如何|怎样)|"
    r"(?:射门|シュート).{0,12}(?:扑不到|防不住)|(?:扑不到|防不住).{0,12}(?:射门|シュート)")
SHOT_METHOD_RE = re.compile(r"射门|シュート|燕返|つばめがえり")
PLAYER_ROLE_Q = re.compile(r"操作什么位置|玩家操作.{0,8}位置|操作.{0,8}(?:什么|哪个).{0,4}位置")
PLAYER_ROLE_REF = re.compile(r"1P|2P|一号|二号|1号|2号")
PLAYER_ROLE_POSITION = re.compile(
    r"GK|MF|FW|DF|门将|中场|前锋|后卫|位置|キーパー|ゴールキーパー|ポジション|役目")
ENDING_CAPABILITY_Q = re.compile(r"(?:会不会|是否|能|会).{0,12}结局|结局.{0,12}(?:会不会|是否|触发)")
ENDING_RE = re.compile(r"结局|エンディング|ending", re.I)
INPUT_SEQUENCE_Q = re.compile(r"按键输入")
INPUT_SEQUENCE_COUNT_RE = re.compile(
    r"(?<![A-Z])([AB])\s*(?:键)?\s*(?:按|×|X|\*)\s*\d+")
INPUT_SEQUENCE_START_RE = re.compile(r"START|スタート")
INPUT_SEQUENCE_CHAIN_RE = re.compile(r"\b[AB]{4,}\b")


def _position_subjects(q):
    if "位置" not in q:
        return []
    out = [name for name in POSITION_SUBJECT_ALIASES if name in q]
    if out:
        return out
    for rx in POSITION_SUBJECT_Q:
        for m in rx.finditer(q):
            name = m.group(1).strip()
            if name and name not in POSITION_SUBJECT_STOP and name not in out:
                out.append(name)
    return out


def _position_subject_ok(q, text):
    subjects = _position_subjects(q)
    normalized = unicodedata.normalize("NFKC", text)
    return all(any(variant in normalized for variant in [name] + POSITION_SUBJECT_ALIASES.get(name, []))
               for name in subjects)


def team_shot_subject(q):
    match = TEAM_SHOT_Q.search(q)
    if not match:
        return None
    captured = match.group(1)
    return next((name for name in TEAM_NAMES if captured.endswith(name)), captured)


def technique_subject(q):
    if not TECHNIQUE_ASK_Q.search(q):
        return None
    return next((name for name in TECHNIQUE_NAMES if name in q), None)


def multiplayer_player(q):
    if not MULTIPLAYER_MODE_Q.search(q):
        return None
    match = re.search(r"([1-4])\s*[PＰ]\s*模式", unicodedata.normalize("NFKC", q).upper())
    return match.group(1) if match else None


def multiplayer_asks_pk(q):
    normalized = unicodedata.normalize("NFKC", q).upper()
    return bool(MULTIPLAYER_MODE_Q.search(q) and re.search(r"点球战|PK\s*(?:战|戦)", normalized))


def _team_shot_ok(q, text):
    subject = team_shot_subject(q)
    if not subject:
        return True
    attribution = re.compile(re.escape(subject) + r"(?:队)?\s*(?:\||:|：|的)?\s*[^。；\n]{0,8}射门")
    return any(attribution.search(line) for line in text.splitlines())


def _technique_ok(q, text):
    subject = technique_subject(q)
    return not subject or subject in text


def _multiplayer_mode_ok(q, text):
    if not MULTIPLAYER_MODE_Q.search(q):
        return True
    normalized = unicodedata.normalize("NFKC", text).upper()
    player = multiplayer_player(q)
    if player and not re.search(r"(?<!\d)" + player + r"\s*P", normalized):
        return False
    if multiplayer_asks_pk(q) and not re.search(r"PK\s*(?:战|戦)", normalized):
        return False
    return True


def _shot_method_ok(q, text):
    return not SHOT_METHOD_Q.search(q) or bool(SHOT_METHOD_RE.search(text))


def _player_role_ok(q, text):
    if not PLAYER_ROLE_Q.search(q):
        return True
    return any(PLAYER_ROLE_REF.search(unicodedata.normalize("NFKC", ln).upper())
               and PLAYER_ROLE_POSITION.search(unicodedata.normalize("NFKC", ln))
               for ln in text.splitlines())


def _ending_capability_ok(q, text):
    return not ENDING_CAPABILITY_Q.search(q) or bool(ENDING_RE.search(text))


def _input_sequence_ok(q, text):
    if not INPUT_SEQUENCE_Q.search(q):
        return True
    t = unicodedata.normalize("NFKC", text).upper()
    counted = INPUT_SEQUENCE_COUNT_RE.findall(t)
    return ((INPUT_SEQUENCE_START_RE.search(t) and len(counted) >= 2)
            or bool(INPUT_SEQUENCE_CHAIN_RE.search(t)))


def _exclusive_attribution_ok(q, text, focus):
    if not EXCLUSIVE_ATTRIBUTION_Q.search(q):
        return True
    return bool(focus) and any(
        EXCLUSIVE_LINE.search(ln) and any(f in ln for f in focus)
        for ln in text.splitlines())


def _value_ok(q, text):
    for qrx, arx in VALUE_SUBTYPES:
        if qrx.search(q):
            return bool(arx.search(text))
    return False


def _count_ok(q, text):
    t = _norm(text)
    for qrx, units in COUNT_ASK:
        if qrx.search(q):
            return any(re.search(r"\d+(?:\s*\([^)]*\))?\s*" + re.escape(u), t)
                       for u in units)
    return bool(COUNT_RE.search(t))


def _intent_ok(intent, q, text):
    t = _norm(text)
    if intent == "count":
        return _count_ok(q, text)
    if intent == "value_lookup":
        return _value_ok(q, text)
    if intent == "yesno":
        return bool(YESNO_RE.search(t))
    if intent == "howto":
        if CAPABILITY_FORMULA_Q.search(q) and CAPABILITY_FORMULA_RE.search(t):
            return True
        return bool(HOWTO_RE.search(t))
    if intent == "existence":
        return bool(EXIST_RE.search(t))
    # identity / topic：焦点形态由 focus_pattern 统一把关，这里不另设卡
    return True


def annotate(q, text, tokens_fn, lang="zh"):
    """返回可答性判定与分解原因。

    五关：focus（焦点词重叠）/ pattern（问句聚焦形态）/ intent（意图校验器）
    / url_list（来源清单结构关，P3）/ topic_anchor（中文块话题锚，P3）。
    focus 对 topic、yesno 和无聚焦形态的 identity 硬性要求——count/value 等
    意图校验器本身就是答案形态证据，跨语块（日文说明书）与换述（"关不掉"vs
    "关掉"）不该被中文 bigram 重叠误杀；量词映射已防"6人制答比赛场数"这类串答。
    P6 治的病：yesno 块只含"可以/不能"就冒充答案（对照控室段含"也可以罚任意球"
    却根本不讨论打雷击倒门将）——yesno 也必须有焦点词重叠。
    P3 治的病：权威块只沾话题词就冒充答案（窗口探针 3/4 翻转假阳性）——
    ≥2 个网址的块是来源清单不是答案正文；howto/existence 的形态词（按/触发/结局）
    太泛，中文块必须另有焦点词重叠（焦点集并入跨语扩展词）；日文块不施话题锚，
    中文焦点词天然不重叠，仍由形态关/意图校验器把关。
    """
    intent = classify_intent(q)
    focus = focus_terms(q, tokens_fn)
    tt = set(tokens_fn(text))
    focus_hit = sorted(focus & tt)
    focus_ok = bool(focus_hit) if focus else True
    fp = focus_pattern(q)
    pattern_ok = bool(fp.search(text)) if fp else True
    intent_ok = _intent_ok(intent, q, text)
    focus_required = intent in ("topic", "yesno") or (intent == "identity" and fp is None)
    url_list = len(URL_RE.findall(text)) >= 2
    anchor_focus = focus | expand_terms(q, tokens_fn)
    anchor_ok = bool(anchor_focus & tt) if anchor_focus else True
    anchor_required = lang == "zh" and intent in ("howto", "existence")
    attribution_ok = _exclusive_attribution_ok(q, text, focus)
    position_subjects = _position_subjects(q)
    position_subject_ok = _position_subject_ok(q, text)
    shot_method_ok = _shot_method_ok(q, text)
    player_role_ok = _player_role_ok(q, text)
    ending_capability_ok = _ending_capability_ok(q, text)
    input_sequence_ok = _input_sequence_ok(q, text)
    team_shot_ok = _team_shot_ok(q, text)
    technique_ok = _technique_ok(q, text)
    multiplayer_mode_ok = _multiplayer_mode_ok(q, text)
    answerable = (pattern_ok and intent_ok and (focus_ok or not focus_required)
                  and not url_list and (anchor_ok or not anchor_required)
                  and attribution_ok and position_subject_ok and shot_method_ok
                  and player_role_ok and ending_capability_ok and input_sequence_ok
                  and team_shot_ok and technique_ok and multiplayer_mode_ok)
    return {"answerable": bool(answerable),
            "intent": intent, "focus_ok": focus_ok, "pattern_ok": pattern_ok,
            "intent_ok": intent_ok, "focus_hit": focus_hit[:6],
            "url_list": url_list, "topic_anchor_ok": anchor_ok,
            "exclusive_attribution_ok": attribution_ok,
            "position_subject_ok": position_subject_ok,
            "position_subjects": position_subjects,
            "shot_method_ok": shot_method_ok,
            "player_role_ok": player_role_ok,
            "ending_capability_ok": ending_capability_ok,
            "input_sequence_ok": input_sequence_ok,
            "team_shot_ok": team_shot_ok,
            "technique_ok": technique_ok,
            "multiplayer_mode_ok": multiplayer_mode_ok}
# -*- coding: utf-8 -*-
"""P1 逐事实可答性闸门（零 LLM）。

治的病：pilot Q09——"指纹/sha1"命中视频指纹规则就判 pass，库里根本没有 ROM SHA1。
原则：词命中 ≠ 回答了问题。每个命中块按问句意图校验答案形态，
全部块不可答 ⇒ insufficient_evidence，绝不 pass。
可答性只影响判定，不影响 hits 列表（检索召回与判定分开计，沿用 pilot 口径）。
"""
import re

from p1_router import classify_intent, focus_terms, focus_pattern

FULLWIDTH = str.maketrans("０１２３４５６７８９", "0123456789")


def _norm(t):
    return t.translate(FULLWIDTH)


VALUE_SUBTYPES = [
    (re.compile(r"SHA1|sha1|指纹|哈希|校验和"), re.compile(r"[0-9a-fA-F]{40}")),
    (re.compile(r"字节|文件大小|多大"), re.compile(r"\d[\d,]*\s*(B|字节|KB|MB|GB)")),
    (re.compile(r"地址"), re.compile(r"(0x|\$)[0-9A-Fa-f]{2,4}")),
]

COUNT_RE = re.compile(r"\d+\s*(种|名|人|场|个|支|条|回|試合)")
# 问句量词 → 可接受的文本量词（含日文映射：场↔試合、名↔人）
COUNT_ASK = [
    (re.compile(r"几种|多少种"), ["种"]),
    (re.compile(r"几名|几名|多少人|几个人|几人"), ["名", "人"]),
    (re.compile(r"几场|多少场"), ["场", "試合"]),
    (re.compile(r"几个|多少个"), ["个"]),
    (re.compile(r"几支|多少支"), ["支"]),
    (re.compile(r"几条|多少条"), ["条"]),
]
YESNO_RE = re.compile(r"不能|可以|不可|能触发|就能|会触发|限制|关不掉|全否|支持|ROM ?侧")
HOWTO_RE = re.compile(r"按键|步骤|→|菜单|作战会议|输入|暂停|Start|start|A×|B×|选择|换到|操作|按")
EXIST_RE = re.compile(r"触发|条件|结局|彩蛋|隐藏|存在")


def _value_ok(q, text):
    for qrx, arx in VALUE_SUBTYPES:
        if qrx.search(q):
            return bool(arx.search(text))
    return False


def _count_ok(q, text):
    t = _norm(text)
    for qrx, units in COUNT_ASK:
        if qrx.search(q):
            return any(re.search(r"\d+\s*" + re.escape(u), t) for u in units)
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
        return bool(HOWTO_RE.search(t))
    if intent == "existence":
        return bool(EXIST_RE.search(t))
    # identity / topic：焦点形态由 focus_pattern 统一把关，这里不另设卡
    return True


def annotate(q, text, tokens_fn):
    """返回可答性判定与分解原因。

    三关：focus（焦点词重叠）/ pattern（问句聚焦形态）/ intent（意图校验器）。
    focus 只对 topic 和无聚焦形态的 identity 硬性要求——count/value/yesno 等
    意图校验器本身就是答案形态证据，跨语块（日文说明书）与换述（"关不掉"vs
    "关掉"）不该被中文 bigram 重叠误杀；量词映射已防"6人制答比赛场数"这类串答。
    """
    intent = classify_intent(q)
    focus = focus_terms(q, tokens_fn)
    tt = set(tokens_fn(text))
    focus_hit = sorted(focus & tt)
    focus_ok = bool(focus_hit) if focus else True
    fp = focus_pattern(q)
    pattern_ok = bool(fp.search(text)) if fp else True
    intent_ok = _intent_ok(intent, q, text)
    focus_required = intent == "topic" or (intent == "identity" and fp is None)
    answerable = pattern_ok and intent_ok and (focus_ok or not focus_required)
    return {"answerable": bool(answerable),
            "intent": intent, "focus_ok": focus_ok, "pattern_ok": pattern_ok,
            "intent_ok": intent_ok, "focus_hit": focus_hit[:6]}
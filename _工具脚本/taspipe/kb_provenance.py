# -*- coding: utf-8 -*-
"""片段级来源资格：二手转述与撤回句不得继承整件权威。"""
import re
from pathlib import Path

from . import sources as S
from .kb_route import expand_terms, focus_pattern, focus_terms

SOURCE_RE = re.compile(r"(?<![A-Za-z0-9])S\d+\b")
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+")
LOCAL_RE = re.compile(
    r"我方(?:实测|复算|核对)|本机(?:实测|复算)|游戏内实测|生产实测|"
    r"\bprobe\d+\b[^。；\n]{0,40}(?:实测|证明|确认)|11-\d+[^。；\n]{0,24}实测")
LOCAL_CONTEXT_RE = re.compile(
    r"^(?:>\s*)?(?:[-*]\s*)?(?:\*\*|__)?(?:⇒\s*)?(?:11-\d+|我方|本机|游戏内|生产)"
    r"[^\n]{0,120}实测[^\n]{0,80}[:：](?:\*\*|__)?\s*$")
RETRACT_RE = re.compile(r"撤回|作废|表述过强|不能据此断言|旧(?:判断|结论)[^。；\n]{0,16}(?:错误|不成立)")
REFERENCE_RE = re.compile(
    r"转载|二手|待实测|待核|据.{0,16}(?:称|表示|介绍|记载)|"
    r"来源\s*[:：]|参考资料|引自|转述|文献侧补强|资料盘点|"
    r"转[^。；\n]{0,12}原文")
META_RE = re.compile(
    r"任务口径|总量口径|规则\s*[:：]|本清单\s*=|^来源\s*[（(]|"
    r"S\d+\s*(?:原文|逐队|操作表)|" + REFERENCE_RE.pattern)
SPLIT_RE = re.compile(r"[。；;\n|]+|(?=[（(]旧)")


def _resolve(path):
    try:
        return S.resolve_path(path)
    except Exception:
        return Path(path)


def _reference_aliases(chunk):
    citations = chunk.get("citation_authority") or {}
    revision = chunk.get("revision") or ""
    game_id = chunk.get("game_id") or ""
    weak = set()
    for alias, cited in citations.items():
        if cited.get("authority") != "authoritative":
            weak.add(alias)
        elif cited.get("status") and cited["status"] != "verified_read":
            weak.add(alias)
        elif cited.get("revision") != revision:
            same_game_multi = revision.endswith("_multi") and cited.get("game_id") == game_id
            if not same_game_multi:
                weak.add(alias)
    return weak


def _context(path, line_start, reference_aliases=None):
    reference_aliases = reference_aliases or set()
    p = _resolve(path)
    if not p.is_file():
        return None
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None
    current = []
    local = False
    reference_context = False
    scopes = []
    for line in lines[:max(0, line_start - 1)]:
        heading = HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            while scopes and scopes[-1][0] >= level:
                scopes.pop()
            parent_reference = scopes[-1][1] if scopes else False
            current = SOURCE_RE.findall(line)
            local = bool(LOCAL_RE.search(line))
            if local:
                current = []
            reference_context = (False if local else
                                 parent_reference or bool(REFERENCE_RE.search(line))
                                 or bool(set(current) & reference_aliases))
            scopes.append((level, reference_context))
        elif LOCAL_CONTEXT_RE.match(line):
            local = True
            reference_context = False
            current = []
        elif LOCAL_RE.search(line):
            local = True
            reference_context = False
            current = []
        elif SOURCE_RE.search(line):
            current = SOURCE_RE.findall(line)
            local = False
    return current, local, reference_context, scopes


def _classify(segment, inherited, front_matter=False, local_context=False,
              reference_context=False, reference_aliases=None):
    if RETRACT_RE.search(segment):
        return "retracted"
    if front_matter or META_RE.search(segment):
        return "reference_only"
    if LOCAL_RE.search(segment):
        return "authoritative"
    if set(inherited) & (reference_aliases or set()):
        return "reference_only"
    if local_context or reference_context:
        return "reference_only"
    return "authoritative"


def assess(q, chunk, tokens_fn):
    """只判问句实际聚焦的片段；混合块保留合格片段，不整块连坐。"""
    reference_aliases = _reference_aliases(chunk)
    context = _context(chunk.get("path", ""), chunk.get("line_start", 1), reference_aliases)
    if context is None:
        return {"policy": "strict", "eligible": False, "reason": "source_unreadable",
                "relevant_segments": 0, "eligible_segments": 0,
                "reference_segments": 0, "retracted_segments": 0,
                "evidence_excerpt": None}
    inherited, local_context, reference_context, scopes = context
    scopes = list(scopes)
    from .kb_answer import _position_subjects, POSITION_SUBJECT_ALIASES
    subjects = _position_subjects(q)
    variants = {name: [name] + POSITION_SUBJECT_ALIASES.get(name, []) for name in subjects}
    subject_context = None
    pattern = focus_pattern(q)
    segments = []
    for line in (chunk.get("text") or "").splitlines():
        heading = HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            while scopes and scopes[-1][0] >= level:
                scopes.pop()
            parent_reference = scopes[-1][1] if scopes else False
            inherited = SOURCE_RE.findall(line)
            local_context = bool(LOCAL_RE.search(line))
            if local_context:
                inherited = []
            reference_context = (False if local_context else
                                 parent_reference or bool(REFERENCE_RE.search(line))
                                 or bool(set(inherited) & reference_aliases))
            scopes.append((level, reference_context))
            subject_context = None
            continue
        if LOCAL_CONTEXT_RE.match(line):
            local_context = True
            reference_context = False
            inherited = []
        elif LOCAL_RE.search(line):
            local_context = True
            reference_context = False
            inherited = []
        elif SOURCE_RE.search(line):
            inherited = SOURCE_RE.findall(line)
            local_context = False
        for part in SPLIT_RE.split(line):
            seg = part.strip(" \t*-=>")
            if len(seg) < 2:
                continue
            state = _classify(seg, inherited, local_context=local_context,
                              reference_context=reference_context,
                              reference_aliases=reference_aliases)
            if subjects and any(variant in seg for names in variants.values() for variant in names):
                subject_context = (seg, state)
            elif (subjects and subject_context and pattern and pattern.search(seg)
                  and not any(variant in seg for names in variants.values() for variant in names)):
                subject, subject_state = subject_context
                if "retracted" in (state, subject_state):
                    state = "retracted"
                elif "reference_only" in (state, subject_state):
                    state = "reference_only"
                seg = subject + "\n" + seg
            segments.append((seg, state))
    terms = focus_terms(q, tokens_fn) | expand_terms(q, tokens_fn)
    scored = []
    for seg, state in segments:
        overlap = terms & set(tokens_fn(seg))
        shape = bool(pattern and pattern.search(seg))
        scored.append((seg, state, overlap, len(overlap) * 10 + int(shape) * 20))
    relevant = [r for r in scored if r[2]]
    judged = relevant or scored
    eligible = [r for r in judged if r[1] == "authoritative"]
    eligible.sort(key=lambda r: (-r[3], r[0]))
    counts = {state: sum(r[1] == state for r in judged)
              for state in ("authoritative", "reference_only", "retracted")}
    reason = "eligible_fragment" if eligible else "no_eligible_fragment"
    if eligible:
        eligible_terms = [set(tokens_fn(r[0])) for r in eligible]
        for retracted in (r for r in relevant if r[1] == "retracted"):
            retracted_terms = set(tokens_fn(retracted[0]))
            if any(len(retracted_terms & terms) >= 2 for terms in eligible_terms):
                eligible = []
                reason = "retracted_claim_conflict"
                break
    return {"policy": "strict", "eligible": bool(eligible),
            "reason": reason,
            "relevant_segments": len(relevant), "eligible_segments": len(eligible),
            "reference_segments": counts["reference_only"],
            "retracted_segments": counts["retracted"],
            "evidence_excerpt": eligible[0][0][:240] if eligible else None}

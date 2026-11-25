# -*- coding: utf-8 -*-
"""本地文献知识库（LM 知识库）：清洗 → 按版本切块 → BM25 → 状态闸门。

治的病：来源库解决了「去哪个站搜」，但正文知识仍散在 12 份取证 md 里，要用只能整份读，
没法用白话问题命中，也没法区分「日版原版 / CN hack / 98UM / ECK」——同名异版混喂正是
11-18 结案的坑（1079 行 98UM 官方指令表不是 ECK 卡的权威）。

本模块把正文变成可检索、带身份与状态的知识库：
  * corpus_map.json 是语料主数据：每份正文必须绑定库内 source_id（且该文件必须在这个来源的
    evidence 列表里，不许凭文件名猜）+ game_revision_id + authority（权威/二手/跨版本/无关）。
  * build：清洗网页噪声（导航/JS/CSS/纯链接行）→ prose 按段落切、table 按行切 →
    中文 bigram + ASCII 词 + 十六进制地址分词 → BM25 倒排；按源文件 sha256 增量重建。
  * query：域路由（域外零语料拒答）→ 按 game/revision/platform/要素过滤 → BM25 排序
    （可选稠密增强 union12 池，见 kb_dense）→ 逐事实可答性核查 → top3 附条件权威闸门；
    命中必回 source_id + status + authority + path#line；只有快照/二手/跨版本支撑
    => inconclusive，不冒充已验证；权威件非最高分位时 pass 必带 condition 字段。
  * audit：取证覆盖（verified_read 的每份 evidence 必须在册或显式排除并给理由）/ 来源绑定 /
    身份错配 / 索引 sha 与正文 sha 同步 / 每个版本是否有权威正文（无则 inconclusive）。

运行（在 F:\\开源掌机教程\\_工具脚本 下）:
  py -3 -m taspipe.kb build
  py -3 -m taspipe.kb query --q "燕返 怎么触发" --revision nekketsu_soccer2_fc_jp
  py -3 -m taspipe.kb query --q "球权 内存地址" --game nekketsu_soccer2 --want 必杀宏,bug
  py -3 -m taspipe.kb audit
  py -3 -m taspipe.kb show
"""
import argparse
import hashlib
import json
import math
import re
import sys
import time
import unicodedata
import uuid
from collections import Counter
from pathlib import Path

from .schema import SchemaError, Verdict
from . import sources as S
from . import kb_dense
from .kb_route import (DOMAINS, route, route_many, domain_route, in_scope,
                       expand_terms, version_hints, TITLE_SCORING_STOP,
                       ATTRIBUTION_SCORING_STOP, TEAM_SIZE_Q, TEAM_BATTLE_Q,
                       TEAM_SIZE_SCORING_STOP, TEAM_BATTLE_SCORING_STOP,
                       MULTIPLAYER_MODE_Q, TEAM_SHOT_Q, TECHNIQUE_ASK_Q,
                       CAPABILITY_LIST_Q, CAPABILITY_LIST_RE,
                       MULTIPLAYER_SCORING_STOP, TEAM_SHOT_SCORING_STOP,
                       TECHNIQUE_SCORING_STOP, CAPABILITY_SCORING_STOP,
                       PLAYER_ROLE_SCORING_STOP)
from .kb_answer import (annotate, _position_subjects, _position_subject_ok, _team_shot_ok,
                        team_shot_subject, technique_subject, multiplayer_player,
                        multiplayer_asks_pk, EXCLUSIVE_ATTRIBUTION_Q,
                        INPUT_SEQUENCE_Q, PLAYER_ROLE_Q)

ROOT = Path(__file__).resolve().parent
KB_DIR = ROOT / "游戏包" / "知识库"
CORPUS_MAP = KB_DIR / "corpus_map.json"
INDEX_JSON = KB_DIR / "index.json"


def hybrid_index_path():
    """hybrid 富集索引路径（base 同目录 index_hybrid.json）。

    跟随 INDEX_JSON 而非写死 KB_DIR：探针 patch INDEX_JSON 进临时目录时，
    富集件也落在临时目录（不存在 => 退回 base），不读真实生产富集件。
    """
    return INDEX_JSON.with_name("index_hybrid.json")

KINDS = ("prose", "table", "code")
AUTHORITY = ("authoritative", "reference_only", "cross_version", "not_applicable")
MAP_KEYS = {"schema_version", "revisions", "entries"}
REV_KEYS = {"game_id", "platform", "name", "note"}
ENTRY_KEYS = {"path", "source_id", "revision", "kind", "authority", "index",
              "reason", "element_types", "note", "hybrid_only", "citations"}

MAX_CHARS = 700
HARD_MAX = 1200
ROWS_PER_CHUNK = 25
K1 = 1.5
B = 0.75
CLEAN_VERSION = 2
TOKEN_VERSION = 4
CHUNK_VERSION = 5
JA_BODY_MAX = 300
KANA_THRESHOLD = 0.30
PIPELINE = (f"clean{CLEAN_VERSION}|tok{TOKEN_VERSION}|chunk{CHUNK_VERSION}"
            f"|max{MAX_CHARS}|hard{HARD_MAX}|rows{ROWS_PER_CHUNK}|ja{JA_BODY_MAX}")

LINK_RE = re.compile(r"!?\[[^\]]*\]\([^)]*\)")
ARROWS = "↓↘→←↙↑↖↗↔⇒"
CJK_RUN = re.compile(r"[\u4e00-\u9fff" + ARROWS + r"]+")
KANA_RUN = re.compile(r"[\u3040-\u30ff]+")
ARROW_RE = re.compile(r"[" + ARROWS + r"]{2,}")
ASCII_RE = re.compile(r"[a-z][a-z0-9_]+|\d+[a-z][a-z0-9_]*|\d+")
FULLWIDTH_ALNUM = str.maketrans(
    "０１２３４５６７８９ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"
    "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ",
    "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
HEX_RE = re.compile(r"(?:0x|\$)[0-9A-Fa-f]{2,4}|\b[0-9A-F]{4}\b")
ATX_RE = re.compile(r"^#{1,6}\s+")
SETEXT_RE = re.compile(r"^[=\-]{3,}$")
JS_HINT = ("var ", "(function", "function(", "window.", "document.", "@supports",
           "baxiaCommon", "gtag", "dataLayer", "/*", "*/", "console.", "jQuery",
           "STYLEID", "contentPageIndex", "wapUrl", "createElement")
NAV_WORDS = {
    "首页", "登录", "注册", "登录/注册", "网站导航", "设为首页", "收藏本站", "切换到窄版",
    "返回顶部", "更多", "分享", "评论", "收藏", "下载", "客户端", "新闻", "体育", "汽车",
    "科技", "财经", "娱乐", "游戏", "单机游戏", "网络游戏", "电视游戏", "手机游戏",
    "网页游戏", "攻略", "秘籍", "补丁", "修改器", "存档", "论坛", "博客", "专栏", "视频",
    "直播", "专题", "排行榜", "开服表", "发号", "礼包", "商城", "会员", "搜索", "导航",
    "菜单", "上一页", "下一页", "返回列表", "打印", "关闭", "原创", "阅读", "关注",
    "トップページに戻る", "资料", "文", "讯", "章", "攻", "略",
}


def _sha256(b):
    return hashlib.sha256(b).hexdigest()


def _sha1(t):
    return hashlib.sha1(t.encode("utf-8")).hexdigest()


def today():
    return time.strftime("%Y-%m-%d")


# ---------------------------------------------------------------- 语料主数据

def load_map(path=None):
    p = Path(path or CORPUS_MAP)
    if not p.is_file():
        raise SchemaError(f"语料主数据不存在: {p}（先 authoring corpus_map.json）")
    try:
        m = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise SchemaError(f"corpus_map 读不出 JSON: {e}")
    unknown = sorted(set(m) - MAP_KEYS)
    if unknown:
        raise SchemaError(f"corpus_map 未知字段 {unknown}")
    revs = m.get("revisions") or {}
    if not revs:
        raise SchemaError("corpus_map 缺 revisions（身份分区表）")
    for rid, r in revs.items():
        if not isinstance(r, dict):
            raise SchemaError(f"revision {rid} 必须是对象")
        bad = sorted(set(r) - REV_KEYS)
        if bad:
            raise SchemaError(f"revision {rid} 未知字段 {bad}")
        for k in ("game_id", "platform", "name"):
            if not r.get(k):
                raise SchemaError(f"revision {rid} 缺 {k}")
        if r["platform"] not in S.PLATFORMS:
            raise SchemaError(f"revision {rid} 平台 {r['platform']!r} 不在 {S.PLATFORMS}")
    entries = m.get("entries") or []
    if not entries:
        raise SchemaError("corpus_map 缺 entries")
    seen = set()
    for e in entries:
        if not isinstance(e, dict):
            raise SchemaError("entry 必须是对象")
        bad = sorted(set(e) - ENTRY_KEYS)
        if bad:
            raise SchemaError(f"entry {e.get('path')!r} 未知字段 {bad}")
        for k in ("path", "source_id", "revision", "kind", "authority"):
            if not e.get(k):
                raise SchemaError(f"entry {e.get('path')!r} 缺 {k}")
        if e["kind"] not in KINDS:
            raise SchemaError(f"entry {e['path']} kind {e['kind']!r} 不在 {KINDS}")
        if e["authority"] not in AUTHORITY:
            raise SchemaError(f"entry {e['path']} authority {e['authority']!r} 不在 {AUTHORITY}")
        if e["revision"] not in revs:
            raise SchemaError(f"entry {e['path']} revision {e['revision']!r} 未定义")
        if not re.fullmatch(r"[a-z0-9_]+", e["source_id"]):
            raise SchemaError(f"entry source_id 非法 {e['source_id']!r}")
        key = str(S.resolve_path(e["path"]))
        if key in seen:
            raise SchemaError(f"同一份正文登记两次: {e['path']}")
        seen.add(key)
        if e.get("index", True) is False and not e.get("reason"):
            raise SchemaError(f"entry {e['path']} 排除索引必须给 reason（不许静默跳过）")
        if "hybrid_only" in e:
            if not isinstance(e["hybrid_only"], bool):
                raise SchemaError(f"entry {e['path']} hybrid_only 必须是布尔")
            if e["hybrid_only"] and e.get("index", True) is not False:
                raise SchemaError(f"entry {e['path']} hybrid_only 只能挂在 index:false 件上"
                                  "（base 排除、仅 hybrid 富集索引收录）")
        for w in e.get("element_types") or []:
            if w not in S.ELEMENT_TYPES:
                raise SchemaError(f"entry {e['path']} 要素类型未知 {w!r}")
    for e in entries:
        if "citations" not in e:
            continue
        if not isinstance(e["citations"], dict):
            raise SchemaError(f"entry {e['path']} citations 必须是别名到正文路径的对象")
        own_key = str(S.resolve_path(e["path"]))
        for alias, target in e["citations"].items():
            if not re.fullmatch(r"S\d+", alias):
                raise SchemaError(f"entry {e['path']} 引用别名非法 {alias!r}")
            if not isinstance(target, str) or not target:
                raise SchemaError(f"entry {e['path']} 引用 {alias} 缺正文路径")
            target_key = str(S.resolve_path(target))
            if target_key not in seen:
                raise SchemaError(f"entry {e['path']} 引用 {alias} 指向未登记正文 {target!r}")
            if target_key == own_key:
                raise SchemaError(f"entry {e['path']} 不得引用自身来洗白来源资格")
    return m


def _citation_authority(entry, corpus_map, by_source=None):
    by_path = {str(S.resolve_path(e["path"])): e for e in corpus_map["entries"]}
    resolved = {}
    for alias, target in (entry.get("citations") or {}).items():
        cited = by_path[str(S.resolve_path(target))]
        rev = corpus_map["revisions"][cited["revision"]]
        source = (by_source or {}).get(cited["source_id"])
        resolved[alias] = {
            "path": cited["path"], "source_id": cited["source_id"],
            "authority": cited["authority"], "revision": cited["revision"],
            "game_id": rev["game_id"],
            "status": source.get("status") if source else None,
        }
    return resolved


def _citation_sha(authority):
    payload = json.dumps(authority, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return _sha256(payload)


# ---------------------------------------------------------------- 清洗与切块

def _is_chrome(s):
    if any(h in s for h in JS_HINT):
        return True
    if "javascript:" in s or "member.php" in s:
        return True
    if "{" in s and "}" in s and re.search(r"\d+px|position:|color:|margin:|padding:", s):
        return True
    if LINK_RE.search(s):
        bare = LINK_RE.sub("", s)
        bare = re.sub(r"[\s\|\*\-#>·:：,，。\.!！\[\]\(\)]+", "", bare)
        if len(bare) < 6:
            return True
    if s in NAV_WORDS:
        return True
    if not re.sub(r"[\s\|]+", "", s):
        return True
    if s.startswith("http") and not CJK_RUN.search(s):
        return True
    return False


def clean(text):
    """返回 ([(原行号, 行文本或空串)], 丢弃行数)。空串保留作段落边界。"""
    kept, dropped = [], 0
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s:
            kept.append((i, ""))
            continue
        if _is_chrome(s):
            dropped += 1
            continue
        kept.append((i, s))
    return kept, dropped


def chunk_prose(lines):
    chunks, buf, start, heading = [], [], None, ""

    def flush(end):
        nonlocal buf, start
        txt = "\n".join(t for _, t in buf).strip()
        if txt:
            chunks.append({"text": txt, "line_start": start, "line_end": end,
                           "heading": heading})
        buf, start = [], None

    for ln, t in lines:
        if ATX_RE.match(t):
            flush(ln - 1)
            heading = ATX_RE.sub("", t).strip()
            continue
        if SETEXT_RE.match(t):
            if buf:
                heading = buf[-1][1].strip()
                buf.pop()
            continue
        if not t:
            if buf and sum(len(x[1]) for x in buf) >= MAX_CHARS:
                flush(ln - 1)
            continue
        if start is None:
            start = ln
        if len(t) > HARD_MAX:
            flush(ln - 1)
            for i in range(0, len(t), HARD_MAX):
                chunks.append({"text": t[i:i + HARD_MAX], "line_start": ln,
                               "line_end": ln, "heading": heading})
            continue
        buf.append((ln, t))
        if sum(len(x[1]) for x in buf) >= HARD_MAX:
            flush(ln)
    flush(lines[-1][0] if lines else 0)
    return chunks


def chunk_table(lines):
    rows = [(ln, t) for ln, t in lines if t]
    chunks = []
    for i in range(0, len(rows), ROWS_PER_CHUNK):
        grp = rows[i:i + ROWS_PER_CHUNK]
        chunks.append({"text": "\n".join(t for _, t in grp),
                       "line_start": grp[0][0], "line_end": grp[-1][0], "heading": ""})
    return chunks


# -------------------------------- v3 日文主导文件：语言同质小段（P1 接线）
# 日文说明书大块混中文标题词会稀释跨语检索；按 `* * *` 章节切 ≤300 字小段并前置
# 章节标题。这类文件是人工转录件，不走网页清洗，行号即原文件行号。
KANA_RE = re.compile(r"[\u3040-\u30ff]")
JA_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
JA_SEP_RE = re.compile(r"^\* \* \*\s*$")


def kana_ratio(text):
    k, c = len(KANA_RE.findall(text)), len(JA_CJK_RE.findall(text))
    return k / (k + c) if k + c else 0.0


def _ja_sections(lines):
    """按 * * * 切章，返回 (start_1based, end_1based, [lines])。"""
    bounds = [i for i, l in enumerate(lines) if JA_SEP_RE.match(l)]
    edges = [-1] + bounds + [len(lines)]
    out = []
    for a, b in zip(edges, edges[1:]):
        seg = lines[a + 1:b]
        if any(l.strip() for l in seg):
            out.append((a + 2, b, seg))
    return out


def _ja_pack(seg_lines, base_line):
    """段落真贪心打包 ≤JA_BODY_MAX：短段落连续合并成一块（参数名+释义不再散落），
    超 300 的段落才按。句切。返回 [(line_start, line_end, body_text)]。"""
    paras, cur, cur_start = [], [], None
    for off, l in enumerate(seg_lines):
        if l.strip():
            if cur_start is None:
                cur_start = base_line + off
            cur.append(l)
        elif cur:
            paras.append((cur_start, base_line + off - 1, cur))
            cur, cur_start = [], None
    if cur:
        paras.append((cur_start, base_line + len(seg_lines) - 1, cur))

    pieces = []
    buf, buf_s, buf_e = "", None, None

    def flush():
        nonlocal buf, buf_s, buf_e
        if buf:
            pieces.append((buf_s, buf_e, buf))
            buf, buf_s, buf_e = "", None, None

    for s, e, pl in paras:
        text = "\n".join(pl)
        if len(text) <= JA_BODY_MAX:
            if buf and len(buf) + 1 + len(text) > JA_BODY_MAX:
                flush()
            if buf:
                buf += "\n" + text
                buf_e = e
            else:
                buf, buf_s, buf_e = text, s, e
            continue
        flush()
        sents = re.split(r"(?<=。)", text)
        sent_bounds, offset = [], 0
        for sent in sents:
            n = sent.count("\n")
            sent_bounds.append((offset, offset + n))
            offset += n
        sbuf, sbuf_s, sbuf_e = "", s, s
        pos = s
        for sent, (first_nl, last_nl) in zip(sents, sent_bounds):
            if not sent:
                continue
            if sbuf and len(sbuf) + len(sent) > JA_BODY_MAX:
                pieces.append((sbuf_s, sbuf_e, sbuf))
                sbuf, sbuf_s, sbuf_e = "", pos, s + first_nl - 1
            if len(sent) > JA_BODY_MAX:
                for i in range(0, len(sent), JA_BODY_MAX):
                    pieces.append((pos, s + last_nl, sent[i:i + JA_BODY_MAX]))
                pos = s + last_nl
            else:
                sbuf += sent
                sbuf_e = s + last_nl
            pos = s + last_nl + 1
        if sbuf:
            pieces.append((sbuf_s, sbuf_e, sbuf))
    flush()
    return pieces


def chunk_ja(raw_lines):
    """日文主导 prose：章节小段 + 前置＜…＞章节标题。返回与 chunk_prose 同构的块。"""
    chunks = []
    for s, e, seg in _ja_sections(raw_lines):
        heading = next((l.strip() for l in seg if "＜" in l and "＞" in l), "")
        heading = heading.strip("* ").strip()
        for ps, pe, body in _ja_pack(seg, s):
            text = (heading + "\n" + body) if heading else body
            chunks.append({"text": text, "line_start": ps, "line_end": pe,
                           "heading": heading, "lang": "ja"})
    return chunks


def tokens(text):
    # 全角字母数字归一（２Ｐ→2p），否则日文说明书里的全角标识符永远不成词
    norm = text.translate(FULLWIDTH_ALNUM)
    low = norm.lower()
    out = ASCII_RE.findall(low)
    out += [m.lower() for m in HEX_RE.findall(norm)]
    out += ARROW_RE.findall(text)
    for run in CJK_RUN.findall(text):
        if len(run) == 1:
            out.append(run)
            continue
        if 2 <= len(run) <= 6:
            out.append(run)
        out += [run[i:i + 2] for i in range(len(run) - 1)]
    # 假名串与汉字串同待遇：整词（≤6）+ bigram。治纯假名块 dl=0 被 BM25 永久看不见
    for run in KANA_RUN.findall(norm):
        if len(run) == 1:
            out.append(run)
            continue
        if 2 <= len(run) <= 6:
            out.append(run)
        out += [run[i:i + 2] for i in range(len(run) - 1)]
    return out


# ---------------------------------------------------------------- 构建索引

def load_index(path=None):
    p = Path(path or INDEX_JSON)
    if not p.is_file():
        return None
    try:
        idx = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise SchemaError(f"知识库索引读不出 JSON: {e}")
    for k in ("chunks", "postings", "files", "stats"):
        if k not in idx:
            raise SchemaError(f"索引缺 {k}（跑 kb build 重建）")
    return idx


def build(map_path=None, index_path=None, reg=None, force=False, hybrid=False):
    m = load_map(map_path)
    reg = reg or S.load_registry()
    by_id = {s["source_id"]: s for s in reg["sources"]}
    ip = Path(index_path or INDEX_JSON)
    old = None if force else load_index(ip)
    old_by_path = {}
    for c in (old or {}).get("chunks", []):
        old_by_path.setdefault(c["path"], []).append(c)

    chunks, files, report = [], {}, []
    postings = {}
    for e in m["entries"]:
        if e.get("index", True) is False:
            # hybrid 富集索引收录 hybrid_only 件（base 仍排除）；其余 index:false 一律排除
            if not (hybrid and e.get("hybrid_only")):
                files[e["path"]] = {"indexed": False, "reason": e["reason"]}
                report.append({"path": e["path"], "indexed": False, "reason": e["reason"]})
                continue
        p = S.resolve_path(e["path"])
        if not p.is_file():
            raise SchemaError(f"语料文件不存在: {e['path']} -> {p}")
        if e["source_id"] not in by_id:
            raise SchemaError(f"entry {e['path']} 的 source_id {e['source_id']!r} 不在来源库（先 ingest）")
        raw = p.read_bytes()
        sha = _sha256(raw)
        prev = (old or {}).get("files", {}).get(e["path"]) or {}
        reuse = bool(prev.get("sha256") == sha and old_by_path.get(e["path"])
                     and (old or {}).get("pipeline") == PIPELINE)
        if reuse:
            payload = [{"text": c["text"], "line_start": c["line_start"],
                        "line_end": c["line_end"], "heading": c.get("heading", ""),
                        "lang": c.get("lang", "zh"),
                        "text_sha": c["text_sha"], "dl": c["dl"]}
                       for c in old_by_path[e["path"]]]
            dropped = prev.get("dropped_lines", 0)
        else:
            text = raw.decode("utf-8", errors="replace")
            lines, dropped = clean(text)
            if e["kind"] == "table":
                raw_chunks = chunk_table(lines)
            elif e["kind"] == "prose" and kana_ratio(
                    "\n".join(t for _, t in lines)) > KANA_THRESHOLD:
                # 日文主导转录件：原行号小段切块，不走网页清洗（无网页噪声可丢）
                raw_chunks = chunk_ja(text.splitlines())
                dropped = 0
            else:
                raw_chunks = chunk_prose(lines)
            payload = []
            for c in raw_chunks:
                tf = Counter(tokens(c["text"]))
                payload.append({**c, "lang": c.get("lang", "zh"),
                                "text_sha": _sha1(c["text"]), "dl": sum(tf.values()),
                                "_tf": dict(tf)})
        rev = m["revisions"][e["revision"]]
        src = by_id[e["source_id"]]
        citation_authority = _citation_authority(e, m, by_id)
        for c in payload:
            # ja 小段存在同行号多块（超长句硬切），cid 必须带 text_sha 防碰撞
            cid_src = f"{e['path']}|{c['line_start']}|{c['line_end']}"
            if c.get("lang") == "ja":
                cid_src += f"|{c['text_sha']}"
            cid = _sha1(cid_src)[:12]
            tf = c.get("_tf")
            if tf is None:
                tf = dict(Counter(tokens(c["text"])))
            chunks.append({
                "chunk_id": cid, "path": e["path"], "source_id": e["source_id"],
                "revision": e["revision"], "game_id": rev["game_id"],
                "platform": rev["platform"], "authority": e["authority"],
                "citation_authority": citation_authority,
                "status": src["status"], "last_verified": src.get("last_verified"),
                "element_types": e.get("element_types") or src["element_types"],
                "kind": e["kind"], "heading": c.get("heading", ""),
                "lang": c.get("lang", "zh"),
                "line_start": c["line_start"], "line_end": c["line_end"],
                "text": c["text"], "text_sha": c["text_sha"], "dl": c["dl"],
            })
            for term, n in tf.items():
                postings.setdefault(term, []).append([len(chunks) - 1, n])
        files[e["path"]] = {"indexed": True, "sha256": sha, "bytes": len(raw),
                            "dropped_lines": dropped, "n_chunks": len(payload),
                            "citation_sha256": _citation_sha(citation_authority),
                            "reused": reuse}
        report.append({"path": e["path"], "indexed": True, "chunks": len(payload),
                       "dropped_lines": dropped, "reused": reuse,
                       "revision": e["revision"], "authority": e["authority"],
                       "citation_aliases": sorted((e.get("citations") or {}).keys())})

    n = len(chunks)
    avgdl = (sum(c["dl"] for c in chunks) / n) if n else 0.0
    idx = {"schema_version": 1, "built_at": today(), "pipeline": PIPELINE,
           "stats": {"N": n, "avgdl": avgdl, "terms": len(postings)},
           "files": files, "chunks": chunks, "postings": postings}
    ip.parent.mkdir(parents=True, exist_ok=True)
    tmp = ip.with_name(ip.name + ".tmp")
    tmp.write_text(json.dumps(idx, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(ip)
    return {"status": "built", "index": str(ip), "chunks": n, "terms": len(postings),
            "files_indexed": sum(1 for f in files.values() if f.get("indexed")),
            "files_excluded": sum(1 for f in files.values() if not f.get("indexed")),
            "bytes": ip.stat().st_size, "report": report}


# ---------------------------------------------------------------- 检索

def _filters(c, game, revision, platform, want, rev_game):
    if game and c["game_id"] != game:
        return False
    if revision and c["revision"] != revision and c["game_id"] != rev_game:
        return False
    if platform and c["platform"] != platform and c["platform"] != "ANY":
        return False
    if want and not (set(want) & set(c["element_types"] or [])):
        return False
    return True


def _score_query_terms(q, terms, has_filters):
    focused_shape = (PLAYER_ROLE_Q.search(q) or TEAM_SIZE_Q.search(q)
                     or TEAM_BATTLE_Q.search(q) or MULTIPLAYER_MODE_Q.search(q)
                     or TEAM_SHOT_Q.search(q) or TECHNIQUE_ASK_Q.search(q)
                     or CAPABILITY_LIST_Q.search(q))
    if not has_filters and not focused_shape:
        return terms, None, []
    if EXCLUSIVE_ATTRIBUTION_Q.search(q):
        mode, stop = "attribution", ATTRIBUTION_SCORING_STOP
    elif INPUT_SEQUENCE_Q.search(q):
        mode, stop = "input_sequence", TITLE_SCORING_STOP
    elif MULTIPLAYER_MODE_Q.search(q):
        mode, stop = "multiplayer_mode", MULTIPLAYER_SCORING_STOP
    elif TEAM_SHOT_Q.search(q):
        mode, stop = "team_shot", TEAM_SHOT_SCORING_STOP
    elif TECHNIQUE_ASK_Q.search(q):
        mode, stop = "technique", TECHNIQUE_SCORING_STOP
    elif CAPABILITY_LIST_Q.search(q):
        mode, stop = "capability_list", CAPABILITY_SCORING_STOP
    elif PLAYER_ROLE_Q.search(q):
        mode, stop = "player_role", PLAYER_ROLE_SCORING_STOP
    elif TEAM_SIZE_Q.search(q):
        mode, stop = "team_size", TEAM_SIZE_SCORING_STOP
    elif TEAM_BATTLE_Q.search(q):
        mode, stop = "team_battle", TEAM_BATTLE_SCORING_STOP
    else:
        return terms, None, []
    removed = sorted(t for t in terms if t in stop)
    return {t for t in terms if t not in stop}, mode, removed


def _select_index(index_path):
    """选索引 + 定 BM25 统计量口径。返回 (索引路径, domain_local)。

    显式 index_path：尊重调用方（文件名 index_hybrid.json => 域内）。
    默认（None）：hybrid 富集件就绪 => 富集 + 域内 IDF；否则 base + 全局（现状不变）。
    bm25 兜底臂永远走 base 全局，构造上不受富集影响（P10）。
    """
    if index_path is not None:
        p = Path(index_path)
        return p, p.name == "index_hybrid.json"
    hp = hybrid_index_path()
    ready, _reason = kb_dense.ready(hp)
    if ready:
        return hp, True
    return INDEX_JSON, False


def _bm25_scores(idx, chunks, cand, qt, domain_local):
    """候选内 BM25 打分，返回 (scores, matched, order)。

    domain_local=False：全局统计量（idx.stats N/avgdl + 全局 df），base 主干逐字原样。
    domain_local=True：域内统计量（N=候选池长、df=池内计数、avgdl=池均值），
      隔离跨域全局 IDF 位移（P9 诊断：再索引加外域块使全局 N/avgdl 漂移，
      经 anchor_top8 把无关域金标挤出 hits；域内口径令本域统计量不受外域影响）。
    """
    cand_set = set(cand)
    if domain_local:
        N = len(cand)
        avgdl = (sum(chunks[ci]["dl"] for ci in cand) / N) if N else 1.0
    else:
        N, avgdl = idx["stats"]["N"], idx["stats"]["avgdl"] or 1.0
    scores = {}
    matched = {}
    for term in qt:
        post = idx["postings"].get(term)
        if not post:
            continue
        if domain_local:
            df = sum(1 for ci, _ in post if ci in cand_set)
            if df == 0:
                continue
        else:
            df = len(post)
        idf = math.log(1 + (N - df + 0.5) / (df + 0.5))
        for ci, tf in post:
            if ci not in cand_set:
                continue
            dl = chunks[ci]["dl"] or 1
            scores[ci] = scores.get(ci, 0.0) + idf * tf * (K1 + 1) / (
                tf + K1 * (1 - B + B * dl / avgdl))
            matched.setdefault(ci, []).append(term)
    order = sorted(scores, key=lambda ci: (-scores[ci], ci))
    return scores, matched, order


def _query_base(q, game=None, revision=None, platform=None, want=None, topk=8,
                require_verified=False, index_path=None, reg=None, map_path=None,
                top_window=3, domain=None, fragment_policy=None):
    if not q or not q.strip():
        raise SchemaError("query 需 --q（问题或术语），别空检索")
    if isinstance(want, str):
        want = [w.strip() for w in want.split(",") if w.strip()]
    for w in want or []:
        if w not in S.ELEMENT_TYPES:
            raise SchemaError(f"未知要素类型 {w!r}，允许 {S.ELEMENT_TYPES}")
    used_index, domain_local = _select_index(index_path)
    idx = load_index(used_index)
    if idx is None:
        return {"status": "not_built", "q": q,
                "reason": "知识库索引不存在，先跑 kb build", "hits": [],
                "counts": {"candidates": 0, "hits": 0}}
    m = load_map(map_path)
    entries_by_path = {e["path"]: e for e in m["entries"]}
    if revision and revision not in m["revisions"]:
        raise SchemaError(f"revision {revision!r} 未在 corpus_map 定义")
    rev_game = m["revisions"][revision]["game_id"] if revision else None
    if platform:
        platform = S.norm_platform(platform)
    chunks = idx["chunks"]
    if domain is not None and domain not in DOMAINS:
        raise SchemaError(f"未知知识域 {domain!r}；允许 {sorted(DOMAINS)}")
    r = domain_route(domain) if domain is not None else route(q)
    has_filters = bool(game or revision or platform)
    base = {"q": q, "game": game, "revision": revision, "platform": platform,
            "want": want or [], "route": r,
            "index_used": Path(used_index).name,
            "index_sha256": hashlib.sha256(Path(used_index).read_bytes()).hexdigest()}
    if fragment_policy:
        base["fragment_policy"] = fragment_policy
    # 问句版本钉（阶段1信息层）：只暴露线索，不改过滤/打分。
    # 显式 --revision 仍是唯一权威过滤；同名异版混喂的判定改动属后续阶段。
    vh = version_hints(q)
    if vh:
        base["version_hints"] = vh
    # 域外零语料拒答：仅在无显式身份过滤时成立（显式 game/revision/platform 是权威意图）
    if not r["corpus_available"] and (domain is not None or not has_filters):
        return {**base, "status": "miss", "hits": [], "refusal": "out_of_scope",
                "counts": {"candidates": 0, "hits": 0},
                "reason": f"路由到 {r['domain']}（命中 {r['matched']}），该域库内零语料"
                          "（不是『不存在』，只是本地没收集）",
                "next": "sources route 延伸段；新域语料 ingest 后 kb build"}
    cand = [i for i, c in enumerate(chunks)
            if ((has_filters and domain is None) or in_scope(c, r))
            and _filters(c, game, revision, platform, want, rev_game)]
    position_subjects = _position_subjects(q)
    if position_subjects:
        focused = [i for i in cand if _position_subject_ok(q, chunks[i]["text"])]
        if focused:
            cand = focused
            base["candidate_focus"] = {"position_subjects": position_subjects,
                                       "candidates": len(cand)}
    team_subject = team_shot_subject(q)
    if team_subject:
        focused = [i for i in cand if _team_shot_ok(q, chunks[i]["text"])]
        if focused:
            cand = focused
            base["candidate_focus"] = {"team_shot_subject": team_subject,
                                       "candidates": len(cand)}
    technique = technique_subject(q)
    if technique:
        focused = [i for i in cand if technique in chunks[i]["text"]]
        if focused:
            cand = focused
            base["candidate_focus"] = {"technique": technique, "candidates": len(cand)}
    player = multiplayer_player(q)
    asks_pk = multiplayer_asks_pk(q)
    if player or asks_pk:
        focused = []
        for i in cand:
            text = unicodedata.normalize("NFKC", chunks[i]["text"]).upper()
            if player and not re.search(r"(?<!\d)" + player + r"\s*P", text):
                continue
            if asks_pk and not re.search(r"PK\s*(?:战|戦)", text):
                continue
            focused.append(i)
        if focused:
            cand = focused
            base["candidate_focus"] = {"multiplayer_player": player, "pk": asks_pk,
                                       "candidates": len(cand)}
    if CAPABILITY_LIST_Q.search(q):
        focused = [i for i in cand if CAPABILITY_LIST_RE.search(chunks[i]["text"])]
        if focused:
            cand = focused
            base["candidate_focus"] = {"capability_list": True, "candidates": len(cand)}
    base["counts"] = {"candidates": len(cand)}
    if not cand:
        return {**base, "status": "miss", "hits": [],
                "reason": "库内没有该身份/要素的正文（不是『不存在』，只是本地没收集）",
                "next": "走 sources route 的 primary→extension；命中后 log 落取证 + kb build"}
    qt = set(tokens(q))
    # 规则式跨语扩展：中文触发词 → 日文表层形式（只影响 BM25 查询侧，稠密仍用原问句）
    extra = expand_terms(q, tokens)
    if extra:
        base["query_expansion"] = sorted(extra)
        qt |= extra
    score_qt, term_mode, removed = _score_query_terms(q, qt, has_filters)
    if term_mode:
        base["query_term_filter"] = {"mode": term_mode, "removed": removed}
    scores, matched, bm25_order = _bm25_scores(idx, chunks, cand, score_qt, domain_local)
    if domain_local:
        base["scoring_note"] = "域内IDF（hybrid 富集臂，隔离跨域全局位移）"
    # 可选稠密增强：指纹件/依赖缺席则退回 BM25 主干，路径明示不静默
    picked, dev, note = kb_dense.enhance(q, chunks, cand, bm25_order,
                                         Path(used_index))
    if picked is not None:
        order = picked[:topk]
        base["retrieval"] = "hybrid_union12"
        base["dense_device"] = dev
    else:
        if domain_local:
            # 运行中降级契约（阶段1）：已选富集索引但增强失败 => 完整重跑
            # base 索引 + 全局 IDF。不许留在富集索引上跑域内 BM25 却标 bm25_only
            # （索引身份/统计口径/结果标签三者必须一致）。
            base_idx = load_index(INDEX_JSON)
            if base_idx is None:
                return {**base, "status": "not_built", "hits": [],
                        "reason": "稠密增强失败且 base 索引不存在，先跑 kb build",
                        "retrieval_note": note,
                        "counts": {**base["counts"], "hits": 0}}
            used_index, domain_local = INDEX_JSON, False
            idx = base_idx
            chunks = idx["chunks"]
            cand = [i for i, c in enumerate(chunks)
                    if ((has_filters and domain is None) or in_scope(c, r))
                    and _filters(c, game, revision, platform, want, rev_game)]
            base["counts"]["candidates"] = len(cand)
            base.pop("scoring_note", None)
            scores, matched, bm25_order = _bm25_scores(idx, chunks, cand, score_qt, False)
            base["retrieval_note"] = (note or "稠密增强未启用") + "；已完整退回 base 索引+全局 IDF"
        else:
            base["retrieval_note"] = note
        order = bm25_order[:topk]
        base["retrieval"] = "bm25_only"
    base["index_used"] = Path(used_index).name
    base["index_sha256"] = hashlib.sha256(Path(used_index).read_bytes()).hexdigest()
    hits = []
    for ci in order:
        c = chunks[ci]
        # 我方跨版本实测件（*_multi）对同一 game_id 的任一版本都算本版本证据
        rev_match = (revision is None or c["revision"] == revision
                     or (c["revision"].endswith("_multi") and rev_game is not None
                         and c["game_id"] == rev_game))
        hits.append({
            "chunk_id": c["chunk_id"], "score": round(scores.get(ci, 0.0), 3),
            "source_id": c["source_id"], "status": c["status"],
            "authority": c["authority"], "revision": c["revision"],
            "game_id": c["game_id"], "platform": c["platform"],
            "revision_match": rev_match,
            "locator": f"{c['path']}#L{c['line_start']}-L{c['line_end']}",
            "heading": c["heading"], "matched_terms": sorted(matched.get(ci, []))[:12],
            "snippet": c["text"][:240],
        })
    base["counts"]["hits"] = len(hits)
    if not hits:
        return {**base, "status": "miss", "hits": [],
                "reason": f"有 {len(cand)} 个候选块但无一词命中（换术语或扩大要素类型）",
                "next": "sources route 延伸段；新站 ingest 后重 build"}

    def _strong(h):
        if h["status"] != "verified_read" or not h["revision_match"]:
            return False
        if fragment_policy == "strict" and not h.get("fragment_provenance", {}).get("eligible"):
            return False
        if h["authority"] == "authoritative":
            return True
        # 跨版本参考件只有在「问的就是它自己那个版本」时才算该版本的权威
        return (h["authority"] == "cross_version" and revision is not None
                and h["revision"] == revision)

    # 逐事实可答性：词命中 ≠ 回答了问题（P1 接线）；全不可答 => 证据不足拒答
    warns = []
    for h in hits:
        if h["authority"] == "cross_version" and not (revision and h["revision"] == revision):
            warns.append(f"{h['source_id']} 是 {h['revision']} 的跨版本参考件，"
                         f"不得当 {revision or '本地卡'} 的权威依据")
        elif not h["revision_match"]:
            warns.append(f"{h['source_id']} 属 {h['revision']}，与所问 {revision} 不是同一版本，只作线索")
        elif h["authority"] == "reference_only":
            warns.append(f"{h['source_id']} 是二手件（reference_only），须与官方件或我方实测交叉核对")
    base["authority_warnings"] = warns
    by_id = {h["chunk_id"]: ci for h, ci in zip(hits, order)}
    for h in hits:
        c = chunks[by_id[h["chunk_id"]]]
        h["answerability"] = annotate(q, c["text"], tokens, lang=c.get("lang", "zh"))
        if fragment_policy == "strict":
            from . import kb_provenance as KP
            source_by_id = {s["source_id"]: s for s in (reg or S.load_registry())["sources"]}
            entry = entries_by_path.get(c["path"])
            provenance_chunk = {**c, "citation_authority":
                                _citation_authority(entry, m, source_by_id) if entry else {}}
            h["fragment_provenance"] = KP.assess(q, provenance_chunk, tokens)
    answerable = [h for h in hits if h["answerability"]["answerable"]]
    base["counts"]["answerable"] = len(answerable)
    if not answerable:
        return {**base, "status": Verdict.INCONCLUSIVE.value, "hits": hits,
                "refusal": "unanswerable",
                "reason": "命中全部未过逐事实可答性核查（词命中≠回答问题），"
                          "缺证据不冒充事实",
                "next": "换问法重查；或补该事实语料取证后 kb build"}
    # 噪声门：只匹配到单字（如"或"）的块不算证据；多字词/指令串才算内容词
    content_terms = {t for t in qt if len(t) >= 2}
    strong = [h for h in answerable
              if _strong(h)
              and content_terms & set(tokens(chunks[by_id[h["chunk_id"]]]["text"]))]
    base["counts"]["strong"] = len(strong)
    if not strong:
        why = ("可答命中只有快照/二手/跨版本支撑，或本版本权威件只匹配到单字噪声（不算证据）"
               if not require_verified else
               "require_verified 下无 verified_read+authoritative 的可答内容词命中")
        if fragment_policy == "strict":
            why += "；strict 片段资格下无合格证据（二手转述/撤回段不继承整件权威）"
        return {**base, "status": Verdict.INCONCLUSIVE.value, "hits": hits, "reason": why,
                "next": "升 authoritative 须官方件/我方实测；升 verified_read 须真读正文落取证"}
    # 附条件出证（P1 用户批准口径 top_window=3）：窗口内有本版本权威可答件即 pass，
    # 非最高分位时必须携带 condition 字段；证据标准不放松，只是不再卡死 top1
    strong_ids = {h["chunk_id"] for h in strong}
    for rank, h in enumerate(hits[:top_window], 1):
        if h["chunk_id"] in strong_ids:
            res = {**base, "status": Verdict.PASS.value, "hits": hits,
                   "reason": f"{len(strong)} 条 verified_read + authoritative 可答命中，"
                             f"权威件在第 {rank} 位",
                   # 出证绑定（阶段1）：pass 凭哪一块放行，显式落字段。
                   # 下游只许把 selected_evidence 叫"证据"，其余命中是相关资料。
                   # 本阶段只记录现有放行块，不改判定逻辑（判定改动属阶段3）。
                   "selected_evidence": [h]}
            if rank > 1:
                res["condition"] = f"权威可答件在第{rank}位，非最高分；出证须附此条件"
            return res
    best = strong[0]
    return {**base, "status": Verdict.INCONCLUSIVE.value, "hits": hits,
            "reason": (f"top{top_window} 内无本版本权威可答件；权威件 {best['source_id']} 只在低分位"
                       f"（score {best['score']}）⇒ 不得直接下结论"),
            "next": "人工核对最高分件是否真讲所问内容；或换更精确的术语重查"}


def _selector_texts(result, index_path):
    name = result.get("index_used")
    if not name:
        raise SchemaError("选择器无法确定本次检索索引，拒绝用截断 snippet 裁决")
    if index_path is not None and Path(index_path).name == name:
        used = Path(index_path)
    elif name == hybrid_index_path().name:
        used = hybrid_index_path()
    else:
        used = INDEX_JSON
    idx = load_index(used)
    if idx is None:
        raise SchemaError(f"选择器读取索引正文失败：{used}；拒绝降级到 snippet")
    texts = {c["chunk_id"]: c["text"] for c in idx["chunks"]}
    missing = [h.get("chunk_id") for h in result.get("hits", [])
               if h.get("chunk_id") not in texts]
    if missing:
        raise SchemaError(f"选择器缺少 {len(missing)} 个命中块正文，拒绝用 snippet 替代")
    return texts


def _query_inner(q, game=None, revision=None, platform=None, want=None, topk=8,
                 require_verified=False, index_path=None, reg=None, map_path=None,
                 top_window=3, domain=None, fact_selector=None,
                 selector_beyond_window=False, fragment_policy=None):
    if fragment_policy not in (None, "legacy", "strict"):
        raise SchemaError(f"未知 fragment_policy {fragment_policy!r}；允许 legacy/strict")
    if fact_selector not in (None, "audit", "scoped", "replace"):
        raise SchemaError(f"未知 fact_selector {fact_selector!r}；允许 audit/scoped/replace")
    if selector_beyond_window and fact_selector is None:
        raise SchemaError("selector_beyond_window 需同时显式指定 fact_selector")
    result = _query_base(q, game=game, revision=revision, platform=platform,
                         want=want, topk=topk, require_verified=require_verified,
                         index_path=index_path, reg=reg, map_path=map_path,
                         top_window=top_window, domain=domain,
                         fragment_policy=fragment_policy)
    if fact_selector is None or not result.get("hits"):
        return result
    from . import kb_selector as KS
    texts = _selector_texts(result, index_path)
    incumbent = (result.get("selected_evidence") or [{}])[0].get("chunk_id")
    selected = KS.select(q, result["hits"], texts, tokens,
                         production_window=top_window,
                         preferred_chunk_id=incumbent)
    report = {"mode": fact_selector, "fact_class": selected["fact_class"],
              "verdict": selected["verdict"], "selected": selected["selected"],
              "selected_rank": selected["selected_rank"],
              "beyond_window": selected["beyond_window"],
              "counterexample_blocks": selected["counterexample_blocks"],
              "reason": selected["reason"], "per_block": selected["per_block"]}
    result["fact_selector"] = report
    if fact_selector == "audit":
        return result
    if fact_selector == "scoped" and selected["fact_class"] is None:
        return result
    can_pass = result.get("counts", {}).get("strong", 0) > 0
    eligible = selected["verdict"] == "pass" and can_pass
    if eligible and not (selected["beyond_window"] and not selector_beyond_window):
        hit = next(h for h in result["hits"]
                   if h["chunk_id"] == selected["selected"])
        result["status"] = Verdict.PASS.value
        result["selected_evidence"] = [hit]
        result["reason"] = selected["reason"]
        result.pop("refusal", None)
        result.pop("next", None)
        if selected["selected_rank"] > 1:
            result["condition"] = (f"选择器第{selected['selected_rank']}位过七项核查"
                                   + ("；显式允许跨出 top_window" if selected["beyond_window"] else ""))
        else:
            result.pop("condition", None)
        return result
    if eligible:
        reason = (selected["reason"] + f"；位于 top{top_window} 外，"
                  "未显式批准 selector_beyond_window，不扩窗放行")
    else:
        reason = selected["reason"]
        if selected["verdict"] == "pass":
            reason += "；生产强证据门未通过，选择器不得单独放行"
    if result.get("status") != Verdict.PASS.value:
        result["selector_reason"] = reason
        return result
    result["status"] = Verdict.INCONCLUSIVE.value
    result.pop("selected_evidence", None)
    result.pop("condition", None)
    result["refusal"] = "fact_selector_rejected"
    result["reason"] = reason
    result["next"] = "人工核对候选块；显式启用选择器并批准扩窗后才可重判"
    return result


def _nli_shadow_summary(raw):
    if raw is None:
        return None
    if isinstance(raw, list):
        return [_nli_shadow_summary(item) for item in raw]
    return {k: raw.get(k) for k in
            ("status", "decision", "reason", "label", "probabilities", "margin",
             "thresholds", "device", "dtype", "model", "revision", "claim_chars",
             "evidence_chars", "calibration_sha256", "policy", "contract_error")
            if raw.get(k) is not None}


def _run_nli_shadow(result, claim, index_path, device):
    if not claim or not claim.strip():
        return {"status": "not_run", "reason": "claim_required",
                "policy": "shadow_only_no_status_change"}
    selected = (result.get("selected_evidence") or [None])[0]
    if result.get("status") != Verdict.PASS.value or selected is None:
        return {"status": "not_run", "reason": "no_production_pass",
                "policy": "shadow_only_no_status_change"}
    if selected.get("authority") != "authoritative":
        return {"status": "not_run", "reason": "hard_gate_rejected",
                "policy": "shadow_only_no_status_change"}
    provenance = selected.get("fragment_provenance") or {}
    if provenance.get("eligible") is False:
        return {"status": "not_run", "reason": "hard_gate_rejected",
                "policy": "shadow_only_no_status_change"}
    try:
        evidence = provenance.get("evidence_excerpt")
        if not evidence:
            evidence = _selector_texts(result, index_path).get(selected.get("chunk_id"))
        if not evidence:
            return {"status": "not_run", "reason": "evidence_text_unavailable",
                    "policy": "shadow_only_no_status_change"}
        from . import kb_nli as KN
        return KN.assess(claim, evidence, device=device)
    except Exception as exc:
        return {"status": "not_run", "reason": f"{type(exc).__name__}: {exc}",
                "policy": "shadow_only_no_status_change"}


def _query_impl(q, game=None, revision=None, platform=None, want=None, topk=8,
                require_verified=False, index_path=None, reg=None, map_path=None,
                top_window=3, domain=None, fact_selector=None,
                selector_beyond_window=False, fragment_policy=None,
                nli_shadow=False, nli_claim=None, nli_device=None):
    result = _query_inner(q, game=game, revision=revision, platform=platform,
                          want=want, topk=topk, require_verified=require_verified,
                          index_path=index_path, reg=reg, map_path=map_path,
                          top_window=top_window, domain=domain,
                          fact_selector=fact_selector,
                          selector_beyond_window=selector_beyond_window,
                          fragment_policy=fragment_policy)
    if nli_shadow:
        before = (result.get("status"), list(result.get("selected_evidence") or []))
        result["nli_shadow"] = _run_nli_shadow(result, nli_claim, index_path, nli_device)
        after = (result.get("status"), list(result.get("selected_evidence") or []))
        if before != after:
            result["status"], evidence = before
            result["nli_shadow"]["contract_error"] = "nli_changed_production_verdict"
            if evidence:
                result["selected_evidence"] = evidence
            else:
                result.pop("selected_evidence", None)
    return result


def _clip(value, limit):
    text = value if isinstance(value, str) else str(value or "")
    return text[:limit]


def _log_context(context):
    allowed = {"request_id", "call_id", "entry_point"}
    src = context or {}
    unknown = sorted(set(src) - allowed)
    if unknown:
        raise SchemaError(f"未知查询日志上下文字段 {unknown}")
    out = {k: _clip(src[k], 100) for k in allowed if src.get(k)}
    out.setdefault("request_id", uuid.uuid4().hex)
    out.setdefault("call_id", uuid.uuid4().hex)
    out.setdefault("entry_point", "api")
    return out


def _log_params(result, params):
    allowed = ("game", "revision", "platform", "want", "topk", "top_window",
               "require_verified", "domain", "fact_selector",
               "selector_beyond_window", "fragment_policy", "nli_shadow")
    src = dict(params or {})
    for key in ("game", "revision", "platform", "want", "domain"):
        if key not in src and key in result:
            src[key] = result[key]
    route = result.get("route") or {}
    if "domain" not in src and route.get("domain"):
        src["domain"] = route["domain"]
    out = {}
    for key in allowed:
        value = src.get(key)
        if value is None or value == "" or value == []:
            continue
        if key == "want":
            if isinstance(value, str):
                value = value.split(",")
            out[key] = [_clip(v, 40) for v in value[:8]]
        elif isinstance(value, str):
            out[key] = _clip(value, 80)
        elif isinstance(value, bool) or isinstance(value, int):
            out[key] = value
    return out


def _log_evidence(result):
    rows = []
    seen = set()
    route_domain = (result.get("route") or {}).get("domain")

    def add(hit, domain=None):
        if not isinstance(hit, dict):
            return
        d = domain or hit.get("domain") or route_domain
        key = (d, hit.get("chunk_id"), hit.get("locator"))
        if key in seen:
            return
        seen.add(key)
        item = {k: hit.get(k) for k in
                ("chunk_id", "locator", "source_id", "authority", "revision")
                if hit.get(k) is not None}
        if d:
            item["domain"] = _clip(d, 80)
        item["snippet"] = _clip(hit.get("snippet"), 240)
        provenance = hit.get("fragment_provenance")
        if isinstance(provenance, dict):
            item["fragment_provenance"] = {
                k: _clip(provenance.get(k), 160) if k in ("status", "authority", "reason")
                else provenance.get(k)
                for k in ("status", "authority", "eligible", "reason")
                if provenance.get(k) is not None}
        rows.append(item)

    for hit in (result.get("selected_evidence") or [])[:8]:
        add(hit)
    for entry in (result.get("domain_results") or [])[:16]:
        if len(rows) >= 8:
            return rows
        for hit in (entry.get("selected_evidence") or [])[:8]:
            add(hit, entry.get("domain"))
            if len(rows) >= 8:
                return rows
    return rows[:8]


def _log_domains(result):
    entries = result.get("domain_results") or []
    if not entries:
        auto = result.get("auto_routing") or {}
        routes = auto.get("domains") or []
        if routes:
            entries = [{**routes[0], "status": result.get("status"),
                        "refusal": result.get("refusal"), "counts": result.get("counts") or {},
                        "retrieval": result.get("retrieval"),
                        "index_sha256": result.get("index_sha256"),
                        "selected_evidence": result.get("selected_evidence") or []}]
    out = []
    for entry in entries[:16]:
        item = {k: entry.get(k) for k in
                ("domain", "tier", "corpus_available", "status", "refusal", "retrieval",
                 "index_sha256") if entry.get(k) is not None}
        item["matched"] = [_clip(v, 80) for v in (entry.get("matched") or [])[:4]]
        counts = entry.get("counts") or {}
        item["counts"] = {k: int(counts.get(k, 0)) for k in
                          ("candidates", "hits", "answerable", "strong")}
        item["selected_chunk_ids"] = [_clip(h.get("chunk_id"), 80)
                                      for h in (entry.get("selected_evidence") or [])[:8]
                                      if h.get("chunk_id")]
        out.append(item)
    return out


def build_query_log_row(result, elapsed_ms=None, caller="kb.query", context=None,
                        event_ids=None, params=None):
    """构造有界诊断行；证据只留定位/短摘录，不落全文或调用参数对象。"""
    ctx = _log_context(context)
    status = result.get("status") or "unknown"
    outcome = ("answered" if status == Verdict.PASS.value else
               "refused" if status in ("miss", Verdict.INCONCLUSIVE.value) else
               "error" if status == "error" else "unknown")
    counts = result.get("counts") or {}
    selector = result.get("fact_selector") or {}
    term_filter = result.get("query_term_filter") or {}
    row = {"schema_version": 2,
           "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "request_id": ctx["request_id"], "call_id": ctx["call_id"],
           "entry_point": ctx["entry_point"], "caller": _clip(caller, 80),
           "api": "query_auto" if result.get("auto_routing") else "query",
           "route_mode": (result.get("auto_routing") or {}).get("mode")
                         or ("explicit" if any(result.get(k) for k in
                                               ("game", "revision", "platform")) else "single"),
           "elapsed_ms": round(max(0.0, float(elapsed_ms or 0)), 3),
           "outcome": outcome, "q": _clip(result.get("q"), 500),
           "status": status, "refusal": result.get("refusal"),
           "reason": _clip(result.get("reason"), 500),
           "counts": {k: int(counts.get(k, 0)) for k in
                      ("candidates", "hits", "answerable", "strong")},
           "params": _log_params(result, params),
           "retrieval": result.get("retrieval"), "index_used": result.get("index_used"),
           "index_sha256": result.get("index_sha256"),
           "query_expansion": [_clip(v, 40) for v in
                               (result.get("query_expansion") or [])[:12]],
           "query_term_filter": {"mode": term_filter.get("mode"),
                                 "removed": [_clip(v, 40) for v in
                                             (term_filter.get("removed") or [])[:12]]},
           "fragment_policy": result.get("fragment_policy"),
           "nli_shadow": _nli_shadow_summary(result.get("nli_shadow")),
           "fact_selector": {k: selector.get(k) for k in
                             ("mode", "fact_class", "verdict", "selected", "selected_rank",
                              "beyond_window") if selector.get(k) is not None},
           "auto_domains": [_clip(d.get("domain"), 80) for d in
                            ((result.get("auto_routing") or {}).get("domains") or [])[:16]],
           "domains": _log_domains(result),
           "selected_evidence": _log_evidence(result),
           "event_ids": [_clip(v, 80) for v in (event_ids or [])[:32]]}
    return row


def write_query_log_row(row, path=None):
    p = Path(path) if path is not None else KB_DIR / "query_log.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False)
    if len(line.encode("utf-8")) > 16384:
        row = {**row, "domains": [], "selected_evidence": [], "log_truncated": True}
        line = json.dumps(row, ensure_ascii=False)
    with p.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return str(p)


def _emit_query_log(result, elapsed_ms, caller, log_sink, log_context,
                    event_ids=None, params=None):
    if log_sink is None:
        return
    if not callable(log_sink):
        raise SchemaError("log_sink 必须是可调用对象")
    row = build_query_log_row(result, elapsed_ms=elapsed_ms, caller=caller,
                              context=log_context, event_ids=event_ids, params=params)
    log_sink(row)


def query(q, game=None, revision=None, platform=None, want=None, topk=8,
          require_verified=False, index_path=None, reg=None, map_path=None,
          top_window=3, domain=None, fact_selector=None,
          selector_beyond_window=False, fragment_policy=None,
          nli_shadow=False, nli_claim=None, nli_device=None,
          log_sink=None, log_context=None):
    if log_sink is not None and not callable(log_sink):
        raise SchemaError("log_sink 必须是可调用对象")
    _log_context(log_context)
    started = time.perf_counter()
    params = dict(game=game, revision=revision, platform=platform, want=want, topk=topk,
                  top_window=top_window, require_verified=require_verified, domain=domain,
                  fact_selector=fact_selector, selector_beyond_window=selector_beyond_window,
                  fragment_policy=fragment_policy, nli_shadow=nli_shadow)
    try:
        result = _query_impl(q, game=game, revision=revision, platform=platform, want=want,
                             topk=topk, require_verified=require_verified,
                             index_path=index_path, reg=reg, map_path=map_path,
                             top_window=top_window, domain=domain,
                             fact_selector=fact_selector,
                             selector_beyond_window=selector_beyond_window,
                             fragment_policy=fragment_policy,
                             nli_shadow=nli_shadow, nli_claim=nli_claim,
                             nli_device=nli_device)
    except Exception as exc:
        if log_sink is not None:
            error = {"q": q, "status": "error",
                     "reason": f"{type(exc).__name__}: {_clip(exc, 300)}",
                     "counts": {"candidates": 0, "hits": 0, "answerable": 0, "strong": 0}}
            _emit_query_log(error, (time.perf_counter() - started) * 1000,
                            "kb.query", log_sink, log_context, params=params)
        raise
    _emit_query_log(result, (time.perf_counter() - started) * 1000,
                    "kb.query", log_sink, log_context, params=params)
    return result


def append_query_log(result, path=None, caller="kb.query", event_ids=None,
                     elapsed_ms=None, log_context=None, params=None):
    """追加一条可审计查询记录；只存定位与短摘录，不落正文全文或凭证。"""
    row = build_query_log_row(result, elapsed_ms=elapsed_ms, caller=caller,
                              context=log_context, event_ids=event_ids, params=params)
    return write_query_log_row(row, path=path)


def _try_query_esports_static(q, game=None, revision=None, platform=None, want=None,
                              fact_selector=None, fragment_policy=None, nli_shadow=False):
    """只试窄 SQLite 臂；文本专用旋钮开启时不绕过原契约。"""
    if want or fact_selector is not None or fragment_policy == "strict" or nli_shadow:
        return None
    from . import kb_esports as KE
    return KE.query_auto_static(q, game=game, revision=revision, platform=platform)


def _attach_static_auto(result, routes):
    rt = dict(routes[0])
    if rt["domain"] == "unrouted":
        rt = {"domain": "esports_lol", "game_ids": [], "revisions": [],
              "corpus_available": False, "matched": [], "tier": "static_entity"}
    rt["structured_available"] = True
    entity = result.get("static_entity") or {}
    if entity:
        rt["entity"] = entity
    result["route"] = rt
    result["auto_routing"] = {"mode": "single", "domains": [rt]}
    return result


def _try_query_megaman1(q, game=None, revision=None, platform=None, want=None,
                        topk=8, top_window=3, fact_selector=None,
                        fragment_policy=None, nli_shadow=False, allow_multi=False):
    if want or fact_selector is not None or nli_shadow or fragment_policy not in (None, "strict"):
        return None
    from . import kb_megaman1 as M
    explicit = game in {"megaman1", "megaman1_candidate"} or revision == M.REVISION
    candidate_route = M.route_question(q)
    series_ambiguity = (candidate_route.get("disposition") == "ambiguous_series"
                        and not candidate_route.get("other_installment"))
    if (not explicit and not series_ambiguity
            and not any(rt["domain"] == M.PRODUCTION_DOMAIN for rt in route_many(q))):
        return None
    raw = M.ask(q, mode="strict" if fragment_policy == "strict" else "default",
                topk=topk, top_window=top_window, assume_revision=explicit,
                production=True, allow_multi=allow_multi)
    answer = raw.get("answer") or {}
    passed = raw.get("status") == Verdict.PASS.value
    return {"q": q, "game": game, "revision": revision, "platform": platform,
            "want": want or [], "status": raw.get("status"),
            "refusal": None if passed else raw.get("refusal"),
            "reason": raw.get("reason", ""), "reason_code": raw.get("reason_code") or raw.get("refusal"),
            "retrieval": "bm25_only" if raw.get("selected_evidence") else "not_run",
            "backend": "megaman1_candidate",
            "index_used": raw.get("index_used"), "index_sha256": raw.get("index_sha256"),
            "answer_text": answer.get("text", "") if answer.get("kind") == "answer" else "",
            "counts": raw.get("counts") or {}, "hits": raw.get("hits") or [],
            "selected_evidence": raw.get("selected_evidence") or [],
            "route": raw.get("route"), "retrieval_query": raw.get("retrieval_query"),
            "fragment_policy": fragment_policy,
            "candidate_only": True, "whole_game_knowledge_base": False,
            "production_route_wired": True}


def _try_query_megaman2(q, game=None, revision=None, platform=None, want=None,
                        topk=8, top_window=3, fact_selector=None,
                        fragment_policy=None, nli_shadow=False, allow_multi=False,
                        index_path=None, map_path=None, reg=None):
    if want or fact_selector is not None or nli_shadow or fragment_policy not in (None, "strict"):
        return None
    from . import kb_megaman2 as M
    revisions = {M.TECHNICAL_REVISION, M.MEMORY_REVISION,
                 M.CATALOG_REVISION, M.TAS_REVISION, M.MANUAL_REVISION}
    explicit = game in {"megaman2", "megaman2_candidate"} or revision in revisions
    candidate_route = M.route_question(q)
    series_ambiguity = (candidate_route.get("disposition") == "ambiguous_series"
                        and not candidate_route.get("other_installment"))
    if (not explicit and not series_ambiguity
            and not any(rt["domain"] == M.PRODUCTION_DOMAIN for rt in route_many(q))):
        return None
    raw = M.ask(q, mode="strict" if fragment_policy == "strict" else "default",
                topk=topk, top_window=top_window, assume_revision=explicit,
                production=True, allow_multi=allow_multi,
                index_path=index_path, map_path=map_path, registry_path=None, reg=reg)
    answer = raw.get("answer") or {}
    passed = raw.get("status") == Verdict.PASS.value
    return {"q": q, "game": game, "revision": revision, "platform": platform,
            "want": want or [], "status": raw.get("status"),
            "refusal": None if passed else raw.get("refusal"),
            "reason": raw.get("reason", ""), "reason_code": raw.get("refusal"),
            "retrieval": "bm25_only" if raw.get("selected_evidence") else "not_run",
            "backend": "megaman2",
            "index_used": raw.get("index_used"), "index_sha256": raw.get("index_sha256"),
            "answer_text": answer.get("text", "") if answer.get("kind") == "evidence_excerpt" else "",
            "counts": raw.get("counts") or {}, "hits": raw.get("hits") or [],
            "selected_evidence": raw.get("selected_evidence") or [],
            "route": raw.get("route"), "retrieval_query": raw.get("retrieval_query"),
            "fragment_policy": fragment_policy,
            "candidate_only": raw.get("candidate_only", False),
            "whole_game_knowledge_base": False,
            "production_route_wired": True}


def _attach_candidate_auto(result, routes):
    candidate_route = result.get("route") or {}
    production_domain = str(result.get("backend") or "").split("_candidate", 1)[0] or "megaman2"
    rt = dict(routes[0]) if routes and routes[0].get("domain") == production_domain else {
        "domain": production_domain, "game_ids": [production_domain],
        "revisions": [rev for rev in [candidate_route.get("revision") or result.get("revision")] if rev],
        "corpus_available": True,
        "matched": candidate_route.get("matched") or ["production_route"],
        "tier": "candidate_index" if result.get("candidate_only") else "production_text"}
    rt["corpus_available"] = True
    result["route"] = rt
    result["candidate_route"] = candidate_route
    result["auto_routing"] = {"mode": "single", "domains": [rt]}
    return result


def _query_auto_impl(q, game=None, revision=None, platform=None, want=None, topk=8,
                     require_verified=False, index_path=None, reg=None, map_path=None,
                     top_window=3, fact_selector=None, selector_beyond_window=False,
                     fragment_policy=None, nli_shadow=False, nli_claim=None,
                     nli_device=None):
    """自动识别全部知识域并分别检索；显式身份过滤仍优先，调用方无需选库。

    唯一 LOL 静态实体 + 静态属性问句先接只读 SQLite；其余问句原样走文本臂。
    多域问题不合并成一个 pass：每个域的权威证据留在 domain_results，
    总体判 inconclusive，要求下游按事实拆分，避免“两域只证一域却答两域”。
    """
    routes = route_many(q)
    if game or revision or platform:
        static = _try_query_esports_static(
            q, game=game, revision=revision, platform=platform, want=want,
            fact_selector=fact_selector, fragment_policy=fragment_policy,
            nli_shadow=nli_shadow)
        if static is not None:
            return _attach_static_auto(static, routes)
        candidate = _try_query_megaman1(
            q, game=game, revision=revision, platform=platform, want=want,
            topk=topk, top_window=top_window, fact_selector=fact_selector,
            fragment_policy=fragment_policy, nli_shadow=nli_shadow)
        if candidate is not None:
            return _attach_candidate_auto(candidate, routes)
        candidate = _try_query_megaman2(
            q, game=game, revision=revision, platform=platform, want=want,
            topk=topk, top_window=top_window, fact_selector=fact_selector,
            fragment_policy=fragment_policy, nli_shadow=nli_shadow,
            index_path=index_path, map_path=map_path, reg=reg)
        if candidate is not None:
            return _attach_candidate_auto(candidate, routes)
        return query(q, game=game, revision=revision, platform=platform, want=want,
                     topk=topk, require_verified=require_verified, index_path=index_path,
                     reg=reg, map_path=map_path, top_window=top_window,
                     fact_selector=fact_selector,
                     selector_beyond_window=selector_beyond_window,
                     fragment_policy=fragment_policy,
                     nli_shadow=nli_shadow, nli_claim=nli_claim,
                     nli_device=nli_device)
    if len(routes) == 1:
        rt = routes[0]
        if rt["domain"] == "project_docs" and rt["tier"] == "weak":
            candidate = _try_query_megaman2(
                q, want=want, topk=topk, top_window=top_window,
                fact_selector=fact_selector, fragment_policy=fragment_policy,
                nli_shadow=nli_shadow, index_path=index_path, map_path=map_path, reg=reg)
            if candidate is not None:
                return _attach_candidate_auto(candidate, routes)
        if rt["domain"] in ("unrouted", "esports_lol"):
            if rt["domain"] == "unrouted":
                candidate = _try_query_megaman1(
                    q, want=want, topk=topk, top_window=top_window,
                    fact_selector=fact_selector, fragment_policy=fragment_policy,
                    nli_shadow=nli_shadow)
                if candidate is not None:
                    return _attach_candidate_auto(candidate, routes)
            static = _try_query_esports_static(
                q, want=want, fact_selector=fact_selector,
                fragment_policy=fragment_policy, nli_shadow=nli_shadow)
            if static is not None:
                return _attach_static_auto(static, routes)
        if rt["domain"] == "megaman1":
            candidate = _try_query_megaman1(
                q, want=want, topk=topk, top_window=top_window,
                fact_selector=fact_selector, fragment_policy=fragment_policy,
                nli_shadow=nli_shadow)
            if candidate is not None:
                return _attach_candidate_auto(candidate, routes)
        if rt["domain"] == "megaman2":
            candidate = _try_query_megaman2(
                q, want=want, topk=topk, top_window=top_window,
                fact_selector=fact_selector, fragment_policy=fragment_policy,
                nli_shadow=nli_shadow, index_path=index_path,
                map_path=map_path, reg=reg)
            if candidate is not None:
                return _attach_candidate_auto(candidate, routes)
        kw = dict(game=None, revision=None, platform=None, want=want, topk=topk,
                  require_verified=require_verified, index_path=index_path, reg=reg,
                  map_path=map_path, top_window=top_window,
                  fact_selector=fact_selector,
                  selector_beyond_window=selector_beyond_window,
                  fragment_policy=fragment_policy,
                  nli_shadow=nli_shadow, nli_claim=nli_claim,
                  nli_device=nli_device)
        if rt["domain"] != "unrouted":
            kw["domain"] = rt["domain"]
        res = query(q, **kw)
        if (rt["domain"] == "unrouted" and res.get("status") == Verdict.PASS.value
                and res.get("selected_evidence")):
            res["status"] = Verdict.INCONCLUSIVE.value
            res["refusal"] = "unanchored"
            res["reason_code"] = "unanchored"
            res["reason"] = ("自动路由未锚定游戏内容域；全库词面命中不可当硬证据，"
                             "原pass理由：" + str(res.get("reason") or ""))
            res["selected_evidence"] = []
            res["auto_unanchored"] = True
        res["auto_routing"] = {"mode": "single", "domains": routes}
        return res
    entries = []
    for rt in routes:
        try:
            res = None
            if rt["domain"] == "esports_lol":
                res = _try_query_esports_static(
                    q, want=want, fact_selector=fact_selector,
                    fragment_policy=fragment_policy, nli_shadow=nli_shadow)
            if rt["domain"] == "megaman1":
                res = _try_query_megaman1(
                    q, want=want, topk=topk, top_window=top_window,
                    fact_selector=fact_selector, fragment_policy=fragment_policy,
                    nli_shadow=nli_shadow, allow_multi=True)
            if rt["domain"] == "megaman2":
                res = _try_query_megaman2(
                    q, want=want, topk=topk, top_window=top_window,
                    fact_selector=fact_selector, fragment_policy=fragment_policy,
                    nli_shadow=nli_shadow, allow_multi=True,
                    index_path=index_path, map_path=map_path, reg=reg)
            if res is None:
                res = query(q, domain=rt["domain"], want=want, topk=topk,
                            require_verified=require_verified, index_path=index_path,
                            reg=reg, map_path=map_path, top_window=top_window,
                            fact_selector=fact_selector,
                            selector_beyond_window=selector_beyond_window,
                            fragment_policy=fragment_policy,
                            nli_shadow=nli_shadow, nli_claim=nli_claim,
                            nli_device=nli_device)
        except Exception as e:
            res = {"q": q, "status": "error", "reason": f"{type(e).__name__}: {e}",
                   "hits": [], "counts": {"candidates": 0, "hits": 0}}
        hits = [{**h, "domain": rt["domain"]} for h in (res.get("hits") or [])[:topk]]
        entries.append({"domain": rt["domain"], "tier": rt["tier"],
                        "matched": rt["matched"], "corpus_available": rt["corpus_available"],
                        "status": res.get("status"), "refusal": res.get("refusal"),
                        "reason": res.get("reason"), "reason_code": res.get("reason_code"),
                        "retrieval": res.get("retrieval"), "backend": res.get("backend"),
                        "answer_text": res.get("answer_text"), "claim": res.get("claim"),
                        "dataset_revision": res.get("dataset_revision"),
                        "query_conditions": res.get("query_conditions"),
                        "static_entity": res.get("static_entity"),
                        "retrieval_note": res.get("retrieval_note"),
                        "index_used": res.get("index_used"),
                        "index_sha256": res.get("index_sha256"), "counts": res.get("counts") or {},
                        "hits": hits, "selected_evidence": res.get("selected_evidence") or [],
                        "fact_selector": res.get("fact_selector"),
                        "fragment_policy": res.get("fragment_policy"),
                        "nli_shadow": res.get("nli_shadow"),
                        "candidate_only": res.get("candidate_only", False),
                        "whole_game_knowledge_base": res.get("whole_game_knowledge_base"),
                        "production_route_wired": res.get("production_route_wired")})
    all_out = all(e["status"] == "miss" and e.get("refusal") == "out_of_scope" for e in entries)
    any_error = any(e["status"] == "error" for e in entries)
    any_pass = any(e["status"] == Verdict.PASS.value for e in entries)
    if all_out:
        status, refusal = "miss", "out_of_scope"
        reason = "自动识别到多个域，但这些域本地均无语料：" + "、".join(e["domain"] for e in entries)
    elif any_error:
        status, refusal = Verdict.INCONCLUSIVE.value, "multi_domain_error"
        reason = "至少一个自动命中域检索失败；未用其他域顶包"
    elif any_pass:
        status, refusal = Verdict.INCONCLUSIVE.value, "multi_domain_needs_split"
        reason = "多个域已分别检索，至少一域有权威证据；总体不合并放行，须按事实拆分后逐域出证"
    else:
        status, refusal = Verdict.INCONCLUSIVE.value, "multi_domain_incomplete"
        reason = "多个域已分别检索，但没有一域达到 pass；缺证据不合并猜答案"
    counts = {k: sum(int(e["counts"].get(k, 0)) for e in entries)
              for k in ("candidates", "hits", "answerable", "strong")}
    retrievals = sorted({e.get("retrieval") for e in entries if e.get("retrieval")})
    indexes = sorted({e.get("index_used") for e in entries if e.get("index_used")})
    hashes = sorted({e.get("index_sha256") for e in entries if e.get("index_sha256")})
    return {"q": q, "game": None, "revision": None, "platform": None, "want": want or [],
            "status": status, "refusal": refusal, "reason": reason,
            "retrieval": retrievals[0] if len(retrievals) == 1 else "mixed",
            "index_used": indexes[0] if len(indexes) == 1 else "、".join(indexes),
            "index_sha256": hashes[0] if len(hashes) == 1 else "、".join(hashes),
            "counts": counts, "hits": [h for e in entries for h in e["hits"]],
            "selected_evidence": [], "domain_results": entries,
            "fragment_policy": fragment_policy,
            "auto_routing": {"mode": "multi", "domains": routes},
            "coverage_note": "只自动检索命中注册词的域；未识别实体不代表不存在，也不得借其他域证据代答",
            **({"nli_shadow": [{"domain": e["domain"],
                                  "shadow": _nli_shadow_summary(e.get("nli_shadow"))}
                                 for e in entries]} if nli_shadow else {})}


def query_auto(q, game=None, revision=None, platform=None, want=None, topk=8,
               require_verified=False, index_path=None, reg=None, map_path=None,
               top_window=3, fact_selector=None, selector_beyond_window=False,
               fragment_policy=None, nli_shadow=False, nli_claim=None,
               nli_device=None, log_sink=None, log_context=None):
    if log_sink is not None and not callable(log_sink):
        raise SchemaError("log_sink 必须是可调用对象")
    _log_context(log_context)
    started = time.perf_counter()
    params = dict(game=game, revision=revision, platform=platform, want=want, topk=topk,
                  top_window=top_window, require_verified=require_verified,
                  fact_selector=fact_selector, selector_beyond_window=selector_beyond_window,
                  fragment_policy=fragment_policy, nli_shadow=nli_shadow)
    try:
        result = _query_auto_impl(q, game=game, revision=revision, platform=platform,
                                  want=want, topk=topk, require_verified=require_verified,
                                  index_path=index_path, reg=reg, map_path=map_path,
                                  top_window=top_window, fact_selector=fact_selector,
                                  selector_beyond_window=selector_beyond_window,
                                  fragment_policy=fragment_policy,
                                  nli_shadow=nli_shadow, nli_claim=nli_claim,
                                  nli_device=nli_device)
    except Exception as exc:
        if log_sink is not None:
            error = {"q": q, "status": "error",
                     "reason": f"{type(exc).__name__}: {_clip(exc, 300)}",
                     "counts": {"candidates": 0, "hits": 0, "answerable": 0, "strong": 0}}
            _emit_query_log(error, (time.perf_counter() - started) * 1000,
                            "kb.query_auto", log_sink, log_context, params=params)
        raise
    _emit_query_log(result, (time.perf_counter() - started) * 1000,
                    "kb.query_auto", log_sink, log_context, params=params)
    return result


def stats_for(game=None, revision=None, platform=None, index_path=None):
    idx = load_index(index_path)
    if idx is None:
        return {"status": "not_built", "chunks": 0,
                "reason": "知识库未建（kb build）", "query_cmd": None}
    cs = [c for c in idx["chunks"]
          if (not game or c["game_id"] == game)
          and (not revision or c["revision"] == revision)
          and (not platform or c["platform"] == platform or c["platform"] == "ANY")]
    strong = sum(1 for c in cs if c["status"] == "verified_read"
                 and c["authority"] == "authoritative")
    cmd = "py -3 -m taspipe.kb query --q <问题>"
    if revision:
        cmd += f" --revision {revision}"
    elif game:
        cmd += f" --game {game}"
    if platform:
        cmd += f" --platform {platform}"
    return {"status": "ready" if cs else "empty", "chunks": len(cs),
            "authoritative_verified": strong,
            "revisions": sorted({c["revision"] for c in cs}),
            "query_cmd": cmd,
            "rule": "先查本地正文（kb query），未命中再走站点 primary/extension"}


# ---------------------------------------------------------------- 审计

def audit(map_path=None, index_path=None, reg=None):
    checks = []

    def add(cid, verdict, reason="", detail=None):
        checks.append({"check_id": cid, "verdict": verdict, "reason": reason,
                       "detail": detail or []})

    try:
        m = load_map(map_path)
        add("map_schema", Verdict.PASS.value,
            f"{len(m['entries'])} 份语料 / {len(m['revisions'])} 个版本分区全部通过 schema")
    except SchemaError as e:
        add("map_schema", Verdict.FAIL.value, str(e))
        return {"status": "fail", "checks": checks}
    try:
        reg = reg or S.load_registry()
    except SchemaError as e:
        add("registry_readable", Verdict.FAIL.value, str(e))
        return {"status": "fail", "checks": checks}
    by_id = {s["source_id"]: s for s in reg["sources"]}
    entries = m["entries"]
    mapped = {str(S.resolve_path(e["path"])): e for e in entries}

    missing, unbound, conflict = [], [], []
    for s in reg["sources"]:
        if s["status"] != "verified_read":
            continue
        for ev in s.get("evidence") or []:
            key = str(S.resolve_path(ev))
            if key not in mapped:
                missing.append(f"{s['source_id']}: {ev} 未进 corpus_map（收正文却不入库＝白收）")
    for e in entries:
        src = by_id.get(e["source_id"])
        if src is None:
            unbound.append(f"{e['path']}: source_id {e['source_id']!r} 不在来源库")
            continue
        ev_keys = {str(S.resolve_path(p)) for p in src.get("evidence") or []}
        if str(S.resolve_path(e["path"])) not in ev_keys:
            unbound.append(f"{e['path']}: 不在 {e['source_id']} 的 evidence 列表里（不许凭文件名猜归属）")
        gid = m["revisions"][e["revision"]]["game_id"]
        hits = src.get("games_hit") or []
        if hits and gid != "multi" and not any(g == gid or g.startswith(gid + "_") or g.startswith(gid)
                                              for g in hits):
            conflict.append(f"{e['path']}: 语料判为 {gid}，但来源 {e['source_id']} 的 games_hit={hits}")
    add("evidence_coverage", Verdict.FAIL.value if missing else Verdict.PASS.value,
        "verified_read 的每份取证正文都在册（或显式排除并给理由）" if not missing else "有取证未入库",
        missing)
    add("source_binding", Verdict.FAIL.value if unbound else Verdict.PASS.value,
        "每份语料都绑定库内来源且在该来源 evidence 列表内" if not unbound else "归属错配", unbound)
    add("identity_conflict", Verdict.FAIL.value if conflict else Verdict.PASS.value,
        "语料版本分区与来源 games_hit 一致" if not conflict else "身份错配（同名异版/异平台混喂）",
        conflict)

    idx = load_index(index_path)
    if idx is None:
        add("index_sync", Verdict.INCONCLUSIVE.value, "索引未建，无法核对（跑 kb build）")
        add("chunk_provenance", Verdict.INCONCLUSIVE.value, "索引未建")
        add("authoritative_ready", Verdict.INCONCLUSIVE.value, "索引未建")
    else:
        # 审计对象是不是富集索引：与 build 同一语义（hybrid_only 件只收进富集索引）。
        # 默认审计 base；显式 --index index_hybrid.json 时按富集口径核对，
        # 否则会把合法收录误报成漂移（阶段1：审计器跟上双索引）。
        auditing_hybrid = Path(index_path or INDEX_JSON).name == "index_hybrid.json"
        drift, stale = [], []
        entries_by_path = {e["path"]: e for e in entries}
        citation_by_path = {e["path"]: _citation_authority(e, m, by_id) for e in entries}
        if idx.get("pipeline") != PIPELINE:
            drift.append(f"索引流水线 {idx.get('pipeline')!r} ≠ 当前 {PIPELINE!r}"
                         "（清洗/切块参数改过，必须重 build）")
        for e in entries:
            f = idx["files"].get(e["path"])
            if e.get("index", True) is False:
                expect_indexed = bool(auditing_hybrid and e.get("hybrid_only"))
                if expect_indexed:
                    if not f or not f.get("indexed"):
                        drift.append(f"{e['path']}: hybrid_only 件应在富集索引收录但缺失（重 build --hybrid）")
                    elif not any(c["path"] == e["path"] for c in idx["chunks"]):
                        drift.append(f"{e['path']}: hybrid_only 件 files 标收录但无块")
                    else:
                        p = S.resolve_path(e["path"])
                        if p.is_file() and f.get("sha256") != _sha256(p.read_bytes()):
                            drift.append(f"{e['path']}: 源文件已变，富集索引是旧的（重 build --hybrid）")
                        if f.get("citation_sha256") != _citation_sha(citation_by_path[e["path"]]):
                            drift.append(f"{e['path']}: 引用别名绑定已变，富集索引是旧的（重 build --hybrid）")
                elif f and f.get("indexed"):
                    drift.append(f"{e['path']}: 已声明排除但索引里仍有块")
                continue
            p = S.resolve_path(e["path"])
            if not f or not f.get("indexed"):
                drift.append(f"{e['path']}: 索引缺这份语料")
                continue
            if not p.is_file():
                drift.append(f"{e['path']}: 语料文件已不存在")
                continue
            if f.get("sha256") != _sha256(p.read_bytes()):
                drift.append(f"{e['path']}: 源文件已变，索引是旧的（重 build）")
            if f.get("citation_sha256") != _citation_sha(citation_by_path[e["path"]]):
                drift.append(f"{e['path']}: 引用别名绑定已变，索引是旧的（重 build）")
        for c in idx["chunks"]:
            if c["text_sha"] != _sha1(c["text"]):
                drift.append(f"{c['chunk_id']}: 索引正文被手改（text_sha 不符）")
            src = by_id.get(c["source_id"])
            if src is None or c["status"] != src["status"]:
                stale.append(f"{c['chunk_id']}: status={c['status']} 与来源库现状不符")
            if c["revision"] not in m["revisions"]:
                stale.append(f"{c['chunk_id']}: revision {c['revision']!r} 未定义")
            entry = entries_by_path.get(c["path"])
            if entry is None or c["authority"] != entry["authority"]:
                stale.append(f"{c['chunk_id']}: authority 与 corpus_map 不符")
            elif c.get("citation_authority") != citation_by_path[c["path"]]:
                stale.append(f"{c['chunk_id']}: citation_authority 与 corpus_map 主数据不符")
        add("index_sync", Verdict.FAIL.value if drift else Verdict.PASS.value,
            "索引与源文件 sha256、块正文 sha1 一致" if not drift else "索引漂移", drift)
        add("chunk_provenance", Verdict.FAIL.value if stale else Verdict.PASS.value,
            "每块都带库内 source_id + 已定义 revision + 当期 status" if not stale else "块溯源失效",
            stale)
        ready = {}
        for rid in m["revisions"]:
            cs = [c for c in idx["chunks"] if c["revision"] == rid]
            ready[rid] = sum(1 for c in cs if c["status"] == "verified_read"
                             and c["authority"] == "authoritative")
        weak = [f"{rid}: {n} 块 verified_read+authoritative" for rid, n in sorted(ready.items())
                if n == 0 and m["revisions"][rid]["game_id"] != "multi"]
        add("authoritative_ready",
            Verdict.INCONCLUSIVE.value if weak else Verdict.PASS.value,
            "每个游戏版本都有权威正文可答" if not weak else
            "以下版本没有 verified_read+authoritative 正文，只能给线索不能给定论", weak)

    # 阶段2（评审§1.8/§3）：权威继承与撤回段——只读识别，事实级出证强制在阶段3。
    # 转述不产生新证据：authoritative 总结里明标二手来源(S\d+)的段落继承来源资格缺口。
    inherit, retract = [], []
    inh_re = re.compile(r"[（(]S\d+|^\s*-\s*S\d+\s")
    ret_re = re.compile(r"撤回|作废|表述过强")
    for e in entries:
        if e.get("authority") != "authoritative":
            continue
        p = S.resolve_path(e["path"])
        if not p.is_file() or p.suffix != ".md":
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if inh_re.search(line):
                inherit.append(f"{e['path']}:L{i}: {line.strip()[:80]}")
            if ret_re.search(line):
                retract.append(f"{e['path']}:L{i}: {line.strip()[:80]}")
    add("authority_inheritance",
        Verdict.INCONCLUSIVE.value if inherit else Verdict.PASS.value,
        "authoritative 件无明标二手转述段" if not inherit else
        "authoritative 总结含明标二手来源段落（转述不升格；事实级出证资格待阶段3强制）",
        inherit)
    add("retraction_markers",
        Verdict.INCONCLUSIVE.value if retract else Verdict.PASS.value,
        "无撤回/作废段" if not retract else
        "撤回段已定位（撤回结论不得出证，排除接线在阶段3）",
        retract)

    fails = sum(1 for c in checks if c["verdict"] == Verdict.FAIL.value)
    incon = sum(1 for c in checks if c["verdict"] == Verdict.INCONCLUSIVE.value)
    passes = sum(1 for c in checks if c["verdict"] == Verdict.PASS.value)
    return {"status": "fail" if fails else ("inconclusive" if incon else "pass"),
            "counts": {"pass": passes, "fail": fails, "inconclusive": incon,
                       "entries": len(entries), "revisions": len(m["revisions"]),
                       "chunks": len(idx["chunks"]) if idx else 0},
            "checks": checks}


def show(index_path=None):
    idx = load_index(index_path)
    if idx is None:
        return {"status": "not_built"}
    per = {}
    for c in idx["chunks"]:
        d = per.setdefault(c["revision"], {"chunks": 0, "strong": 0, "sources": set()})
        d["chunks"] += 1
        d["sources"].add(c["source_id"])
        if c["status"] == "verified_read" and c["authority"] == "authoritative":
            d["strong"] += 1
    return {"status": "ready", "built_at": idx["built_at"], "stats": idx["stats"],
            "index_bytes": Path(index_path or INDEX_JSON).stat().st_size,
            "revisions": {k: {"chunks": v["chunks"], "strong": v["strong"],
                              "sources": sorted(v["sources"])} for k, v in sorted(per.items())}}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="taspipe.kb", description="本地文献知识库")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="清洗+切块+BM25 建索引（按 sha256 增量）")
    b.add_argument("--force", action="store_true")
    b.add_argument("--map")
    b.add_argument("--out")
    b.add_argument("--hybrid", action="store_true",
                   help="建 hybrid 富集索引（收录 hybrid_only 对照件，默认落 index_hybrid.json，base 不动）")
    q = sub.add_parser("query", help="按身份分区检索正文")
    q.add_argument("--q", required=True)
    q.add_argument("--game")
    q.add_argument("--revision")
    q.add_argument("--platform")
    q.add_argument("--want")
    q.add_argument("--topk", type=int, default=8)
    q.add_argument("--top-window", type=int, default=3,
                   help="附条件出证的权威件排名窗口（默认3=批准口径；改大属新策略变体）")
    q.add_argument("--require-verified", action="store_true")
    q.add_argument("--fact-selector", choices=("audit", "scoped", "replace"),
                   help="显式启用七项事实核查；audit只报告，scoped只管五类事实，replace裁决复杂问句")
    q.add_argument("--selector-beyond-window", action="store_true",
                   help="显式允许选择器采用 top_window 外的候选；默认不扩窗")
    q.add_argument("--fragment-policy", choices=("legacy", "strict"),
                   help="strict：二手转述/撤回片段不继承整件权威；默认保持 legacy")
    q.add_argument("--nli-shadow", action="store_true",
                   help="显式运行 NLI 影子评估；校准未通过时自动关闭，绝不改变裁决")
    q.add_argument("--nli-claim", help="完整待核主张；缺失时不运行，不拿问题冒充主张")
    q.add_argument("--nli-device", help="CUDA 设备，如 cuda:0；默认不静默改 CPU")
    q.add_argument("--json", action="store_true")
    kt = sub.add_parser("kt-candidates", help="《热血格斗传说》生日 KT 候选（二手 FAQ，reference_only）")
    kt.add_argument("--month", type=int, required=True)
    kt.add_argument("--day", type=int, required=True)
    kt.add_argument("--json", action="store_true")
    d = sub.add_parser("dense", help="建稠密指纹件（BGE-M3，需 sentence_transformers，优先 CUDA）")
    d.add_argument("--index")
    d.add_argument("--device")
    a = sub.add_parser("audit", help="语料覆盖/归属/身份/索引同步/权威就绪")
    a.add_argument("--map")
    a.add_argument("--index")
    s = sub.add_parser("show", help="索引概览")
    s.add_argument("--index")
    c = sub.add_parser("coverage", help="全域覆盖看板（文本索引 + 电竞结构化事实，只读）")
    c.add_argument("--index")
    c.add_argument("--db")
    c.add_argument("--eval")
    c.add_argument("--log")
    c.add_argument("--out", help="输出前缀；同时写 .json 与 .md")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if args.cmd == "build":
        out = args.out
        if args.hybrid and not out:
            out = str(hybrid_index_path())
        r = build(map_path=args.map, index_path=out, force=args.force, hybrid=args.hybrid)
        for row in r["report"]:
            if row["indexed"]:
                print(f"  {row['chunks']:>4} 块  丢噪声 {row['dropped_lines']:>5} 行  "
                      f"{'复用' if row['reused'] else '重建'}  {row['revision']:<32} {row['path']}")
            else:
                print(f"  排除  {row['path']}  理由: {row['reason']}")
        print(f"KB BUILD OK chunks={r['chunks']} terms={r['terms']} "
              f"indexed={r['files_indexed']} excluded={r['files_excluded']} bytes={r['bytes']}")
        return 0
    if args.cmd == "kt-candidates":
        from .nkd_kt import candidates_for_birthday
        try:
            r = candidates_for_birthday(args.month, args.day)
        except ValueError as exc:
            ap.error(str(exc))
        if args.json:
            print(json.dumps(r, ensure_ascii=False, indent=2))
        else:
            print(f"[reference_only] {args.month}/{args.day} → KT#{r['candidate_kt_number']}")
            print("候选必杀：" + " / ".join(r["candidate_moves"]))
            print("来源：" + r["source_locator"])
            print("警告：" + r["warning"])
        return 0
    if args.cmd == "query":
        _query_started = time.perf_counter()
        r = query_auto(args.q, game=args.game, revision=args.revision, platform=args.platform,
                       want=args.want, topk=args.topk, require_verified=args.require_verified,
                       top_window=args.top_window, fact_selector=args.fact_selector,
                       selector_beyond_window=args.selector_beyond_window,
                       fragment_policy=args.fragment_policy,
                       nli_shadow=args.nli_shadow, nli_claim=args.nli_claim,
                       nli_device=args.nli_device)
        append_query_log(r, caller="cli",
                         elapsed_ms=(time.perf_counter() - _query_started) * 1000,
                         log_context={"entry_point": "cli"},
                         params={"game": args.game, "revision": args.revision,
                                 "platform": args.platform, "want": args.want,
                                 "topk": args.topk, "top_window": args.top_window,
                                 "require_verified": args.require_verified,
                                 "fact_selector": args.fact_selector,
                                 "selector_beyond_window": args.selector_beyond_window,
                                 "fragment_policy": args.fragment_policy,
                                 "nli_shadow": args.nli_shadow})
        if args.json:
            print(json.dumps(r, ensure_ascii=False, indent=1))
        else:
            print(f"[{r['status']}] {r.get('reason', '')}  候选 {r['counts'].get('candidates', 0)}"
                  f"  检索={r.get('retrieval', '?')}")
            if r.get("auto_routing", {}).get("mode") == "multi":
                print("  自动命中域: " + "、".join(r["auto_routing"]["domains"][i]["domain"]
                                                  for i in range(len(r["auto_routing"]["domains"]))))
                for d in r.get("domain_results") or []:
                    print(f"    {d['domain']}: {d['status']}"
                          f"/{d.get('refusal') or '-'}  {d.get('reason') or ''}")
            if r.get("query_expansion"):
                print(f"  跨语扩展: {' '.join(r['query_expansion'])}")
            if r.get("condition"):
                print(f"  ⚠ 附条件: {r['condition']}")
            if r.get("refusal"):
                print(f"  拒答类型: {r['refusal']}（缺证据不冒充事实）")
            if r.get("retrieval_note"):
                print(f"  检索路径说明: {r['retrieval_note']}")
            for h in r["hits"]:
                print(f"  {h['score']:>7}  {h['status']}/{h['authority']}  {h['revision']}")
                print(f"           {h['locator']}")
                print(f"           {h['snippet'][:120].replace(chr(10), ' ')}")
            for w in r.get("authority_warnings") or []:
                print(f"  ⚠ {w}")
            if r.get("next"):
                print(f"  下一步: {r['next']}")
        return 0 if r["status"] == Verdict.PASS.value else 2
    if args.cmd == "dense":
        r = kb_dense.build_dense(Path(args.index or INDEX_JSON), device=args.device)
        print(f"KB DENSE OK chunks={r['chunks']} device={r['device']} seconds={r['seconds']}")
        print(f"  {r['npz']}")
        return 0
    if args.cmd == "audit":
        r = audit(map_path=args.map, index_path=args.index)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if r["status"] == Verdict.PASS.value else 2
    if args.cmd == "coverage":
        from . import kb_coverage
        cov_argv = []
        for flag, value in (("--index", args.index), ("--db", args.db),
                            ("--eval", args.eval), ("--log", args.log),
                            ("--out", args.out)):
            if value:
                cov_argv.extend((flag, value))
        return kb_coverage.main(cov_argv)
    r = show(index_path=args.index)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
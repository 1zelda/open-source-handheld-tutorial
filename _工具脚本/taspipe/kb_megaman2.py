# -*- coding: utf-8 -*-
"""洛克人2隔离候选问答：显式别名、版本拒答、候选索引与隔离日志。"""
import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

from . import kb as K
from . import kb_route as KR
from . import sources as S

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent.parent
CANDIDATE_DIR = REPO_ROOT / "知识库P1_20261118" / "megaman2_candidate_v2_manual_20261125"
INDEX_PATH = CANDIDATE_DIR / "index.json"
MAP_PATH = CANDIDATE_DIR / "corpus_map.json"
REGISTRY_PATH = CANDIDATE_DIR / "sources.json"
CONTRACT_PATH = CANDIDATE_DIR / "contract.json"
FROZEN_QUESTIONS = REPO_ROOT / "知识库P1_20261118" / "megaman2_questions_frozen_v2_manual_20261125.json"
DOMAIN = "megaman2_candidate"
PRODUCTION_DOMAIN = "megaman2"
PRODUCTION_SOURCE_ID = "tasvideos_rockman_data_mm2_extract"
TECHNICAL_REVISION = "megaman2_nes_tasvideos_rockman2"
MEMORY_REVISION = "megaman2_nes_memory_dictionary_unverified"
CATALOG_REVISION = "megaman2_nes_title_catalog"
TAS_REVISION = "megaman2_nes_tas_publications"
MANUAL_REVISION = "megaman2_nes_us_manual"
MANUAL_SOURCE_ID = "nintendo_mega_man_2_nes_us_manual"

MM2_ALIASES = (
    ("洛克人2", re.compile(r"洛克人\s*(?:2|Ⅱ|II)(?!\d)", re.I)),
    ("Mega Man 2", re.compile(
        r"(?<![a-z0-9])mega\s*man\s*(?:2|Ⅱ|II)(?![a-z0-9])", re.I)),
    ("Rockman 2", re.compile(
        r"(?<![a-z0-9])rockman\s*(?:2|Ⅱ|II)(?![a-z0-9])", re.I)),
    ("MM2", re.compile(r"(?<![a-z0-9])mm\s*(?:2|Ⅱ|II)(?![a-z0-9])", re.I)),
)
SERIES_RX = re.compile(
    r"洛克人|(?<![a-z0-9])mega\s*man(?![a-z0-9])|"
    r"(?<![a-z0-9])rockman(?![a-z0-9])|(?<![a-z0-9])mm(?![a-z0-9])",
    re.I,
)
OTHER_WORK_RX = re.compile(
    r"power\s*fighters|力量对决|"
    r"(?<![a-z0-9])rockman\s*2\s*(?:claw|dash|min|basic\s*master)(?![a-z0-9])|"
    r"deus\s*ex\s*machina|gray\s*zone|洛克人\s*x(?![a-z0-9])",
    re.I,
)
OTHER_INSTALLMENT_RX = re.compile(
    r"洛克人\s*(?:[13-9]|10|11|12)(?!\d)|"
    r"(?<![a-z0-9])(?:mega\s*man|rockman)\s*"
    r"(?:[13-9]|10|11|12|x(?:\s*[1-9])?)(?![a-z0-9])",
    re.I,
)
UNSUPPORTED_VERSION_RX = re.compile(
    r"(?<![a-z0-9])pal(?:\s*[-_]?\s*b)?(?![a-z0-9])|"
    r"欧版|欧洲版|日版|日本版|韩版|韩国版|"
    r"(?<![a-z0-9])jp(?:\s*[-_ ]?\s*rom)?(?![a-z0-9])",
    re.I,
)
US_REGION_RX = re.compile(
    r"美版|美国版|美国\s*NES|(?<![a-z0-9])usa(?![a-z0-9])", re.I,
)
NTSC_RX = re.compile(r"(?<![a-z0-9])ntsc(?![a-z0-9])", re.I)
ROM_QUALIFIER_RX = re.compile(r"(?<![a-z0-9])roms?(?![a-z0-9])|镜像", re.I)
MANUAL_INTENT_RX = re.compile(r"(?:官方\s*)?(?:说明书|手册)|game\s*pak\s*instructions", re.I)
TECHNICAL_INTENT_RX = re.compile(
    r"walking|running|jump|climb|accelerat|decelerat|coordinate|object|screen|"
    r"y\s*speed|x\s*speed|item\s*1|transform|坐标|对象|屏幕|跳跃|攀爬|步行|"
    r"跑步|速度|加速|减速|全速停止|加速度|减速度|xspd|地址范围|变换",
    re.I,
)
MEMORY_INTENT_RX = re.compile(
    r"内存|ram|地址|hp|weapon[_ ]?select|武器选择|血条|0x",
    re.I,
)
TAS_INTENT_RX = re.compile(r"tas|4057|4410|fm2|fm3|录像", re.I)
CATALOG_INTENT_RX = re.compile(
    r"platform|发售|销量|别名|英文名|中文名|平台", re.I,
)
MOVELIST_RX = re.compile(r"出招表|出招|指令表|连招表", re.I)

# 候选消费方的查询侧词表扩展：只补 TASVideos 原文使用的词形，不新增事实。
# 显式游戏别名在 revision 已钉死时从检索串移除，避免目录/标题元数据抢占技术证据。
SOURCE_TERM_FORMS = (
    (re.compile(r"(?<![a-z0-9])jump(?:s|ing)?(?![a-z0-9])", re.I), "jumps"),
    (re.compile(r"(?<![a-z0-9])climb(?:s|ing)?(?![a-z0-9])", re.I), "climbs"),
    (re.compile(r"(?<![a-z0-9])accelerat(?:e|es|ed|ing|ion)?(?![a-z0-9])", re.I), "accelerates"),
    (re.compile(r"(?<![a-z0-9])decelerat(?:e|es|ed|ing|ion)?(?![a-z0-9])", re.I), "decelerates"),
    (re.compile(r"(?<![a-z0-9])transform(?:s|ed|ing|ation)?(?![a-z0-9])", re.I), "transforming"),
    (re.compile(r"(?<![a-z0-9])coordinates?(?![a-z0-9])", re.I), "coordinates"),
)
ZH_SOURCE_TERM_FORMS = (
    (re.compile(r"步行|走路|行走"), "walking"),
    (re.compile(r"跳跃|起跳"), "jumps"),
    (re.compile(r"攀爬|爬梯"), "climbs"),
    (re.compile(r"加速"), "accelerates"),
    (re.compile(r"减速|(?:从)?全速停止"), "decelerates"),
    (re.compile(r"变换"), "transforming"),
    (re.compile(r"坐标"), "coordinates"),
    (re.compile(r"x\s*速度", re.I), "X speed"),
    (re.compile(r"地址范围|内存地址|ram\s*地址", re.I), "Memory addresses"),
)


def _retrieval_query(q):
    text = unicodedata.normalize("NFKC", q or "")
    for _name, rx in MM2_ALIASES:
        text = rx.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(?:的|之)+\s*", "", text).strip()
    text = re.sub(r"(?:速度(?:是)?多少|(?:地址范围|(?<!内存)地址|范围|平台)(?:是)?什么)$", "", text).strip()
    if not text:
        return q.strip()
    if TECHNICAL_INTENT_RX.search(text):
        if (MEMORY_INTENT_RX.search(text)
                and re.search(r"(?<![a-z0-9])x\s*(?:speed|速度)(?![a-z0-9])", text, re.I)
                and not re.search(r"(?<![a-z0-9])xspd(?![a-z0-9])", text, re.I)):
            text += " Xspd"
        jump_x = (re.search(r"jump|跳跃|起跳", text, re.I)
                  and re.search(r"(?<![a-z0-9])x\s*(?:speed|速度)(?![a-z0-9])", text, re.I))
        for rx, source_form in SOURCE_TERM_FORMS:
            present = re.search(r"(?<![a-z0-9])" + re.escape(source_form)
                                + r"(?![a-z0-9])", text, re.I)
            if rx.search(text) and not present and not (jump_x and source_form == "jumps"):
                text += " " + source_form
        for rx, source_form in ZH_SOURCE_TERM_FORMS:
            present = re.search(r"(?<![a-z0-9])" + re.escape(source_form)
                                + r"(?![a-z0-9])", text, re.I)
            if (rx.search(text) and not present
                    and not (jump_x and source_form == "jumps")):
                text += " " + source_form
        if jump_x:
            for source_form in ("jumping", "falling"):
                if not re.search(r"(?<![a-z0-9])" + source_form + r"(?![a-z0-9])", text, re.I):
                    text += " " + source_form
    return text


def _speed_axis_ok(q, text):
    normalized = unicodedata.normalize("NFKC", text or "")
    asks_x = re.search(r"(?<![a-z0-9])x\s*(?:speed|速度)(?![a-z0-9])",
                       unicodedata.normalize("NFKC", q), re.I)
    asks_y = re.search(r"(?<![a-z0-9])y\s*(?:speed|速度)(?![a-z0-9])",
                       unicodedata.normalize("NFKC", q), re.I)
    if asks_x and not re.search(r"(?<![a-z0-9])(?:x\s*speed|xspd)(?![a-z0-9])", normalized, re.I):
        return False
    if asks_y and not re.search(r"(?<![a-z0-9])(?:y\s*speed|yspd)(?![a-z0-9])", normalized, re.I):
        return False
    return True


def _revision_for(text):
    if MANUAL_INTENT_RX.search(text):
        return MANUAL_REVISION, "任天堂官方托管的美国 NES 说明书扫描短摘录；不证明 PAL/日版 ROM 等价"
    if TECHNICAL_INTENT_RX.search(text):
        return TECHNICAL_REVISION, "TASVideos GameResources 的 Rockman 2 技术条目；不主张地区 ROM 等价"
    if MEMORY_INTENT_RX.search(text):
        return MEMORY_REVISION, "本地二手内存字典；逐字段来源与 ROM 身份未核，只作线索"
    if TAS_INTENT_RX.search(text):
        return TAS_REVISION, "本地 TAS 出版物元数据；不证明 ROM 可用或玩法已验证"
    if CATALOG_INTENT_RX.search(text):
        return CATALOG_REVISION, "本地标题目录；平台与别名为二手目录口径"
    return TECHNICAL_REVISION, "TASVideos GameResources 的 Rockman 2 技术条目；不主张地区 ROM 等价"


def route_question(q):
    text = unicodedata.normalize("NFKC", q or "")
    matched = [name for name, rx in MM2_ALIASES if rx.search(text)]
    series = SERIES_RX.search(text) or matched
    if series and OTHER_WORK_RX.search(text):
        return {"domain": DOMAIN, "disposition": "ambiguous_series", "matched": matched,
                "revision": None,
                "reason": "问句指向力量对决/改版/洛克人X等同名或近名作品，不是本候选的 NES Rockman 2 技术范围"}
    unsupported = UNSUPPORTED_VERSION_RX.search(text)
    us_region = US_REGION_RX.search(text)
    ntsc = NTSC_RX.search(text)
    region = us_region or ntsc
    manual = MANUAL_INTENT_RX.search(text)
    manual_us_identity = bool(manual and us_region and not ROM_QUALIFIER_RX.search(text))
    if series and (unsupported or (region and not manual_us_identity)):
        version = unsupported or region
        return {"domain": DOMAIN, "disposition": "version_not_collected",
                "matched": matched, "revision": None,
                "reason": (f"候选只核验美国 NES 官方说明书；问句点名 {version.group(0)}，"
                           "未建立该地区 ROM 身份或跨版等价证据，不得用技术条目顶包")}
    if matched:
        other = [r for r in KR.route_many(text)
                 if r["tier"] == "strong"
                 and r["domain"] not in {"project_docs", "tooling", DOMAIN, PRODUCTION_DOMAIN}]
        if other or OTHER_INSTALLMENT_RX.search(text):
            return {"domain": DOMAIN, "disposition": "multi_domain_needs_split",
                    "matched": matched, "revision": None,
                    "reason": "问句同时点名其他游戏/代次内容域，候选消费方不合并放行"}
        revision, scope = _revision_for(text)
        return {"domain": DOMAIN, "disposition": "candidate", "matched": matched,
                "revision": revision, "evidence_scope": scope,
                "reason": "显式洛克人2别名；只查指定候选 revision，不借生产文本域"}
    if series:
        return {"domain": DOMAIN, "disposition": "ambiguous_series", "matched": [],
                "revision": None, "reason": "只有系列名、MM泛词或近名作品，不能认定是 NES 洛克人2；请补作品代次/版本"}
    return {"domain": "unrouted", "disposition": "not_matched", "matched": [],
            "revision": None, "reason": "未命中洛克人2显式别名；候选消费方不借其他库顶包"}


def _multi_domain_clause(q):
    parts = [part.strip(" ，,；;") for part in re.split(
        r"\s*(?:，|,|；|;)\s*(?:以及|并且|同时|和|与)\s*|\s*以及\s*", q, flags=re.I)
        if part.strip(" ，,；;")]
    matches = [part for part in parts
               if route_question(part).get("disposition") == "candidate"
               and route_question(part).get("matched")]
    return matches[0] if len(matches) == 1 else None


def expected_index_sha256():
    try:
        doc = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if doc.get("domain") != DOMAIN or not doc.get("index_sha256"):
        return None
    return doc["index_sha256"]


EXPECTED_INDEX_SHA256 = expected_index_sha256()


def _blocked(route, q, mode, refusal_override=None, reason_override=None, production=False):
    status = "miss" if route["disposition"] in {"ambiguous_series", "not_matched"} else "inconclusive"
    refusals = {
        "ambiguous_series": "ambiguous_series",
        "not_matched": "candidate_domain_not_matched",
        "version_not_collected": "version_not_collected",
        "multi_domain_needs_split": "multi_domain_needs_split",
    }
    reason = reason_override or route["reason"]
    return {"q": q, "mode": mode, "status": status,
            "refusal": refusal_override or refusals[route["disposition"]],
            "reason_code": refusal_override or refusals[route["disposition"]],
            "reason": reason, "route": route, "index_used": None,
            "index_sha256": None, "selected_evidence": [], "hits": [],
            "answer": {"kind": "refusal", "text": reason},
            "candidate_only": not production or route.get("revision") == MANUAL_REVISION,
            "whole_game_knowledge_base": False,
            "production_route_wired": production, "query_log": None}


def _blocked_log(q, mode, result, production=False):
    return {"schema_version": 2, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "caller": "kb_megaman2.ask", "entry_point": f"mm2-candidate-consumer-{mode}",
            "q": q, "status": result["status"], "refusal": result["refusal"],
            "reason": result["reason"], "route": result["route"],
            "retrieval": "not_run", "index_used": None, "index_sha256": None,
            "selected_evidence": [], "candidate_domain": DOMAIN,
            "production_route_wired": production}


def _append_log(path, row):
    path = Path(path)
    root = CANDIDATE_DIR.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("日志路径必须在 megaman2_candidate 候选目录内；拒绝写生产或其他目录")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return str(path)


def _finish(result, q, mode, log_path, raw_row=None, production=False):
    row = raw_row or _blocked_log(q, mode, result, production=production)
    result["query_log"] = row
    if log_path:
        _append_log(log_path, row)
    return result


def _inside_candidate(path):
    try:
        return S.resolve_path(path).resolve().is_relative_to(CANDIDATE_DIR.resolve())
    except OSError:
        return False


def _inside_source_evidence(path, source):
    try:
        resolved = S.resolve_path(path).resolve()
        return any(resolved == S.resolve_path(p).resolve() for p in source.get("evidence", []))
    except OSError:
        return False


def _display_path(path):
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def ask(q, mode="default", log_path=None, topk=8, top_window=3, assume_revision=False,
        production=False, allow_multi=False, index_path=None, map_path=None,
        registry_path=None, reg=None):
    if mode not in {"default", "strict"}:
        raise ValueError("mode 只允许 default/strict")
    if not isinstance(q, str) or not q.strip():
        raise ValueError("question 不能为空")
    if topk < 1 or top_window < 1:
        raise ValueError("topk/top_window 必须为正整数")
    request_q = q
    route = route_question(q)
    if allow_multi and route["disposition"] == "multi_domain_needs_split":
        q = _multi_domain_clause(q) or q
        route = route_question(q)
        if route["disposition"] == "multi_domain_needs_split":
            revision, scope = _revision_for(unicodedata.normalize("NFKC", q))
            route = {"domain": DOMAIN, "disposition": "candidate",
                     "matched": route.get("matched") or [], "revision": revision,
                     "evidence_scope": scope,
                     "reason": "生产多域分解：本域独立检索，外层不合并放行"}
        else:
            route = {**route, "reason": "生产多域分解：本域独立检索，外层不合并放行"}
    if assume_revision and route["disposition"] == "not_matched":
        revision, scope = _revision_for(unicodedata.normalize("NFKC", q))
        route = {"domain": DOMAIN, "disposition": "candidate",
                 "matched": ["explicit_revision_context"], "revision": revision,
                 "evidence_scope": scope,
                 "reason": "调用方显式提供洛克人2候选 revision 上下文"}
    if route["disposition"] != "candidate":
        return _finish(_blocked(route, q, mode, production=production),
                       q, mode, log_path, production=production)

    manual_revision = route["revision"] == MANUAL_REVISION
    candidate_mode = not production or manual_revision
    if manual_revision:
        index_file, map_file, registry_file = INDEX_PATH, MAP_PATH, REGISTRY_PATH
    else:
        index_file = Path(index_path) if index_path else (K.INDEX_JSON if production else INDEX_PATH)
        map_file = Path(map_path) if map_path else (K.CORPUS_MAP if production else MAP_PATH)
        registry_file = Path(registry_path) if registry_path else (S.REG_JSON if production else REGISTRY_PATH)
    expected = expected_index_sha256() if candidate_mode else None
    if (not index_file.is_file() or not map_file.is_file()
            or (reg is None and not registry_file.is_file())
            or (candidate_mode and not expected)):
        label = "候选" if candidate_mode else "生产"
        result = _blocked(route, q, mode, refusal_override="candidate_unavailable",
                          reason_override=f"{label}索引、corpus map、来源库或冻结契约缺失；失败关闭",
                          production=production)
        return _finish(result, q, mode, log_path, production=production)
    actual_sha = hashlib.sha256(index_file.read_bytes()).hexdigest()
    if candidate_mode and actual_sha != expected:
        result = _blocked(route, q, mode, refusal_override="candidate_hash_mismatch",
                          reason_override="候选索引 SHA 与冻结消费契约不符；不回退生产索引",
                          production=production)
        return _finish(result, q, mode, log_path, production=production)
    if production and route["revision"] not in {TECHNICAL_REVISION, MANUAL_REVISION}:
        result = _blocked(route, q, mode, refusal_override="revision_not_produced",
                          reason_override="生产域只接 TASVideos 技术 revision 与美国 NES 官方说明书候选；内存字典、目录与 TAS 元数据仍只作参考",
                          production=production)
        return _finish(result, q, mode, log_path, production=production)

    rows = []
    retrieval_q = _retrieval_query(q)
    try:
        registry = S.load_registry(registry_file) if manual_revision or reg is None else reg
        raw = K.query(retrieval_q, revision=route["revision"], topk=topk,
                      index_path=index_file, map_path=map_file, reg=registry,
                      top_window=top_window, require_verified=True,
                      fragment_policy="strict" if mode == "strict" else None,
                      log_sink=rows.append,
                      log_context={"entry_point": f"mm2-{'production' if production else 'candidate'}-consumer-{mode}"})
    except K.SchemaError as exc:
        result = _blocked(route, q, mode, refusal_override="candidate_unavailable",
                          reason_override=f"{'生产' if production else '候选'}主数据校验失败：{exc}；失败关闭",
                          production=production)
        return _finish(result, q, mode, log_path, production=production)

    if raw.get("index_used") != index_file.name or raw.get("index_sha256") != actual_sha:
        result = _blocked(route, q, mode, refusal_override="candidate_evidence_invalid",
                          reason_override="查询返回的索引身份不是本次冻结候选索引；失败关闭",
                          production=production)
        return _finish(result, q, mode, log_path, production=production)

    selected = raw.get("selected_evidence") or []
    index_chunks = {c["chunk_id"]: c for c in (K.load_index(index_file) or {}).get("chunks", [])}
    by_id = {s["source_id"]: s for s in registry["sources"]}
    invalid = []
    for hit in selected:
        source_path = hit.get("locator", "").split("#L", 1)[0]
        source = by_id.get(hit.get("source_id"))
        path_ok = (_inside_candidate(source_path) if candidate_mode else
                   bool(source and _inside_source_evidence(source_path, source)))
        allowed_source = MANUAL_SOURCE_ID if manual_revision else PRODUCTION_SOURCE_ID
        if (hit.get("status") != "verified_read" or hit.get("authority") != "authoritative"
                or hit.get("revision") != route["revision"]
                or source is None or source.get("status") != "verified_read"
                or (production and hit.get("source_id") != allowed_source)
                or not path_ok):
            invalid.append(hit.get("chunk_id"))
    axis_ok = True
    if raw.get("status") == "pass" and len(selected) == 1:
        selected_chunk = index_chunks.get(selected[0].get("chunk_id"), {})
        axis_ok = _speed_axis_ok(q, selected_chunk.get("text") or selected[0].get("snippet") or "")
    if raw.get("status") == "pass" and (len(selected) != 1 or invalid or not axis_ok):
        result = _blocked(route, q, mode, refusal_override="candidate_evidence_invalid",
                          reason_override="出证未通过来源/revision/路径/资格/问题轴向复核；失败关闭",
                          production=production)
        return _finish(result, q, mode, log_path, production=production)

    if raw.get("status") == "pass":
        selected_chunk = index_chunks.get(selected[0].get("chunk_id"), {})
        answer = {"kind": "evidence_excerpt",
                  "text": selected_chunk.get("text") or selected[0].get("snippet")
                          or selected[0].get("locator") or "",
                  "locator": selected[0].get("locator"),
                  "scope": route["evidence_scope"]}
    else:
        reason = raw.get("reason") or "候选证据不足，未放行"
        refusal = raw.get("refusal") or "candidate_evidence_insufficient"
        if MOVELIST_RX.search(q):
            refusal = "move_list_not_collected"
            reason = ("候选已收技术条目与美国 NES 官方说明书短摘录，但未收洛克人2出招表；"
                      "不会借 kb_route 的 KOF98 弱词或生产文本域回答。" + reason)
        answer = {"kind": "refusal", "text": reason}

    result = {"q": request_q, "mode": mode, "status": raw.get("status"),
              "refusal": raw.get("refusal"), "reason": raw.get("reason", ""),
              "retrieval_query": retrieval_q,
              "route": route, "index_used": raw.get("index_used"),
              "index_path": _display_path(index_file),
              "index_sha256": raw.get("index_sha256"), "selected_evidence": selected,
              "hits": raw.get("hits") or [], "answer": answer,
              "counts": raw.get("counts") or {},
              "production_route_observed": KR.route(unicodedata.normalize("NFKC", q)),
              "candidate_only": candidate_mode, "whole_game_knowledge_base": False,
              "production_route_wired": production, "query_log": None}
    if raw.get("status") != "pass":
        result["refusal"] = answer["kind"] == "refusal" and (
            "move_list_not_collected" if MOVELIST_RX.search(q)
            else raw.get("refusal") or "candidate_evidence_insufficient")
        if MOVELIST_RX.search(q):
            result["reason"] = reason
    if rows:
        row = dict(rows[0])
        row.update({"q": request_q, "caller": "kb_megaman2.ask", "candidate_domain": DOMAIN,
                    "candidate_revision": route["revision"],
                    "retrieval_query": retrieval_q,
                    "index_path": _display_path(index_file),
                    "registry_path": _display_path(registry_file),
                    "production_route_wired": production})
    else:
        row = _blocked_log(q, mode, result)
        row["retrieval"] = "missing_log_row"
    return _finish(result, request_q, mode, log_path, row, production=production)


def main(argv=None):
    parser = argparse.ArgumentParser(description="洛克人2隔离候选问答（不写生产索引/日志）")
    parser.add_argument("question")
    parser.add_argument("--mode", choices=("default", "strict"), default="default")
    parser.add_argument("--log", type=Path, help="可选：仅允许写候选目录内日志")
    parser.add_argument("--topk", type=int, default=8)
    parser.add_argument("--top-window", type=int, default=3)
    args = parser.parse_args(argv)
    result = ask(args.question, mode=args.mode, log_path=args.log,
                 topk=args.topk, top_window=args.top_window)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"pass", "miss", "inconclusive"} else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())

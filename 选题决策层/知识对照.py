# -*- coding: utf-8 -*-
"""KB对照：走 taspipe.kb.query_auto 生产代码路径，三档模式全部显式（说明书§5）。
自动识别问题中的全部知识域；多域独立检索且绝不合并成总 pass，查询留痕。
hybrid 需空闲内存≥8GB；bm25 用本层索引快照（不带指纹件→生产路径显式退回）；
off 不调KB但必须留痕。共享索引只读，快照是本层自己的副本。"""
import ctypes
import hashlib
import shutil
import sys
from pathlib import Path

MODDIR = Path(__file__).resolve().parent
TOOLS = MODDIR.parent / "_工具脚本"
SNAP = MODDIR / "kb快照"
QUERY_LOG = MODDIR / "查询日志.jsonl"
HYBRID_MIN_RAM_GB = 8.0


def free_ram_gb():
    class MEM(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    m = MEM()
    m.dwLength = ctypes.sizeof(MEM)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullAvailPhys / (1024 ** 3)


def resolve_mode(mode):
    """返回 (实际模式, 降级原因或None)。hybrid 内存不足时显式降 bm25。"""
    if mode == "hybrid":
        ram = free_ram_gb()
        if ram < HYBRID_MIN_RAM_GB:
            return "bm25", f"空闲内存{ram:.1f}GB<{HYBRID_MIN_RAM_GB:.0f}GB，hybrid降级bm25"
    return mode, None


def _import_kb():
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))
    from taspipe import kb
    return kb


def make_snapshot():
    """复制生产 index.json 到本层（不带嵌入指纹件）。返回 (快照路径, 源sha256)。"""
    kb = _import_kb()
    src = Path(kb.INDEX_JSON)
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    SNAP.mkdir(parents=True, exist_ok=True)
    dst = SNAP / "index.json"
    if not dst.is_file() or hashlib.sha256(dst.read_bytes()).hexdigest() != sha:
        tmp = dst.with_suffix(".tmp")
        shutil.copyfile(src, tmp)
        tmp.replace(dst)
    return dst, sha


def _domains():
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))
    from taspipe.kb_route import DOMAINS
    return DOMAINS


def static_sqlite_anchored(r):
    """只认 query_auto 的窄 LOL SQLite pass，不把通用文本 pass 放宽。"""
    if r.get("status") != "pass" or r.get("backend") != "esports_sqlite":
        return False
    auto = r.get("auto_routing") or {}
    domains = auto.get("domains") or []
    selected = r.get("selected_evidence") or []
    if auto.get("mode") != "single" or len(domains) != 1 or len(selected) != 1:
        return False
    if domains[0].get("domain") != "esports_lol" or not domains[0].get("structured_available"):
        return False
    entity = r.get("static_entity") or {}
    evidence = selected[0]
    return (entity.get("game_id") == "lol"
            and entity.get("entity_type") in {"game_character", "game_item", "game_spell"}
            and evidence.get("locator_type") == "json_pointer"
            and str(evidence.get("locator") or "").startswith("/data/")
            and bool(r.get("dataset_revision"))
            and evidence.get("backend") == "esports_sqlite")


def content_domains():
    """游戏内容域（从共享 DOMAINS 推导，只读）：有 game_ids 或游戏 revision，排除
    project_docs/tooling 内部文档域。域锚点闸门(crosscheck)与入口B域过滤(mine)共用此唯一权威。"""
    D = _domains()
    return {n for n, d in D.items()
            if (d["game_ids"] or d["revisions"]) and d["revisions"] != ["project_docs"]}


def content_block(game_id, revision):
    """块(game_id,revision)是否锚定游戏内容域。meta 域内部文档块永远排除，新游戏域自动纳入。
    与 crosscheck 域锚点同源（content_domains），不开第二份名单。"""
    D = _domains()
    gids, revs = set(), set()
    for n in content_domains():
        gids |= set(D[n]["game_ids"])
        revs |= set(D[n]["revisions"])
    return (game_id in gids) or (revision in revs)


def crosscheck(events, mode="bm25", limit=None, index_path=None):
    """event_id -> KB对照结果。limit 只限制查询条数，未查的显式标 not_queried。"""
    actual, downgrade = resolve_mode(mode)
    out = {}
    if actual == "off":
        for ev in events:
            out[ev["event_id"]] = {"mode": "off", "status": "未执行",
                                   "reason": "KB对照关闭（运行记录须点名原因）", "hits": []}
        return out, {"mode": "off", "downgrade": downgrade, "queried": 0}
    kb = _import_kb()
    from taspipe.kb_route import route
    # 域锚点闸门与入口B域过滤共用 content_domains() 唯一权威（meta 域永远排除，新游戏域自动纳入）。
    cdomains = content_domains()
    if index_path is None and actual == "bm25":
        index_path, src_sha = make_snapshot()
    else:
        src_sha = (hashlib.sha256(Path(index_path).read_bytes()).hexdigest()
                   if index_path and Path(index_path).is_file() else None)
    cache = {}
    cache_events = {}
    queried = 0
    unanchored = 0
    multi_domain = 0
    for i, ev in enumerate(events):
        eid = ev["event_id"]
        if limit is not None and queried >= limit:
            out[eid] = {"mode": actual, "status": "not_queried",
                        "reason": f"超出本轮KB查询上限{limit}，未对照", "hits": []}
            continue
        q = ev["titles"][0] if ev["titles"] else ""
        if not q.strip():
            out[eid] = {"mode": actual, "status": "empty_title", "reason": "无标题可查", "hits": []}
            continue
        if q not in cache:
            try:
                cache[q] = kb.query_auto(q, topk=3, index_path=index_path)
            except Exception as e:  # 单点失败不拖死整批，但必须留痕
                cache[q] = {"status": "error", "reason": f"{type(e).__name__}: {e}", "hits": []}
            cache_events[q] = []
            queried += 1
        cache_events[q].append(eid)
        r = cache[q]
        status = r.get("status")
        reason = r.get("reason", "")
        refusal = r.get("refusal", "")
        selected_evidence = r.get("selected_evidence") or []
        # 域锚点闸门：只有锚定到游戏内容域的 pass 才可当硬证据。
        # unrouted（无域关键词→全库乱撞，如 Kirby 的 Switch 撞 FBNeo switch 0x4081 token）
        # 与弱词撞进内部文档域（如 "tas"⊂"Fantasy" 把 FF 新闻路由到 project_docs，
        # 拿本项目闸门文档当证据）都是 bm25 词面噪声，显式降级 inconclusive/unanchored。
        if status == "pass":
            auto = r.get("auto_routing") or {}
            auto_domains = auto.get("domains") or [route(q)]
            anchored = ((auto.get("mode") == "single" and len(auto_domains) == 1
                         and auto_domains[0].get("domain") in cdomains)
                        or static_sqlite_anchored(r))
            if not anchored:
                rt = auto_domains[0] if auto_domains else route(q)
                status = "inconclusive"
                refusal = "unanchored"
                selected_evidence = []
                reason = (f"自动路由未锚定游戏内容域（route={rt.get('domain')}/tier={rt.get('tier')}），"
                        f"全库或内部文档域词面命中不可当硬证据；原pass理由：" + reason)
                unanchored += 1
        out[eid] = {
            "mode": actual,
            "status": status,
            "retrieval": r.get("retrieval", ""),
            "backend": r.get("backend", ""),
            "answer_text": r.get("answer_text", ""),
            "claim": r.get("claim"),
            "dataset_revision": r.get("dataset_revision"),
            "reason_code": r.get("reason_code"),
            "query_conditions": r.get("query_conditions"),
            "static_entity": r.get("static_entity"),
            "retrieval_note": r.get("retrieval_note", ""),
            "reason": reason,
            "refusal": refusal,
            # 出证绑定透传（阶段1）：pass 凭哪块放行。旧结果/mock 无此字段时为空，
            # 下游不得拿全部 hits 冒充证据；域外降级时同步清空原 pass 出证。
            "selected_evidence": selected_evidence,
            "index_used": r.get("index_used", ""),
            "index_sha256": "" if r.get("backend") == "esports_sqlite" else (r.get("index_sha256") or src_sha),
            "version_hints": r.get("version_hints") or [],
            "auto_routing": r.get("auto_routing") or {},
            "domain_results": [{k: d.get(k) for k in
                                ("domain", "tier", "matched", "corpus_available", "status",
                                 "refusal", "reason", "reason_code", "retrieval", "backend",
                                 "answer_text", "claim", "dataset_revision", "query_conditions",
                                 "static_entity", "counts", "selected_evidence",
                                 "index_used", "index_sha256")}
                               for d in (r.get("domain_results") or [])],
            "hits": [{"locator": h.get("locator"), "snippet": h.get("snippet", "")[:240],
                      "authority": h.get("authority"), "status": h.get("status"),
                      "answerable": (h.get("answerability") or {}).get("answerable")}
                     for h in (r.get("hits") or [])[:3]],
        }
    logged = 0
    for q, r in cache.items():
        event_ids = cache_events.get(q) or []
        final = {**r, **(out[event_ids[0]] if event_ids else {}), "q": q}
        kb.append_query_log(final, path=QUERY_LOG, caller="选题决策层.crosscheck",
                            event_ids=event_ids)
        logged += 1
        if (r.get("auto_routing") or {}).get("mode") == "multi":
            multi_domain += 1
    actual_sha = src_sha or next((r.get("index_sha256") for r in out.values()
                                  if r.get("index_sha256")), None)
    info = {"mode": actual, "downgrade": downgrade, "queried": queried,
            "unanchored_downgraded": unanchored,
            "routing": "auto_multi", "multi_domain_queries": multi_domain,
            "query_log": str(QUERY_LOG), "logged_queries": logged,
            "index_sha256": actual_sha, "snapshot": str(index_path) if index_path else "生产默认索引"}
    return out, info
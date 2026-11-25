# -*- coding: utf-8 -*-
"""洛克人1隔离候选问答：显式别名、版本拒答、生产 kb.query 与候选日志。"""
import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

from . import kb as K
from . import kb_route as KR
from . import sources as S

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent.parent
CANDIDATE_DIR = REPO_ROOT / "知识库P1_20261118" / "megaman1_candidate_v2_manual_20261125"
INDEX_PATH = CANDIDATE_DIR / "index.json"
MAP_PATH = CANDIDATE_DIR / "corpus_map.json"
REGISTRY_PATH = CANDIDATE_DIR / "sources.json"
EXPECTED_INDEX_SHA256 = "d8de2bcf742e5a7df4df86a29b6162bcc815c1977719009b5cfe3542bc86c6be"
SOURCES_PATH = S.REG_JSON
FROZEN_QUESTIONS = REPO_ROOT / "知识库P1_20261118" / "megaman1_questions_frozen_v2_manual_20261125.json"


def expected_index_sha256():
    return EXPECTED_INDEX_SHA256
REVISION = "megaman1_nes_us"
DOMAIN = "megaman1_candidate"
PRODUCTION_DOMAIN = "megaman1"

MM1_ALIASES = (
    ("洛克人1", re.compile(r"洛克人\s*(?:1|一)(?![\d一二三四五六七八九十ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ])")),
    ("洛克人Ⅰ", re.compile(r"洛克人\s*Ⅰ(?![ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ])", re.I)),
    ("Mega Man 1", re.compile(r"(?<![a-z0-9])mega\s*man\s*(?:1|Ⅰ)(?![a-z0-9])", re.I)),
    ("Rockman 1", re.compile(r"(?<![a-z0-9])rockman\s*(?:1|Ⅰ)(?![a-z0-9])", re.I)),
    ("MM1", re.compile(r"(?<![a-z0-9])mm\s*1(?![a-z0-9])", re.I)),
)
SERIES_RX = re.compile(r"洛克人|(?<![a-z0-9])mega\s*man(?![a-z0-9])|(?<![a-z0-9])rockman(?![a-z0-9])", re.I)
OTHER_INSTALLMENT_RX = re.compile(
    r"洛克人\s*(?:[2-9]|\d{2,}|[二三四五六七八九十ⅡⅢⅣⅤⅥⅦⅧⅨⅩ])"
    r"|(?<![a-z0-9])(?:mega\s*man|rockman|mm)\s*"
    r"(?:[2-9]|\d{2,}|ii|iii|iv|v|vi|vii|viii|ix|x)(?![a-z0-9])", re.I)
VERSION_CONFLICT_RX = re.compile(r"(?<![a-z0-9])pal(?:\s*[-_]?\s*b)?(?![a-z0-9])|欧版|欧洲版", re.I)


def route_question(q):
    text = unicodedata.normalize("NFKC", q or "")
    series = SERIES_RX.search(text)
    conflict = VERSION_CONFLICT_RX.search(text)
    matched = [name for name, rx in MM1_ALIASES if rx.search(text)]
    if series and conflict:
        return {"domain": DOMAIN, "disposition": "version_not_collected",
                "matched": matched, "revision": None,
                "reason": f"候选只覆盖 NTSC 美版；问句点名 {conflict.group(0)}，不得跨版代答"}
    if matched:
        other = [r for r in KR.route_many(text)
                 if r["tier"] == "strong"
                 and r["domain"] not in {DOMAIN, PRODUCTION_DOMAIN, "project_docs", "tooling"}]
        if other:
            return {"domain": DOMAIN, "disposition": "multi_domain_needs_split",
                    "matched": matched, "revision": None,
                    "reason": "问句同时点名其他游戏内容域，候选消费方不合并放行"}
        return {"domain": DOMAIN, "disposition": "candidate", "matched": matched,
                "revision": REVISION, "reason": "显式洛克人1别名；只查 NTSC 美版 RAM/工具方法与官方说明书短摘录候选"}
    if SERIES_RX.search(text):
        other_installment = bool(OTHER_INSTALLMENT_RX.search(text))
        return {"domain": DOMAIN, "disposition": "ambiguous_series", "matched": [],
                "other_installment": other_installment, "revision": None,
                "reason": ("点名其他洛克人代次或近名作品，不是本候选" if other_installment else
                           "只给系列名或缺代次，不能认定是洛克人1；请补作品代次/版本")}
    return {"domain": "unrouted", "disposition": "not_matched", "matched": [],
            "revision": None, "reason": "未命中洛克人1显式别名；候选消费方不借其他库顶包"}


def _blocked(route, q, mode, *, production=False, refusal=None, reason_code=None):
    if refusal is None:
        refusal = {"ambiguous_series": "ambiguous_series", "not_matched": "candidate_domain_not_matched",
                   "version_not_collected": "version_not_collected",
                   "multi_domain_needs_split": "multi_domain_needs_split"}[route["disposition"]]
    status = "miss" if route["disposition"] in {"ambiguous_series", "not_matched"} else "inconclusive"
    if refusal in {"candidate_unavailable", "candidate_hash_mismatch", "candidate_schema_error",
                   "candidate_evidence_invalid"}:
        status = "inconclusive"
    return {"q": q, "mode": mode, "status": status, "refusal": refusal,
            "reason_code": reason_code or refusal, "reason": route["reason"], "route": route,
            "index_used": None, "index_sha256": None, "selected_evidence": [], "hits": [],
            "counts": {"candidate_chunks": 0, "returned_hits": 0,
                       "selected_evidence": 0, "window_passed": 0},
            "retrieval_query": None,
            "answer": {"kind": "refusal", "text": route["reason"]},
            "candidate_only": True, "whole_game_knowledge_base": False,
            "production_route_wired": bool(production), "query_log": None}


def _blocked_log(route, q, mode, result, production):
    return {"caller": "kb_megaman1.ask",
            "entry_point": f"mm1-{'production' if production else 'candidate-consumer'}-{mode}",
            "q": q, "status": result["status"], "refusal": result["refusal"],
            "reason_code": result["reason_code"], "reason": result["reason"],
            "route": route, "retrieval": "not_run"}


def _append_log(path, row):
    path = Path(path).resolve()
    if path != CANDIDATE_DIR and CANDIDATE_DIR not in path.parents:
        raise K.SchemaError("洛克人1候选日志只能写入候选目录")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return str(path)


def ask(q, mode="default", log_path=None, topk=8, top_window=3, assume_revision=False,
        production=False, allow_multi=False):
    if mode not in {"default", "strict"}:
        raise ValueError("mode 只允许 default/strict")
    if not isinstance(q, str) or not q.strip():
        raise ValueError("question 不能为空")
    if topk < 1 or top_window < 1:
        raise ValueError("topk/top_window 必须为正整数")
    route = route_question(q)
    if assume_revision and route["disposition"] in {"not_matched", "ambiguous_series"}:
        route = {"domain": DOMAIN, "disposition": "candidate",
                 "matched": ["explicit_revision_context"], "revision": REVISION,
                 "reason": "调用方显式提供洛克人1 NTSC 美版 revision 上下文"}
    if (production and allow_multi and route["disposition"] == "multi_domain_needs_split"):
        route = {**route, "disposition": "candidate",
                 "reason": "生产多域已拆分；本分支只检索洛克人1候选，不合并其他域结论"}
    if route["disposition"] != "candidate":
        result = _blocked(route, q, mode, production=production)
        if log_path:
            result["query_log"] = _append_log(log_path, _blocked_log(route, q, mode, result, production))
        return result

    def unavailable(disposition, reason, refusal):
        blocked_route = {"domain": DOMAIN, "disposition": disposition,
                         "matched": route["matched"], "revision": None, "reason": reason}
        result = _blocked(blocked_route, q, mode, production=production,
                          refusal=refusal, reason_code=refusal)
        if log_path:
            result["query_log"] = _append_log(
                log_path, _blocked_log(blocked_route, q, mode, result, production))
        return result

    expected = expected_index_sha256()
    if (not all(p.is_file() for p in (INDEX_PATH, MAP_PATH, REGISTRY_PATH))
            or not expected):
        return unavailable("not_matched", "候选索引、corpus map、来源库或冻结契约缺失；不回退生产索引",
                           "candidate_unavailable")
    actual_sha = hashlib.sha256(INDEX_PATH.read_bytes()).hexdigest()
    if actual_sha != expected:
        return unavailable("not_matched", "候选索引 SHA 与冻结消费契约不符；不回退生产索引",
                           "candidate_hash_mismatch")
    try:
        index = K.load_index(INDEX_PATH)
        corpus_map = K.load_map(MAP_PATH)
        registry = S.load_registry(REGISTRY_PATH)
    except Exception as exc:
        return unavailable("not_matched", f"候选输入无法解析：{type(exc).__name__}；不回退生产索引",
                           "candidate_schema_error")
    if REVISION not in corpus_map.get("revisions", {}):
        return unavailable("not_matched", "候选 corpus map 未登记洛克人1 NTSC 美版 revision",
                           "candidate_schema_error")
    retrieval_q = q.strip()
    rows = []
    raw = K.query(retrieval_q, revision=REVISION, topk=topk, index_path=INDEX_PATH,
                  map_path=MAP_PATH, reg=registry, top_window=top_window,
                  fragment_policy="strict" if mode == "strict" else None,
                  require_verified=True, log_sink=rows.append,
                  log_context={"entry_point": f"mm1-{'production' if production else 'candidate-consumer'}-{mode}"})
    by_id = {s["source_id"]: s for s in registry["sources"]}
    selected = raw.get("selected_evidence") or []
    evidence_error = None
    if raw.get("index_used") != INDEX_PATH.name or raw.get("index_sha256") != actual_sha:
        evidence_error = "返回索引身份或 SHA 与冻结候选不一致"
    if evidence_error is None and raw.get("status") == "pass":
        if len(selected) != 1:
            evidence_error = "候选 pass 必须恰好给出一条 selected evidence"
        else:
            evidence = selected[0]
            source = by_id.get(evidence.get("source_id"))
            locator_text = str(evidence.get("locator") or "").split("#L", 1)[0]
            locator_path = Path(locator_text)
            if not locator_path.is_absolute():
                locator_path = REPO_ROOT / locator_path
            if (evidence.get("status") != "verified_read"
                    or evidence.get("authority") != "authoritative"
                    or evidence.get("revision") != REVISION
                    or evidence.get("source_id") not in by_id
                    or not isinstance(source, dict)
                    or source.get("status") != "verified_read"
                    or not locator_path.is_absolute()
                    or CANDIDATE_DIR.resolve() not in locator_path.resolve().parents):
                evidence_error = "候选出证未通过来源、revision 或证据路径资格复核"
    if evidence_error:
        return unavailable("not_matched", f"{evidence_error}；不回退生产索引",
                           "candidate_evidence_invalid")
    answer_text = (selected[0].get("answer_text") or selected[0].get("snippet")
                   or selected[0].get("locator") or raw.get("reason") or "") if selected else (
                       raw.get("reason") or "候选证据不足，未放行")
    answer_kind = "answer" if raw.get("status") == "pass" and selected else "refusal"
    result = {"q": q, "mode": mode, "status": raw.get("status"),
              "refusal": raw.get("refusal"), "reason_code": raw.get("reason_code"),
              "reason": raw.get("reason", ""), "route": route,
              "index_used": raw.get("index_used"), "index_sha256": raw.get("index_sha256"),
              "index_path": INDEX_PATH.relative_to(REPO_ROOT).as_posix(),
              "selected_evidence": selected, "hits": raw.get("hits") or [],
              "counts": raw.get("counts") or {}, "retrieval_query": retrieval_q,
              "answer_text": answer_text,
              "answer": {"kind": answer_kind, "text": answer_text,
                         "locator": selected[0].get("locator") if selected else None},
              "candidate_only": True, "whole_game_knowledge_base": False,
              "production_route_observed": KR.route(unicodedata.normalize("NFKC", q)),
              "production_route_wired": bool(production),
              "query_log": rows[0] if rows else None}
    if log_path:
        result["query_log"] = _append_log(log_path, rows[0] if rows else
                                          _blocked_log(route, q, mode, result, production))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="洛克人1隔离候选问答（不写生产索引/日志）")
    parser.add_argument("question")
    parser.add_argument("--mode", choices=("default", "strict"), default="default")
    parser.add_argument("--log", type=Path, help="可选：仅写指定候选日志文件")
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

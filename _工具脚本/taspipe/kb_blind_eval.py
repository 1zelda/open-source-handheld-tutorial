# -*- coding: utf-8 -*-
"""隔离盲测：调用生产 kb.query/query_auto，复用 grade_v2，不写真实知识库状态。"""
import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "知识库小样_20261118"))

from taspipe import kb as K  # noqa: E402
from taspipe import kb_answer as KA  # noqa: E402
from taspipe import kb_esports as KE  # noqa: E402
from taspipe import kb_route as KR  # noqa: E402
from taspipe import kb_selector as KS  # noqa: E402
from taspipe import sources as S  # noqa: E402
from taspipe.schema import SchemaError  # noqa: E402
import eval_common as E  # noqa: E402

TIERS = {"strict_pass", "gold_in_topk", "refuse", "version_guard"}
FILTER_KEYS = {"game", "revision", "platform", "want"}


class InputError(ValueError):
    pass


def _sha(path):
    p = Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def _snapshot(paths):
    out = {}
    for path in paths:
        p = Path(path)
        try:
            st = p.stat()
        except FileNotFoundError:
            out[str(p)] = {"exists": False, "mtime_ns": None, "size": None, "sha256": None}
            continue
        out[str(p)] = {"exists": p.is_file(), "mtime_ns": st.st_mtime_ns,
                       "size": st.st_size, "sha256": _sha(p)}
    return out


def _atomic_text(path, text):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".tmp-{uuid.uuid4().hex}")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(str(tmp), str(p))
    finally:
        if tmp.exists():
            tmp.unlink()


def _protected_paths():
    return [K.INDEX_JSON, K.CORPUS_MAP, S.REG_JSON, S.LEDGER_JSON,
            KE.DB_PATH, K.KB_DIR / "query_log.jsonl"]


def _validate_suite(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputError(f"题集不可读：{exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
        raise InputError("题集必须是含 questions 数组的对象")
    questions = data["questions"]
    if not questions:
        raise InputError("题集 questions 不能为空")
    seen = set()
    for i, q in enumerate(questions, 1):
        if not isinstance(q, dict):
            raise InputError(f"第 {i} 题不是对象")
        qid = q.get("id")
        if not isinstance(qid, str) or not qid.strip() or qid in seen:
            raise InputError(f"第 {i} 题 id 缺失或重复：{qid!r}")
        seen.add(qid)
        if not isinstance(q.get("q"), str) or not q["q"].strip():
            raise InputError(f"{qid} 缺问题正文")
        if q.get("expect") not in TIERS:
            raise InputError(f"{qid} expect 必须是 {sorted(TIERS)} 之一")
        filters = q.get("filters", {})
        if not isinstance(filters, dict):
            raise InputError(f"{qid} filters 必须是对象")
        unknown = sorted(set(filters) - FILTER_KEYS)
        if unknown:
            raise InputError(f"{qid} filters 含未知字段：{unknown}")
        if q["expect"] in ("strict_pass", "gold_in_topk"):
            gold = q.get("gold")
            if not isinstance(gold, dict) or not isinstance(gold.get("path_contains"), str):
                raise InputError(f"{qid} 缺 gold.path_contains")
            s, e = gold.get("line_start"), gold.get("line_end")
            if not isinstance(s, int) or not isinstance(e, int) or s < 1 or e < s:
                raise InputError(f"{qid} gold 行段非法")
    return questions


def _result_summary(result):
    selected = []
    for hit in (result.get("selected_evidence") or [])[:8]:
        selected.append({k: hit.get(k) for k in
                         ("chunk_id", "locator", "source_id", "authority", "revision")
                         if hit.get(k) is not None})
        selected[-1]["snippet"] = str(hit.get("snippet") or "")[:240]
    hits = []
    for hit in (result.get("hits") or [])[:30]:
        hits.append({k: hit.get(k) for k in
                     ("chunk_id", "locator", "score", "status", "authority", "revision")
                     if hit.get(k) is not None})
        hits[-1]["snippet"] = str(hit.get("snippet") or "")[:240]
    return {"status": result.get("status"), "refusal": result.get("refusal"),
            "reason": str(result.get("reason") or "")[:500],
            "answer_text": str(result.get("answer_text") or "")[:2000],
            "counts": result.get("counts") or {}, "retrieval": result.get("retrieval"),
            "index_used": result.get("index_used"), "index_sha256": result.get("index_sha256"),
            "authority_warnings": result.get("authority_warnings") or [],
            "selected_evidence": selected, "hits": hits,
            "auto_routing": result.get("auto_routing")}


def _render(data):
    summary = data["summary"]
    lines = [f"# 隔离盲测 · {data['taken_at']}", "",
             f"- 严格通过：{summary['ok']}/{summary['total']}",
             f"- API：`{data['api']}`；topk={data['params']['topk']}；"
             f"top_window={data['params']['top_window']}",
             f"- 索引：`{data['index']['path']}` sha256 `{data['index']['sha256']}`",
             f"- 真实状态隔离：{'PASS' if data['isolation']['ok'] else 'FAIL'}",
             f"- 隔离查询日志：{data.get('query_log') or '未启用'}", "",
             "## 分档", "", "| 档 | 通过 | 总数 |", "|---|---:|---:|"]
    for tier, counts in summary["by_tier"].items():
        lines.append(f"| {tier} | {counts['ok']} | {counts['total']} |")
    lines += ["", "## 逐题", "", "| 题 | 档 | 结果 | 状态/拒答 | 出证定位 | 说明 |",
              "|---|---|---|---|---|---|"]
    for row in data["questions"]:
        grade = row["grade"]
        locator = (row["result"].get("selected_evidence") or [{}])[0].get("locator") or "-"
        lines.append(f"| {row['id']} | {row['tier']} | {grade['ok']} | "
                     f"{row['result'].get('status')}/{row['result'].get('refusal') or '-'} | "
                     f"{locator} | {grade.get('why') or grade.get('error') or '-'} |")
    if not data["isolation"]["ok"]:
        lines += ["", "## 隔离失败", ""]
        for path in data["isolation"]["changed_paths"]:
            lines.append(f"- {path}")
    return "\n".join(lines) + "\n"


def run(questions, args, run_id, log_path):
    rows = []
    request_id = f"blind-{run_id}"
    for i, q in enumerate(questions, 1):
        filters = q.get("filters", {})
        params = dict(game=filters.get("game"), revision=filters.get("revision"),
                      platform=filters.get("platform"), want=filters.get("want"),
                      topk=args.topk, top_window=args.top_window,
                      index_path=str(args.index), map_path=str(args.map))
        call_id = f"{request_id}-{i}"
        sink = None
        if log_path is not None:
            def sink(row, _qid=q["id"], _call_id=call_id):
                row = {**row, "call_id": _call_id, "eval_question_id": _qid,
                       "eval_run_id": run_id}
                K.write_query_log_row(row, path=log_path)
        try:
            if args.api == "query_auto":
                result = K.query_auto(q["q"], log_sink=sink,
                                      log_context={"request_id": request_id,
                                                   "call_id": call_id,
                                                   "entry_point": "blind_eval"}, **params)
            else:
                result = K.query(q["q"], log_sink=sink,
                                 log_context={"request_id": request_id,
                                              "call_id": call_id,
                                              "entry_point": "blind_eval"}, **params)
            grade = E.grade_v2(q, result)
            summary = _result_summary(result)
        except Exception as exc:
            grade = {"id": q["id"], "tier": q["expect"], "ok": False,
                     "why": "", "error": f"{type(exc).__name__}: {exc}"[:500]}
            summary = {"status": "error", "refusal": None,
                       "reason": grade["error"], "selected_evidence": [], "hits": []}
        rows.append({"id": q["id"], "tier": q["expect"], "q": q["q"],
                     "grade": grade, "result": summary})
        print(f"{q['id']} {grade['ok']} {summary.get('status')}/"
              f"{summary.get('refusal') or grade.get('error') or '-'}", flush=True)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--suite", required=True)
    ap.add_argument("--out", required=True, help="输出前缀；写 .json/.md，日志写 .query_log.jsonl")
    ap.add_argument("--api", choices=("query", "query_auto"), default="query_auto")
    ap.add_argument("--topk", type=int, default=30)
    ap.add_argument("--top-window", type=int, default=3)
    ap.add_argument("--index", default=str(K.INDEX_JSON))
    ap.add_argument("--map", default=str(K.CORPUS_MAP))
    ap.add_argument("--no-log", action="store_true")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        if args.topk < 1 or args.top_window < 1:
            raise InputError("topk 与 top-window 必须为正整数")
        args.index = Path(args.index).resolve()
        args.map = Path(args.map).resolve()
        args.suite = Path(args.suite).resolve()
        args.out = Path(args.out).resolve()
        if K.load_index(args.index) is None:
            raise InputError(f"索引不存在：{args.index}")
        K.load_map(args.map)
        questions = _validate_suite(args.suite)
        json_path = args.out.with_suffix(".json")
        md_path = args.out.with_suffix(".md")
        log_path = None if args.no_log else args.out.with_suffix(".query_log.jsonl")
        outputs = [json_path, md_path] + ([log_path] if log_path else [])
        protected = {str(p.resolve()) for p in _protected_paths()}
        if any(str(p.resolve()) in protected for p in outputs) or args.suite in outputs:
            raise InputError("输出路径不得覆盖真实知识库状态或题集原件")
    except (InputError, OSError, SchemaError) as exc:
        print(f"INPUT ERROR {exc}", file=sys.stderr)
        return 2

    before = _snapshot(_protected_paths())
    run_id = uuid.uuid4().hex
    if log_path is not None:
        _atomic_text(log_path, "")
    rows = run(questions, args, run_id, log_path)
    after = _snapshot(_protected_paths())
    changed = [p for p in before if before[p] != after[p]]
    grades = [r["grade"] for r in rows if "error" not in r["grade"]]
    summary = E.summarize_v2(grades)
    error_rows = [r for r in rows if "error" in r["grade"]]
    by_tier = {}
    for row in rows:
        counts = by_tier.setdefault(row["tier"], {"total": 0, "ok": 0})
        counts["total"] += 1
        counts["ok"] += int(row["grade"]["ok"])
    summary["total"] = len(rows)
    summary["ok"] = sum(int(r["grade"]["ok"]) for r in rows)
    summary["by_tier"] = by_tier
    summary["failed_ids"] = [r["id"] for r in rows if not r["grade"]["ok"]]
    summary["errors"] = len(error_rows)
    data = {"schema": "kb_blind_eval_v1", "taken_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "run_id": run_id, "suite": {"path": str(args.suite), "sha256": _sha(args.suite)},
            "api": args.api,
            "params": {"topk": args.topk, "top_window": args.top_window,
                       "index": str(args.index), "map": str(args.map), "logging": not args.no_log},
            "index": {"path": str(args.index), "sha256": _sha(args.index),
                      "chunks": len(K.load_index(args.index)["chunks"])},
            "map_sha256": _sha(args.map), "query_log": str(log_path) if log_path else None,
            "code": {name: _sha(module.__file__) for name, module in
                     (("kb", K), ("kb_answer", KA), ("kb_route", KR), ("kb_selector", KS),
                      ("kb_esports", KE), ("grader", E), ("producer", sys.modules[__name__]))},
            "summary": summary, "questions": rows,
            "isolation": {"ok": not changed, "changed_paths": changed,
                          "before": before, "after": after}}
    _atomic_text(json_path, json.dumps(data, ensure_ascii=False, indent=1))
    _atomic_text(md_path, _render(data))
    print(f"DONE {summary['ok']}/{summary['total']} isolation={data['isolation']['ok']} {md_path}")
    return 0 if data["isolation"]["ok"] and summary["ok"] == summary["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

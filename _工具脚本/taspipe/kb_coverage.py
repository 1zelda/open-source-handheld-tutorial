# -*- coding: utf-8 -*-
"""全域知识库覆盖看板：文本索引 + 电竞结构化事实，只读聚合。"""
import argparse
import collections
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import kb
from . import kb_esports as KE
from . import kb_route as KR

STATES = ("verified", "partial", "present_unverified", "registered_empty",
          "not_registered", "stale", "unknown")
DYNAMIC_TABLES = ("series", "membership", "transfer_event", "patch_deployment")


def _sha(p):
    p = Path(p)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _domains_for(game=None, revision=None, q=None):
    found = []
    for domain, spec in KR.DOMAINS.items():
        if ((game and game in spec["game_ids"]) or
                (revision and revision in spec["revisions"])):
            found.append(domain)
    if found or not q:
        return found
    return [r["domain"] for r in KR.route_many(q) if r["domain"] != "unrouted"]


def _state(chunks=0, strong=0, evidence=0, verified_read=0, registered=True, stale=False):
    if not registered:
        return "not_registered"
    if stale:
        return "stale"
    if strong or evidence:
        return "verified"
    if verified_read:
        return "present_unverified"
    if chunks:
        return "partial"
    return "registered_empty"


def _read_eval(path):
    if not path or not Path(path).is_file():
        return None, {}
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    by_domain = collections.defaultdict(lambda: {"questions": 0, "base_correct": 0})
    for r in d.get("questions", []):
        domains = _domains_for(q=r.get("q", ""))
        for domain in domains:
            by_domain[domain]["questions"] += 1
            by_domain[domain]["base_correct"] += int(r["base"]["grade"]["ok"])
    return d, by_domain


def _query_bucket():
    return {"total_rows": 0, "questions": set(), "status_counts": collections.Counter(),
            "selected_evidence_rows": 0, "malformed_rows": 0, "empty_questions": 0,
            "missing_index_fingerprints": 0, "missing_status": 0,
            "pass_without_evidence": 0, "nonpass_with_evidence": 0,
            "fragment_policies": collections.Counter(), "latest_ts": None,
            "diagnostic_rows": 0, "multi_domain_rows": 0, "domain_evidence_rows": 0,
            "route_modes": collections.Counter(), "entry_points": collections.Counter(),
            "elapsed_ms_total": 0.0, "elapsed_samples": 0, "elapsed_ms_max": 0.0}


def _add_query_row(bucket, row):
    q = row.get("q")
    q = q.strip() if isinstance(q, str) else ""
    status = row.get("status") or "unknown"
    selected = bool(row.get("selected_evidence"))
    bucket["total_rows"] += 1
    if q:
        bucket["questions"].add(q)
    else:
        bucket["empty_questions"] += 1
    bucket["status_counts"][status] += 1
    bucket["selected_evidence_rows"] += int(selected)
    bucket["missing_index_fingerprints"] += int(not row.get("index_sha256"))
    bucket["missing_status"] += int(not row.get("status"))
    bucket["pass_without_evidence"] += int(status == "pass" and not selected)
    bucket["nonpass_with_evidence"] += int(status != "pass" and selected)
    bucket["fragment_policies"][row.get("fragment_policy") or "unspecified"] += 1
    bucket["diagnostic_rows"] += int(isinstance(row.get("schema_version"), int)
                                      and row["schema_version"] >= 2)
    if row.get("route_mode"):
        bucket["route_modes"][str(row["route_mode"])] += 1
    if row.get("entry_point"):
        bucket["entry_points"][str(row["entry_point"])] += 1
    elapsed = row.get("elapsed_ms")
    if isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool) and elapsed >= 0:
        bucket["elapsed_ms_total"] += float(elapsed)
        bucket["elapsed_samples"] += 1
        bucket["elapsed_ms_max"] = max(bucket["elapsed_ms_max"], float(elapsed))
    ts = row.get("ts")
    if isinstance(ts, str) and (bucket["latest_ts"] is None or ts > bucket["latest_ts"]):
        bucket["latest_ts"] = ts


def _finish_query_bucket(bucket):
    total = bucket["total_rows"]
    bucket["unique_questions"] = len(bucket.pop("questions"))
    bucket["status_counts"] = dict(bucket["status_counts"])
    bucket["fragment_policies"] = dict(bucket["fragment_policies"])
    bucket["route_modes"] = dict(bucket["route_modes"])
    bucket["entry_points"] = dict(bucket["entry_points"])
    bucket["evidence_selection_rate"] = (
        round(bucket["selected_evidence_rows"] / total, 4) if total else None)
    bucket["elapsed_ms_avg"] = (
        round(bucket["elapsed_ms_total"] / bucket["elapsed_samples"], 3)
        if bucket["elapsed_samples"] else None)
    bucket["elapsed_ms_max"] = round(bucket["elapsed_ms_max"], 3)
    return bucket


def _read_query_metrics(path):
    summary = _query_bucket()
    by_domain = collections.defaultdict(_query_bucket)
    last = {}
    if path and Path(path).is_file():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                summary["malformed_rows"] += 1
                continue
            if not isinstance(row, dict):
                summary["malformed_rows"] += 1
                continue
            _add_query_row(summary, row)
            explicit = [d for d in (row.get("domains") or [])
                        if isinstance(d, dict) and d.get("domain")]
            if explicit:
                summary["multi_domain_rows"] += int(len(explicit) > 1)
                grouped = []
                for domain_row in explicit:
                    domain = str(domain_row["domain"])
                    selected = [{"chunk_id": cid} for cid in
                                (domain_row.get("selected_chunk_ids") or [])]
                    summary["domain_evidence_rows"] += int(bool(selected))
                    projected = {**row, "status": domain_row.get("status"),
                                 "refusal": domain_row.get("refusal"),
                                 "counts": domain_row.get("counts") or {},
                                 "index_sha256": domain_row.get("index_sha256")
                                                 or row.get("index_sha256"),
                                 "selected_evidence": selected}
                    grouped.append((domain, projected))
            else:
                grouped = [(domain, row) for domain in
                           (_domains_for(q=row.get("q", "")) or ["unrouted"])]
            for domain, projected in grouped:
                _add_query_row(by_domain[domain], projected)
                ts = projected.get("ts")
                if domain not in last or (isinstance(ts, str) and
                                          ts >= (last[domain].get("ts") or "")):
                    last[domain] = {"ts": ts, "status": projected.get("status"),
                                    "refusal": projected.get("refusal")}
    return {"summary": _finish_query_bucket(summary),
            "by_domain": {d: _finish_query_bucket(v) for d, v in sorted(by_domain.items())},
            "last": last}


def _esports(db_path):
    p = Path(db_path or KE.DB_PATH)
    out = {"path": str(p), "schema": None, "entity_types": {}, "entity_evidence": {},
           "dynamic_tables": {}, "source_policies": [], "versions": [], "languages": [],
           "snapshots": 0, "evidence": 0, "foreign_key_violations": 0,
           "snapshot_hash_errors": [], "pointer_roundtrip_errors": [], "error": None}
    if not p.is_file():
        out["error"] = "数据库不存在"
        return out
    con = sqlite3.connect(p.resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        out["schema"] = con.execute("select schema_version from schema_meta").fetchone()[0]
        out["entity_types"] = dict(con.execute(
            "select entity_type,count(*) from entity group by entity_type").fetchall())
        out["entity_evidence"] = {
            r["entity_type"]: {"entities": r["entities"], "evidence": r["evidence"]}
            for r in con.execute(
                "select e.entity_type,count(distinct e.entity_id) entities,"
                "count(distinct ev.evidence_id) evidence from entity e "
                "join fact_support fs on fs.row_version_id=e.entity_id "
                "join evidence_block ev on ev.evidence_id=fs.evidence_id "
                "group by e.entity_type")}
        out["dynamic_tables"] = {t: con.execute(f"select count(*) from {t}").fetchone()[0]
                                 for t in DYNAMIC_TABLES}
        out["source_policies"] = [dict(r) for r in con.execute(
            "select source_id,purpose,automated_access,local_retention,commercial_use,"
            "quotation,redistribution,authorization_ref,note from source_policy")]
        out["versions"] = [r[0] for r in con.execute(
            "select distinct source_record_id from source_snapshot where source_id='E02' "
            "order by source_record_id")]
        out["languages"] = [r[0] for r in con.execute(
            "select distinct language from evidence_block order by language")]
        out["snapshots"] = con.execute("select count(*) from source_snapshot").fetchone()[0]
        out["evidence"] = con.execute("select count(*) from evidence_block").fetchone()[0]
        out["foreign_key_violations"] = len(con.execute("pragma foreign_key_check").fetchall())
        for s in con.execute("select * from source_snapshot where fetch_status='ok'"):
            sp = Path(s["storage_ref"])
            if not sp.is_file() or _sha(sp) != s["content_sha256"]:
                out["snapshot_hash_errors"].append(s["snapshot_id"])
        for e in con.execute(
                "select ev.*,ss.storage_ref from evidence_block ev "
                "join source_snapshot ss on ss.snapshot_id=ev.snapshot_id"):
            obj = json.loads(Path(e["storage_ref"]).read_text(encoding="utf-8"))
            key = e["locator"].removeprefix("/data/")
            if (json.loads(e["exact_text_or_value"]) != obj["data"].get(key) or
                    _sha_text(e["exact_text_or_value"]) != e["content_hash"]):
                out["pointer_roundtrip_errors"].append(e["evidence_id"])
    except (sqlite3.Error, OSError, ValueError, KeyError) as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        con.close()
    return out


def _sha_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def collect(index_path=None, db_path=None, eval_path=None, log_path=None):
    generated = _now()
    errors = []
    try:
        m = kb.load_map()
    except Exception as exc:
        m = {"entries": [], "revisions": {}}
        errors.append(f"corpus_map: {type(exc).__name__}: {exc}")
    idx = kb.load_index(index_path)
    if idx is None:
        errors.append("文本索引未建或不可读")
        idx = {"chunks": [], "files": {}, "built_at": None}
    try:
        audit = kb.audit(index_path=index_path)
    except Exception as exc:
        audit = {"status": "unknown", "counts": {}, "checks": []}
        errors.append(f"text_audit: {type(exc).__name__}: {exc}")
    stale = any(c["check_id"] == "index_sync" and c["verdict"] == "fail"
                for c in audit.get("checks", []))
    eval_data, eval_by_domain = _read_eval(eval_path)
    query_log_path = Path(log_path or (kb.KB_DIR / "query_log.jsonl"))
    query_metrics = _read_query_metrics(query_log_path)
    last_queries = query_metrics["last"]
    esports = _esports(db_path)

    grouped = collections.defaultdict(list)
    for c in idx["chunks"]:
        domains = _domains_for(game=c.get("game_id"), revision=c.get("revision"))
        for domain in domains or ["unrouted_text"]:
            grouped[(domain, c.get("game_id"), c.get("revision"),
                     c.get("platform"), "text_documents")].append(c)
    rows = []
    for (domain, game, revision, platform, kind), chunks in sorted(grouped.items()):
        strong = sum(c["status"] == "verified_read" and c["authority"] == "authoritative"
                     for c in chunks)
        verified_read = sum(c["status"] == "verified_read" for c in chunks)
        state = _state(len(chunks), strong, verified_read=verified_read, stale=stale)
        rows.append(_row(domain, "text", game, kind, platform, "本地身份分区",
                         revision, state, chunks=len(chunks), strong=strong,
                         last_query=last_queries.get(domain),
                         gaps=[] if strong else ["没有 verified_read + authoritative 正文"]))
    represented = {r["domain"] for r in rows}
    for domain in KR.DOMAINS:
        if domain in represented or domain == "esports_lol":
            continue
        rows.append(_row(domain, "registered", None, "all", None, "未登记",
                         None, "registered_empty",
                         last_query=last_queries.get(domain),
                         gaps=["域已注册但本地无语料；未收集不等于不存在"]))

    if esports.get("error"):
        lol_rows = [_row("esports_lol", "structured", "lol", "all", None, "未知",
                         None, "unknown", gaps=[esports["error"]])]
    else:
        lol_rows = []
        versions = "/".join(esports["versions"]) or "未登记"
        languages = "/".join(esports["languages"]) or "未登记"
        for kind in ("game_character", "game_item", "game_spell"):
            counts = esports["entity_evidence"].get(kind, {})
            n = counts.get("entities", 0)
            evidence = counts.get("evidence", 0)
            lol_rows.append(_row(
                "esports_lol", "structured", "lol", kind, None, f"{languages} locale",
                versions, _state(evidence=evidence), entities=n, evidence=evidence,
                last_query=last_queries.get("esports_lol"),
                gaps=[] if evidence else ["该静态实体类型未导入"]))
        for table in DYNAMIC_TABLES:
            n = esports["dynamic_tables"].get(table, 0)
            lol_rows.append(_row(
                "esports_lol", "structured", "lol", table, None, "未登记",
                None, _state(evidence=n), entities=n, evidence=n,
                last_query=last_queries.get("esports_lol"),
                gaps=[] if n else ["真实记录为0；待获准来源，不能用合成夹具顶替"]))
    rows.extend(lol_rows)
    rows.sort(key=lambda r: (r["domain"], r["knowledge_type"], r["version"] or ""))
    state_counts = collections.Counter(r["state"] for r in rows)
    return {"schema": "kb_coverage_v1", "generated_at": generated,
            "cutoffs": {"text_index_built_at": idx.get("built_at"),
                        "evaluation_taken_at": eval_data.get("taken_at") if eval_data else None},
            "text": {"chunks": len(idx["chunks"]),
                     "index_sha256": _sha(index_path or kb.INDEX_JSON),
                     "audit_status": audit.get("status"),
                     "audit_counts": audit.get("counts", {}),
                     "audit_checks": audit.get("checks", [])},
            "esports": esports, "evaluation": eval_data.get("summary") if eval_data else None,
            "query_log": {"path": str(query_log_path), "present": query_log_path.is_file(),
                          "summary": query_metrics["summary"],
                          "by_domain": query_metrics["by_domain"]},
            "domain_evaluation": [
                {"domain": domain, **v,
                 "rate": round(v["base_correct"] / v["questions"], 4) if v["questions"] else None}
                for domain, v in sorted(eval_by_domain.items())],
            "state_counts": {s: state_counts.get(s, 0) for s in STATES},
            "registered_domains": len(KR.DOMAINS), "rows": rows, "errors": errors}


def _row(domain, category, game, kind, platform, region, version, state,
         chunks=0, strong=0, entities=0, evidence=0, last_query=None, gaps=None):
    return {"domain": domain, "category": category, "game": game,
            "knowledge_type": kind, "region": region, "platform": platform,
            "version": version, "state": state, "chunks": chunks,
            "authoritative_verified": strong, "entities": entities,
            "evidence": evidence, "last_query": last_query, "gaps": gaps or []}


def render(d):
    L = [f"# 全域知识库覆盖看板 · {d['generated_at']}", "",
         f"- 文本索引：{d['text']['chunks']} 块；审计 `{d['text']['audit_status']}`；"
         f"sha256 `{d['text']['index_sha256']}`",
         f"- 电竞库：schema `{d['esports'].get('schema')}`；"
         f"实体 {sum(d['esports']['entity_types'].values())}；证据 {d['esports']['evidence']}；"
         f"快照 {d['esports']['snapshots']}",
         f"- 状态计数：{d['state_counts']}", ""]
    failed_checks = [c for c in d["text"].get("audit_checks", []) if c.get("verdict") == "fail"]
    if failed_checks:
        L += ["## 文本审计缺口", ""]
        for check in failed_checks:
            L.append(f"- `{check['check_id']}`：{check['reason']}")
            L.extend(f"  - {item}" for item in (check.get("detail") or [])[:20])
        L.append("")
    if d["evaluation"]:
        L += ["## 生产评测", "",
              f"基线严格评测：{d['evaluation']['base_v2_ok']}/26", "",
              "| 模式 | 严格评测 | 修好 | 打坏 | 错误出证 | 新放行探针 |",
              "|---|---|---|---|---|---|"]
        for mode, s in d["evaluation"]["modes"].items():
            L.append(f"| {mode} | {s['v2_ok']}/26 | {s['classes'].get('fixed', 0)} | "
                     f"{s['classes'].get('regressed', 0)} | {s['wrong_evidence']} | "
                     f"{s['newly_passed']} |")
        if d["domain_evaluation"]:
            L += ["", "按域成绩（域级题数，不摊到每个版本或知识类型）：", "",
                  "| 域 | 题数 | 基线评测通过 | 通过率 |", "|---|---|---|---|"]
            for r in d["domain_evaluation"]:
                L.append(f"| {r['domain']} | {r['questions']} | {r['base_correct']} | "
                         f"{r['rate'] if r['rate'] is not None else '-'} |")
        L.append("")
    qm = d["query_log"]
    qs = qm["summary"]
    L += ["## 查询日志健康度", "",
          f"- 日志：`{qm['path']}`（{'存在' if qm['present'] else '不存在'}）；"
          f"有效行 {qs['total_rows']}；独立问题 {qs['unique_questions']}；"
          f"最近 {qs['latest_ts'] or '-'}",
          f"- 状态计数：{qs['status_counts']}；选中证据 {qs['selected_evidence_rows']} 行"
          f"（{qs['evidence_selection_rate'] if qs['evidence_selection_rate'] is not None else '-'}）",
          f"- 诊断行 {qs['diagnostic_rows']}；多域调用 {qs['multi_domain_rows']}；"
          f"逐域证据 {qs['domain_evidence_rows']}；入口 {qs['entry_points']}；"
          f"路由模式 {qs['route_modes']}；平均耗时 {qs['elapsed_ms_avg']}ms",
          f"- 异常：坏行 {qs['malformed_rows']}；空问题 {qs['empty_questions']}；"
          f"缺索引指纹 {qs['missing_index_fingerprints']}；缺状态 {qs['missing_status']}；"
          f"pass无证据 {qs['pass_without_evidence']}；非pass带证据 {qs['nonpass_with_evidence']}", ""]
    if qs.get("entry_points") and set(qs["entry_points"]) <= {"blind_eval"}:
        L += ["- 口径：当前只有隔离盲测日志，不是真实使用记录，也不能当作独立盲测集。", ""]
    if qm["by_domain"]:
        L += ["| 域 | 有效行 | 独立问题 | pass | miss | inconclusive | 证据选中率 | 最近查询 |",
              "|---|---|---|---|---|---|---|---|"]
        for domain, v in qm["by_domain"].items():
            sc = v["status_counts"]
            L.append(f"| {domain} | {v['total_rows']} | {v['unique_questions']} | "
                     f"{sc.get('pass', 0)} | {sc.get('miss', 0)} | {sc.get('inconclusive', 0)} | "
                     f"{v['evidence_selection_rate'] if v['evidence_selection_rate'] is not None else '-'} | "
                     f"{v['latest_ts'] or '-'} |")
        L.append("")
    L += ["## 覆盖矩阵", "",
          "| 域 | 类目 | 游戏 | 知识类型 | 地区/平台 | 版本 | 状态 | 块/强证据 | 实体/证据 | 缺口 |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for r in d["rows"]:
        L.append(f"| {r['domain']} | {r['category']} | {r['game'] or '-'} | "
                 f"{r['knowledge_type']} | {r['region'] or '-'}/{r['platform'] or '-'} | "
                 f"{r['version'] or '-'} | {r['state']} | {r['chunks']}/{r['authoritative_verified']} | "
                 f"{r['entities']}/{r['evidence']} | {'；'.join(r['gaps']) or '-'} |")
    if d["esports"].get("source_policies"):
        L += ["", "## 电竞来源权限口径", "",
              "| 来源 | 自动访问 | 本地留存 | 商用 | 引用 | 再分发 | 授权引用 |",
              "|---|---|---|---|---|---|---|"]
        for p in d["esports"]["source_policies"]:
            L.append(f"| {p['source_id']} | {p['automated_access']} | {p['local_retention']} | "
                     f"{p['commercial_use']} | {p['quotation']} | {p['redistribution']} | "
                     f"{p.get('authorization_ref') or '-'} |")
        L += ["", "`unknown` 不等于已获商用/再分发授权；未获明确许可的维度保持待核。"]
    if d["errors"]:
        L += ["", "## 读取错误", ""] + [f"- {e}" for e in d["errors"]]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--index")
    ap.add_argument("--db")
    ap.add_argument("--eval")
    ap.add_argument("--log")
    ap.add_argument("--out", help="输出前缀；同时写 .json 与 .md")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    d = collect(args.index, args.db, args.eval, args.log)
    if args.out:
        out = Path(args.out)
        out.with_suffix(".json").write_text(json.dumps(d, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
        out.with_suffix(".md").write_text(render(d), encoding="utf-8")
        print(out.with_suffix(".json"))
        print(out.with_suffix(".md"))
    else:
        print(json.dumps(d, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

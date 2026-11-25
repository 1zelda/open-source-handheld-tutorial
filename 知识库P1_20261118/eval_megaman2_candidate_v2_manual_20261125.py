import hashlib
import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
sys.path.insert(0, str(ROOT / "_工具脚本"))

from taspipe import kb as K
from taspipe import kb_esports as KE
from taspipe import kb_megaman2 as M
from taspipe import sources as S

CANDIDATE = BASE / "megaman2_candidate_v2_manual_20261125"
INDEX = CANDIDATE / "index.json"
MAP = CANDIDATE / "corpus_map.json"
REGISTRY = CANDIDATE / "sources.json"
FROZEN = BASE / "megaman2_questions_frozen_v2_manual_20261125.json"
OUT_JSON = BASE / "megaman2_candidate_v2_manual_eval_20261125.json"
OUT_MD = BASE / "megaman2_candidate_v2_manual_eval_20261125.md"
LOG = CANDIDATE / "qc" / "isolated_eval_query_log_20261125.jsonl"
REAL_PATHS = [K.INDEX_JSON, K.CORPUS_MAP, S.REG_JSON, K.KB_DIR / "query_log.jsonl",
              KE.DB_PATH, ROOT / "选题决策层" / "kb快照" / "index.json"]
GUARDED = REAL_PATHS + [INDEX, MAP, REGISTRY, FROZEN]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(path):
    path = Path(path)
    if not path.is_file():
        return {"present": False}
    st = path.stat()
    return {"present": True, "bytes": st.st_size, "mtime_ns": st.st_mtime_ns,
            "sha256": sha(path)}


def loc(hit):
    try:
        start, end = hit["locator"].rsplit("#L", 1)[1].split("-L", 1)
        return int(start), int(end)
    except (KeyError, ValueError, IndexError):
        return 0, 0


def validate_frozen(doc, index):
    if doc.get("status") != "frozen":
        raise RuntimeError("question set is not frozen")
    if sha(INDEX) != doc["candidate_index_sha256"]:
        raise RuntimeError("frozen index hash mismatch")
    questions = doc["questions"]
    counts = {"total": len(questions),
              "strict_pass": sum(q["expect"] == "strict_pass" for q in questions),
              "weak": sum(q["expect"] == "weak" for q in questions),
              "refuse": sum(q["expect"] == "refuse" for q in questions)}
    if counts != doc["expected_counts"] or len({q["id"] for q in questions}) != counts["total"]:
        raise RuntimeError("frozen count or id contract mismatch")
    chunks = {c["chunk_id"]: c for c in index["chunks"]}
    for q in questions:
        if q["expect"] == "refuse":
            if q.get("gold") is not None:
                raise RuntimeError(f"refuse question has gold: {q['id']}")
            continue
        gold = q["gold"]
        chunk = chunks.get(gold["anchor_chunk"])
        if chunk is None or gold["path_contains"] not in chunk["path"]:
            raise RuntimeError(f"gold chunk/path mismatch: {q['id']}")
        if not (chunk["line_start"] <= gold["line_end"] and chunk["line_end"] >= gold["line_start"]):
            raise RuntimeError(f"gold line mismatch: {q['id']}")
        if chunk["revision"] != q["revision"] or chunk["source_id"] != q["source_id"]:
            raise RuntimeError(f"gold identity mismatch: {q['id']}")


def grade(item, result, mode):
    checks = []

    def check(name, value):
        checks.append({"name": name, "ok": bool(value)})

    selected = result.get("selected_evidence") or []
    check("index_identity", result.get("index_used") == "index.json"
          and result.get("index_sha256") == sha(INDEX))
    if item["expect"] == "strict_pass":
        gold = item["gold"]
        check("status_pass", result.get("status") == "pass")
        check("one_selected", len(selected) == 1)
        if selected:
            hit = selected[0]
            check("gold_locator", gold["path_contains"] in hit.get("locator", ""))
            s, e = loc(hit)
            check("gold_overlap", s <= gold["line_end"] and e >= gold["line_start"])
            check("revision", hit.get("revision") == item["revision"])
            check("source", hit.get("source_id") == item["source_id"])
            check("qualified", hit.get("status") == "verified_read"
                  and hit.get("authority") == "authoritative")
            if item.get("manual_pages"):
                check("manual_source", hit.get("source_id") == "nintendo_mega_man_2_nes_us_manual")
            if mode == "strict":
                check("strict_fragment", (hit.get("fragment_provenance") or {}).get("eligible") is True)
    else:
        check("status_inconclusive", result.get("status") == "inconclusive")
        check("no_selected", not selected)
        check("reference_hit", any(h.get("source_id") == item["source_id"]
                                   and h.get("authority") == "reference_only"
                                   for h in result.get("hits") or []))
    return {"id": item["id"], "expect": item["expect"], "mode": mode,
            "ok": all(c["ok"] for c in checks), "checks": checks,
            "status": result.get("status"), "selected_locator":
                selected[0].get("locator") if selected else None,
            "hit_sources": sorted({h.get("source_id") for h in result.get("hits") or []})}


def main():
    before = {str(p): snapshot(p) for p in GUARDED}
    doc = json.loads(FROZEN.read_text(encoding="utf-8"))
    index = K.load_index(INDEX)
    registry = S.load_registry(REGISTRY)
    validate_frozen(doc, index)
    rows, grades, results = [], [], []
    by_mode = {"default": [], "strict": []}
    for item in doc["questions"]:
        if item["expect"] == "refuse":
            results.append({"id": item["id"], "q": item["q"], "expect": "refuse",
                            "deferred_to_production_route": True})
            continue
        modes = {}
        retrieval_q = M._retrieval_query(item["q"])
        for mode, policy in (("default", None), ("strict", "strict")):
            result = K.query(retrieval_q, revision=item["revision"], topk=8,
                             index_path=INDEX, map_path=MAP, reg=registry, top_window=3,
                             fragment_policy=policy, require_verified=True,
                             log_sink=rows.append,
                             log_context={"entry_point": f"mm2-v2-manual-eval-{mode}"})
            graded = grade(item, result, mode)
            grades.append(graded)
            by_mode[mode].append(graded)
            modes[mode] = {"status": result.get("status"),
                           "selected_evidence": result.get("selected_evidence") or [],
                           "hits": result.get("hits") or [], "grade": graded}
        results.append({"id": item["id"], "q": item["q"], "retrieval_query": retrieval_q,
                        "expect": item["expect"], "revision": item["revision"],
                        "gold": item.get("gold"), **modes})
    LOG.parent.mkdir(parents=True, exist_ok=True)
    tmp = LOG.with_name(LOG.name + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n"
                           for r in rows), encoding="utf-8")
    tmp.replace(LOG)
    after = {str(p): snapshot(p) for p in GUARDED}
    changed = [p for p in before if before[p] != after[p]]
    if changed:
        raise RuntimeError(f"guarded state changed during isolated eval: {changed}")
    summary = {}
    for mode, items in by_mode.items():
        summary[mode] = {
            "total": len(items), "ok": sum(g["ok"] for g in items),
            "strict_pass": {"total": sum(g["expect"] == "strict_pass" for g in items),
                            "ok": sum(g["expect"] == "strict_pass" and g["ok"] for g in items)},
            "weak": {"total": sum(g["expect"] == "weak" for g in items),
                     "ok": sum(g["expect"] == "weak" and g["ok"] for g in items)},
            "failed_ids": [g["id"] for g in items if not g["ok"]],
        }
    all_ok = all(v["ok"] == v["total"] for v in summary.values())
    report = {
        "schema_version": 1, "status": "evaluated_isolated_v2_manual",
        "taken_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "candidate_revision": doc["candidate_revision"],
        "candidate_scope": "RAM/tooling plus scan-verified official-manual excerpts; not a whole-game knowledge base",
        "index_chunks": len(index["chunks"]), "index_sha256": sha(INDEX),
        "question_counts": doc["expected_counts"], "retrieval_question_counts": {
            "total": doc["expected_counts"]["strict_pass"] + doc["expected_counts"]["weak"],
            "route_refusals_deferred": doc["expected_counts"]["refuse"]},
        "query_count": len(rows), "summary": summary, "all_ok": all_ok,
        "manual_source": doc["manual_source"], "questions": results,
        "isolation": {"ok": not changed, "changed_paths": changed,
                      "real_state_unchanged": all(before[str(p)] == after[str(p)] for p in REAL_PATHS),
                      "candidate_inputs_unchanged": all(before[str(p)] == after[str(p)]
                                                         for p in (INDEX, MAP, REGISTRY, FROZEN)),
                      "before": before, "after": after},
        "query_log": {"path": str(LOG), "lines": len(rows), "sha256": sha(LOG)},
        "external_generative_model_calls": 0, "paid_api_calls": 0,
    }
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 洛克人2候选v2说明书扩展隔离评测", "", "## 结论", "",
             f"- 候选索引：{len(index['chunks'])} 块，SHA-256 `{sha(INDEX)}`。",
             f"- 冻结题：{doc['expected_counts']['total']} 题；隔离检索 {report['retrieval_question_counts']['total']} 题，路由拒答 {doc['expected_counts']['refuse']} 题留到生产验收。",
             f"- default：{summary['default']['ok']}/{summary['default']['total']}；strict：{summary['strict']['ok']}/{summary['strict']['total']}。",
             f"- 共享状态与候选输入：{'全部未变' if not changed else '检测到变化'}。", "",
             "## 边界", "", "- 这是洛克人2候选子域，不是整款游戏知识库。",
             "- 官方说明书只保存短摘录，完整手册不在候选目录。",
             "- PAL/日版等价、全部敌人与关卡、出招表仍未覆盖。", ""]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"all_ok": all_ok, "summary": summary,
                      "question_counts": doc["expected_counts"],
                      "changed_paths": changed, "report": str(OUT_JSON)},
                     ensure_ascii=False, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())

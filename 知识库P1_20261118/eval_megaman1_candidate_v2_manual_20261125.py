import hashlib
import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
sys.path.insert(0, str(ROOT / "_工具脚本"))
sys.path.insert(0, str(ROOT / "知识库小样_20261118"))

from taspipe import kb as K
from taspipe import kb_esports as KE
from taspipe import sources as S
import eval_common as E

CANDIDATE = BASE / "megaman1_candidate_v2_manual_20261125"
INDEX = CANDIDATE / "index.json"
MAP = CANDIDATE / "corpus_map.json"
REGISTRY = CANDIDATE / "sources.json"
FROZEN = BASE / "megaman1_questions_frozen_v2_manual_20261125.json"
OUT_JSON = BASE / "megaman1_candidate_v2_manual_eval_20261125.json"
OUT_MD = BASE / "megaman1_candidate_v2_manual_eval_20261125.md"
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


def validate_frozen(doc, index):
    if doc.get("status") != "frozen":
        raise RuntimeError("question set is not frozen")
    if sha(INDEX) != doc["candidate_index_sha256"]:
        raise RuntimeError("frozen index hash mismatch")
    questions = doc["questions"]
    counts = {
        "total": len(questions),
        "strict_pass": sum(q["expect"] == "strict_pass" for q in questions),
        "refuse": sum(q["expect"] == "refuse" for q in questions),
    }
    if counts != doc["expected_counts"] or len({q["id"] for q in questions}) != counts["total"]:
        raise RuntimeError("frozen count or id contract mismatch")
    chunks = {c["chunk_id"]: c for c in index["chunks"]}
    for q in questions:
        gold = q.get("gold")
        if q["expect"] == "refuse":
            if gold is not None:
                raise RuntimeError(f"refuse question has gold: {q['id']}")
            continue
        chunk = chunks.get(gold["anchor_chunk"])
        if chunk is None or gold["path_contains"] not in chunk["path"]:
            raise RuntimeError(f"gold chunk/path mismatch: {q['id']}")
        if not (chunk["line_start"] <= gold["line_end"] and chunk["line_end"] >= gold["line_start"]):
            raise RuntimeError(f"gold line mismatch: {q['id']}")
        if chunk["revision"] != doc["candidate_revision"]:
            raise RuntimeError(f"gold revision mismatch: {q['id']}")
        if q["id"] >= "MM13" and chunk["source_id"] != doc["manual_source"]["source_id"]:
            raise RuntimeError(f"manual gold source mismatch: {q['id']}")


def compact(result):
    return {
        "status": result.get("status"), "reason": result.get("reason"),
        "refusal": result.get("refusal"), "reason_code": result.get("reason_code"),
        "counts": result.get("counts"), "index_used": result.get("index_used"),
        "index_sha256": result.get("index_sha256"),
        "selected_evidence": result.get("selected_evidence") or [],
        "authority_warnings": result.get("authority_warnings") or [],
        "hits": [{"chunk_id": h.get("chunk_id"), "locator": h.get("locator"),
                  "score": h.get("score"), "authority": h.get("authority"),
                  "status": h.get("status"), "snippet": h.get("snippet"),
                  "answerability": h.get("answerability")}
                 for h in (result.get("hits") or [])[:8]],
    }


def main():
    before = {str(p): snapshot(p) for p in GUARDED}
    doc = json.loads(FROZEN.read_text(encoding="utf-8"))
    index = K.load_index(INDEX)
    registry = S.load_registry(REGISTRY)
    validate_frozen(doc, index)
    rows, results = [], []
    grades = {"default": [], "strict": []}
    for item in doc["questions"]:
        modes = {}
        for mode, policy in (("default", None), ("strict", "strict")):
            result = K.query(item["q"], revision=doc["candidate_revision"], topk=8,
                             index_path=INDEX, map_path=MAP, reg=registry, top_window=3,
                             fragment_policy=policy, require_verified=True,
                             log_sink=rows.append,
                             log_context={"entry_point": f"mm1-v2-manual-eval-{mode}"})
            grade = E.grade_v2(item, result)
            selected = result.get("selected_evidence") or []
            if item["expect"] == "strict_pass":
                grade["ok"] = grade["ok"] and len(selected) == 1 and (
                    item["gold"]["path_contains"] in selected[0].get("locator", ""))
            else:
                grade["ok"] = grade["ok"] and not selected
            grades[mode].append(grade)
            modes[mode] = {**compact(result), "grade": grade}
        results.append({"id": item["id"], "q": item["q"], "expect": item["expect"],
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
    summary = {mode: E.summarize_v2(items) for mode, items in grades.items()}
    report = {
        "schema_version": 1, "status": "evaluated_isolated_v2_manual",
        "taken_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "candidate_revision": doc["candidate_revision"],
        "candidate_scope": "RAM/tooling plus scan-verified official-manual excerpts; not a whole-game knowledge base",
        "index_chunks": len(index["chunks"]), "index_sha256": sha(INDEX),
        "question_counts": doc["expected_counts"], "query_count": len(rows),
        "summary": summary, "all_ok": all(g["ok"] for items in grades.values() for g in items),
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
    lines = ["# 洛克人1候选v2说明书扩展隔离评测", "", "## 结论", "",
             f"- 候选索引：{len(index['chunks'])} 块，SHA-256 `{sha(INDEX)}`。",
             f"- 冻结题：{doc['expected_counts']['total']} 题（{doc['expected_counts']['strict_pass']} 事实题、{doc['expected_counts']['refuse']} 拒答题）。",
             f"- default：{summary['default']['ok']}/{summary['default']['total']}；strict：{summary['strict']['ok']}/{summary['strict']['total']}。",
             f"- 错误出证：default {summary['default']['split_table']['wrong_evidence']}，strict {summary['strict']['split_table']['wrong_evidence']}。",
             f"- 共享状态与候选输入：{'全部未变' if not changed else '检测到变化'}。",
             "- 官方手册只收扫描核验短摘录；完整手册未进入候选目录。", "",
             "## 逐题", "", "| ID | 类型 | default | strict | default 出证 | strict 出证 |",
             "|---|---|---|---|---|---|"]
    for row in results:
        d, s = row["default"], row["strict"]
        dl = (d["selected_evidence"] or [{}])[0].get("locator", "—")
        sl = (s["selected_evidence"] or [{}])[0].get("locator", "—")
        lines.append(f"| {row['id']} | {row['expect']} | {d['status']} | {s['status']} | {dl or '—'} | {sl or '—'} |")
    lines += ["", "## 边界", "",
              "- MM01–MM12 原题保留并重新锚定；新增 MM13–MM23 只覆盖官方说明书短摘录。",
              "- MM10 目标时刻续作、MM11 角色创建系统、MM12 PAL-B 跨版等价仍拒答。",
              "- 说明书覆盖操作、选关、能量、道具、Magnet Beam、Robot Master、奖励与得分；不是整款游戏知识库。",
              "- 零外部生成式模型调用、零付费 API。", "",
              f"- 完整 JSON：`{OUT_JSON.relative_to(ROOT).as_posix()}`",
              f"- 隔离日志：`{LOG.relative_to(ROOT).as_posix()}`", ""]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"all_ok": report["all_ok"], "question_counts": doc["expected_counts"],
                      "default": summary["default"]["ok"], "strict": summary["strict"]["ok"],
                      "wrong_default": summary["default"]["split_table"]["wrong_evidence"],
                      "wrong_strict": summary["strict"]["split_table"]["wrong_evidence"],
                      "changed_paths": changed, "report": str(OUT_JSON)},
                     ensure_ascii=False, indent=2))
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())

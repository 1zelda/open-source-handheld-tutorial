import hashlib
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
sys.path.insert(0, str(ROOT / "_工具脚本"))
sys.path.insert(0, str(ROOT / "知识库小样_20261118"))

from taspipe import kb as K
from taspipe import kb_esports as KE
from taspipe import sources as S
import eval_common as E

CANDIDATE = BASE / "megaman1_candidate_20261125"
INDEX = CANDIDATE / "index.json"
MAP = CANDIDATE / "corpus_map.json"
REGISTRY = CANDIDATE / "sources.json"
FROZEN = BASE / "megaman1_questions_frozen_20261125.json"
OUT_JSON = BASE / "megaman1_candidate_eval_20261125.json"
OUT_MD = BASE / "megaman1_candidate_eval_20261125.md"
LOG = CANDIDATE / "eval_query_log.jsonl"
REAL_PATHS = [
    K.INDEX_JSON,
    K.CORPUS_MAP,
    S.REG_JSON,
    K.KB_DIR / "query_log.jsonl",
    KE.DB_PATH,
    ROOT / "选题决策层" / "kb快照" / "index.json",
]
GUARDED_PATHS = REAL_PATHS + [INDEX, MAP, REGISTRY]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(path):
    if not path.is_file():
        return {"present": False}
    st = path.stat()
    return {
        "present": True,
        "bytes": st.st_size,
        "mtime_ns": st.st_mtime_ns,
        "sha256": sha(path),
    }


def validate_frozen(doc, index):
    if doc.get("status") != "frozen":
        raise RuntimeError("question set is not frozen")
    if sha(INDEX) != doc["candidate_index_sha256"]:
        raise RuntimeError("frozen index hash mismatch")
    questions = doc["questions"]
    if len(questions) != 12 or len({q["id"] for q in questions}) != 12:
        raise RuntimeError("frozen question count or id uniqueness mismatch")
    if sum(q["expect"] == "strict_pass" for q in questions) != 9:
        raise RuntimeError("strict_pass count mismatch")
    if sum(q["expect"] == "refuse" for q in questions) != 3:
        raise RuntimeError("refuse count mismatch")
    chunks = {c["chunk_id"]: c for c in index["chunks"]}
    for q in questions:
        gold = q.get("gold")
        if q["expect"] == "refuse":
            if gold is not None:
                raise RuntimeError(f"refuse question has gold: {q['id']}")
            continue
        chunk = chunks.get(gold["anchor_chunk"])
        if chunk is None:
            raise RuntimeError(f"gold chunk missing: {q['id']}")
        if gold["path_contains"] not in chunk["path"]:
            raise RuntimeError(f"gold path mismatch: {q['id']}")
        if not (chunk["line_start"] <= gold["line_end"] and chunk["line_end"] >= gold["line_start"]):
            raise RuntimeError(f"gold line mismatch: {q['id']}")
        if chunk["revision"] != doc["candidate_revision"]:
            raise RuntimeError(f"gold revision mismatch: {q['id']}")


def compact_result(result):
    return {
        "status": result.get("status"),
        "reason": result.get("reason"),
        "refusal": result.get("refusal"),
        "counts": result.get("counts"),
        "index_used": result.get("index_used"),
        "index_sha256": result.get("index_sha256"),
        "selected_evidence": result.get("selected_evidence") or [],
        "authority_warnings": result.get("authority_warnings") or [],
        "hits": [
            {
                "chunk_id": h.get("chunk_id"),
                "locator": h.get("locator"),
                "score": h.get("score"),
                "authority": h.get("authority"),
                "status": h.get("status"),
                "answerable": (h.get("answerability") or {}).get("answerable"),
                "fragment_eligible": (h.get("fragment_provenance") or {}).get("eligible"),
                "snippet": h.get("snippet"),
            }
            for h in (result.get("hits") or [])[:8]
        ],
    }


def render_md(report):
    lines = [
        "# 洛克人1隔离候选子域评测（2026-11-25）",
        "",
        "## 结论",
        "",
        f"- 候选索引：{report['index_chunks']} 块，SHA-256 `{report['index_sha256']}`。",
        f"- 默认生产查询：{report['summary']['default']['ok']}/{report['summary']['default']['total']}；strict 影子臂：{report['summary']['strict']['ok']}/{report['summary']['strict']['total']}。",
        f"- 错误出证：默认 {report['summary']['default']['split_table']['wrong_evidence']}，strict {report['summary']['strict']['split_table']['wrong_evidence']}。",
        f"- 真实 index / corpus map / sources / query log / 电竞 DB / 新闻快照：{'全部未变' if report['isolation']['real_state_unchanged'] else '检测到变化'}。",
        "- 范围仅为 NTSC 美版洛克人1的 RAM 与工具方法；未接生产路由，不是整款游戏知识库。",
        "",
        "## 逐题结果",
        "",
        "| ID | 类型 | 默认 | strict | 默认出证 | strict 出证 |",
        "|---|---|---|---|---|---|",
    ]
    for row in report["questions"]:
        d = row["default"]
        s = row["strict"]
        lines.append(
            f"| {row['id']} | {row['expect']} | {d['status']} | {s['status']} | "
            f"{d['grade_v2']['selected_locator'] or '—'} | {s['grade_v2']['selected_locator'] or '—'} |"
        )
    lines.extend([
        "",
        "## 冻结与边界",
        "",
        "- 9 道事实题按候选索引真实 chunk 重锚；3 道缺证/版本边界题冻结为拒答。",
        "- MM10 只有 segmented TAS 通用术语与 FM2 导入参考流程，不能证明洛克人1的目标时刻续作流程。",
        "- MM11 缺官方说明书级角色创建证据；MM12 缺 PAL-B 与 NTSC 美版等价证据。",
        "- 题集保留原草案文件不覆盖；问句细化理由逐题写入冻结 JSON。",
        "- 本轮零外部生成式模型调用、零付费 API；生产默认参数未改。",
        "",
        "## 复核入口",
        "",
        f"- 冻结题集：`{FROZEN.relative_to(ROOT).as_posix()}`",
        f"- 候选索引：`{INDEX.relative_to(ROOT).as_posix()}`",
        f"- 隔离查询日志：`{LOG.relative_to(ROOT).as_posix()}`",
        f"- 完整 JSON：`{OUT_JSON.relative_to(ROOT).as_posix()}`",
        "",
    ])
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main():
    before = {str(p): snapshot(p) for p in GUARDED_PATHS}
    doc = json.loads(FROZEN.read_text(encoding="utf-8"))
    index = K.load_index(INDEX)
    validate_frozen(doc, index)
    registry = S.load_registry(REGISTRY)
    rows = []
    question_results = []
    mode_grades = {"default": [], "strict": []}

    for q in doc["questions"]:
        modes = {}
        for mode, policy in (("default", None), ("strict", "strict")):
            result = K.query(
                q["q"],
                revision=q["filters"]["revision"],
                topk=8,
                index_path=INDEX,
                map_path=MAP,
                reg=registry,
                top_window=3,
                fragment_policy=policy,
                log_sink=rows.append,
                log_context={"entry_point": f"mm1-eval-{mode}"},
            )
            grade = E.grade_v2(q, result)
            mode_grades[mode].append(grade)
            modes[mode] = {**compact_result(result), "grade_v2": grade}
        question_results.append({
            "id": q["id"],
            "q": q["q"],
            "expect": q["expect"],
            "gold": q.get("gold"),
            **modes,
        })

    log_tmp = LOG.with_name(LOG.name + ".tmp")
    log_tmp.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )
    log_tmp.replace(LOG)
    after = {str(p): snapshot(p) for p in GUARDED_PATHS}
    real_before = {str(p): before[str(p)] for p in REAL_PATHS}
    real_after = {str(p): after[str(p)] for p in REAL_PATHS}
    candidate_unchanged = all(before[str(p)] == after[str(p)] for p in (INDEX, MAP, REGISTRY))
    real_unchanged = real_before == real_after
    if not candidate_unchanged or not real_unchanged:
        raise RuntimeError("guarded state changed during candidate evaluation")

    summary = {mode: E.summarize_v2(grades) for mode, grades in mode_grades.items()}
    report = {
        "status": "evaluated_isolated",
        "frozen_at": doc["frozen_at"],
        "candidate_revision": doc["candidate_revision"],
        "candidate_scope": "RAM/tooling subdomain only; not a whole-game knowledge base",
        "index_chunks": len(index["chunks"]),
        "index_sha256": sha(INDEX),
        "query_count": len(rows),
        "summary": summary,
        "all_ok": all(g["ok"] for grades in mode_grades.values() for g in grades),
        "isolation": {
            "real_state_unchanged": real_unchanged,
            "candidate_inputs_unchanged": candidate_unchanged,
            "real_state_before": real_before,
            "real_state_after": real_after,
            "isolated_query_log": str(LOG),
            "production_defaults_unchanged": True,
        },
        "questions": question_results,
    }
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    render_md(report)
    print(f"EVAL_OK default={summary['default']['ok']}/{summary['default']['total']} "
          f"strict={summary['strict']['ok']}/{summary['strict']['total']} "
          f"wrong_default={summary['default']['split_table']['wrong_evidence']} "
          f"wrong_strict={summary['strict']['split_table']['wrong_evidence']} "
          f"unchanged={real_unchanged}")
    print(str(OUT_JSON))
    print(str(OUT_MD))


if __name__ == "__main__":
    main()

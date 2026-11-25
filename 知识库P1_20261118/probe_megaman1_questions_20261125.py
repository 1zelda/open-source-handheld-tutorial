import hashlib
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
sys.path.insert(0, str(ROOT / "_工具脚本"))

from taspipe import kb as K
from taspipe import kb_esports as KE
from taspipe import sources as S

CANDIDATE = BASE / "megaman1_candidate_20261125"
INDEX = CANDIDATE / "index.json"
MAP = CANDIDATE / "corpus_map.json"
REGISTRY = CANDIDATE / "sources.json"
DRAFT = BASE / "megaman1_questions_draft_20261124.json"
OUT = BASE / "megaman1_question_probe_20261125.json"
LOG = CANDIDATE / "query_log.jsonl"
REAL_PATHS = [
    K.INDEX_JSON,
    K.CORPUS_MAP,
    S.REG_JSON,
    K.KB_DIR / "query_log.jsonl",
    KE.DB_PATH,
    ROOT / "选题决策层" / "kb快照" / "index.json",
]


def snapshot(path):
    if not path.is_file():
        return {"present": False}
    st = path.stat()
    return {
        "present": True,
        "bytes": st.st_size,
        "mtime_ns": st.st_mtime_ns,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def compact(result):
    hits = []
    for hit in (result.get("hits") or [])[:8]:
        hits.append({
            "chunk_id": hit.get("chunk_id"),
            "locator": hit.get("locator"),
            "revision": hit.get("revision"),
            "source_id": hit.get("source_id"),
            "matched_terms": hit.get("matched_terms"),
            "snippet": hit.get("snippet"),
            "heading": hit.get("heading"),
            "authority": hit.get("authority"),
            "status": hit.get("status"),
            "score": hit.get("score"),
            "answerable": hit.get("answerable"),
            "answerability": hit.get("answerability"),
            "text": hit.get("text"),
        })
    return {
        "q": result.get("q"),
        "status": result.get("status"),
        "reason": result.get("reason"),
        "refusal": result.get("refusal"),
        "counts": result.get("counts"),
        "retrieval": result.get("retrieval"),
        "index_used": result.get("index_used"),
        "index_sha256": result.get("index_sha256"),
        "fragment_policy": result.get("fragment_policy"),
        "selected_evidence": result.get("selected_evidence"),
        "authority_warnings": result.get("authority_warnings"),
        "hits": hits,
    }


def main():
    before = {str(p): snapshot(p) for p in REAL_PATHS}
    draft = json.loads(DRAFT.read_text(encoding="utf-8"))
    registry = S.load_registry(REGISTRY)
    rows = []
    results = []
    for question in draft["questions"]:
        modes = {}
        for mode, policy in (("default", None), ("strict", "strict")):
            result = K.query(
                question["q"],
                revision=draft["candidate_revision"],
                topk=8,
                index_path=INDEX,
                map_path=MAP,
                reg=registry,
                top_window=3,
                fragment_policy=policy,
                log_sink=rows.append,
                log_context={"entry_point": f"mm1-candidate-{mode}"},
            )
            modes[mode] = compact(result)
        results.append({
            "id": question["id"],
            "q": question["q"],
            "draft_expect": question["expect"],
            "modes": modes,
        })
    log_tmp = LOG.with_name(LOG.name + ".tmp")
    log_tmp.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )
    log_tmp.replace(LOG)
    after = {str(p): snapshot(p) for p in REAL_PATHS}
    if before != after:
        raise RuntimeError("real state changed during candidate query probe")
    OUT.write_text(json.dumps({
        "status": "probe_complete_not_frozen",
        "candidate_revision": draft["candidate_revision"],
        "index_sha256": hashlib.sha256(INDEX.read_bytes()).hexdigest(),
        "query_count": len(rows),
        "isolated_query_log": str(LOG),
        "real_state_unchanged": before == after,
        "questions": results,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PROBE_OK questions={len(results)} queries={len(rows)} unchanged={before == after}")
    print(str(OUT))


if __name__ == "__main__":
    main()

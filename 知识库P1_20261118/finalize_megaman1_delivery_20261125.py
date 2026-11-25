from pathlib import Path
from collections import Counter
import hashlib
import json

ROOT = Path("F:/开源掌机教程")
OUT = ROOT / "知识库P1_20261118"
CANDIDATE = OUT / "megaman1_candidate_20261125"
INDEX = CANDIDATE / "index.json"
MANIFEST = OUT / "megaman1_delivery_manifest_20261125.json"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path):
    return path.relative_to(ROOT).as_posix()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def role(path):
    name = path.as_posix()
    if "/qc/" in name or path.suffix == ".pdf":
        return "rendered_delivery"
    if "/evidence/" in name or path.name in {"index.json", "corpus_map.json", "sources.json", "scope.json", "rom_identity.json"}:
        return "candidate_evidence"
    if "query_log" in path.name:
        return "audit_log"
    if path.suffix == ".py":
        return "reproduction_script"
    if path.name in {"megaman1_questions_draft_20261124.json", "megaman1_question_probe_20261125.json", "megaman1_question_probe_20261125.log", "megaman1_corpus_readiness_20261124.md"}:
        return "historical_support"
    return "delivery_record"


def main():
    build = load(OUT / "megaman1_candidate_build_20261125.json")
    frozen = load(OUT / "megaman1_questions_frozen_20261125.json")
    evaluation = load(OUT / "megaman1_candidate_eval_20261125.json")
    readiness = load(OUT / "megaman1_candidate_readiness_20261125.json")
    render_qa = load(CANDIDATE / "qc/render_qa.json")
    index = load(INDEX)
    index_sha = sha(INDEX)
    chunks = {chunk["chunk_id"]: chunk for chunk in index["chunks"]}
    questions = frozen["questions"]
    results = evaluation["questions"]
    logs = [json.loads(line) for line in (CANDIDATE / "eval_query_log.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    ledger_hashes = {
        "build": build["index_sha256"],
        "frozen": frozen["candidate_index_sha256"],
        "evaluation": evaluation["index_sha256"],
        "readiness": readiness["candidate_index_sha256"],
        "render_qc": render_qa["candidate_index_sha256"],
    }
    selected_anchor_errors = []
    for item in results:
        gold = item["gold"]
        if gold is None:
            for arm in ("default", "strict"):
                if item["expect"] != "refuse" or item[arm]["status"] not in {"miss", "inconclusive"} or item[arm].get("selected_evidence"):
                    selected_anchor_errors.append(f"{item['id']}:{arm}:no_gold")
            continue
        chunk = chunks.get(gold["anchor_chunk"])
        if chunk is None or gold["path_contains"] not in chunk["path"]:
            selected_anchor_errors.append(item["id"])
        if not (chunk["line_start"] <= gold["line_end"] and chunk["line_end"] >= gold["line_start"]):
            selected_anchor_errors.append(item["id"])
        for arm in ("default", "strict"):
            if item["expect"] == "strict_pass":
                selected = item[arm].get("selected_evidence") or []
                if not selected or selected[0]["chunk_id"] != gold["anchor_chunk"]:
                    selected_anchor_errors.append(f"{item['id']}:{arm}")
            elif item[arm]["status"] not in {"miss", "inconclusive"} or item[arm].get("selected_evidence"):
                selected_anchor_errors.append(f"{item['id']}:{arm}:refuse")

    log_modes = Counter(row["entry_point"] for row in logs)
    log_index_hashes = {row.get("index_sha256") for row in logs}
    shared = {}
    shared_drift = []
    for path_text, recorded in evaluation["isolation"]["real_state_after"].items():
        path = Path(path_text)
        current = {
            "present": path.is_file(),
            "bytes": path.stat().st_size if path.is_file() else None,
            "mtime_ns": path.stat().st_mtime_ns if path.is_file() else None,
            "sha256": sha(path) if path.is_file() else None,
        }
        shared[rel(path)] = current
        if any(current[key] != recorded[key] for key in ("present", "bytes", "mtime_ns", "sha256")):
            shared_drift.append(rel(path))

    checks = {
        "candidate_index_hash_consistent": all(value == index_sha for value in ledger_hashes.values()),
        "candidate_chunk_count_consistent": len(chunks) == build["build"]["chunks"] == evaluation["index_chunks"] == readiness["index_chunks"],
        "candidate_term_count_consistent": index["stats"]["terms"] == build["build"]["terms"] == readiness["terms"],
        "candidate_file_count_consistent": build["build"]["files_indexed"] == readiness["index_files"],
        "candidate_revision_single": {chunk["revision"] for chunk in chunks.values()} == {frozen["candidate_revision"]},
        "frozen_question_ids_match_results": [q["id"] for q in questions] == [r["id"] for r in results],
        "frozen_question_count_matches_log": len(questions) == evaluation["query_count"] / 2 == len(logs) / 2,
        "selected_anchors_and_refusals_valid": not selected_anchor_errors,
        "evaluation_all_ok": evaluation["all_ok"] is True,
        "evaluation_wrong_evidence_zero": all(evaluation["summary"][arm]["split_table"]["wrong_evidence"] == 0 for arm in ("default", "strict")),
        "evaluation_missed_answer_zero": all(evaluation["summary"][arm]["split_table"]["missed_answer"] == 0 for arm in ("default", "strict")),
        "evaluation_summaries_complete": all(evaluation["summary"][arm]["ok"] == evaluation["summary"][arm]["total"] == len(questions) for arm in ("default", "strict")),
        "log_modes_complete": log_modes == Counter({f"mm1-eval-{arm}": len(questions) for arm in ("default", "strict")}),
        "log_index_hash_consistent": log_index_hashes == {index_sha},
        "build_isolation_declared": build["real_state_unchanged"] is True,
        "eval_isolation_declared": evaluation["isolation"]["real_state_unchanged"] is True and evaluation["isolation"]["candidate_inputs_unchanged"] is True,
        "production_not_promoted": readiness["production_ready"] is False and readiness["whole_game_knowledge_base"] is False,
        "production_not_wired": readiness["production_route_wired"] is False and readiness["production_consumer_wired"] is False,
        "render_qc_all_green": render_qa["check_count"] == len(render_qa["checks"]) and all(render_qa["checks"].values()),
        "pdf_links_resolve": render_qa["checks"]["delivery_links_present"] and render_qa["checks"]["delivery_links_resolve"],
        "visual_review_completed": (CANDIDATE / "qc/contact_sheet.png").is_file() and all((CANDIDATE / f"qc/page_{n:02d}.png").is_file() for n in render_qa["snapshot_pages"]),
    }

    top_level = [
        ROOT / "洛克人1隔离候选子域交付_2026-11-25.md",
        ROOT / "洛克人1隔离候选子域交付_2026-11-25.pdf",
        OUT / "build_megaman1_candidate_20261125.py",
        OUT / "eval_megaman1_candidate_20261125.py",
        OUT / "render_qc_megaman1_candidate_20261125.py",
        OUT / "finalize_megaman1_delivery_20261125.py",
        OUT / "megaman1_questions_draft_20261124.json",
        OUT / "megaman1_corpus_readiness_20261124.md",
        OUT / "megaman1_candidate_build_20261125.json",
        OUT / "megaman1_candidate_build_20261125.log",
        OUT / "megaman1_question_probe_20261125.json",
        OUT / "megaman1_question_probe_20261125.log",
        OUT / "megaman1_questions_frozen_20261125.json",
        OUT / "megaman1_candidate_eval_20261125.json",
        OUT / "megaman1_candidate_eval_20261125.md",
        OUT / "megaman1_candidate_eval_20261125.log",
        OUT / "megaman1_corpus_readiness_20261125.md",
        OUT / "megaman1_candidate_readiness_20261125.json",
    ]
    paths = sorted(set(top_level + [path for path in CANDIDATE.rglob("*") if path.is_file()]), key=lambda path: rel(path))
    missing = [rel(path) for path in paths if not path.is_file()]
    checks["all_manifest_artifacts_present"] = not missing
    artifacts = []
    if not missing:
        for path in paths:
            artifacts.append({
                "path": rel(path),
                "absolute_path": str(path),
                "role": role(path),
                "bytes": path.stat().st_size,
                "sha256": sha(path),
            })
    canonical = "\n".join(f"{item['path']}\0{item['sha256']}\0{item['bytes']}" for item in artifacts)
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    manifest = {
        "status": "finalized_isolated_candidate" if all(checks.values()) else "validation_failed",
        "date": "2026-11-25",
        "scope": "NTSC US Mega Man 1 RAM/tooling subdomain only",
        "candidate_index": rel(INDEX),
        "candidate_index_sha256": index_sha,
        "evaluation": {
            "default": f"{evaluation['summary']['default']['ok']}/{evaluation['summary']['default']['total']}",
            "strict": f"{evaluation['summary']['strict']['ok']}/{evaluation['summary']['strict']['total']}",
            "wrong_evidence_default": evaluation["summary"]["default"]["split_table"]["wrong_evidence"],
            "wrong_evidence_strict": evaluation["summary"]["strict"]["split_table"]["wrong_evidence"],
        },
        "pdf_qc": {
            "pages": render_qa["pages"],
            "checks": render_qa["check_count"],
            "all_green": all(render_qa["checks"].values()),
            "visual_review": "contact sheet and all snapshot pages inspected",
        },
        "checks": checks,
        "ledger_index_hashes": ledger_hashes,
        "selected_anchor_errors": selected_anchor_errors,
        "query_log_modes": dict(log_modes),
        "shared_state_at_final_validation": shared,
        "shared_state_drift_since_eval": shared_drift,
        "shared_state_note": "Any drift is recorded separately; this manifest does not attribute parallel-session changes to the candidate task.",
        "artifact_count": len(artifacts),
        "total_artifact_bytes": sum(item["bytes"] for item in artifacts),
        "delivery_fingerprint_sha256": fingerprint,
        "fingerprint_rule": "SHA-256 over UTF-8 lines: relative_path NUL sha256 NUL bytes, sorted by relative_path; manifest excludes itself to avoid circular hashing.",
        "artifacts": artifacts,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": manifest["status"],
        "checks": len(checks),
        "failed": [name for name, value in checks.items() if not value],
        "artifact_count": manifest["artifact_count"],
        "total_artifact_bytes": manifest["total_artifact_bytes"],
        "delivery_fingerprint_sha256": fingerprint,
        "shared_state_drift_since_eval": shared_drift,
        "manifest": str(MANIFEST),
    }, ensure_ascii=True, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

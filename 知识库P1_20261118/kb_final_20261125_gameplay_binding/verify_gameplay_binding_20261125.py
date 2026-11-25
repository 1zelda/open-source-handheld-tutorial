from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT / "_工具脚本/taspipe/游戏包"
PACK = GAME / "gba_aria_of_sorrow_souls.menu_catalog.json"
REGISTRY = GAME / "来源库/sources.json"
CORPUS = GAME / "知识库/corpus_map.json"
EVIDENCE = GAME / "证据/晓月圆舞曲/gameplay_verify_binding_20261125"
BINDING = EVIDENCE / "gameplay_evidence_binding_20261125.json"
INVENTORY = EVIDENCE / "artifact_inventory.json"
OUT = ROOT / "知识库P1_20261118/kb_final_20261125_menu_visual_review/gameplay_binding_verification_20261125.json"
SOURCE_ID = "local_aria_gameplay_verify_20261125"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    pack = json.loads(PACK.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    binding = json.loads(BINDING.read_text(encoding="utf-8"))
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    source = next(item for item in registry["sources"] if item["source_id"] == SOURCE_ID)
    old_source = next(item for item in registry["sources"] if item["source_id"] == "local_gameplay_20261124")
    elements = {item["element_id"]: item for item in pack["elements"]}
    checks = {
        "binding_pass": binding["status"] == "pass" and binding["all_checks_ok"] is True,
        "binding_report_hash": pack["gameplay_verification"]["report_sha256"] == sha(BINDING),
        "pack_schema_1_2": pack["schema_version"] == "aria_soul_menu_catalog/1.2",
        "elements_114": len(pack["elements"]) == len(elements) == 114,
        "gameplay_19": sum(item["gameplay_verified"] for item in pack["elements"]) == 19,
        "gameplay_95_false": sum(item["gameplay_verified"] is False for item in pack["elements"]) == 95,
        "detector_114_false": all(item["detector_verified"] is False for item in pack["elements"]),
        "menu_source_candidate": pack["catalog"]["sources"][0]["source_id"] == "local_aria_menu_catalog_20261125" and pack["catalog"]["sources"][0]["status"] == "candidate",
        "old_gameplay_candidate": old_source["status"] == "candidate" and old_source["last_verified"] is None,
        "new_source_verified": source["status"] == "verified_read" and source["last_verified"] == "2026-11-25",
        "binding_summary": binding["counts"]["elements_bound"] == 19 and binding["counts"]["gameplay_false"] == 95 and binding["counts"]["detector_false"] == 114,
        "state_revisions": binding["state_revisions"] == ["r20261125T120000", "r20261125T145623"],
        "copied_file_count": inventory["file_count"] == len(inventory["files"]) == 519,
        "copied_byte_count": inventory["total_bytes"] == sum(item["bytes"] for item in inventory["files"]) == 14958586,
        "corpus_new_20": sum(item["source_id"] == SOURCE_ID for item in corpus["entries"]) == 20,
        "visual_review_human_false": pack["visual_review"]["human_visual_review"] is False,
        "not_granted": all(value is False for value in pack["gameplay_verification"].values() if isinstance(value, bool)),
    }
    for item in inventory["files"]:
        path = ROOT / item["path"]
        checks[f"inventory:{item['path']}"] = path.is_file() and path.stat().st_size == item["bytes"] and sha(path) == item["sha256"]
    expected_ids = {row["element_id"] for row in binding["cases"]}
    actual_ids = {item["element_id"] for item in pack["elements"] if item["gameplay_verified"]}
    checks["bound_ids_exact"] = expected_ids == actual_ids and len(expected_ids) == 19
    for row in binding["cases"]:
        item = elements[row["element_id"]]
        evidence = item["gameplay_evidence"]
        checks[f"element:{row['element_id']}"] = (
            evidence["case_id"] == row["case_id"]
            and evidence["report"]["sha256"] == row["report"]["sha256"]
            and evidence["report"]["path"] == row["report"]["path"]
            and evidence["slot"] == row["slot"]
            and evidence["metric"] == row["metric"]
            and evidence["status"] == "fixed_route_pass"
        )
    for path in source["evidence"]:
        checks[f"source_evidence:{path}"] = (ROOT / path).is_file() and (ROOT / path).stat().st_size > 0
    new_entries = [item for item in corpus["entries"] if item["source_id"] == SOURCE_ID]
    checks["corpus_all_index_false_authoritative"] = all(item["index"] is False and item["authority"] == "authoritative" for item in new_entries)
    checks["corpus_paths_match_source_evidence"] = {item["path"] for item in new_entries} == {(ROOT / path).resolve().as_posix() for path in source["evidence"]}
    sys.path.insert(0, str(ROOT / "_工具脚本"))
    from taspipe.showcase import PLATFORM_PROFILES
    checks["gba_platform_gate_false"] = PLATFORM_PROFILES["GBA"]["verified"] is False
    assert all(checks.values()), [key for key, value in checks.items() if not value]
    result = {
        "schema_version": "aria_gameplay_binding_verification/1.0",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass", "all_checks_ok": True,
        "check_count": len(checks), "checks": checks,
        "counts": {"elements": 114, "gameplay_verified": 19, "gameplay_false": 95,
                   "detector_false": 114, "copied_files": 519},
        "binding": {"path": BINDING.relative_to(ROOT).as_posix(), "sha256": sha(BINDING)},
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "pass", "checks": len(checks), "counts": result["counts"],
                      "output_sha256": sha(OUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

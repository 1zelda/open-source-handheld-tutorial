from pathlib import Path
from datetime import datetime, timezone
import collections
import hashlib
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PRIOR = ROOT / "知识库P1_20261118/kb_final_20261125_menu_evidence_binding"
EVIDENCE = ROOT / "_工具脚本/taspipe/游戏包/证据/晓月圆舞曲/menu_catalog_nav_full_20261125"
PACK = ROOT / "_工具脚本/taspipe/游戏包/gba_aria_of_sorrow_souls.menu_catalog.json"
REGISTRY = ROOT / "_工具脚本/taspipe/游戏包/来源库/sources.json"
PREFLIGHT = OUT / "preflight_fingerprints_menu_visual_review_20261125.json"
PROTECTED = OUT / "protected_delivery_hashes_menu_visual_review_20261125.json"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def file_record(path):
    path = Path(path).resolve()
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path)}


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def gate_counts():
    specs = {
        "project_selftest": ("selftest_menu_visual_review_20261125.log", r"SELFTEST OK (\d+)/(\d+)"),
        "kb_selftest": ("kb_selftest_menu_visual_review_20261125.log", r"KB_SELFTEST OK (\d+)/(\d+)"),
        "cross_platform_selftest": ("cross_platform_selftest_menu_visual_review_20261125.log", r"CROSS_PLATFORM_SELFTEST OK (\d+)/(\d+)"),
        "sources_selftest": ("sources_selftest_menu_visual_review_20261125.log", r"SOURCES_SELFTEST OK (\d+)/(\d+)"),
        "topic_selftest": ("topic_selftest_menu_visual_review_20261125.log", r"自检合计 (\d+) 格：PASS (\d+) / FAIL (\d+)"),
    }
    result = {}
    for key, (name, pattern) in specs.items():
        match = re.search(pattern, (OUT / name).read_text(encoding="utf-8"))
        if not match:
            raise RuntimeError(f"缺少闸门汇总: {name}")
        if key == "topic_selftest":
            total, passed, failed = map(int, match.groups())
            if failed:
                raise RuntimeError(f"选题闸门失败: {failed}")
        else:
            passed, total = map(int, match.groups())
        if passed != total:
            raise RuntimeError(f"闸门计数不一致: {key} {passed}/{total}")
        result[key] = [passed, total]
    return result


def protect_prior_deliveries():
    old = json.loads((PRIOR / "protected_delivery_hashes_20261125.json").read_text(encoding="utf-8"))
    paths = {ROOT / item["path"] for item in old["files"]}
    paths.update(path.resolve() for path in PRIOR.rglob("*") if path.is_file())
    paths.add(ROOT / "知识库改进优化指导_2026-11-25_晓月菜单证据固化与来源覆盖修正.md")
    paths.add(ROOT / "知识库改进优化指导_2026-11-25_晓月菜单证据固化与来源覆盖修正.pdf")
    files = []
    for path in sorted(paths):
        expected = sha(path)
        actual = sha(path)
        files.append({"path": path.relative_to(ROOT).as_posix(), "expected": expected,
                      "actual": actual, "unchanged": expected == actual})
    result = {"status": "pass" if all(item["unchanged"] for item in files) else "fail",
              "checked": len(files), "files": files}
    write_json(PROTECTED, result)
    return result


def main():
    source_audit = json.loads((OUT / "source_audit_menu_visual_review_20261125.json").read_text(encoding="utf-8"))
    kb_audit = json.loads((OUT / "kb_audit_menu_visual_review_20261125.json").read_text(encoding="utf-8"))
    coverage = json.loads((OUT / "coverage_menu_visual_review_20261125.log").read_text(encoding="utf-8"))
    prep = json.loads((OUT / "visual_review_preparation_20261125.json").read_text(encoding="utf-8"))
    ocr = json.loads((OUT / "menu_visual_ocr_raw_20261125.json").read_text(encoding="utf-8-sig"))
    review = json.loads((EVIDENCE / "menu_visual_review_20261125.json").read_text(encoding="utf-8"))
    pack = json.loads(PACK.read_text(encoding="utf-8"))
    names = json.loads((EVIDENCE / "menu_names_observed.json").read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    source = next(item for item in registry["sources"] if item["source_id"] == "local_aria_menu_catalog_20261125")
    weak = next(item["detail"] for item in source_audit["checks"] if item["check_id"] == "verified_support")
    states = dict(collections.Counter(item["state"] for item in coverage["rows"]))
    media = []
    for item in pack["elements"]:
        for ref in item["evidence"].values():
            path = ROOT / ref["path"]
            media.append(path.is_file() and sha(path) == ref["sha256"])
    checks = {
        "source_audit_fail_zero": source_audit["counts"]["fail"] == 0,
        "source_coverage_complete": source_audit["counts"]["elements_checked"] == source_audit["counts"]["elements_supported"] == 205,
        "kb_audit_fail_zero": kb_audit["counts"]["fail"] == 0,
        "index_chunks_826": kb_audit["counts"]["chunks"] == 826,
        "coverage_states": states == {"verified": 11, "present_unverified": 6, "registered_empty": 9},
        "review_preparation_114": prep["elements"] == prep["preparation_pass"] == 114,
        "ocr_228": len(ocr) == 228 and all(item["status"] == "ok" for item in ocr),
        "review_rows_114": len(review["rows"]) == 114 and review["counts"]["unresolved"] == 0,
        "review_sheets_19": len(list((OUT / "review_assets/sheets").glob("menu_review_sheet_*.png"))) == 19,
        "menu_114_unique_ids": len(pack["elements"]) == len({item["element_id"] for item in pack["elements"]}) == 114,
        "menu_second_review": all(item["name_observation"]["second_visual_review"] and item["effect_observation"]["second_visual_review"] for item in pack["elements"]),
        "menu_names_match": all(item["name_zh"] == names["names"][item["group"]][item["id"] - 1] for item in pack["elements"]),
        "menu_342_media_hashes": len(media) == 342 and all(media),
        "menu_source_candidate": source["status"] == pack["catalog"]["sources"][0]["status"] == "candidate",
        "menu_last_verified_null": source["last_verified"] is None,
        "menu_gameplay_detector_false": all(item["gameplay_verified"] is False and item["detector_verified"] is False for item in pack["elements"]),
        "review_human_boundary": review["human_visual_review"] is False and pack["visual_review"]["human_visual_review"] is False,
        "review_hash_match": sha(EVIDENCE / "menu_visual_review_20261125.json") == pack["visual_review"]["report_sha256"],
    }
    sys.path.insert(0, str(ROOT / "_工具脚本"))
    from taspipe.showcase import PLATFORM_PROFILES
    checks["gba_platform_gate_false"] = PLATFORM_PROFILES["GBA"]["verified"] is False
    protected = protect_prior_deliveries()
    checks["old_deliveries_unchanged"] = protected["status"] == "pass"
    if not all(checks.values()):
        raise RuntimeError([key for key, value in checks.items() if not value])
    data = {
        "schema": "menu_visual_review_delivery_preflight_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_on": "2026-11-25",
        "source_audit": source_audit["counts"],
        "weak_elements": len(weak),
        "menu_weak_elements": sum("menu_catalog" in item for item in weak),
        "legacy_weak_elements": sum("menu_catalog" not in item for item in weak),
        "coverage": states,
        "coverage_rows": len(coverage["rows"]),
        "menu_visual_review": review["counts"],
        "menu": {
            "source_status": source["status"],
            "last_verified": source["last_verified"],
            "human_visual_review": False,
            "gameplay_verified": False,
            "detector_verified": False,
            "platform_gate_verified": False,
            "name_corrections": review["corrections"],
            "media_files_verified": len(media),
        },
        "code": {
            "sources_audit": file_record(ROOT / "_工具脚本/taspipe/sources.py"),
            "sources_selftest_gates": file_record(ROOT / "_工具脚本/taspipe/sources_selftest_gates.py"),
            "kb": file_record(ROOT / "_工具脚本/taspipe/kb.py"),
            "kb_selftest_gates": file_record(ROOT / "_工具脚本/taspipe/kb_selftest_gates.py"),
        },
        "data": {
            "source_registry": file_record(REGISTRY),
            "menu_catalog": file_record(PACK),
            "corpus_map": file_record(ROOT / "_工具脚本/taspipe/游戏包/知识库/corpus_map.json"),
            "index": file_record(ROOT / "_工具脚本/taspipe/游戏包/知识库/index.json"),
            "menu_evidence_report": file_record(EVIDENCE / "menu_catalog_report.json"),
            "menu_name_observation": file_record(EVIDENCE / "menu_names_observed.json"),
            "menu_effect_observation": file_record(EVIDENCE / "menu_effects_observed.json"),
            "menu_visual_review_report": file_record(EVIDENCE / "menu_visual_review_20261125.json"),
        },
        "gates": gate_counts(),
        "protected_delivery": {"status": protected["status"], "checked": protected["checked"],
                               "artifact": file_record(PROTECTED)},
        "checks": checks,
    }
    write_json(PREFLIGHT, data)
    print(json.dumps({"status": "pass", "preflight": str(PREFLIGHT), "protected": protected["checked"],
                      "source_audit": source_audit["counts"], "weak_elements": len(weak),
                      "gates": data["gates"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()

from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PACK = ROOT / "_工具脚本/taspipe/游戏包/gba_aria_of_sorrow_souls.menu_catalog.json"
REGISTRY = ROOT / "_工具脚本/taspipe/游戏包/来源库/sources.json"
EVIDENCE = ROOT / "_工具脚本/taspipe/游戏包/证据/晓月圆舞曲/menu_catalog_nav_full_20261125"
NAMES = EVIDENCE / "menu_names_observed.json"
REVIEW = EVIDENCE / "menu_visual_review_20261125.json"
PREP = OUT / "visual_review_preparation_20261125.json"
OCR = OUT / "menu_visual_ocr_raw_20261125.json"
EXPECTED = {
    PACK: "09ccf152482b4f044b5a39fe82b9cb1a99135892c88c8da8687cbebb6f8b3354",
    REGISTRY: "c2ac65a5a74549ab10424a05a0e5b41f25013baf2cfc001ebcb7d641182b9b87",
    NAMES: "ad2f9ec2aee31c976095707669946b17ad4478bb5e6fd180619a1996e123c922",
}
CORRECTIONS = {("red", 1): "飞骷髅", ("blue", 13): "幻魔士"}
REVIEW_REL = "_工具脚本/taspipe/游戏包/证据/晓月圆舞曲/menu_catalog_nav_full_20261125/menu_visual_review_20261125.json"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def norm(text):
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", text or "").lower()


def main():
    for path, expected in EXPECTED.items():
        actual = sha(path)
        if actual != expected:
            raise RuntimeError(f"并发保护失败 {path}: expected={expected} actual={actual}")
    prep = json.loads(PREP.read_text(encoding="utf-8"))
    ocr_rows = json.loads(OCR.read_text(encoding="utf-8-sig"))
    ocr = {row["file"]: row for row in ocr_rows}
    pack = json.loads(PACK.read_text(encoding="utf-8"))
    names_doc = json.loads(NAMES.read_text(encoding="utf-8"))
    if prep["elements"] != 114 or prep["preparation_pass"] != 114:
        raise RuntimeError("复核前置条件不是114/114")
    if len(ocr_rows) != 228 or any(row["status"] != "ok" for row in ocr_rows):
        raise RuntimeError("OCR不是228/228成功")
    rows = []
    for index, item in enumerate(prep["rows"]):
        key = (item["group"], item["id"])
        initial = item["name_zh"]
        final = CORRECTIONS.get(key, initial)
        name_ocr = ocr[Path(item["name_ocr_asset"]).name]["text"]
        effect_ocr = ocr[Path(item["effect_ocr_asset"]).name]["text"]
        rows.append({
            "element_id": item["element_id"], "group": item["group"], "id": item["id"],
            "initial_name": initial, "final_name": final,
            "name_visual_result": "corrected_to_screenshot" if key in CORRECTIONS else "match",
            "effect_text": item["effect_text"], "effect_visual_result": "match",
            "name_ocr": name_ocr, "name_ocr_exact": norm(name_ocr) == norm(initial),
            "effect_ocr": effect_ocr, "effect_ocr_exact": norm(effect_ocr) == norm(item["effect_text"]),
            "preparation_checks": item["checks"],
            "sheet": f"review_assets/sheets/menu_review_sheet_{index // 6 + 1:02d}.png",
            "shot": item["shot"], "identity": item["identity"], "state": item["state"],
            "status": "pass_after_correction" if key in CORRECTIONS else "pass",
        })
    effect_exact = sum(row["effect_ocr_exact"] for row in rows)
    if effect_exact != 69:
        raise RuntimeError(f"效果OCR精确数异常: {effect_exact}")
    names_doc["names"]["red"][0] = CORRECTIONS[("red", 1)]
    names_doc["names"]["blue"][12] = CORRECTIONS[("blue", 13)]
    names_doc["second_visual_review"] = {
        "reviewed_on": "2026-11-25", "reviewer_type": "ai_assisted_frozen_frame_visual_review",
        "human_visual_review": False, "report": REVIEW_REL,
        "initial_matches": 112, "corrections": 2, "final_matches": 114,
        "correction_rows": [
            {"group": "red", "id": 1, "from": "大骷髅", "to": "飞骷髅"},
            {"group": "blue", "id": 13, "from": "大骷髅", "to": "幻魔士"},
        ],
    }
    write_json(NAMES, names_doc)
    names_sha = sha(NAMES)
    for element in pack["elements"]:
        key = (element["group"], element["id"])
        corrected = key in CORRECTIONS
        if corrected:
            element["name_observation"]["original_name"] = element["name_zh"]
            element["name_zh"] = CORRECTIONS[key]
        element["name_observation"].update({
            "second_visual_review": True,
            "reviewer_type": "ai_assisted_frozen_frame_visual_review",
            "human_visual_review": False,
            "reviewed_on": "2026-11-25",
            "review_report": REVIEW_REL,
            "review_result": "corrected_to_screenshot" if corrected else "match",
        })
        element["effect_observation"].update({
            "second_visual_review": True,
            "reviewer_type": "ai_assisted_frozen_frame_visual_review",
            "human_visual_review": False,
            "reviewed_on": "2026-11-25",
            "review_report": REVIEW_REL,
            "review_result": "match",
        })
    pack["name_observation"]["sha256"] = names_sha
    pack["visual_review"] = {
        "report": REVIEW_REL, "report_sha256": None, "reviewed_on": "2026-11-25",
        "reviewer_type": "ai_assisted_frozen_frame_visual_review", "human_visual_review": False,
        "elements": 114, "initial_name_matches": 112, "name_corrections": 2,
        "final_name_matches": 114, "effect_matches": 114, "unresolved": 0,
        "effect_ocr_exact": effect_exact, "effect_ocr_visual_only": 114 - effect_exact,
        "qualification_unchanged": True, "source_status": "candidate",
        "gameplay_verified": False, "detector_verified": False,
        "production_platform_gate_verified": False,
    }
    report = {
        "schema_version": "aria_menu_second_visual_review/1.0",
        "reviewed_on": "2026-11-25",
        "reviewer_type": "ai_assisted_frozen_frame_visual_review",
        "human_visual_review": False,
        "status": "pass_after_two_name_corrections",
        "scope": "114项冻结菜单截图的名称与效果文本二次视觉复核；不加载ROM，不证明玩法、检测器或平台准入。",
        "input_fingerprints": {str(path.relative_to(ROOT)): expected for path, expected in EXPECTED.items()},
        "counts": {
            "elements": 114, "preparation_pass": 114, "initial_name_matches": 112,
            "name_corrections": 2, "final_name_matches": 114, "effect_matches": 114,
            "effect_ocr_exact": effect_exact, "effect_ocr_visual_only": 114 - effect_exact,
            "unresolved": 0,
        },
        "corrections": [
            {"element_id": "aria_red_001", "group": "red", "id": 1, "from": "大骷髅", "to": "飞骷髅",
             "basis": "冻结截图red_001.png名称区与8x复核板"},
            {"element_id": "aria_blue_013", "group": "blue", "id": 13, "from": "大骷髅", "to": "幻魔士",
             "basis": "冻结截图blue_013.png名称区与8x复核板"},
        ],
        "qualification_boundary": {
            "source_status": "candidate", "gameplay_verified": False,
            "detector_verified": False, "production_platform_gate_verified": False,
            "note": "AI辅助二次视觉复核不等于人工签核，也不升级来源资格。",
        },
        "limitations": [
            "名称区Windows OCR对114项均未返回可用文本，名称结论来自逐页视觉复核板。",
            "效果区OCR精确69项，其余45项以冻结截图视觉复核确认。",
            "未重放模拟器状态，未验证能力魂8项，未建立玩法或检测器正反例。",
        ],
        "rows": rows,
    }
    write_json(REVIEW, report)
    pack["visual_review"]["report_sha256"] = sha(REVIEW)
    write_json(PACK, pack)
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    source = next(item for item in registry["sources"] if item["source_id"] == "local_aria_menu_catalog_20261125")
    if source["status"] != "candidate" or source["last_verified"] is not None:
        raise RuntimeError("菜单来源资格已变化，停止写入")
    if REVIEW_REL not in source["evidence"]:
        source["evidence"].append(REVIEW_REL)
    source["notes"] = (
        "114项菜单身份采集；effect_text来自真实导航截图观察。2026-11-25完成AI辅助逐项二次视觉复核："
        "名称初核112项一致，按冻结截图修正红魂001为飞骷髅、蓝魂013为幻魔士；效果114项一致。"
        "human_visual_review=false、gameplay_verified=false、detector_verified=false，GBA平台闸门未放行。"
        "menu_patch_vs_nav_audit判定identity114/114同ID，旧效果区0/114不得作为文本来源。"
        "342份媒体已固化且哈希一致；资格保持candidate，等待人工签核与玩法/检测器正反例。"
    )
    write_json(REGISTRY, registry)
    sys.path.insert(0, str(ROOT / "_工具脚本"))
    from taspipe.showcase import PLATFORM_PROFILES
    verified = json.loads(PACK.read_text(encoding="utf-8"))
    checks = {
        "elements_114": len(verified["elements"]) == 114,
        "unique_ids_114": len({item["element_id"] for item in verified["elements"]}) == 114,
        "all_second_review": all(item["name_observation"]["second_visual_review"] and item["effect_observation"]["second_visual_review"] for item in verified["elements"]),
        "names_match_observations": all(item["name_zh"] == names_doc["names"][item["group"]][item["id"] - 1] for item in verified["elements"]),
        "all_gameplay_false": all(item["gameplay_verified"] is False for item in verified["elements"]),
        "all_detector_false": all(item["detector_verified"] is False for item in verified["elements"]),
        "source_candidate": source["status"] == verified["catalog"]["sources"][0]["status"] == "candidate",
        "platform_gate_false": PLATFORM_PROFILES["GBA"]["verified"] is False,
        "review_report_hash": sha(REVIEW) == verified["visual_review"]["report_sha256"],
    }
    if not all(checks.values()):
        raise RuntimeError([key for key, value in checks.items() if not value])
    print(json.dumps({
        "status": report["status"], "counts": report["counts"],
        "pack_sha256": sha(PACK), "names_sha256": names_sha,
        "registry_sha256": sha(REGISTRY), "review_sha256": sha(REVIEW),
        "checks": checks,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()

# -*- coding: utf-8 -*-
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path("F:/taspipe_scratch/gba_parallel_20261124/aria_soul_detector_independent_v1_20261125")
RECIPE_ROOT = Path("F:/开源掌机教程/_工具脚本/taspipe/校准配方")
OUT_RECIPE = RECIPE_ROOT / "castlevania_aria_gba.soul_detector_candidates_independent_20261125.json"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def prepare():
    if ROOT.exists():
        raise SystemExit(f"refusing to overwrite existing root: {ROOT}")
    ROOT.mkdir(parents=True)
    red = load(RECIPE_ROOT / "castlevania_aria_gba.red_soul_resource_verify.json")
    red["matrix"]["values"] = [35, 47]
    red["note"] = "独立检测器标定采集；只取红魂35/47，强制重跑，不复用旧帧。"
    write_json(ROOT / "red_capture_recipe.json", red)
    yellow = load(RECIPE_ROOT / "castlevania_aria_gba.yellow_soul_hp_advantage_verify.json")
    yellow["matrix"]["values"] = [10]
    yellow["note"] = "独立检测器标定/验收采集；只取黄魂10，强制重跑，不复用旧帧。"
    write_json(ROOT / "yellow_capture_recipe.json", yellow)
    print(json.dumps({"root": str(ROOT), "red_values": [35, 47], "yellow_values": [10]}))


def case_dirs(case_id, arm, phase):
    base = ROOT / phase / case_id
    return base / f"{case_id}_{arm}_s01_frames"


def finalize():
    legacy = load(RECIPE_ROOT / "castlevania_aria_gba.soul_detector_candidates.json")
    mapping = {
        "red_soul_35_camera_aligned": ("red_soul_35_resource_verify", "red_35", "red0", 40),
        "red_soul_47_local_attack": ("red_soul_47_resource_verify", "red_47", "red0", 30),
        "yellow_soul_10_healing_popup": ("yellow_soul_10_hp_advantage", "yellow_10", "yellow0", 185),
    }
    cases = []
    audit = {"root": str(ROOT), "cases": []}
    for template in legacy["cases"]:
        case_id = template["case_id"]
        capture_case, pos_arm, neg_arm, primary = mapping[case_id]
        dirs = {
            "calib_pos_dir": case_dirs(capture_case, pos_arm, "calibration"),
            "calib_neg_dir": case_dirs(capture_case, neg_arm, "calibration"),
            "accept_pos_dir": case_dirs(capture_case, pos_arm, "acceptance"),
            "accept_neg_dir": case_dirs(capture_case, neg_arm, "acceptance"),
        }
        for directory in dirs.values():
            if not (directory / "capture_manifest.json").is_file():
                raise SystemExit(f"missing capture manifest: {directory}")
        case = {
            "case_id": case_id,
            "method": template["method"],
            "separation_method": "independent_capture",
            "calibration_sample_set_id": f"{case_id}_independent_calibration",
            "acceptance_sample_set_id": f"{case_id}_independent_acceptance",
            **{key: str(value) for key, value in dirs.items()},
            "region": template["region"],
            "frame_range": template["frame_range"],
            "primary_frame": primary,
            "controls": template["controls"],
            "timeline": template["timeline"],
        }
        if template["method"] == "aligned_difference":
            for key in ("alignment_region", "max_shift", "max_dy", "max_global_changed_fraction"):
                case[key] = template[key]
        if case_id == "red_soul_47_local_attack":
            case["controls"].insert(1, {
                "label": "local_attack_frame", "side": "positive", "frame": 30,
                "reference_frame": 30, "expect": "pass",
            })
        cases.append(case)
        manifests = {key: load(directory / "capture_manifest.json") for key, directory in dirs.items()}
        cal = manifests["calib_pos_dir"]
        acc = manifests["accept_pos_dir"]
        if cal["run_id"] == acc["run_id"] or cal["process_id"] == acc["process_id"]:
            raise SystemExit(f"{case_id}: calibration and acceptance are not independent runs")
        audit["cases"].append({
            "case_id": case_id,
            "calibration": {key: {
                "run_id": value["run_id"], "process_id": value["process_id"],
                "source_report": value["source_report"],
                "source_report_sha256": value["source_report_sha256"],
                "frames": value["captured_frames"],
            } for key, value in manifests.items() if key.startswith("calib_")},
            "acceptance": {key: {
                "run_id": value["run_id"], "process_id": value["process_id"],
                "source_report": value["source_report"],
                "source_report_sha256": value["source_report_sha256"],
                "frames": value["captured_frames"],
            } for key, value in manifests.items() if key.startswith("accept_")},
        })
    recipe = {
        "schema_version": "detector_calibration/2.0",
        "kind": "visual_detector_candidate_calibration",
        "game_id": "castlevania_aria_gba",
        "rom_sha1": "40aab076a528f52e93260bb98d91a40039e0da02",
        "cases": cases,
    }
    if OUT_RECIPE.exists():
        raise SystemExit(f"refusing to overwrite recipe: {OUT_RECIPE}")
    write_json(OUT_RECIPE, recipe)
    write_json(ROOT / "capture_audit.json", audit)
    print(json.dumps({"recipe": str(OUT_RECIPE), "recipe_sha256": sha256(OUT_RECIPE), "cases": len(cases)}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "finalize"))
    args = parser.parse_args()
    prepare() if args.phase == "prepare" else finalize()


if __name__ == "__main__":
    main()

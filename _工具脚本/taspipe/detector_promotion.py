# -*- coding: utf-8 -*-
"""把分离验收通过的视觉检测器晋升为正式 showcase catalog 要素。"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
from pathlib import Path

from . import detector_calibration as DC
from . import showcase

SCHEMA_VERSION = "detector_promotion/1.0"


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _resolve(base_dir, value):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base_dir / path).resolve()


def validate_recipe(recipe, base_dir=None):
    if recipe.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"schema_version 须为 {SCHEMA_VERSION}")
    base_dir = Path(base_dir or ".").resolve()
    for key in ("source_report", "base_pack", "output_pack", "output_report", "rom_sha1"):
        if not isinstance(recipe.get(key), str) or not recipe[key].strip():
            raise ValueError(f"缺 {key}")
        recipe[key] = str(_resolve(base_dir, recipe[key]))
    if recipe.get("kind") != "visual_detector_promotion":
        raise ValueError("kind 须为 visual_detector_promotion")
    catalog = recipe.get("catalog")
    if not isinstance(catalog, dict) or catalog.get("status") != "complete":
        raise ValueError("catalog.status 须为 complete")
    if type(catalog.get("expected_total")) is not int or catalog["expected_total"] < 1:
        raise ValueError("catalog.expected_total 须为正整数")
    if not isinstance(catalog.get("sources"), list) or not catalog["sources"]:
        raise ValueError("catalog.sources 不能为空")
    verification = recipe.get("verification")
    if not isinstance(verification, dict) or not verification.get("status"):
        raise ValueError("verification.status 缺失")
    elements = recipe.get("elements")
    if not isinstance(elements, list) or len(elements) != catalog["expected_total"]:
        raise ValueError("elements 数必须等于 catalog.expected_total")
    seen_cases, seen_ids = set(), set()
    for element in elements:
        if not isinstance(element, dict):
            raise ValueError("element 须为对象")
        case_id = element.get("case_id")
        element_id = element.get("element_id")
        if not isinstance(case_id, str) or not case_id or case_id in seen_cases:
            raise ValueError(f"case_id 缺失/重复: {case_id!r}")
        if not isinstance(element_id, str) or not element_id or element_id in seen_ids:
            raise ValueError(f"element_id 缺失/重复: {element_id!r}")
        seen_cases.add(case_id)
        seen_ids.add(element_id)
        for key in ("label", "kind", "base_state", "positive_source_dir", "negative_source_dir"):
            if not isinstance(element.get(key), str) or not element[key].strip():
                raise ValueError(f"{element_id}: 缺 {key}")
            element[key] = str(_resolve(base_dir, element[key]))
        if not Path(element["base_state"]).is_file():
            raise ValueError(f"{element_id}: base_state 不存在")
        for key in ("positive_source_dir", "negative_source_dir"):
            if not Path(element[key]).is_dir():
                raise ValueError(f"{element_id}: {key} 不存在")
        trigger = element.get("trigger")
        control = element.get("negative_control")
        if not isinstance(trigger, dict) or not isinstance(control, dict):
            raise ValueError(f"{element_id}: trigger/negative_control 须为对象")
        if type(element.get("capture_frame")) is not int or element["capture_frame"] < 0:
            raise ValueError(f"{element_id}: capture_frame 须为非负整数")
        if element.get("reference_asset") is not None:
            element["reference_asset"] = str(_resolve(base_dir, element["reference_asset"]))
        identity = element.get("identity")
        if not isinstance(identity, dict) or not identity.get("name_zh"):
            raise ValueError(f"{element_id}: identity.name_zh 缺失")
    return recipe


def _validated_case(report, case_id):
    if report.get("schema_version") != DC.SCHEMA_VERSION:
        raise ValueError(f"标定报告须为 {DC.SCHEMA_VERSION}，旧同集报告不得晋升")
    if report.get("status") != "pass":
        raise ValueError("标定报告总状态不是 pass")
    if report.get("detector_impl_sha256") != showcase._detector_impl_sha():
        raise ValueError("detect.py 实现指纹已变化，必须重新标定")
    matches = [case for case in report.get("cases", []) if case.get("case_id") == case_id]
    if len(matches) != 1 or matches[0].get("status") != "pass":
        raise ValueError(f"{case_id}: 标定 case 缺失或未通过")
    case = matches[0]
    if not case.get("verification", {}).get("pass"):
        raise ValueError(f"{case_id}: 正反例/控制帧未通过")
    timeline = case.get("timeline_audit") or {}
    if not timeline.get("pass") or not timeline.get("negative_all_fail"):
        raise ValueError(f"{case_id}: 全时间轴审计或负例全拒未通过")
    isolation = case.get("sample_isolation") or {}
    if isolation.get("method") != "disjoint_frame_partition":
        raise ValueError(f"{case_id}: 只允许互不重叠的帧分区晋升")
    if isolation.get("source_partition", {}).get("pos", {}).get("overlap") != []:
        raise ValueError(f"{case_id}: 正例标定/验收帧仍有重叠")
    if isolation.get("source_partition", {}).get("neg", {}).get("overlap") != []:
        raise ValueError(f"{case_id}: 负例标定/验收帧仍有重叠")
    return case


def _frame(source_dir, index):
    path = Path(source_dir) / f"f{int(index):04d}.png"
    if not path.is_file():
        raise ValueError(f"帧不存在: {path}")
    return path


def _copy_reference(source, asset):
    asset = Path(asset)
    asset.parent.mkdir(parents=True, exist_ok=True)
    if asset.exists():
        raise ValueError(f"参考帧资产已存在，拒绝覆盖: {asset}")
    shutil.copyfile(source, asset)
    return _sha256(asset)


def promote(recipe_path, overwrite=False):
    recipe_path = Path(recipe_path).resolve()
    recipe = validate_recipe(_json(recipe_path), base_dir=recipe_path.parent)
    report_path = Path(recipe["source_report"])
    report = _json(report_path)
    report_sha = _sha256(report_path)
    base_pack = _json(recipe["base_pack"])
    if base_pack.get("rom_sha1", "").lower() != recipe["rom_sha1"].lower():
        raise ValueError("晋升配方 ROM SHA1 与基础 showcase 包不一致")
    output_pack = Path(recipe["output_pack"])
    if output_pack.exists() and not overwrite:
        raise ValueError(f"输出包已存在，拒绝覆盖: {output_pack}")

    prepared = []
    for spec in recipe["elements"]:
        case = _validated_case(report, spec["case_id"])
        detection = copy.deepcopy(case["detection"])
        detection["frame"] = spec["capture_frame"]
        reference_sha = None
        if case["method"] == "aligned_difference":
            if not spec.get("reference_asset"):
                raise ValueError(f"{spec['element_id']}: 对齐检测器缺 reference_asset")
            source = _frame(spec["negative_source_dir"], spec["capture_frame"])
            reference_sha = _copy_reference(source, spec["reference_asset"])
            detection["success_checks"][0]["params"]["reference_frame"] = str(Path(spec["reference_asset"]).resolve())
        elif spec.get("reference_asset"):
            raise ValueError(f"{spec['element_id']}: 颜色检测器不需要 reference_asset")
        element = {
            "element_id": spec["element_id"],
            "label": spec["label"],
            "kind": spec["kind"],
            "base_state": spec["base_state"],
            "trigger": copy.deepcopy(spec["trigger"]),
            "detection": detection,
            "negative_control": copy.deepcopy(spec["negative_control"]),
            "identity": copy.deepcopy(spec["identity"]),
            "detector_provenance": {
                "calibration_report": str(report_path),
                "calibration_report_sha256": report_sha,
                "case_id": spec["case_id"],
                "sample_isolation": copy.deepcopy(case["sample_isolation"]),
                "timeline_audit": {key: case["timeline_audit"][key] for key in (
                    "scope", "paired_frames", "positive_counts", "negative_counts",
                    "negative_all_fail", "negative_control_kind", "expectations",
                )},
                "capture_frame": spec["capture_frame"],
                "reference_asset_sha256": reference_sha,
            },
            "note": spec["note"],
        }
        positive = _frame(spec["positive_source_dir"], spec["capture_frame"])
        negative = _frame(spec["negative_source_dir"], spec["capture_frame"])
        frame_verification = showcase.verify_detection(element, str(positive), str(negative))
        if frame_verification["verdict"] != "pass":
            raise ValueError(f"{spec['element_id']}: 正式采集帧正反例复验失败: {frame_verification}")
        prepared.append((element, frame_verification, positive, negative))

    pack = copy.deepcopy(base_pack)
    pack["catalog"] = copy.deepcopy(recipe["catalog"])
    pack["elements"] = [row[0] for row in prepared]
    pack["verification"] = copy.deepcopy(recipe["verification"])
    showcase.validate_spec(pack)
    output_pack.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_pack.with_suffix(output_pack.suffix + ".tmp")
    tmp.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(output_pack)

    plan = showcase.plan(str(output_pack))
    result = {
        "schema_version": SCHEMA_VERSION,
        "kind": "visual_detector_promotion",
        "status": "pass",
        "source_report": str(report_path),
        "source_report_sha256": report_sha,
        "output_pack": str(output_pack),
        "output_pack_sha256": _sha256(output_pack),
        "detector_impl_sha256": showcase._detector_impl_sha(),
        "gameplay_verified": False,
        "semantic_identity_verified": False,
        "full_game_timeline_verified": False,
        "platform_verified": False,
        "showcase_plan": plan,
        "elements": [
            {
                "element_id": element["element_id"],
                "case_id": element["detector_provenance"]["case_id"],
                "frame_verification": verification,
                "positive_frame": str(positive),
                "negative_frame": str(negative),
                "reference_asset_sha256": element["detector_provenance"]["reference_asset_sha256"],
            }
            for element, verification, positive, negative in prepared
        ],
    }
    _write_json(recipe["output_report"], result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe", required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    result = promote(args.recipe, overwrite=args.overwrite)
    print(json.dumps({key: result[key] for key in (
        "status", "output_pack", "output_pack_sha256", "platform_verified",
    )}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

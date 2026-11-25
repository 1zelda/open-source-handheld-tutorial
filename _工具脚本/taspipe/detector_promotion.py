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
from . import sources as S

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


def _validate_catalog_sources(recipe):
    reg = S.load_registry(recipe.get("registry_path"))
    by_id = {row["source_id"]: row for row in reg["sources"]}
    element_ids = {row["element_id"] for row in recipe["elements"]}
    source_report = Path(recipe["source_report"]).resolve()
    seen_sources, covered = set(), set()
    for source in recipe["catalog"]["sources"]:
        if not isinstance(source, dict):
            raise ValueError("catalog.sources 元素须为对象")
        unknown = sorted(set(source) - S.PACK_SOURCE_KEYS)
        if unknown:
            raise ValueError(f"来源字段未知: {unknown}")
        sid = source.get("source_id")
        if sid not in by_id:
            raise ValueError(f"野来源 source_id={sid!r}（先登记来源库）")
        if sid in seen_sources:
            raise ValueError(f"source_id 重复: {sid}")
        seen_sources.add(sid)
        registered = by_id[sid]
        if registered["status"] == "dead":
            raise ValueError(f"不得引用 dead 来源: {sid}")
        if source.get("status") != registered["status"]:
            raise ValueError(f"{sid}: 包状态 {source.get('status')!r} 与来源库 {registered['status']!r} 不一致")
        if source.get("verified_date") != registered["last_verified"]:
            raise ValueError(f"{sid}: verified_date 与来源库 last_verified 不一致")
        report = source.get("evidence_report")
        if not isinstance(report, str) or not report.strip():
            raise ValueError(f"{sid}: 缺 evidence_report")
        report_path = S.resolve_path(report).resolve()
        if not report_path.is_file() or report_path.stat().st_size == 0:
            raise ValueError(f"{sid}: evidence_report 缺失或为空: {report}")
        evidence = {S.resolve_path(path).resolve() for path in registered.get("evidence") or []}
        if report_path not in evidence:
            raise ValueError(f"{sid}: evidence_report 未登记到来源库 evidence")
        # 检测器标定只能证明局部画面差异，不能把自己的报告升成玩法或语义验收。
        if report_path == source_report and registered["status"] != "candidate":
            raise ValueError(f"{sid}: 标定报告不得由检测器晋升为 verified_read")
        ids = source.get("element_ids")
        if not isinstance(ids, list) or not ids:
            raise ValueError(f"{sid}: element_ids 须为非空列表")
        for element_id in ids:
            if element_id not in element_ids:
                raise ValueError(f"{sid}: element_id 不在本包: {element_id!r}")
            covered.add(element_id)
    missing = element_ids - covered
    if missing:
        raise ValueError(f"要素缺来源支撑: {sorted(missing)}")


def validate_recipe(recipe, base_dir=None):
    if recipe.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"schema_version 须为 {SCHEMA_VERSION}")
    base_dir = Path(base_dir or ".").resolve()
    for key in ("source_report", "base_pack", "output_pack", "output_report", "bizhawk", "base_state"):
        if not isinstance(recipe.get(key), str) or not recipe[key].strip():
            raise ValueError(f"缺 {key}")
        recipe[key] = str(_resolve(base_dir, recipe[key]))
    if "registry_path" in recipe:
        if not isinstance(recipe["registry_path"], str) or not recipe["registry_path"].strip():
            raise ValueError("registry_path 须为非空路径")
        recipe["registry_path"] = str(_resolve(base_dir, recipe["registry_path"]))
    if not Path(recipe["base_state"]).is_file():
        raise ValueError("base_state 不存在")
    if not Path(recipe["bizhawk"]).is_dir():
        raise ValueError("bizhawk 目录不存在")
    rom_sha1 = recipe.get("rom_sha1")
    if not isinstance(rom_sha1, str) or len(rom_sha1) != 40 or any(ch not in "0123456789abcdefABCDEF" for ch in rom_sha1):
        raise ValueError("rom_sha1 须为 40 位十六进制")
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
        for key in ("label", "kind"):
            if not isinstance(element.get(key), str) or not element[key].strip():
                raise ValueError(f"{element_id}: 缺 {key}")
        for key in ("base_state", "positive_source_dir", "negative_source_dir"):
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
    _validate_catalog_sources(recipe)
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


def _positive_frames(source_dir, total_frames):
    if type(total_frames) is not int or total_frames < 1:
        raise ValueError("正式采集总帧数必须为正整数")
    frames = [_frame(source_dir, index) for index in range(total_frames)]
    return frames


def _copy_reference(source, asset, overwrite=False):
    asset = Path(asset)
    asset.parent.mkdir(parents=True, exist_ok=True)
    if asset.exists():
        if not overwrite:
            raise ValueError(f"参考帧资产已存在，拒绝覆盖: {asset}")
        if _sha256(asset) != _sha256(source):
            raise ValueError(f"已有参考帧资产与源帧不一致，拒绝覆盖: {asset}")
        return _sha256(asset)
    shutil.copyfile(source, asset)
    return _sha256(asset)


def promote(recipe_path, overwrite=False):
    recipe_path = Path(recipe_path).resolve()
    recipe = validate_recipe(_json(recipe_path), base_dir=recipe_path.parent)
    report_path = Path(recipe["source_report"])
    report = _json(report_path)
    report_sha = _sha256(report_path)
    base_pack = _json(recipe["base_pack"])
    platform = str(base_pack.get("platform", "NES")).upper()
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
            reference_sha = _copy_reference(source, spec["reference_asset"], overwrite=overwrite)
            detection["success_checks"][0]["params"]["reference_frame"] = str(Path(spec["reference_asset"]).resolve())
            for key in ("action_checks", "effect_checks"):
                for check in spec.get(key) or []:
                    if check.get("plugin_id") == "frame_pair_aligned_region_difference":
                        check.setdefault("params", {})["reference_frame"] = str(Path(spec["reference_asset"]).resolve())
        elif spec.get("reference_asset"):
            raise ValueError(f"{spec['element_id']}: 颜色检测器不需要 reference_asset")
        missing_acceptance = [key for key in showcase.ACCEPTANCE_FIELDS if key not in spec]
        if missing_acceptance:
            raise ValueError(f"{spec['element_id']}: 检测器不能自动晋升为正式素材，缺三类验收声明 {missing_acceptance}")
        total_frames = (showcase._macro_frames(spec["trigger"].get("macro"), platform)
                        + spec["trigger"].get("extra", 0))
        if spec["capture_frame"] >= total_frames:
            raise ValueError(f"{spec['element_id']}: capture_frame 越出正式采集窗口")
        element = {
            "element_id": spec["element_id"],
            "label": spec["label"],
            "kind": spec["kind"],
            "base_state": spec["base_state"],
            "trigger": copy.deepcopy(spec["trigger"]),
            "detection": detection,
            "negative_control": copy.deepcopy(spec["negative_control"]),
            "identity": copy.deepcopy(spec["identity"]),
            **{key: copy.deepcopy(spec[key]) for key in showcase.ACCEPTANCE_FIELDS},
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
                "capture_total_frames": total_frames,
                "capture_window": [0, total_frames - 1],
                "source_frame_count": sum(
                    1 for path in Path(spec["positive_source_dir"]).glob("f*.png")
                    if path.stem.startswith("f") and path.stem[1:].isdigit()
                ),
                "reference_asset_sha256": reference_sha,
            },
            "note": spec["note"],
        }
        positive = _frame(spec["positive_source_dir"], spec["capture_frame"])
        negative = _frame(spec["negative_source_dir"], spec["capture_frame"])
        positive_frames = _positive_frames(spec["positive_source_dir"], total_frames)
        frame_verification = showcase.verify_detection(
            element, str(positive), str(negative),
            positive_frames=[str(path) for path in positive_frames],
        )
        if (frame_verification["verdict"] != "pass"
                or frame_verification["acceptance"]["verdict"] != "pass"):
            raise ValueError(f"{spec['element_id']}: 正式采集帧候选或三类验收复验失败: {frame_verification}")
        prepared.append((element, frame_verification, positive, negative))

    pack = copy.deepcopy(base_pack)
    pack["bizhawk"] = recipe["bizhawk"]
    pack["base_state"] = recipe["base_state"]
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

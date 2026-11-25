"""配置驱动的视觉检测器候选标定与真实帧正反例验收。"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import detect
from . import showcase
from . import universal_authoring as UA
from .schema import CheckSpec, Verdict

SCHEMA_VERSION = "detector_calibration/2.0"


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _frame(frame_dir, index):
    return Path(frame_dir) / f"f{int(index):04d}.png"


def _frame_indices(frame_dir):
    indices = []
    for path in Path(frame_dir).glob("f*.png"):
        stem = path.stem[1:]
        if stem.isdigit():
            indices.append(int(stem))
    return sorted(indices)


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _directory_fingerprint(path):
    root = Path(path)
    rows = []
    for frame in sorted(root.glob("f*.png")):
        rows.append(f"{frame.name}\0{_sha256(frame)}\n")
    return hashlib.sha256("".join(rows).encode("utf-8")).hexdigest()


def _independent_capture(case, dirs, role):
    captures = {}
    for side in ("pos", "neg"):
        key = f"{'calib' if role == 'calibration' else 'accept'}_{side}_dir"
        directory = dirs[key]
        manifest_path = directory / "capture_manifest.json"
        if not manifest_path.is_file():
            raise ValueError(f"{case['case_id']}: {key} 缺少 capture_manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("schema_version") != "detector_capture/1.0":
            raise ValueError(f"{case['case_id']}: {key} capture manifest 版本非法")
        report_path = Path(manifest.get("source_report", ""))
        if not report_path.is_absolute() or not report_path.is_file():
            raise ValueError(f"{case['case_id']}: {key} 源报告不存在或不是绝对路径")
        report_path = report_path.resolve()
        if _sha256(report_path) != manifest.get("source_report_sha256"):
            raise ValueError(f"{case['case_id']}: {key} 源报告 SHA256 不符")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        provenance = report.get("capture_provenance")
        if not isinstance(provenance, dict):
            raise ValueError(f"{case['case_id']}: {key} 源报告缺少 capture_provenance")
        if provenance.get("force") is not True:
            raise ValueError(f"{case['case_id']}: {key} 独立采集必须来自 --force 运行")
        if type(provenance.get("process_id")) is not int or provenance["process_id"] <= 0:
            raise ValueError(f"{case['case_id']}: {key} 进程 ID 非法")
        if not isinstance(provenance.get("run_id"), str) or not provenance["run_id"]:
            raise ValueError(f"{case['case_id']}: {key} 运行 ID 缺失")
        if Path(provenance.get("out_dir", "")) != report_path.parent:
            raise ValueError(f"{case['case_id']}: {key} 运行输出目录与源报告不一致")
        try:
            started = datetime.fromisoformat(provenance["started_at"])
            finished = datetime.fromisoformat(provenance["finished_at"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{case['case_id']}: {key} 采集时间非法") from exc
        if started.tzinfo is None or finished.tzinfo is None or finished < started:
            raise ValueError(f"{case['case_id']}: {key} 采集时间必须含时区且结束不早于开始")
        allowed_status = {"pass", "candidates_only"} if role == "calibration" else {"pass"}
        if report.get("status") not in allowed_status:
            raise ValueError(f"{case['case_id']}: {key} 源报告状态不支持{role}样本")
        if role == "acceptance" and report.get("mode") != "verify":
            raise ValueError(f"{case['case_id']}: {key} 独立验收必须来自 verify 运行")
        arm_name = manifest.get("arm")
        step_index = manifest.get("step_index")
        arm = (report.get("arms") or {}).get(arm_name)
        steps = arm.get("steps") if isinstance(arm, dict) else None
        if not isinstance(steps, list) or type(step_index) is not int or not (0 <= step_index < len(steps)):
            raise ValueError(f"{case['case_id']}: {key} arm/step 在源报告中不存在")
        step = steps[step_index]
        if (step.get("captured_frames") != manifest.get("captured_frames")
                or Path(step.get("frames_dir", "")) != directory
                or step.get("attempt", {}).get("ok") is not True):
            raise ValueError(f"{case['case_id']}: {key} 帧目录/帧数/attempt 与源报告不一致")
        if report.get("rom_sha1") != manifest.get("rom_sha1"):
            raise ValueError(f"{case['case_id']}: {key} ROM SHA1 与源报告不一致")
        if report.get("base_state") != manifest.get("base_state"):
            raise ValueError(f"{case['case_id']}: {key} 基态与源报告不一致")
        expected_fields = {
            "run_id": provenance["run_id"],
            "process_id": provenance["process_id"],
            "started_at": provenance["started_at"],
            "finished_at": provenance["finished_at"],
            "force": True,
            "source_report_status": report["status"],
            "game_id": report.get("game_id"),
            "system": report.get("system"),
            "core": report.get("core"),
        }
        if any(manifest.get(key) != value for key, value in expected_fields.items()):
            raise ValueError(f"{case['case_id']}: {key} manifest 运行元数据与源报告不一致")
        rows = manifest.get("frames")
        indices = _frame_indices(directory)
        if not isinstance(rows, list) or len(rows) != len(indices):
            raise ValueError(f"{case['case_id']}: {key} manifest 帧清单与目录不一致")
        for destination, row in enumerate(rows):
            if (not isinstance(row, dict) or row.get("destination_frame") != destination
                    or _sha256(directory / f"f{destination:04d}.png") != row.get("sha256")):
                raise ValueError(f"{case['case_id']}: {key} manifest 帧编号/SHA256 不符")
        captures[side] = {
            "capture_id": manifest.get("capture_id"),
            "run_id": provenance["run_id"],
            "process_id": provenance["process_id"],
            "source_report": str(report_path),
            "source_report_sha256": manifest["source_report_sha256"],
            "manifest_sha256": _sha256(manifest_path),
            "frames": len(rows),
        }
    pos, neg = captures["pos"], captures["neg"]
    if any(pos[key] != neg[key] for key in ("run_id", "process_id", "source_report")):
        raise ValueError(f"{case['case_id']}: {role} 正反例必须来自同一次运行")
    if not pos["capture_id"] or pos["capture_id"] == neg["capture_id"]:
        raise ValueError(f"{case['case_id']}: {role} 正反例 capture_id 缺失或重复")
    return captures


def _sample_isolation(case):
    calibration_id = case.get("calibration_sample_set_id")
    acceptance_id = case.get("acceptance_sample_set_id")
    if not isinstance(calibration_id, str) or not calibration_id.strip():
        raise ValueError(f"{case['case_id']}: calibration_sample_set_id 缺失")
    if not isinstance(acceptance_id, str) or not acceptance_id.strip():
        raise ValueError(f"{case['case_id']}: acceptance_sample_set_id 缺失")
    if calibration_id == acceptance_id:
        raise ValueError(f"{case['case_id']}: 标定与验收不能使用同一 sample_set_id")
    if case.get("separation_method") not in ("independent_capture", "disjoint_frame_partition"):
        raise ValueError(f"{case['case_id']}: separation_method 非法")
    keys = ("calib_pos_dir", "calib_neg_dir", "accept_pos_dir", "accept_neg_dir")
    dirs = {key: Path(case[key]).resolve() for key in keys}
    if len(set(dirs.values())) != len(keys):
        raise ValueError(f"{case['case_id']}: 标定与验收的四个帧目录必须互不相同")
    def fingerprint(pos_key, neg_key):
        payload = (f"positive\0{_directory_fingerprint(dirs[pos_key])}\n"
                   f"negative\0{_directory_fingerprint(dirs[neg_key])}\n")
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    calibration_fp = fingerprint("calib_pos_dir", "calib_neg_dir")
    acceptance_fp = fingerprint("accept_pos_dir", "accept_neg_dir")
    if case["separation_method"] == "disjoint_frame_partition" and calibration_fp == acceptance_fp:
        raise ValueError(f"{case['case_id']}: 标定与验收帧目录内容完全相同，不能作为分离样本")
    source_partition = None
    if case["separation_method"] == "disjoint_frame_partition":
        mappings = {}
        for key, directory in dirs.items():
            mapping_path = directory / "source_mapping.json"
            if not mapping_path.is_file():
                raise ValueError(f"{case['case_id']}: {key} 缺少 source_mapping.json")
            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
            if not isinstance(mapping, dict):
                raise ValueError(f"{case['case_id']}: {key} 来源映射须为对象")
            rows = mapping.get("frames")
            if not isinstance(mapping.get("source_dir"), str) or not isinstance(rows, list) or not rows:
                raise ValueError(f"{case['case_id']}: {key} 来源映射格式非法")
            source_frames = []
            for destination, row in enumerate(rows):
                source = row.get("source_frame")
                if (not isinstance(row, dict) or row.get("destination_frame") != destination
                        or type(source) is not int or source in source_frames):
                    raise ValueError(f"{case['case_id']}: {key} 来源帧编号缺失/重复/不连续")
                frame_path = directory / f"f{destination:04d}.png"
                if not frame_path.is_file() or _sha256(frame_path) != row.get("sha256"):
                    raise ValueError(f"{case['case_id']}: {key} 来源映射 SHA256 不符")
                source_frames.append(source)
            mappings[key] = {"source_dir": mapping["source_dir"], "source_frames": source_frames,
                             "mapping_sha256": _sha256(mapping_path)}
        for side in ("pos", "neg"):
            calib_key, accept_key = f"calib_{side}_dir", f"accept_{side}_dir"
            if mappings[calib_key]["source_dir"] != mappings[accept_key]["source_dir"]:
                raise ValueError(f"{case['case_id']}: {side} 分区两侧来源目录不一致")
            overlap = sorted(set(mappings[calib_key]["source_frames"])
                             & set(mappings[accept_key]["source_frames"]))
            if overlap:
                raise ValueError(f"{case['case_id']}: {side} 标定与验收来源帧重叠: {overlap[:10]}")
        source_partition = {
            side: {
                "calibration_count": len(mappings[f"calib_{side}_dir"]["source_frames"]),
                "acceptance_count": len(mappings[f"accept_{side}_dir"]["source_frames"]),
                "overlap": [],
                "mapping_sha256": {
                    key: mappings[key]["mapping_sha256"]
                    for key in (f"calib_{side}_dir", f"accept_{side}_dir")
                },
            }
            for side in ("pos", "neg")
        }
    independent_runs = None
    if case["separation_method"] == "independent_capture":
        calibration = _independent_capture(case, dirs, "calibration")
        acceptance = _independent_capture(case, dirs, "acceptance")
        calibration_run = calibration["pos"]
        acceptance_run = acceptance["pos"]
        if calibration_run["run_id"] == acceptance_run["run_id"]:
            raise ValueError(f"{case['case_id']}: 标定与验收不能来自同一 run_id")
        if calibration_run["process_id"] == acceptance_run["process_id"]:
            raise ValueError(f"{case['case_id']}: 标定与验收不能来自同一进程")
        if calibration_run["source_report"] == acceptance_run["source_report"]:
            raise ValueError(f"{case['case_id']}: 标定与验收不能复用同一源报告")
        independent_runs = {"calibration": calibration, "acceptance": acceptance}
    return {
        "method": case["separation_method"],
        "calibration_sample_set_id": calibration_id,
        "acceptance_sample_set_id": acceptance_id,
        "calibration_fingerprint": calibration_fp,
        "acceptance_fingerprint": acceptance_fp,
        "source_partition": source_partition,
        "independent_runs": independent_runs,
        "directories": {key: str(value) for key, value in dirs.items()},
    }


def _validate_region(case_id, region):
    if (not isinstance(region, list) or len(region) != 4
            or not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in region)):
        raise ValueError(f"{case_id}: region 须为四个归一化数值")
    x0, y0, x1, y1 = region
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ValueError(f"{case_id}: region 越界 {region}")


def _validate_window(case_id, window, total, key):
    if window is None:
        return
    if (not isinstance(window, list) or len(window) != 2
            or any(type(value) is not int for value in window)):
        raise ValueError(f"{case_id}: {key} 须为 [start,end] 整数")
    start, end = window
    if not (0 <= start <= end < total):
        raise ValueError(f"{case_id}: {key} 越界 {window}, 可用 0..{total - 1}")


def validate_recipe(recipe, base_dir=None):
    if recipe.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"schema_version 须为 {SCHEMA_VERSION}；1.0 同集标定验收配方不再产生通过报告")
    cases = recipe.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases 须为非空列表")
    base_dir = Path(base_dir or ".").resolve()
    seen = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("case 须为对象")
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise ValueError(f"case_id 缺失/重复: {case_id!r}")
        seen.add(case_id)
        method = case.get("method")
        if method not in ("aligned_difference", "color_region"):
            raise ValueError(f"{case_id}: 未知 method")
        indices = {}
        for key in ("calib_pos_dir", "calib_neg_dir", "accept_pos_dir", "accept_neg_dir"):
            value = case.get(key)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{case_id}: {key} 缺失")
            path = Path(value)
            if not path.is_absolute():
                path = base_dir / path
            case[key] = str(path.resolve())
            if not path.is_dir():
                raise ValueError(f"{case_id}: {key} 不存在: {case[key]}")
            indices[key] = _frame_indices(path)
            if len(indices[key]) < 3:
                raise ValueError(f"{case_id}: {key} 至少需要 3 帧")
            if indices[key] != list(range(len(indices[key]))):
                raise ValueError(f"{case_id}: {key} 帧号必须从 0 连续编号")
        case["_sample_isolation"] = _sample_isolation(case)
        calibration_total = min(len(indices["calib_pos_dir"]), len(indices["calib_neg_dir"]))
        acceptance_total = min(len(indices["accept_pos_dir"]), len(indices["accept_neg_dir"]))
        _validate_region(case_id, case.get("region"))
        _validate_window(case_id, case.get("frame_range"), calibration_total, "frame_range")
        primary_frame = case.get("primary_frame")
        if type(primary_frame) is not int or not (0 <= primary_frame < acceptance_total):
            raise ValueError(f"{case_id}: primary_frame 须为验收帧范围内的整数")
        if method == "aligned_difference":
            _validate_region(case_id, case.get("alignment_region", [0.0, 0.125, 1.0, 0.4875]))
            for key, upper in (("max_shift", 64), ("max_dy", 16)):
                value = case.get(key, 0)
                if type(value) is not int or not (0 <= value <= upper):
                    raise ValueError(f"{case_id}: {key} 须为 0..{upper} 整数")
            max_global = case.get("max_global_changed_fraction", 0.25)
            if not isinstance(max_global, (int, float)) or isinstance(max_global, bool) or not (0 <= max_global <= 1):
                raise ValueError(f"{case_id}: max_global_changed_fraction 须落在 0..1")
        controls = case.get("controls") or []
        if not isinstance(controls, list):
            raise ValueError(f"{case_id}: controls 须为列表")
        for control in controls:
            if not isinstance(control, dict) or type(control.get("frame")) is not int:
                raise ValueError(f"{case_id}: control 缺少整数 frame")
            side = control.get("side", "positive")
            if side not in ("positive", "negative") or control.get("expect", "fail") not in ("pass", "fail"):
                raise ValueError(f"{case_id}: control side/expect 非法")
            limit = len(indices["accept_pos_dir" if side == "positive" else "accept_neg_dir"])
            if not (0 <= control["frame"] < limit):
                raise ValueError(f"{case_id}: control frame 越界 {control['frame']}")
            if "reference_frame" in control:
                if method != "aligned_difference" or type(control["reference_frame"]) is not int:
                    raise ValueError(f"{case_id}: reference_frame 仅 aligned_difference 可用且须为整数")
                if not (0 <= control["reference_frame"] < len(indices["accept_neg_dir"])):
                    raise ValueError(f"{case_id}: reference_frame 越界")
        timeline = case.get("timeline") or {}
        if not isinstance(timeline, dict) or type(timeline.get("negative_all_fail", True)) is not bool:
            raise ValueError(f"{case_id}: timeline 配置非法")
        expectations = timeline.get("expectations") or []
        if not isinstance(expectations, list):
            raise ValueError(f"{case_id}: timeline.expectations 须为列表")
        for expectation in expectations:
            if not isinstance(expectation, dict) or expectation.get("side") not in ("positive", "negative"):
                raise ValueError(f"{case_id}: timeline expectation 缺少 side")
            if expectation.get("expect") not in ("any_pass", "all_pass", "all_fail"):
                raise ValueError(f"{case_id}: timeline expectation.expect 非法")
            _validate_window(case_id, [expectation.get("start"), expectation.get("end")], acceptance_total,
                             "timeline expectation")
    return recipe


def build_detection(case_id, calibration, frame=None, reference_frame=None):
    if calibration["plugin_id"] == "frame_pair_aligned_region_difference":
        params = {
            key: calibration[key]
            for key in (
                "reference_frame", "region", "alignment_region", "max_shift", "max_dy",
                "diff_threshold", "min_changed_fraction", "max_global_changed_fraction",
            )
        }
        if reference_frame is not None:
            params["reference_frame"] = str(reference_frame)
    else:
        params = {
            key: calibration[key]
            for key in ("region", "rgb", "tol", "min_fraction")
        }
    return {
        "frame": calibration["frame"] if frame is None else frame,
        "success_checks": [{
            "check_id": f"{case_id}_visual",
            "plugin_id": calibration["plugin_id"],
            "params": params,
            "required": True,
        }],
    }


def calibrate_case(case):
    if case["method"] == "aligned_difference":
        return UA.calibrate_aligned_element_detector(
            Path(case["calib_pos_dir"]), Path(case["calib_neg_dir"]), case["region"],
            alignment_region=case.get("alignment_region"),
            frame_range=case.get("frame_range"),
            max_shift=int(case.get("max_shift", 0)),
            max_dy=int(case.get("max_dy", 0)),
            max_global_changed_fraction=float(case.get("max_global_changed_fraction", 0.25)),
        )
    return UA.calibrate_region_color_detector(
        Path(case["calib_pos_dir"]), Path(case["calib_neg_dir"]), case["region"],
        frame_range=case.get("frame_range"),
    )


def _control_spec(case, detection, control):
    spec = dict(detection["success_checks"][0])
    spec["params"] = dict(spec["params"])
    if case["method"] == "aligned_difference" and "reference_frame" in control:
        spec["params"]["reference_frame"] = str(_frame(case["accept_neg_dir"], control["reference_frame"]))
    return CheckSpec(**spec)


def verify_case(case, detection):
    primary = showcase.verify_detection(
        {"detection": detection},
        str(_frame(case["accept_pos_dir"], detection["frame"])),
        str(_frame(case["accept_neg_dir"], detection["frame"])),
    )
    controls = []
    for control in case.get("controls") or []:
        spec = _control_spec(case, detection, control)
        side = control.get("side", "positive")
        frame_dir = case["accept_pos_dir"] if side == "positive" else case["accept_neg_dir"]
        result = detect.run_check(spec, str(_frame(frame_dir, control["frame"])))
        expected = control.get("expect", "fail")
        ok = result.verdict == (Verdict.PASS if expected == "pass" else Verdict.FAIL)
        controls.append({
            "label": control.get("label", f"frame_{control['frame']}"),
            "side": side,
            "frame": control["frame"],
            "reference_frame": control.get("reference_frame"),
            "expected": expected,
            "verdict": result.verdict.value,
            "pass": ok,
            "reason": result.reason,
        })
    return {
        "primary": primary,
        "controls": controls,
        "pass": primary["verdict"] == Verdict.PASS.value and all(row["pass"] for row in controls),
    }


def audit_case(case, detection):
    pos_dir, neg_dir = Path(case["accept_pos_dir"]), Path(case["accept_neg_dir"])
    total = min(len(_frame_indices(pos_dir)), len(_frame_indices(neg_dir)))
    rows = []
    for index in range(total):
        pos_params = dict(detection["success_checks"][0]["params"])
        if case["method"] == "aligned_difference":
            pos_params["reference_frame"] = str(_frame(neg_dir, index))
        pos_spec = CheckSpec(
            check_id=detection["success_checks"][0]["check_id"],
            plugin_id=detection["success_checks"][0]["plugin_id"],
            params=pos_params,
            required=True,
        )
        pos = detect.run_check(pos_spec, str(_frame(pos_dir, index)))
        neg_spec = _control_spec(case, detection, {"reference_frame": index})
        neg = detect.run_check(neg_spec, str(_frame(neg_dir, index)))
        rows.append({
            "frame": index,
            "positive": pos.verdict.value,
            "negative": neg.verdict.value,
            "positive_reason": pos.reason,
            "negative_reason": neg.reason,
        })
    timeline = case.get("timeline") or {}
    expectations = []
    for spec in timeline.get("expectations") or []:
        selected = [row[spec["side"]] for row in rows if spec["start"] <= row["frame"] <= spec["end"]]
        expect = spec["expect"]
        if expect == "any_pass":
            passed = Verdict.PASS.value in selected
        elif expect == "all_pass":
            passed = bool(selected) and all(value == Verdict.PASS.value for value in selected)
        else:
            passed = bool(selected) and all(value == Verdict.FAIL.value for value in selected)
        expectations.append({
            "label": spec.get("label", f"{spec['side']}_{spec['start']}_{spec['end']}"),
            "side": spec["side"],
            "start": spec["start"],
            "end": spec["end"],
            "expect": expect,
            "counts": dict(Counter(selected)),
            "pass": passed,
        })
    negative_values = [row["negative"] for row in rows]
    negative_all_fail = bool(negative_values) and all(value == Verdict.FAIL.value for value in negative_values)
    negative_gate = negative_all_fail if timeline.get("negative_all_fail", True) else True
    return {
        "scope": "all_available_acceptance_dump_frames",
        "paired_frames": total,
        "positive_frames": len(_frame_indices(pos_dir)),
        "negative_frames": len(_frame_indices(neg_dir)),
        "positive_counts": dict(Counter(row["positive"] for row in rows)),
        "negative_counts": dict(Counter(negative_values)),
        "negative_all_fail": negative_all_fail,
        "negative_control_kind": ("same_empty_frame_self_difference" if case["method"] == "aligned_difference"
                                  else "empty_soul_frame_color_absence"),
        "expectations": expectations,
        "frames": rows,
        "pass": negative_gate and all(row["pass"] for row in expectations),
    }


def run_recipe(recipe_path, out_path):
    recipe_path = Path(recipe_path).resolve()
    recipe = validate_recipe(_json(recipe_path), base_dir=recipe_path.parent)
    cases = []
    for case in recipe["cases"]:
        row = {"case_id": case["case_id"], "method": case["method"]}
        try:
            calibration = calibrate_case(case)
            detection = build_detection(
                case["case_id"], calibration, frame=case["primary_frame"],
                reference_frame=_frame(case["accept_neg_dir"], case["primary_frame"]),
            )
            verification = verify_case(case, detection)
            timeline = audit_case(case, detection)
            row.update({
                "status": "pass" if verification["pass"] and timeline["pass"] else "failed",
                "sample_isolation": case["_sample_isolation"],
                "calibration": calibration,
                "detection": detection,
                "verification": verification,
                "timeline_audit": timeline,
            })
        except Exception as exc:
            row.update({"status": "error", "error": f"{type(exc).__name__}: {exc}"})
        cases.append(row)
    counts = Counter(row["status"] for row in cases)
    report = {
        "schema_version": SCHEMA_VERSION,
        "kind": "visual_detector_candidate_calibration",
        "recipe": str(recipe_path),
        "recipe_sha256": _sha256(recipe_path),
        "out": str(out_path),
        "status": "pass" if counts.get("pass") == len(cases) else "failed",
        "total": len(cases),
        "counts": dict(counts),
        "detector_impl_sha256": showcase._detector_impl_sha(),
        "gameplay_verified": False,
        "semantic_identity_verified": False,
        "detector_scope": "separated_acceptance_frames_with_explicit_expectations",
        "sample_separation_methods": sorted({case["separation_method"] for case in recipe["cases"]}),
        "calibration_acceptance_separated": True,
        "full_game_timeline_verified": False,
        "platform_verified": False,
        "cases": cases,
    }
    _write_json(out_path, report)
    lines = [
        "# 视觉检测器候选标定",
        "",
        "> 标定与验收使用不同样本集；independent_capture 必须绑定不同进程的强制运行、源报告与逐帧 SHA256。确定性回放允许不同进程采集到逐帧相同的画面，但不得复用同一运行或源报告。验收覆盖验收采集的全部正反例帧和显式时间窗，不等于技能身份、整套玩法、平台准入或未采集时间轴。",
        "",
        f"- 配方：`{recipe_path}`",
        f"- 配方 SHA256：`{report['recipe_sha256']}`",
        f"- 总数：{len(cases)}；状态逐格计数：`{dict(counts)}`",
        f"- detector 实现 SHA256：`{report['detector_impl_sha256']}`",
        "",
        "| ID | 方法 | 状态 | frame | 局部/颜色正例 | 反例 | 控制 | 全帧审计 |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    for row in cases:
        if row["status"] == "error":
            lines.append(f"| {row['case_id']} | {row['method']} | error | - | - | - | {row['error']} |")
            continue
        cal = row["calibration"]
        verification = row["verification"]
        timeline = row["timeline_audit"]
        pos_value = cal.get("pos_fraction")
        lines.append(
            f"| {row['case_id']} | {row['method']} | {row['status']} | {cal['frame']} | "
            f"{pos_value} | {verification['primary']['negative']['verdict']} | "
            f"{sum(control['pass'] for control in verification['controls'])}/{len(verification['controls'])} | "
            f"{timeline['paired_frames']} 对帧 / "
            f"{sum(item['pass'] for item in timeline['expectations'])}/{len(timeline['expectations'])} 时间窗 |"
        )
    lines.extend(["", "## 时间轴边界", ""])
    for row in cases:
        if row["status"] == "error":
            continue
        timeline = row["timeline_audit"]
        isolation = row["sample_isolation"]
        lines.append(f"### {row['case_id']}")
        lines.append(
            f"- 样本分离：`{isolation['method']}`；标定集 `{isolation['calibration_sample_set_id']}`；"
            f"验收集 `{isolation['acceptance_sample_set_id']}`"
        )
        lines.append(f"- 正例逐格计数：`{timeline['positive_counts']}`；反例逐格计数：`{timeline['negative_counts']}`")
        lines.append(f"- 反例控制：`{timeline['negative_control_kind']}`；全负例拒绝：`{timeline['negative_all_fail']}`")
        if isolation["independent_runs"]:
            lines.append(f"- 帧内容指纹：标定 `{isolation['calibration_fingerprint']}`；验收 `{isolation['acceptance_fingerprint']}`")
            for role, label in (("calibration", "标定"), ("acceptance", "验收")):
                run = isolation["independent_runs"][role]["pos"]
                lines.append(
                    f"- 独立{label}采集：进程 `{run['process_id']}`；运行 `{run['run_id']}`；"
                    f"源报告 `{run['source_report']}`；报告 SHA256 `{run['source_report_sha256']}`"
                )
        for item in timeline["expectations"]:
            lines.append(
                f"- {item['label']}：{item['side']} {item['start']}..{item['end']} "
                f"要求 {item['expect']}，实测 `{item['counts']}`，{'PASS' if item['pass'] else 'FAIL'}"
            )
        lines.append("")
    Path(out_path).with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = run_recipe(args.recipe, args.out)
    print(json.dumps({key: report[key] for key in ("status", "total", "counts", "detector_impl_sha256")},
                     ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())

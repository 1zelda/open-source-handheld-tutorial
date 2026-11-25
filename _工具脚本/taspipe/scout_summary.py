import argparse
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path

SCHEMA_VERSION = "scout_summary/1.1"
GBA_MGBA_CORE_TYPE = "BizHawk.Emulation.Cores.Nintendo.GBA.MGBAHawk"


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def expected_cases(recipe):
    if recipe.get("matrix"):
        pattern = recipe["matrix"]["case_id"]
        return [pattern.replace("{value}", str(value)) for value in recipe["matrix"]["values"]]
    return [case["id"] for case in recipe["cases"]]


def summarize_case(report_path):
    report_path = Path(report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    arms = report.get("arms") or {}
    step_rows = [step for arm in arms.values() for step in arm.get("steps", [])]
    expectations = [row for step in step_rows for row in step.get("expect", [])]
    screens = [step["screen"] for step in step_rows if step.get("screen")]
    missing_evidence = [path for path in report.get("evidence", []) if not Path(path).is_file()]
    comparisons = []
    for comp in report.get("candidate_comparisons", []):
        frames = comp.get("frames", [])
        pixels = [frame.get("changed_pixels") for frame in frames if frame.get("changed_pixels") is not None]
        fractions = [frame.get("changed_fraction") for frame in frames if frame.get("changed_fraction") is not None]
        changed = [frame["frame"] for frame in frames if not frame.get("equal", True)]
        comparisons.append({
            "left": comp.get("left"),
            "right": comp.get("right"),
            "relation": comp.get("relation"),
            "pass": bool(comp.get("pass")),
            "frames": frames,
            "changed_frames": changed,
            "changed_frame_count": len(changed),
            "min_changed_pixels": min(pixels) if pixels else None,
            "median_changed_pixels": statistics.median(pixels) if pixels else None,
            "max_changed_pixels": max(pixels) if pixels else None,
            "max_changed_fraction": max(fractions) if fractions else None,
        })
    frame_rows = [frame for comp in comparisons for frame in comp["frames"]]
    different_rows = [frame for comp in comparisons if comp["relation"] == "different" for frame in comp["frames"]]
    equal_rows = [frame for comp in comparisons if comp["relation"] == "equal" for frame in comp["frames"]]
    visual_pass = bool(comparisons) and all(comp["pass"] for comp in comparisons)
    any_visual_change = any((frame.get("changed_pixels") or 0) > 0 for frame in frame_rows)
    different_pass = sum(frame.get("pass") is True for frame in different_rows)
    equal_pass = sum(frame.get("pass") is True for frame in equal_rows)
    partial_visual = different_pass > 0 and not visual_pass
    equal_baseline_fail = any(frame.get("pass") is not True for frame in equal_rows)
    initial_screens_pass = bool(screens) and all(screen.get("pass") is True for screen in screens)
    actual_cores = sorted({step.get("actual_core") for step in step_rows if step.get("actual_core")})
    ram_diffs = report.get("ram_diffs", [])
    ram_changed = any(diff.get("changed_bytes", 0) for diff in ram_diffs)
    negative_fingerprint = {}
    for name, arm in arms.items():
        if not name.endswith("0") or not arm.get("steps"):
            continue
        final = arm["steps"][-1]
        ram = final.get("ram")
        shot = final.get("shot")
        frames_dir = final.get("frames_dir")
        selected = []
        if frames_dir and Path(frames_dir).is_dir():
            for frame in (8, 12, 20, 40, 60, 80, 85, 86, 90, 100, 120, 164):
                path = Path(frames_dir) / f"f{frame:04d}.png"
                if path.is_file():
                    selected.append(str(path))
        negative_fingerprint[name] = {
            "ram_sha256": digest(ram) if ram and Path(ram).is_file() else None,
            "final_shot_sha256": digest(shot) if shot and Path(shot).is_file() else None,
            "frame_sha256": {Path(path).name: digest(path) for path in selected},
        }
    if visual_pass:
        classification = "visual_candidate"
    elif partial_visual:
        classification = "partial_visual_candidate"
    elif any_visual_change:
        classification = "visual_change_without_passing_different_frame"
    elif frame_rows:
        classification = "no_visual_change"
    else:
        classification = "no_comparisons"
    return {
        "case_id": report.get("case_id"),
        "status": report.get("status"),
        "cache_key": report.get("cache_key"),
        "report": str(report_path),
        "expectations_total": len(expectations),
        "expectations_pass": all(row.get("pass") is True for row in expectations),
        "screens_total": len(screens),
        "screens_pass": initial_screens_pass,
        "actual_cores": actual_cores,
        "core_ok": actual_cores == [GBA_MGBA_CORE_TYPE],
        "evidence_total": len(report.get("evidence", [])),
        "evidence_complete": not missing_evidence,
        "missing_evidence": missing_evidence,
        "captured_frames": {
            f"{name}:{step.get('index')}": step.get("captured_frames")
            for name, arm in arms.items() for step in arm.get("steps", [])
            if "captured_frames" in step
        },
        "comparison_pass": visual_pass,
        "visual_candidate": visual_pass,
        "partial_visual_candidate": partial_visual,
        "equal_baseline_fail": equal_baseline_fail,
        "any_visual_change": any_visual_change,
        "different_frames_pass": different_pass,
        "different_frames_total": len(different_rows),
        "equal_frames_pass": equal_pass,
        "equal_frames_total": len(equal_rows),
        "classification": classification,
        "ram_changed": ram_changed,
        "combined_candidate": visual_pass and ram_changed,
        "ram_only": ram_changed and not any_visual_change,
        "ram_plus_partial_visual": ram_changed and partial_visual,
        "comparisons": comparisons,
        "ram_diffs": ram_diffs,
        "negative_fingerprint": negative_fingerprint,
    }


def negative_inconsistencies(cases):
    negatives = {}
    for row in cases:
        for name, fingerprint in row.get("negative_fingerprint", {}).items():
            negatives.setdefault(name, []).append((row["case_id"], fingerprint))
    result = []
    for name, rows in negatives.items():
        ram_values = Counter(fingerprint.get("ram_sha256") for _, fingerprint in rows)
        shot_values = Counter(fingerprint.get("final_shot_sha256") for _, fingerprint in rows)
        frame_values = {}
        for _, fingerprint in rows:
            for frame, sha in fingerprint.get("frame_sha256", {}).items():
                frame_values.setdefault(frame, Counter())[sha] += 1
        bad = [value for value in ram_values.values() if value != len(rows)]
        bad += [value for value in shot_values.values() if value != len(rows)]
        bad += [value for counts in frame_values.values() for value in counts.values() if value != len(rows)]
        if bad:
            result.append({
                "arm": name,
                "cases": len(rows),
                "ram_counts": dict(ram_values),
                "shot_counts": dict(shot_values),
                "frame_counts": {frame: dict(counts) for frame, counts in frame_values.items()},
            })
    return result


def build_summary(recipe_path, run_dir):
    recipe_path = Path(recipe_path)
    run_dir = Path(run_dir)
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    cases = []
    for case_id in expected_cases(recipe):
        report_path = run_dir / case_id / "report.json"
        if report_path.is_file():
            cases.append(summarize_case(report_path))
        else:
            cases.append({"case_id": case_id, "status": "error", "error": "missing report.json", "report": str(report_path)})
    visual = [row for row in cases if row.get("visual_candidate")]
    partial = [row for row in cases if row.get("partial_visual_candidate")]
    equal_fail = [row for row in cases if row.get("equal_baseline_fail")]
    no_visual = [row for row in cases if row.get("classification") == "no_visual_change"]
    combined = [row for row in cases if row.get("combined_candidate")]
    visual_only = [row for row in visual if not row.get("ram_changed")]
    ram_only = [row for row in cases if row.get("ram_only")]
    ram_partial = [row for row in cases if row.get("ram_plus_partial_visual")]
    integrity_bad = [row["case_id"] for row in cases if row.get("status") != "error" and not (
        row["expectations_pass"] and row["screens_pass"] and row["core_ok"] and row["evidence_complete"]
    )]
    cache_keys = sorted({row.get("cache_key") for row in cases if row.get("cache_key")})
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "candidate_audit_not_verification",
        "recipe": str(recipe_path),
        "run": str(run_dir),
        "total": len(cases),
        "counts": dict(Counter(row["status"] for row in cases)),
        "classification_counts": dict(Counter(row.get("classification", "error") for row in cases)),
        "visual_candidate_count": len(visual),
        "partial_visual_candidate_count": len(partial),
        "equal_baseline_fail_count": len(equal_fail),
        "no_visual_change_count": len(no_visual),
        "combined_candidate_count": len(combined),
        "visual_only_count": len(visual_only),
        "ram_only_count": len(ram_only),
        "ram_plus_partial_visual_count": len(ram_partial),
        "integrity_bad": integrity_bad,
        "cache_keys": cache_keys,
        "negative_inconsistent": negative_inconsistencies(cases),
        "visual_candidates": visual,
        "partial_visual_candidates": partial,
        "equal_baseline_failures": equal_fail,
        "visual_only": visual_only,
        "ram_only": ram_only,
        "ram_plus_partial_visual": ram_partial,
        "cases": cases,
    }


def write_summary(output, out):
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# 魂候选扫描审计",
        "",
        "> 本文件只审计 scout 产物；候选不等于技能身份、玩法验收或平台准入。",
        "",
        f"- 配方：`{output['recipe']}`",
        f"- 运行目录：`{output['run']}`",
        f"- 总数：{output['total']}",
        f"- 状态逐格计数：`{output['counts']}`",
        f"- 分类逐格计数：`{output['classification_counts']}`",
        f"- 全比较通过：{output['visual_candidate_count']}；部分差异帧通过：{output['partial_visual_candidate_count']}；相等基线失败：{output['equal_baseline_fail_count']}",
        f"- 视觉+RAM：{output['combined_candidate_count']}；仅视觉：{output['visual_only_count']}；纯 RAM：{output['ram_only_count']}；RAM+部分视觉：{output['ram_plus_partial_visual_count']}",
        f"- 完整性异常：{output['integrity_bad'] or '无'}",
        f"- 负例不一致：{output['negative_inconsistent'] or '无'}",
        f"- cache key：{output['cache_keys']}",
        "",
        "| ID | 分类 | different帧 | equal帧 | 最大像素差 | RAM变化 | 完整性 | 报告 |",
        "|---|---|---:|---:|---:|---:|---|---|",
    ]
    for row in output["cases"]:
        if row["status"] == "error":
            lines.append(f"| {row['case_id']} | error | - | - | - | - | 缺报告 | `{row['report']}` |")
            continue
        max_pixels = max((frame.get("changed_pixels", 0) or 0 for comp in row["comparisons"] for frame in comp["frames"]), default=0)
        ram = sum(diff.get("changed_bytes", 0) for diff in row["ram_diffs"])
        integrity = "OK" if row["expectations_pass"] and row["screens_pass"] and row["core_ok"] and row["evidence_complete"] else "BAD"
        lines.append(f"| {row['case_id']} | {row['classification']} | {row['different_frames_pass']}/{row['different_frames_total']} | {row['equal_frames_pass']}/{row['equal_frames_total']} | {max_pixels} | {ram} B | {integrity} | `{row['report']}` |")
    out.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    output = build_summary(args.recipe, args.run)
    write_summary(output, args.out)
    keys = (
        "total", "counts", "classification_counts", "visual_candidate_count",
        "partial_visual_candidate_count", "equal_baseline_fail_count", "no_visual_change_count",
        "combined_candidate_count", "visual_only_count", "ram_only_count",
        "ram_plus_partial_visual_count", "integrity_bad", "negative_inconsistent", "cache_keys",
    )
    print(json.dumps({key: output[key] for key in keys}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

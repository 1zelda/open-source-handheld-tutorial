# -*- coding: utf-8 -*-
"""配置驱动的跨游戏 RAM 校准：菜单闭环、真实输入正反例、证据归档与指纹复用。

配方只描述游戏身份、状态包、宏和断言；模拟器执行、帧对齐 RAM 窗口、像素比较、
报告与归档由本模块统一完成。scout 只产生候选，verify 才输出字段级验收结论。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import hashlib
import json
import os
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageChops

from . import statejump as SJ
from . import state_registry as SR
from .schema import SchemaError, sha256_file

HERE = Path(__file__).resolve().parent
RECIPE_ROOT = HERE / "校准配方"
SCRATCH_ROOT = Path("F:/taspipe_scratch/ram_calibration")
SCHEMA_VERSION = "ram_calibration/1.0"
_OPS = {"==": lambda a, b: a == b, "!=": lambda a, b: a != b,
        ">": lambda a, b: a > b, "<": lambda a, b: a < b,
        ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b}
_SAFE = "abcdefghijklmnopqrstuvwxyz0123456789_"


def _json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _safe(value: str, fallback: str = "item") -> str:
    out = "".join(ch if ch in _SAFE else "_" for ch in str(value).lower()).strip("_")
    return out[:48] or fallback


def _addr(value) -> int:
    return int(str(value), 0) if isinstance(value, str) else int(value)


def _macro(recipe: dict, value) -> str:
    if isinstance(value, dict):
        value = value.get("macro")
    if value is None:
        return "-"
    value = str(value)
    if value in ("", "-"):
        return "-"
    if value.startswith("@"):
        name = value[1:]
        if name not in recipe.get("macros", {}):
            raise SchemaError(f"未定义宏: {name}")
        value = recipe["macros"][name]
        if isinstance(value, dict):
            value = value.get("macro")
    return SJ.parse_macro(str(value), recipe["profile"]["system"])


def _frame_count(spec: str) -> int:
    return 0 if spec == "-" else len(spec.split(","))


def _matrix_substitute(value, token):
    if isinstance(value, str):
        return token if value == "{value}" else value.replace("{value}", str(token))
    if isinstance(value, list):
        return [_matrix_substitute(item, token) for item in value]
    if isinstance(value, dict):
        return {key: _matrix_substitute(item, token) for key, item in value.items()}
    return value


def expand_recipe(recipe: dict) -> dict:
    matrix = recipe.get("matrix")
    if matrix is None:
        return recipe
    if recipe.get("cases"):
        raise SchemaError("matrix 不能与 cases 同时使用")
    if not isinstance(matrix, dict):
        raise SchemaError("matrix 必须为对象")
    pattern, values, template = matrix.get("case_id"), matrix.get("values"), matrix.get("template")
    if not isinstance(pattern, str) or "{value}" not in pattern:
        raise SchemaError("matrix.case_id 必须包含 {value}")
    if not isinstance(values, list) or not values:
        raise SchemaError("matrix.values 必须是非空列表")
    if any(type(value) is not int or not 0 <= value <= 255 for value in values):
        raise SchemaError("matrix.values 只允许 0..255 整数")
    if len(set(values)) != len(values):
        raise SchemaError("matrix.values 不允许重复")
    if not isinstance(template, dict):
        raise SchemaError("matrix.template 必须为对象")
    cases = []
    for value in values:
        case = _matrix_substitute(template, value)
        case["id"] = pattern.replace("{value}", str(value))
        cases.append(case)
    out = dict(recipe)
    out["cases"] = cases
    out.pop("matrix", None)
    return out


def compile_recipe(recipe: dict) -> dict:
    rows = []
    for name, value in (recipe.get("macros") or {}).items():
        spec = _macro(recipe, value)
        rows.append({"name": name, "frames": _frame_count(spec), "macro": spec,
                     "sha256": hashlib.sha256(spec.encode()).hexdigest()})
    return {"schema_version": SCHEMA_VERSION, "game_id": recipe["game_id"],
            "system": recipe["profile"]["system"], "macros": rows,
            "total_frames": sum(r["frames"] for r in rows)}


def validate_recipe(recipe: dict) -> list[str]:
    try:
        recipe = expand_recipe(recipe)
    except SchemaError as exc:
        return [str(exc)]
    errors = []
    if recipe.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version 必须为 {SCHEMA_VERSION}")
    if not recipe.get("game_id"):
        errors.append("game_id 必填")
    profile = recipe.get("profile")
    if not isinstance(profile, dict):
        return errors + ["profile 必须为对象"]
    for key in ("rom", "rom_sha1", "bizhawk", "core", "system", "domain"):
        if not str(profile.get(key) or "").strip():
            errors.append(f"profile.{key} 必填")
    for key in ("state_package", "window"):
        if key in profile and not isinstance(profile[key], dict):
            errors.append(f"profile.{key} 必须为对象")
    if "isolated_slot" in profile and not isinstance(profile["isolated_slot"], bool):
        errors.append("profile.isolated_slot 必须为布尔值")
    macros = recipe.get("macros") or {}
    if not isinstance(macros, dict):
        errors.append("macros 必须为对象")
    else:
        for name in macros:
            if not _safe(name) or _safe(name) != name:
                errors.append(f"宏名须为小写 ASCII: {name!r}")
            try:
                _macro(recipe, macros[name])
            except (SchemaError, KeyError, TypeError, ValueError) as exc:
                errors.append(f"宏 {name}: {exc}")
    prepare = recipe.get("prepare") or []
    prepare_ids = set()
    if not isinstance(prepare, list):
        errors.append("prepare 必须为列表")
        prepare = []
    for pi, step in enumerate(prepare):
        label = f"prepare[{pi}]"
        name = step.get("id") if isinstance(step, dict) else None
        if not name or _safe(name) != name or name in prepare_ids:
            errors.append(f"{label}.id 非法或重复: {name!r}")
            continue
        prepare_ids.add(name)
        try:
            _macro(recipe, step.get("macro"))
        except (SchemaError, KeyError, TypeError, ValueError) as exc:
            errors.append(f"{label}: {exc}")
        if step.get("patches"):
            errors.append(f"{label} 准备阶段禁止内存补丁，必须通过真实菜单/导航形成状态")
        if not step.get("expect"):
            errors.append(f"{label} 至少一个 RAM 断言")
        for expect in step.get("expect") or []:
            try:
                address = _addr(expect["addr"])
                width = int(expect.get("width", 1))
                if width not in (1, 2, 4):
                    raise ValueError("width 必须为 1/2/4")
                if expect.get("op", "==") not in _OPS:
                    raise ValueError("op 未知")
                int(expect["value"])
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"{label}.expect: {exc}")
        screen = step.get("screen")
        if not isinstance(screen, dict):
            errors.append(f"{label}.screen 必填")
            continue
        try:
            if screen.get("reference") != "$base":
                raise ValueError("screen.reference 目前只支持 $base")
            if screen.get("relation") not in ("equal", "near", "different"):
                raise ValueError("screen.relation 非法")
            fraction = float(screen.get("max_changed_fraction", 1))
            if not 0 <= fraction <= 1:
                raise ValueError("screen.max_changed_fraction 须为 0..1")
        except (TypeError, ValueError) as exc:
            errors.append(f"{label}.screen: {exc}")
    cases = recipe.get("cases")
    if not isinstance(cases, list) or not cases:
        return errors + ["cases 必须是非空列表"]
    seen = set()
    for ci, case in enumerate(cases):
        cid = case.get("id")
        if not cid or _safe(cid) != cid or cid in seen:
            errors.append(f"cases[{ci}].id 非法或重复: {cid!r}")
            continue
        seen.add(cid)
        case_base = case.get("base_state", recipe.get("base_state", "base"))
        if prepare and case_base not in prepare_ids:
            errors.append(f"{cid}.base_state 必须引用 prepare 形成的状态: {sorted(prepare_ids)}")
        elif not prepare and (not isinstance(case_base, str) or not case_base.strip()):
            errors.append(f"{cid}.base_state 必须是非空状态名或路径")
        if case.get("kind") != "scenario":
            errors.append(f"{cid}.kind 目前只支持 scenario")
        arms = case.get("arms")
        if not isinstance(arms, list) or len(arms) < 1:
            errors.append(f"{cid}.arms 至少一个分支")
            continue
        arm_names = set()
        expect_addrs = set()
        screen_checks = 0
        for arm in arms:
            name = arm.get("name")
            if not name or _safe(name) != name or name in arm_names:
                errors.append(f"{cid} 分支名非法或重复: {name!r}")
                continue
            arm_names.add(name)
            steps = arm.get("steps")
            if not isinstance(steps, list) or not steps:
                errors.append(f"{cid}.{name}.steps 至少一步")
                continue
            for si, step in enumerate(steps):
                label = f"{cid}.{name}.steps[{si}]"
                if not any(k in step for k in ("macro", "extra", "capture_frames")):
                    errors.append(f"{label} 需要 macro/extra/capture_frames")
                try:
                    _macro(recipe, step.get("macro"))
                except (SchemaError, KeyError, TypeError, ValueError) as exc:
                    errors.append(f"{label}: {exc}")
                for patch in step.get("patches") or []:
                    if patch.get("apply", "one_shot") != "one_shot":
                        errors.append(f"{label} 校准只允许一次性补丁，拒绝逐帧掩盖消费")
                    try:
                        _addr(patch["addr"])
                        if not 0 <= int(patch["value"]) <= 255:
                            raise ValueError("value 不是字节")
                    except (KeyError, TypeError, ValueError) as exc:
                        errors.append(f"{label}.patches: {exc}")
                if "screen" in step:
                    screen_checks += 1
                    screen = step["screen"]
                    try:
                        count = _frame_count(_macro(recipe, step.get("macro"))) + int(step.get("extra", 0))
                        if count != 0:
                            raise ValueError("screen 锚点校验只允许零帧步骤")
                        if screen.get("reference") != "$base":
                            raise ValueError("screen.reference 目前只支持 $base")
                        if screen.get("relation") not in ("equal", "near", "different"):
                            raise ValueError("screen.relation 非法")
                        fraction = float(screen.get("max_changed_fraction", 1))
                        if not 0 <= fraction <= 1:
                            raise ValueError("screen.max_changed_fraction 须为 0..1")
                    except (SchemaError, TypeError, ValueError) as exc:
                        errors.append(f"{label}.screen: {exc}")
                for expect in step.get("expect") or []:
                    try:
                        address = _addr(expect["addr"])
                        width = int(expect.get("width", 1))
                        if width not in (1, 2, 4):
                            raise ValueError("width 必须为 1/2/4")
                        if expect.get("op", "==") not in _OPS:
                            raise ValueError("op 未知")
                        int(expect["value"])
                        expect_addrs.add(address)
                    except (KeyError, TypeError, ValueError) as exc:
                        errors.append(f"{label}.expect: {exc}")
        if not expect_addrs:
            errors.append(f"{cid} 至少一个 RAM 断言，禁止只凭截图宣称地址有效")
        for comparison in case.get("comparisons") or []:
            try:
                left, right = comparison["left"], comparison["right"]
                li, ri = int(comparison["left_step"]), int(comparison["right_step"])
                if left not in arm_names or right not in arm_names:
                    raise ValueError("分支不存在")
                for name, index in ((left, li), (right, ri)):
                    steps = next(a["steps"] for a in arms if a["name"] == name)
                    frames = comparison.get("frames", ["final"])
                    if not 0 <= index < len(steps):
                        raise ValueError(f"{name} 步序号越界")
                    try:
                        count = _frame_count(_macro(recipe, steps[index].get("macro"))) + int(steps[index].get("extra", 0))
                    except (SchemaError, TypeError, ValueError) as exc:
                        raise ValueError(f"{name} 步 {index} 帧数无效: {exc}") from exc
                    for frame in frames:
                        if frame != "final" and frame >= count:
                            raise ValueError(f"{name} 步 {index} 比较帧 {frame} 越界，总帧数 {count}")
                if comparison.get("relation") not in ("equal", "different"):
                    raise ValueError("relation 必须为 equal/different")
                frames = comparison.get("frames", ["final"])
                if not isinstance(frames, list) or not frames:
                    raise ValueError("frames 必须是非空列表")
                for frame in frames:
                    if frame != "final" and (not isinstance(frame, int) or frame < 0):
                        raise ValueError("frame 须为非负整数或 final")
            except (KeyError, TypeError, ValueError, StopIteration) as exc:
                errors.append(f"{cid}.comparisons: {exc}")
        for claim in case.get("claims") or []:
            try:
                address = _addr(claim["addr"])
                if address not in expect_addrs:
                    raise ValueError("claim 地址必须在本 case 的 expect 中出现")
                if claim.get("level") not in ("menu", "gameplay", "consumption"):
                    raise ValueError("claim.level 非法")
                if claim.get("level") in ("gameplay", "consumption") and not screen_checks:
                    raise ValueError("玩法/消费 claim 必须有 screen 基态锚点校验")
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"{cid}.claims: {exc}")
    return errors


def load_recipe(path) -> tuple[dict, dict]:
    path = Path(path)
    recipe = expand_recipe(_json(path))
    errors = validate_recipe(recipe)
    if errors:
        raise SchemaError("配方无效:\n- " + "\n- ".join(errors))
    return recipe, compile_recipe(recipe)


def _package_state(profile: dict, name: str) -> Path:
    ref = profile.get("state_package")
    if not ref:
        path = Path(str(name))
        if not path.is_file():
            raise SchemaError(f"状态文件不存在: {path}")
        return path
    doc = SR.load(ref["game_id"], ref["profile_id"], ref["revision"])
    if doc["status"] not in SR.CONSUMABLE + ("candidate", "resources_ready"):
        raise SchemaError(f"状态包不可用于校准: {doc['status']}")
    entry = (doc.get("states") or {}).get(name)
    if not entry:
        raise SchemaError(f"状态包无 {name!r}")
    path = SR.package_dir(ref["game_id"], ref["profile_id"], ref["revision"]) / entry["path"]
    if not path.is_file() or sha256_file(str(path)) != entry["sha256"]:
        raise SchemaError(f"状态实物缺失或哈希不符: {path}")
    return path


def resolve_profile(recipe: dict) -> dict:
    profile = dict(recipe["profile"])
    rom, bizhawk = Path(profile["rom"]), Path(profile["bizhawk"])
    if not rom.is_file():
        raise SchemaError(f"ROM 不存在: {rom}")
    got = SJ.sha1_file(rom).upper()
    if got != str(profile["rom_sha1"]).upper():
        raise SchemaError(f"ROM SHA1 不符: 期望 {profile['rom_sha1']} 实际 {got}")
    if not (bizhawk / "EmuHawk.exe").is_file():
        raise SchemaError(f"BizHawk 不存在: {bizhawk}")
    base = _package_state(profile, recipe.get("base_state", "base"))
    window = profile.get("window") or {"start": 0, "length": 2048}
    start, length = _addr(window["start"]), int(window["length"])
    if start < 0 or not 1 <= length <= 0x10000:
        raise SchemaError("window 须满足 start>=0 且 1<=length<=65536")
    case_bases = {}
    for case in recipe.get("cases") or []:
        if recipe.get("prepare"):
            continue
        name = case.get("base_state", recipe.get("base_state", "base"))
        case_bases[case["id"]] = base if name == recipe.get("base_state", "base") else _package_state(profile, name)
    profile.update(rom_path=rom, bizhawk_path=bizhawk, base_state_path=base,
                   case_base_state_paths=case_bases,
                   window_start=start, window_length=length, rom_sha1_actual=got)
    return profile


def cache_key(recipe: dict, profile: dict) -> str:
    h = hashlib.sha256()
    for name, path in (("ram_calibration.py", HERE / "ram_calibration.py"),
                       ("statejump.py", HERE / "statejump.py"),
                       ("tas_replay.py", HERE.parent / "tas_replay.py")):
        h.update(name.encode())
        h.update(SJ.sha1_file(path).encode())
    h.update(json.dumps(recipe, sort_keys=True, ensure_ascii=False).encode())
    h.update(profile["rom_sha1_actual"].encode())
    state_paths = [profile["bizhawk_path"] / "EmuHawk.exe", profile["base_state_path"],
                   *(profile.get("case_base_state_paths") or {}).values()]
    for path in dict.fromkeys(Path(path) for path in state_paths):
        h.update(sha256_file(str(path)).encode())
    if profile["system"].upper() == "GBA":
        dll = profile["bizhawk_path"] / "dll" / "mgba.dll"
        h.update(sha256_file(str(dll)).encode())
    ref = profile.get("state_package")
    if ref:
        h.update(json.dumps(SR.load(ref["game_id"], ref["profile_id"], ref["revision"]),
                            sort_keys=True, ensure_ascii=False).encode())
    return h.hexdigest()


def read_width(sess, address: int, width: int, domain: str) -> int:
    return sum(sess.read(address + i, domain) << (8 * i) for i in range(width))


def _check_expect(ram: bytes, expects, window_start: int) -> list[dict]:
    rows = []
    for expect in expects or []:
        address, width = _addr(expect["addr"]), int(expect.get("width", 1))
        offset = address - window_start
        if offset < 0 or offset + width > len(ram):
            raise SchemaError(f"expect 地址不在原子 RAM 窗口内: {address:#x}")
        got = int.from_bytes(ram[offset:offset + width], "little")
        want, op = int(expect["value"]), expect.get("op", "==")
        rows.append({"addr": address, "width": width, "op": op, "want": want,
                     "got": got, "pass": bool(_OPS[op](got, want))})
    return rows


def pixel_metrics(left: Path, right: Path) -> dict:
    with Image.open(left) as a, Image.open(right) as b:
        aa, bb = a.convert("RGB"), b.convert("RGB")
        if aa.size != bb.size:
            return {"changed_pixels": None, "equal": False, "error": "画面尺寸不同"}
        diff = ImageChops.difference(aa, bb).convert("L")
        histogram = diff.histogram()
        changed = aa.width * aa.height - histogram[0]
        return {"changed_pixels": changed, "changed_fraction": changed / (aa.width * aa.height),
                "total_pixels": aa.width * aa.height, "equal": changed == 0,
                "bbox": diff.point(lambda v: 255 if v else 0).getbbox()}


def _screen_result(reference: Path, shot: Path, screen: dict) -> dict:
    metrics = pixel_metrics(reference, shot)
    relation = screen["relation"]
    ok = metrics["equal"] if relation == "equal" else (
        metrics["changed_fraction"] <= float(screen.get("max_changed_fraction", 1))
        if relation == "near" else not metrics["equal"])
    return {"reference": str(reference), "relation": relation,
            "max_changed_fraction": screen.get("max_changed_fraction"),
            "pass": bool(ok), **metrics}


def _shot_for(step_row: dict, frame) -> Path:
    if frame == "final":
        return Path(step_row["shot"])
    return Path(step_row["frames_dir"]) / f"f{int(frame):04d}.png"


@contextlib.contextmanager
def _emulator_session(profile: dict, work_dir: Path):
    if profile.get("isolated_slot"):
        from .parallel import EmulatorSlots
        slots = EmulatorSlots(workers=1, system=profile["system"], core=profile["core"])
        with slots.lease(profile["bizhawk_path"], system=profile["system"], core=profile["core"]) as slot:
            with SJ.StateSession(str(profile["rom_path"]), str(slot.path),
                                 core=profile["core"], system=profile["system"],
                                 work=str(work_dir)) as sess:
                yield sess, {"root": str(slots.root), "bizhawk": str(slot.path),
                             "system": slot.system, "core": slot.core}
    else:
        with SJ.StateSession(str(profile["rom_path"]), str(profile["bizhawk_path"]),
                             core=profile["core"], system=profile["system"],
                             work=str(work_dir)) as sess:
            yield sess, None


def _execute(recipe: dict, case: dict, profile: dict, out_dir: Path,
             work_dir: Path, mode: str, force: bool = False) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc).isoformat()
    report = {"schema_version": SCHEMA_VERSION, "mode": mode,
              "game_id": recipe["game_id"], "case_id": case["id"],
              "rom_sha1": profile["rom_sha1_actual"], "core": profile["core"],
              "system": profile["system"], "domain": profile["domain"],
              "recipe": recipe, "base_state": str(profile["base_state_path"]),
              "cache_key": cache_key(recipe, profile),
              "capture_provenance": {
                  "run_id": uuid.uuid4().hex,
                  "process_id": os.getpid(),
                  "started_at": started_at,
                  "force": bool(force),
                  "out_dir": str(out_dir.resolve()),
                  "implementation_sha256": sha256_file(str(HERE / "ram_calibration.py")),
              },
              "arms": {}, "preparation": [], "evidence": [str(profile["base_state_path"])]}
    rows_by_arm = {}
    with _emulator_session(profile, work_dir) as (sess, slot_info):
        report["emulator_slot"] = slot_info
        root_ascii = sess.use_state(str(profile["base_state_path"]), name=f"{case['id']}_root")
        prepared = {}
        if recipe.get("prepare"):
            root_anchor = out_dir / f"{case['id']}_prepare_base.png"
            sess.attempt(root_ascii, spec="-", extra=0, shot=str(root_anchor))
            report["evidence"].append(str(root_anchor))
            previous = root_ascii
            for index, step in enumerate(recipe["prepare"]):
                stem = f"{case['id']}_prepare_{step['id']}"
                shot, saved = out_dir / f"{stem}.png", out_dir / f"{stem}.state"
                ram = out_dir / f"{stem}.bin"
                spec = _macro(recipe, step.get("macro"))
                extra = int(step.get("extra", 0))
                result = sess.attempt(str(previous), spec=spec, extra=extra,
                                      shot=str(shot), save=str(saved), ram=str(ram),
                                      probe_domain=profile["domain"],
                                      ram_start=profile["window_start"],
                                      ram_length=profile["window_length"])
                if ram.stat().st_size != profile["window_length"]:
                    raise RuntimeError(f"准备阶段 RAM 窗口长度不符: {ram}")
                row = {"id": step["id"], "index": index, "macro": spec,
                       "frames": _frame_count(spec) + extra, "attempt": result,
                       "shot": str(shot), "state": str(saved), "ram": str(ram),
                       "expect": _check_expect(ram.read_bytes(), step["expect"], profile["window_start"]),
                       "screen": _screen_result(root_anchor, shot, step["screen"]),
                       "actual_core": SJ.saved_core_type(saved)}
                report["preparation"].append(row)
                report["evidence"].extend((str(root_anchor), str(shot), str(saved), str(ram)))
                if not all(item["pass"] for item in row["expect"]) or not row["screen"]["pass"]:
                    raise RuntimeError(f"准备阶段未通过: {step['id']}")
                prepared[step["id"]] = saved
                previous = saved
        case_state = case.get("base_state", recipe.get("base_state", "base"))
        case_source = prepared.get(case_state)
        if case_source is None:
            case_source = (profile.get("case_base_state_paths") or {}).get(case["id"])
        if case_source is None:
            case_source = _package_state(profile, case_state)
        report["base_state"] = {"name": case_state, "path": str(case_source)}
        base_ascii = sess.use_state(str(case_source), name=f"{case['id']}_base")
        base_anchor = out_dir / f"{case['id']}_base_anchor.png"
        sess.attempt(base_ascii, spec="-", extra=0, shot=str(base_anchor))
        report["evidence"].append(str(base_anchor))
        default_state = case_source
        for arm in case["arms"]:
            name = arm["name"]
            previous = None
            step_rows = []
            for index, step in enumerate(arm["steps"]):
                source = step.get("state") or previous or default_state
                if source == "$previous":
                    if previous is None:
                        raise SchemaError(f"{case['id']}.{name}.steps[{index}] 无前一步可引用")
                    source = previous
                elif isinstance(source, str) and not Path(source).is_absolute() and profile.get("state_package"):
                    source = _package_state(profile, source)
                source = Path(source)
                if not source.is_file():
                    raise SchemaError(f"状态不存在: {source}")
                ascii_state = sess.use_state(str(source), name=f"{case['id']}_{name}_{index}")
                stem = f"{case['id']}_{name}_s{index:02d}"
                shot = out_dir / f"{stem}.png"
                saved = out_dir / f"{stem}.state"
                spec = _macro(recipe, step.get("macro"))
                extra = int(step.get("extra", 0))
                if extra < 0:
                    raise SchemaError("extra 不能为负")
                patches = [
                    {**patch, "domain": patch.get("domain", profile["domain"])}
                    for patch in step.get("patches") or []
                ]
                attempt_source = ascii_state
                ram = out_dir / f"{stem}.bin"
                result = sess.attempt(str(attempt_source), spec=spec, extra=extra,
                                      shot=str(shot), save=str(saved), ram=str(ram),
                                      probe_domain=profile["domain"],
                                      ram_start=profile["window_start"],
                                      ram_length=profile["window_length"],
                                      patches=patches)
                if ram.stat().st_size != profile["window_length"]:
                    raise RuntimeError(f"RAM 窗口长度不符: {ram} {ram.stat().st_size}")
                row = {"index": index, "source_state": str(source), "attempt_state": str(attempt_source),
                       "patches": patches, "macro": spec,
                       "frames": _frame_count(spec) + extra, "attempt": result,
                       "shot": str(shot), "state": str(saved), "ram": str(ram),
                       "expect": _check_expect(ram.read_bytes(), step.get("expect"), profile["window_start"]),
                       "actual_core": SJ.saved_core_type(saved)}
                if "screen" in step:
                    row["screen"] = _screen_result(base_anchor, shot, step["screen"])
                    report["evidence"].extend((str(base_anchor), str(shot)))
                report["evidence"].extend((str(shot), str(saved), str(ram)))
                if "capture_frames" in step:
                    frames = int(step["capture_frames"])
                    if frames < 1 or frames != row["frames"]:
                        raise SchemaError(f"capture_frames 须等于 macro+extra 帧数: {frames} != {row['frames']}")
                    frames_dir = out_dir / f"{stem}_frames"
                    count = sess.dump(str(frames_dir), spec=spec, extra=extra,
                                      state=str(attempt_source))
                    if count != frames:
                        raise RuntimeError(f"{stem} 采集 {count} 帧，配方要求 {frames} 帧")
                    row.update(frames_dir=str(frames_dir), captured_frames=count)
                step_rows.append(row)
                previous = saved
            rows_by_arm[name] = step_rows
            report["arms"][name] = {"steps": step_rows}
        comparisons = []
        if mode in ("verify", "scout"):
            for comparison in case.get("comparisons") or []:
                left = rows_by_arm[comparison["left"]][comparison["left_step"]]
                right = rows_by_arm[comparison["right"]][comparison["right_step"]]
                frame_rows = []
                for frame in comparison.get("frames", ["final"]):
                    lp, rp = _shot_for(left, frame), _shot_for(right, frame)
                    metrics = pixel_metrics(lp, rp)
                    ok = metrics["equal"] if comparison["relation"] == "equal" else not metrics["equal"]
                    frame_rows.append({"frame": frame, "left": str(lp), "right": str(rp),
                                       "pass": bool(ok), **metrics})
                    report["evidence"].extend((str(lp), str(rp)))
                comparisons.append({"left": comparison["left"], "right": comparison["right"],
                                    "relation": comparison["relation"], "frames": frame_rows,
                                    "pass": all(r["pass"] for r in frame_rows)})
        if mode == "verify":
            report["comparisons"] = comparisons
            report["checks"] = {
                "preparation": all(all(item["pass"] for item in step["expect"]) and step["screen"]["pass"]
                                   for step in report["preparation"]),
                "expectations": all(e["pass"] for arm in report["arms"].values()
                                    for step in arm["steps"] for e in step["expect"]),
                "comparisons": all(c["pass"] for c in comparisons),
                "frame_counts": all(step.get("captured_frames", step["frames"]) == step["frames"]
                                    for arm in report["arms"].values() for step in arm["steps"]),
                "screen_anchors": all(step["screen"]["pass"] for arm in report["arms"].values()
                                      for step in arm["steps"] if "screen" in step),
                "gba_core": profile["system"].upper() != "GBA" or all(
                    step["actual_core"] == SJ.GBA_MGBA_CORE_TYPE
                    for step in [*report["preparation"],
                                 *(row for arm in report["arms"].values() for row in arm["steps"])]),
            }
            report["status"] = "pass" if all(report["checks"].values()) else "failed"
            report["verified_fields"] = [
                {**claim, "case_id": case["id"]}
                for claim in case.get("claims") or []
            ] if report["status"] == "pass" else []
        else:
            report["candidate_comparisons"] = comparisons
            final = {name: Path(rows[-1]["ram"]) for name, rows in rows_by_arm.items()}
            names = list(final)
            diffs = []
            for i, left in enumerate(names):
                for right in names[i + 1:]:
                    a, b = final[left].read_bytes(), final[right].read_bytes()
                    changed = [profile["window_start"] + off for off, (x, y) in enumerate(zip(a, b)) if x != y]
                    diffs.append({"left": left, "right": right, "changed_bytes": len(changed),
                                  "addresses": [f"0x{x:X}" for x in changed[:512]],
                                  "truncated": len(changed) > 512})
            report["ram_diffs"] = diffs
            report["status"] = "candidates_only"
            report["verified_fields"] = []
    report["capture_provenance"]["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["evidence"] = sorted(set(report["evidence"]))
    report_path = out_dir / "report.json"
    _write_json(report_path, report)
    _bind_capture_manifests(report_path, report)
    return report


def _bind_capture_manifests(report_path: Path, report: dict) -> None:
    report_path = report_path.resolve()
    report_sha = sha256_file(str(report_path))
    provenance = report["capture_provenance"]
    for arm_name, arm in report["arms"].items():
        for step in arm["steps"]:
            frames_dir = step.get("frames_dir")
            if not frames_dir:
                continue
            root = Path(frames_dir)
            frames = [{"destination_frame": int(path.stem[1:]),
                       "sha256": sha256_file(str(path))}
                      for path in sorted(root.glob("f*.png"))]
            manifest = {
                "schema_version": "detector_capture/1.0",
                "capture_id": f"{report['case_id']}:{arm_name}:{step['index']}",
                "run_id": provenance["run_id"],
                "process_id": provenance["process_id"],
                "started_at": provenance["started_at"],
                "finished_at": provenance["finished_at"],
                "force": provenance["force"],
                "source_report": str(report_path),
                "source_report_sha256": report_sha,
                "source_report_status": report["status"],
                "game_id": report["game_id"],
                "rom_sha1": report["rom_sha1"],
                "system": report["system"],
                "core": report["core"],
                "base_state": report["base_state"],
                "emulator_slot": report.get("emulator_slot"),
                "arm": arm_name,
                "step_index": step["index"],
                "frames_dir": str(root.resolve()),
                "captured_frames": step["captured_frames"],
                "frames": frames,
            }
            _write_json(root / "capture_manifest.json", manifest)


def run_recipe(recipe_path, case_id: str, out_dir: Path, mode="verify", force=False) -> dict:
    recipe, _ = load_recipe(recipe_path)
    case = next((c for c in recipe["cases"] if c["id"] == case_id), None)
    if not case:
        raise SchemaError(f"无 case: {case_id}")
    profile = resolve_profile(recipe)
    key = cache_key(recipe, profile)
    out_dir = Path(out_dir)
    report_path = out_dir / "report.json"
    wanted_status = "pass" if mode == "verify" else "candidates_only"
    if not force and report_path.is_file():
        old = _json(report_path)
        if (old.get("cache_key") == key and old.get("status") == wanted_status
                and all(Path(path).is_file() for path in old.get("evidence") or [])):
            return {**old, "reused": True}
    work_key = hashlib.sha256(str(out_dir.resolve()).encode()).hexdigest()[:16]
    work = SCRATCH_ROOT / work_key
    if force and work.exists():
        shutil.rmtree(work)
    return _execute(recipe, case, profile, out_dir, work, mode, force=force)


def run_many(recipe_path, out_dir: Path, mode="verify", force=False, workers=1) -> dict:
    if type(workers) is not int or workers < 1:
        raise SchemaError("workers 须为正整数")
    recipe, _ = load_recipe(recipe_path)
    out_dir = Path(out_dir)

    def run_one(case_id):
        try:
            report = run_recipe(recipe_path, case_id, out_dir / case_id, mode=mode, force=force)
            return {"case_id": case_id, "status": report["status"],
                    "reused": bool(report.get("reused")),
                    "report": str(out_dir / case_id / "report.json")}
        except Exception as exc:
            return {"case_id": case_id, "status": "error",
                    "error": f"{type(exc).__name__}: {exc}"}

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(run_one, [case["id"] for case in recipe["cases"]]))
    counts = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {"schema_version": SCHEMA_VERSION, "mode": mode,
            "recipe": str(Path(recipe_path)), "out": str(out_dir), "workers": workers,
            "total": len(rows), "counts": counts, "cases": rows}


def archive_report(report_path, dest: Path) -> dict:
    report_path, dest = Path(report_path), Path(dest)
    report = _json(report_path)
    if dest.exists() and any(dest.iterdir()):
        raise SchemaError(f"归档目录非空，拒绝覆盖: {dest}")
    sources = [Path(source) for source in report.get("evidence") or []]
    for source in sources:
        if not source.is_file():
            raise SchemaError(f"证据缺失: {source}")
    dest.mkdir(parents=True, exist_ok=True)
    entries = []
    for index, source in enumerate(sources):
        target = dest / "evidence" / f"{index:03d}_{source.name}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        entries.append({"source": str(source), "path": f"evidence/{target.name}",
                        "sha256": sha256_file(str(target)), "bytes": target.stat().st_size})
    shutil.copyfile(report_path, dest / "report.json")
    recipe = report.get("recipe")
    if recipe is not None:
        _write_json(dest / "recipe.json", recipe)
    manifest = {"schema_version": SCHEMA_VERSION, "report": str(report_path),
                "report_sha256": sha256_file(str(report_path)), "status": report.get("status"),
                "mode": report.get("mode"), "game_id": report.get("game_id"),
                "case_id": report.get("case_id"), "cache_key": report.get("cache_key"),
                "recipe_sha256": sha256_file(str(dest / "recipe.json")) if recipe is not None else None,
                "verified_fields": report.get("verified_fields") or [], "evidence": entries}
    _write_json(dest / "manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("validate", "compile", "scout", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--recipe", required=True)
        if name in ("scout", "verify"):
            target = p.add_mutually_exclusive_group(required=True)
            target.add_argument("--case")
            target.add_argument("--all", action="store_true")
            p.add_argument("--out", required=True)
            p.add_argument("--workers", type=int, default=1)
            p.add_argument("--force", action="store_true")
    p = sub.add_parser("archive")
    p.add_argument("--report", required=True)
    p.add_argument("--dest", required=True)
    args = parser.parse_args()
    if args.cmd in ("validate", "compile"):
        recipe, compiled = load_recipe(args.recipe)
        print(json.dumps(compiled if args.cmd == "compile" else
                         {"status": "valid", "cases": [c["id"] for c in recipe["cases"]]},
                         ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "archive":
        result = archive_report(args.report, Path(args.dest))
        print(json.dumps({"status": "archived", "dest": str(Path(args.dest)),
                          "evidence_files": len(result["evidence"])}, ensure_ascii=False))
        return 0
    mode = "verify" if args.cmd == "verify" else "scout"
    if args.all:
        if args.workers < 1:
            parser.error("--workers 须为正整数")
        result = run_many(args.recipe, Path(args.out), mode=mode,
                          force=args.force, workers=args.workers)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        ok = all(row["status"] in ("pass", "candidates_only") for row in result["cases"])
        return 0 if ok else 2
    result = run_recipe(args.recipe, args.case, Path(args.out), mode=mode, force=args.force)
    print(json.dumps({"status": result["status"], "case": result["case_id"],
                      "reused": result.get("reused", False), "report": str(Path(args.out) / "report.json"),
                      "verified_fields": result.get("verified_fields") or []},
                     ensure_ascii=False, indent=2))
    return 0 if result["status"] in ("pass", "candidates_only") else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""RAM 校准流水线离线自检：不启动模拟器、不修改生产包。"""
import contextlib
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageDraw

from . import ram_calibration as RC
from . import statejump as SJ
from .schema import SchemaError

RESULTS = []


def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition)))
    print(f"{'PASS' if condition else 'FAIL'} {name}" + (f" | {detail}" if detail and not condition else ""))


def recipe():
    return {
        "schema_version": RC.SCHEMA_VERSION,
        "game_id": "synthetic",
        "profile": {"rom": "F:/tmp/game.nes", "rom_sha1": "00", "bizhawk": "F:/tmp/bh",
                    "core": "NesHawk", "system": "NES", "domain": "RAM",
                    "window": {"start": 0, "length": 2048}},
        "macros": {"attack": "B,,,,"},
        "cases": [{"id": "effect", "kind": "scenario",
                   "arms": [
                       {"name": "positive", "steps": [
                        {"macro": "-", "extra": 0, "screen": {"reference": "$base", "relation": "near", "max_changed_fraction": 0.01},
                         "expect": [{"addr": 170, "value": 1}]},
                        {"state": "$previous", "macro": "@attack", "capture_frames": 5,
                         "expect": [{"addr": 170, "value": 1}]}]},
                       {"name": "negative", "steps": [
                        {"macro": "-", "extra": 0, "screen": {"reference": "$base", "relation": "near", "max_changed_fraction": 0.01},
                         "expect": [{"addr": 170, "value": 0}]},
                        {"state": "$previous", "macro": "-", "extra": 5,
                         "expect": [{"addr": 170, "value": 0}]}]}],
                   "comparisons": [{"left": "positive", "right": "negative", "left_step": 1,
                                   "right_step": 1, "relation": "different", "frames": [4]}],
                   "claims": [{"name": "weapon", "addr": 170, "width": 1, "level": "gameplay"}]}],
    }


def t_validation():
    doc = recipe()
    check("R1 合法配方通过", RC.validate_recipe(doc) == [])
    compiled = RC.compile_recipe(doc)
    check("R2 命名宏展开且帧数精确", compiled["macros"][0]["macro"] == "B,,,," and
          compiled["macros"][0]["frames"] == 5)
    bad = recipe()
    for arm in bad["cases"][0]["arms"]:
        for step in arm["steps"]:
            step["expect"] = []
    check("R3 无 RAM 断言拒绝验收", any("至少一个 RAM 断言" in e for e in RC.validate_recipe(bad)))
    bad = recipe()
    bad["cases"][0]["claims"][0]["addr"] = 171
    check("R4 claim 外推地址拒绝", any("claim 地址" in e for e in RC.validate_recipe(bad)))
    bad = recipe()
    bad["cases"][0]["arms"][0]["steps"][0]["patches"] = [{"addr": 170, "value": 1, "apply": "per_frame"}]
    check("R5 逐帧补丁拒绝掩盖消费", any("一次性补丁" in e for e in RC.validate_recipe(bad)))
    bad = recipe()
    bad["cases"][0]["comparisons"][0]["frames"] = [5]
    check("R6 越界比较帧拒绝", any("比较帧" in e for e in RC.validate_recipe(bad)))
    bad = recipe()
    for arm in bad["cases"][0]["arms"]:
        arm["steps"][0].pop("screen")
    check("R13 玩法 claim 缺少画面锚点拒绝", any("screen 基态锚点" in e for e in RC.validate_recipe(bad)))

    good = recipe()
    good["prepare"] = [{"id": "ready", "macro": "@attack",
                        "expect": [{"addr": 170, "value": 1}],
                        "screen": {"reference": "$base", "relation": "different"}}]
    good["cases"][0]["base_state"] = "ready"
    check("R24 菜单/导航准备阶段允许非零帧画面锚点", RC.validate_recipe(good) == [])
    bad = json.loads(json.dumps(good))
    bad["prepare"][0]["patches"] = [{"addr": 170, "value": 1}]
    check("R25 准备阶段禁止补丁冒充菜单装备", any("准备阶段禁止内存补丁" in e for e in RC.validate_recipe(bad)))
    bad = json.loads(json.dumps(good))
    bad["cases"][0]["base_state"] = "missing"
    check("R26 case 必须引用实际准备状态", any("必须引用 prepare" in e for e in RC.validate_recipe(bad)))

    multi_scene = recipe()
    multi_scene["cases"][0]["base_state"] = "alternate_scene"
    check("R27 无 prepare 时 case 可引用独立场景状态", RC.validate_recipe(multi_scene) == [])
    bad = json.loads(json.dumps(multi_scene))
    bad["cases"][0]["base_state"] = ""
    check("R28 独立场景状态名不允许为空", any("base_state 必须是非空" in e for e in RC.validate_recipe(bad)))

    isolated = recipe()
    isolated["profile"]["isolated_slot"] = True
    check("R33 隔离槽配置合法", RC.validate_recipe(isolated) == [])
    bad = json.loads(json.dumps(isolated))
    bad["profile"]["isolated_slot"] = "yes"
    check("R34 隔离槽配置拒绝非布尔值", any("isolated_slot 必须为布尔值" in e for e in RC.validate_recipe(bad)))

    matrix = recipe()
    template = matrix["cases"][0]
    template["arms"][0]["name"] = "positive_{value}"
    template["arms"][0]["steps"][0]["patches"] = [{"addr": 170, "value": "{value}"}]
    template["arms"][0]["steps"][0]["expect"][0]["value"] = "{value}"
    template["arms"][0]["steps"][1]["expect"][0]["value"] = "{value}"
    template["comparisons"][0]["left"] = "positive_{value}"
    matrix.pop("cases")
    matrix["matrix"] = {"case_id": "effect_{value}", "values": [2, 4],
                        "template": template}
    expanded = RC.expand_recipe(matrix)
    check("R37 矩阵配方按 ID 展开案例/分支/补丁/断言",
          [case["id"] for case in expanded["cases"]] == ["effect_2", "effect_4"]
          and expanded["cases"][0]["arms"][0]["name"] == "positive_2"
          and expanded["cases"][1]["arms"][0]["steps"][0]["patches"][0]["value"] == 4
          and expanded["cases"][1]["arms"][0]["steps"][1]["expect"][0]["value"] == 4
          and RC.validate_recipe(matrix) == [])
    bad = json.loads(json.dumps(matrix))
    bad["matrix"]["values"] = [2, 2]
    check("R38 矩阵拒绝重复值", any("不允许重复" in e for e in RC.validate_recipe(bad)))
    bad = json.loads(json.dumps(matrix))
    bad["matrix"]["case_id"] = "effect"
    check("R39 矩阵案例名必须含值占位符", any("必须包含 {value}" in e for e in RC.validate_recipe(bad)))


def t_expect():
    rows = RC._check_expect(bytes([1, 2, 3, 4, 5, 0]), [
        {"addr": 0, "value": 1},
        {"addr": 1, "width": 2, "value": 770},
        {"addr": 1, "width": 2, "op": ">", "value": 1000},
        {"addr": 5, "op": "==", "value": 0},
    ], 0)
    check("R7 小端多字节与比较符正确", [r["got"] for r in rows] == [1, 770, 770, 0] and
          [r["pass"] for r in rows] == [True, True, False, True])


def t_pixels():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        a, b = root / "a.png", root / "b.png"
        Image.new("RGB", (64, 48), "black").save(a)
        Image.new("RGB", (64, 48), "black").save(b)
        check("R8 相同像素判定 equal", RC.pixel_metrics(a, b)["equal"])
        image = Image.new("RGB", (64, 48), "black")
        ImageDraw.Draw(image).rectangle((10, 10, 20, 20), fill="white")
        image.save(b)
        metrics = RC.pixel_metrics(a, b)
        check("R9 像素差异计数与包围盒正确", metrics["changed_pixels"] == 121 and
              metrics["changed_fraction"] == 121 / 3072 and
              metrics["bbox"] == (10, 10, 21, 21) and not metrics["equal"])
        Image.new("RGB", (32, 48), "black").save(b)
        check("R10 尺寸不同不误判相同", RC.pixel_metrics(a, b)["error"] == "画面尺寸不同")


def t_protocol():
    kw = {"state": "C:/x.state", "spec": "-", "extra": 0, "ram": "C:/x.bin",
          "ram_start": 0x13200, "ram_length": 0x600, "platform": "GBA",
          "patches": [{"addr": 170, "value": 3, "domain": "System Bus"}]}
    args = SJ._v_attempt(kw)
    check("R11 attempt RAM 窗口与一次性补丁使用独立参数", args[-3:] == ["78336", "1536", "170:3@System%20Bus"] and
          len(args) == 13, str(args))
    wire = SJ.format_command(1, "attempt", **kw).split()
    check("R15 线协议 p13/p14/p15 位置精确", wire[12:15] == ["78336", "1536", "170:3@System%20Bus"], str(wire))
    domain_args = SJ._v_attempt({**kw, "probe_domain": "EWRAM"})
    check("R31 RAM-only attempt 在 p10 传递内存域", domain_args[7] == "EWRAM" and
          domain_args[10:13] == ["78336", "1536", "170:3@System%20Bus"], str(domain_args))
    captured = {}
    session = object.__new__(SJ.StateSession)
    session.platform = "GBA"
    session.command = lambda op, **params: captured.update(op=op, **params) or {"ok": True}
    session._check_domain_range = lambda *args: None
    session.attempt("C:/x.state", ram="C:/x.bin", ram_start=0x13200,
                    ram_length=0x200, probe_domain="EWRAM")
    check("R32 StateSession.attempt 保留 RAM-only 内存域", captured.get("probe_domain") == "EWRAM",
          str(captured))
    try:
        SJ._v_attempt({**kw, "patches": [{"addr": 170, "value": 3, "apply": "per_frame"}]})
        rejected = False
    except SchemaError:
        rejected = True
    check("R14 attempt 拒绝逐帧补丁", rejected)
    try:
        SJ._v_attempt({**kw, "ram_length": 0})
        rejected = False
    except SchemaError:
        rejected = True
    check("R12 零长度 RAM 窗口拒绝", rejected)


def t_cache_archive():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        emu = root / "emu"
        (emu / "dll").mkdir(parents=True)
        (emu / "EmuHawk.exe").write_bytes(b"emuhawk")
        (emu / "dll" / "mgba.dll").write_bytes(b"mgba")
        state = root / "base.state"
        state.write_bytes(b"state")
        doc = recipe()
        profile = {"bizhawk_path": emu, "base_state_path": state,
                   "rom_sha1_actual": "00", "system": "NES"}
        key = RC.cache_key(doc, profile)
        check("R16 缓存键同输入稳定", key == RC.cache_key(doc, profile))
        profile["system"] = "GBA"
        check("R18 GBA 核心 DLL 纳入缓存键", RC.cache_key(doc, profile) != key)
        gba_key = RC.cache_key(doc, profile)
        doc["macros"]["attack"] = "B,,,"
        check("R17 宏变化使缓存键失效", gba_key != RC.cache_key(doc, profile))
        dll_key = RC.cache_key(doc, profile)
        (emu / "dll" / "mgba.dll").write_bytes(b"mgba-new")
        check("R19 GBA 核心 DLL 变化使缓存键失效", RC.cache_key(doc, profile) != dll_key)
        doc["cases"][0]["base_state"] = "alternate_scene"
        alternate = root / "alternate.state"
        alternate.write_bytes(b"alternate")
        profile["case_base_state_paths"] = {"effect": alternate}
        alternate_key = RC.cache_key(doc, profile)
        alternate.write_bytes(b"alternate-new")
        check("R29 case 独立基态变化使缓存键失效", RC.cache_key(doc, profile) != alternate_key)
        profile["state_package"] = {"game_id": "g", "profile_id": "p", "revision": "r"}
        with patch.object(RC.SR, "load", return_value={"status": "state_verified"}):
            package_key = RC.cache_key(doc, profile)
        with patch.object(RC.SR, "load", return_value={"status": "state_verified", "revision": 2}):
            check("R20 状态包元数据纳入缓存键", RC.cache_key(doc, profile) != package_key)

        protocol_profile = {k: v for k, v in profile.items() if k != "state_package"}
        protocol_key = RC.cache_key(doc, protocol_profile)
        real_sha1 = RC.SJ.sha1_file
        invalidated = []
        for source in ("statejump.py", "tas_replay.py"):
            with patch.object(RC.SJ, "sha1_file", side_effect=lambda path, source=source:
                              ("0" * 40 if Path(path).name == source else real_sha1(path))):
                invalidated.append(RC.cache_key(doc, protocol_profile) != protocol_key)
        check("R36 协议与 Lua 模板源码变化使缓存失效", all(invalidated), str(invalidated))

        a, b = root / "a.png", root / "b.bin"
        Image.new("RGB", (8, 8), "black").save(a)
        b.write_bytes(bytes(range(16)))
        report_path = root / "report.json"
        report = {"schema_version": RC.SCHEMA_VERSION, "mode": "verify",
                  "game_id": "synthetic", "case_id": "effect", "status": "pass",
                  "recipe": doc, "evidence": [str(a), str(b)], "verified_fields": []}
        RC._write_json(report_path, report)
        dest = root / "archive"
        manifest = RC.archive_report(report_path, dest)
        copied_report = dest / "report.json"
        copied_recipe = dest / "recipe.json"
        check("R21 归档包含原报告与完整配方", copied_report.read_bytes() == report_path.read_bytes()
              and copied_recipe.is_file() and RC._json(copied_recipe) == doc)
        check("R22 归档 SHA256 与实物一致", manifest["report_sha256"] == RC.sha256_file(str(copied_report))
              and manifest["recipe_sha256"] == RC.sha256_file(str(copied_recipe))
              and all(row["sha256"] == RC.sha256_file(str(dest / row["path"]))
                      for row in manifest["evidence"]))
        try:
            RC.archive_report(report_path, dest)
            rejected = False
        except SchemaError:
            rejected = True
        check("R23 非空归档拒绝覆盖", rejected)


def t_case_base_execution():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        emu = root / "emu"
        emu.mkdir()
        (emu / "EmuHawk.exe").write_bytes(b"emuhawk")
        base, alternate = root / "base.state", root / "alternate.state"
        base.write_bytes(b"base")
        alternate.write_bytes(b"alternate")
        doc = recipe()
        case = doc["cases"][0]
        case["base_state"] = "alternate_scene"
        case["arms"] = [{"name": "probe", "steps": [
            {"macro": "-", "extra": 0, "expect": [{"addr": 0, "value": 7}]}
        ]}]
        case["comparisons"] = []
        case["claims"] = []
        profile = {"rom_path": root / "game.nes", "bizhawk_path": emu,
                   "rom_sha1_actual": "00", "core": "NesHawk", "system": "NES",
                   "domain": "RAM", "base_state_path": base,
                   "case_base_state_paths": {case["id"]: alternate},
                   "window_start": 0, "window_length": 16}
        used = []

        class Session:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def use_state(self, path, name):
                used.append(Path(path))
                return str(path)

            def attempt(self, state, spec="-", extra=0, shot=None, save=None, ram=None, **kwargs):
                if shot:
                    Image.new("RGB", (8, 8), "black").save(shot)
                if save:
                    Path(save).write_bytes(b"saved")
                if ram:
                    Path(ram).write_bytes(bytes([7]) + bytes(15))
                return {"ok": True}

            def dump(self, path, spec, extra=0, state=None):
                target = Path(path)
                target.mkdir(parents=True, exist_ok=True)
                color = "white" if "positive" in str(state) else "black"
                count = (0 if spec == "-" else len(spec.split(","))) + extra
                for index in range(count):
                    Image.new("RGB", (8, 8), color).save(target / f"f{index:04d}.png")
                return count

        with patch.object(RC.SJ, "StateSession", return_value=Session()), \
             patch.object(RC.SJ, "saved_core_type", return_value="NesHawk"):
            report = RC._execute(doc, case, profile, root / "out", root / "work", "scout")
            first_used = list(used)
            scout_doc = recipe()
            scout_doc["cases"][0]["arms"][1]["steps"][1]["capture_frames"] = 5
            scout_report = RC._execute(scout_doc, scout_doc["cases"][0],
                                       {**profile, "window_start": 170},
                                       root / "scout_out", root / "scout_work", "scout")
        check("R30 生产执行按 case 独立基态加载并生成画面锚点",
              first_used == [base, alternate, alternate] and report["base_state"]["path"] == str(alternate)
              and report["status"] == "candidates_only", str(first_used))
        check("R40 scout 输出逐帧视觉候选但不产生已验证字段",
              scout_report["candidate_comparisons"][0]["frames"][0]["pass"]
              and scout_report["verified_fields"] == [], str(scout_report.get("candidate_comparisons")))


def t_isolated_slot_session():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        source = root / "source"
        source.mkdir()
        (source / "EmuHawk.exe").write_bytes(b"emuhawk")
        slot_path = root / "slot" / "BizHawk"
        calls = {"slots": [], "lease": [], "session": []}

        class Session:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class Slots:
            def __init__(self, **kwargs):
                calls["slots"].append(kwargs)
                self.root = root / "slots"

            @contextlib.contextmanager
            def lease(self, bizhawk, system=None, core=None):
                calls["lease"].append((Path(bizhawk), system, core))
                yield SimpleNamespace(path=slot_path, system=system, core=core)

        def make_session(rom, bizhawk, **kwargs):
            calls["session"].append((Path(rom), Path(bizhawk), kwargs))
            return Session()

        profile = {"rom_path": root / "game.gba", "bizhawk_path": source,
                   "system": "GBA", "core": "mGBA", "isolated_slot": True}
        with patch("taspipe.parallel.EmulatorSlots", Slots), \
             patch.object(RC.SJ, "StateSession", side_effect=make_session):
            with RC._emulator_session(profile, root / "work") as (_, info):
                pass
        check("R35 校准生产按平台/核心租隔离槽并把槽路径交给会话",
              calls["slots"] == [{"workers": 1, "system": "GBA", "core": "mGBA"}]
              and calls["lease"] == [(source, "GBA", "mGBA")]
              and calls["session"][0][1] == slot_path
              and calls["session"][0][2]["core"] == "mGBA"
              and info["bizhawk"] == str(slot_path), str(calls))


def t_reuse():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        doc = recipe()
        recipe_path = root / "recipe.json"
        recipe_path.write_text(json.dumps(doc), encoding="utf-8")
        evidence = root / "evidence.bin"
        evidence.write_bytes(b"evidence")
        out = root / "out"
        out.mkdir()
        RC._write_json(out / "report.json", {"cache_key": "same", "status": "candidates_only",
                                            "evidence": [str(evidence)]})
        with patch.object(RC, "load_recipe", return_value=(doc, {})), \
             patch.object(RC, "resolve_profile", return_value={}), \
             patch.object(RC, "cache_key", return_value="same"), \
             patch.object(RC, "_execute") as execute:
            reused = RC.run_recipe(recipe_path, "effect", out, mode="scout")
            check("R42 scout 同指纹且证据齐全时幂等复用",
                  reused.get("reused") is True and not execute.called)
            evidence.unlink()
            execute.return_value = {"status": "candidates_only"}
            rerun = RC.run_recipe(recipe_path, "effect", out, mode="scout")
            check("R43 scout 证据缺失时拒绝复用并重跑",
                  execute.call_count == 1 and rerun["status"] == "candidates_only")


def t_batch():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        doc = recipe()
        second = json.loads(json.dumps(doc["cases"][0]))
        second["id"] = "effect2"
        doc["cases"].append(second)
        path = root / "recipe.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        calls = []

        def fake_run(recipe_path, case_id, out_dir, mode="verify", force=False):
            calls.append(case_id)
            if case_id == "effect2":
                raise RuntimeError("synthetic failure")
            return {"status": "candidates_only", "case_id": case_id}

        with patch.object(RC, "run_recipe", side_effect=fake_run):
            result = RC.run_many(path, root / "out", mode="scout", workers=2)
        check("R41 批跑覆盖全部 case 且单案失败不中断其余",
              result["total"] == 2 and result["counts"] == {"candidates_only": 1, "error": 1}
              and set(calls) == {"effect", "effect2"}
              and "synthetic failure" in result["cases"][1]["error"], str(result))


def main():
    t_validation()
    t_expect()
    t_pixels()
    t_protocol()
    t_cache_archive()
    t_case_base_execution()
    t_isolated_slot_session()
    t_reuse()
    t_batch()
    failed = [name for name, ok in RESULTS if not ok]
    print(json.dumps({"status": "pass" if not failed else "failed",
                      "checks": len(RESULTS), "failed": failed}, ensure_ascii=False))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())

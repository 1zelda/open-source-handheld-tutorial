# -*- coding: utf-8 -*-
"""Isolated production-controller tests; no emulator, network or real asset writes."""
import sys

sys.dont_write_bytecode = True

from collections import Counter
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
SCRATCH = Path("F:/taspipe_scratch/control_tests").resolve()
from taspipe import popularity as POP

# 夹具默认作品：名单上的 NES T1（EN 维基畅销表 40,240,000 行），选题闸门对它放行。
FAMOUS_NES = "Super Mario Bros."
_GUARD_ACTIVE = True
_VIOLATIONS = []
LUA_RUNTIME_SOURCE = (TOOLS / "taspipe" / "control_runtime.lua").read_text(encoding="utf-8")


def _inside(path, root):
    return Path(path).resolve().is_relative_to(root)


def _audit(event, args):
    """Fail closed on writes outside fixtures, runtime reads, launches and network."""
    if not _GUARD_ACTIVE:
        return
    reason = None
    paths = []
    if event == "open":
        path, mode, flags = args
        if not isinstance(path, int):
            name = Path(path).name.lower()
            if name.startswith("control_runtime"):
                reason = "runtime read/write forbidden"
            if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
            ):
                paths = [path]
    elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.utime", "os.truncate"}:
        paths = [args[0]]
    elif event in {"os.rename", "os.link", "os.symlink"}:
        paths = list(args[:2])
    elif event in {"subprocess.Popen", "os.system", "os.exec", "os.spawn", "os.startfile", "os.startfile/2"}:
        reason = "process launch forbidden"
    elif event.startswith("socket."):
        reason = "network forbidden"
    elif event == "import" and args[0] == "taspipe.control_runtime":
        reason = "runtime import forbidden"
    for path in paths:
        if not isinstance(path, int) and not _inside(path, SCRATCH):
            reason = "write outside fixture root: " + str(path)
    if reason:
        _VIOLATIONS.append((event, reason))
        raise PermissionError(reason)


sys.addaudithook(_audit)

from taspipe import control as C
from taspipe import produce as P
from taspipe import registry as R
from taspipe.retro_platforms import PLATFORM_SPECS
from taspipe.schema import (SchemaError, adopt_state_sync_settings, apply_movie_sync_settings, asset,
                            core_identity_expectation, state_sync_settings, verify_core_identity)

REAL_RUN = C.run
REAL_WRITE_JSON = C.write_json


def sha1(data):
    return hashlib.sha1(data).hexdigest()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(root):
    """Content and mtime evidence, including directory entries; read only."""
    root = Path(root)
    return {
        str(p.relative_to(root)): (p.stat().st_mtime_ns, sha256(p) if p.is_file() else None)
        for p in [root, *root.rglob("*")]
    }


def setUpModule():
    # Check the fixed parent before any mkdir/TemporaryDirectory call.
    os.listdir(SCRATCH.parent)
    SCRATCH.mkdir(exist_ok=True)


def tearDownModule():
    global _GUARD_ACTIVE
    try:
        if _VIOLATIONS:
            raise AssertionError("isolation violation(s): " + repr(_VIOLATIONS))
    finally:
        _GUARD_ACTIVE = False


class Fixture(unittest.TestCase):
    def cli(self, args):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = C.main(args)
        return code, json.loads(stdout.getvalue())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="控制 % fixture_", dir=str(SCRATCH))
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.rom_bytes = bytes(range(64))
        self.rom = self.put("roms/演示 ROM.nes", self.rom_bytes)
        self.emu_root = self.base / "emulators"
        self.bh = self.emu_root / "BizHawk/BizHawk-2.8"
        self.put("emulators/BizHawk/BizHawk-2.8/EmuHawk.exe", b"fixture-not-executable")
        self.put("emulators/BizHawk/BizHawk-2.8/core.dll", b"fixture-core")
        self.put("emulators/BizHawk/BizHawk-2.8/config.ini", b"fixture-config")
        self.work = self.base / "work"
        self.out = self.base / "output"
        self.calls = []
        self.shots = {}
        self.tail = None
        # Only plan's source-file enumeration uses HERE. The implementation is
        # not copied/executed from here and the concurrent runtime is untouched.
        self.source_marker = self.put("fingerprint_sources/control.py", Path(C.__file__).read_bytes())
        patcher = mock.patch.object(C, "HERE", self.source_marker.parent)
        patcher.start()
        self.addCleanup(patcher.stop)

    def put(self, relative, data):
        path = self.base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def json_file(self, relative, doc):
        return self.put(relative, json.dumps(doc, ensure_ascii=False).encode("utf-8"))

    def session(self, jid="session", steps=None):
        return {
            "version": 1, "id": jid, "mode": "session",
            # 选题闸门（2026-11-22）要求 NES/SNES 任务带作品名，且必须是名单上的名作；
            # 夹具用真名作，其余闸门行为才不被这条规则掩盖。
            "game": FAMOUS_NES,
            "rom": {"path": str(self.rom.relative_to(self.base)), "sha1": sha1(self.rom_bytes)},
            "platform": "NES",
            "profile": {"bizhawk": str(self.bh.relative_to(self.base)), "core": "NesHawk", "system": "NES"},
            "steps": steps if steps is not None else [{"id": "wait", "op": "advance", "frames": 2}],
        }

    def rom_patch(self, jid="patch"):
        return {
            "version": 1, "id": jid, "mode": "rom_patch",
            "game": FAMOUS_NES,
            "rom": {"path": str(self.rom), "sha1": sha1(self.rom_bytes)},
            "patches": [{"offset": 2, "expect": "020304", "value": "aabbcc"}],
        }

    def movie(self, header=None, frames=8, wrapper=False, relative="movies/演示 % movie.bk2",
              names=None, raw_header=None):
        values = {"SHA1": sha1(self.rom_bytes).upper(), "Platform": "NES", "Core": "NesHawk", "emuVersion": "Version 2.8"}
        if header:
            values.update(header)
        header_bytes = raw_header if raw_header is not None else (
            "\ufeff" + "\n".join(f"{k} {v}" for k, v in values.items())).encode("utf-8")
        header_name, input_name = names or ("Header.txt", "Input Log.txt")
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w") as z:
            z.writestr(header_name, header_bytes)
            z.writestr(input_name, "[Input]\nLogKey:#P1\n" + "|..|........|\n" * frames + "[/Input]\n")
        data = content.getvalue()
        if wrapper:
            outer = io.BytesIO()
            with zipfile.ZipFile(outer, "w") as z:
                z.writestr("nested/demo.bk2", data)
                z.writestr("readme.txt", "not an input frame")
            data = outer.getvalue()
            relative = str(Path(relative).with_suffix(".zip"))
        return self.put(relative, data)

    def movie_doc(self, movie=None, steps=None):
        path = movie or self.movie()
        doc = self.session(steps=steps or [{"id": "replay", "op": "replay", "frames": "end"}])
        doc["start"] = {"kind": "movie", "path": str(path), "sha256": sha256(path)}
        return doc

    def executor(self, execution="pass", completion="inconclusive", error=None, empty=False, zero_bytes=False):
        def execute(program, attempt, work, timeout):
            self.assertTrue(_inside(attempt, self.base))
            self.assertEqual(Path(work).resolve(), self.work)
            self.assertEqual(timeout, 7)
            self.calls.append(deepcopy(program))
            if error:
                raise error
            refs = []
            if not empty:
                output = Path(attempt) / "executor-evidence.json"
                output.write_bytes(b"" if zero_bytes else json.dumps({"id": program["id"], "steps": program["steps"]}, ensure_ascii=False).encode("utf-8"))
                refs.append(str(output))
            return self.attach_shots(attempt, {"execution": execution, "completion": completion,
                                               "core_identity": "pass", "artifacts": refs, "reason": "offline fixture"})
        return execute

    SHOT_SEED = b"\x89PNG\r\n\x1a\nfixture-picture-"

    def shot_bytes(self, name):
        return self.SHOT_SEED + name.encode("utf-8")

    def shot(self, name="shot_end", frame=5, tolerance=3, seen=None):
        """给通关判据登记一张"真看过的截图"证词。

        字节在写任务时就固定、摘要当场算出，执行器再把同一份字节落进本次产物——
        这对应真实流程：先 window 出图 → 人眼读数 → 把图名/读数/摘要写进 evidence。
        """
        self.shots[name] = (frame, self.shot_bytes(name))
        return {"checkpoint": name, "seen": seen or "fixture：最终 Boss 倒下，HUD 计数归零",
                "sha256": hashlib.sha256(self.shot_bytes(name)).hexdigest(),
                "frame_tolerance": tolerance}

    def attach_shots(self, attempt, report):
        checkpoints = {}
        for name, (frame, data) in sorted(self.shots.items()):
            path = Path(attempt) / f"checkpoint_{name}.png"
            path.write_bytes(data)
            checkpoints[name] = {"frame": frame, "screenshot": str(path)}
        if checkpoints:
            report["checkpoints"] = checkpoints
        if self.tail:
            folder = Path(attempt) / "tail"
            folder.mkdir(exist_ok=True)
            report["tail_samples"] = []
            for frame, data in self.tail:
                path = folder / ("f%06d.png" % frame)
                path.write_bytes(data)
                report["tail_samples"].append({"frame": frame, "screenshot": str(path)})
        return report

    def set_tail(self, from_frame=1800, stride=20, count=76, frozen_from=None):
        """造末段采样：frozen_from 及之后的图逐字节相同（=停在结算/菜单），之前每张都不同。"""
        self.tail = []
        for i in range(count):
            frame = from_frame + i * stride
            tag = "frozen" if frozen_from is not None and frame >= frozen_from else "alive%03d" % i
            self.tail.append((frame, self.shot_bytes("tail-" + tag)))
        return self.tail

    def with_shot_completion(self, doc, checks, frame=5, name="shot_end", tolerance=3, source="fixture"):
        """把判据挂成"带证词"的写法：额外插一个 checkpoint 步骤，证词指向它。"""
        self.shots.clear()
        doc["steps"] = list(doc["steps"]) + [{"id": "cp_shot", "op": "checkpoint", "name": name}]
        for item in checks:
            item.setdefault("evidence", self.shot(name, frame, tolerance))
        doc["completion"] = {"source": source, "checks": checks}
        return doc

    def run_doc(self, doc=None, executor=None, out=None, allow=()):
        return REAL_RUN(doc or self.session(), self.base, out or self.out, self.work, 7,
                        executor=executor if executor is not None else self.executor(), allow=allow)

    def assert_blocked(self, doc, code):
        report = C.plan(doc, self.base)
        self.assertEqual(report["status"], "blocked")
        self.assertIn(code, [b["code"] for b in report["blockers"]])
        return report

    def assert_artifacts(self, report):
        self.assertTrue(report["artifacts"])
        for ref in report["artifacts"]:
            self.assertTrue(_inside(ref["uri"], self.base))
            self.assertEqual(ref["sha256"], sha256(ref["uri"]))
            self.assertEqual(ref["byte_size"], Path(ref["uri"]).stat().st_size)


class NormalizeTests(Fixture):
    def test_replay_speed_tier_defaults_and_rejects_unknown(self):
        doc = self.session()
        self.assertEqual(C.normalize(doc, self.base)[1]["speed"], "realtime")
        doc["record"] = {"speed": "unthrottled"}
        self.assertEqual(C.normalize(doc, self.base)[1]["speed"], "unthrottled")
        doc["record"] = {"speed": "turbo"}
        with self.assertRaises(SchemaError):
            C.normalize(doc, self.base)

    def test_completion_cannot_certify_written_target(self):
        doc = self.session(steps=[{"id": "set", "op": "patch", "writes": [
            {"domain": "RAM", "addr": 10, "width": 2, "value": 1}]}])
        doc["completion"] = {"source": "fixture", "checks": [
            {"id": "win", "domain": "RAM", "addr": 11, "cmp": "eq", "value": 0}]}
        with self.assertRaises(SchemaError):
            C.normalize(doc, self.base)
        doc["completion"]["checks"][0]["addr"] = 12
        self.assertEqual(C.normalize(doc, self.base)[1]["completion"][0]["addr"], 12)

    def test_duplicate_screenshot_rejected(self):
        doc = self.session(steps=[{"id": str(i), "op": "screenshot", "name": "same"} for i in range(2)])
        with self.assertRaises(SchemaError):
            C.normalize(doc, self.base)

    def test_array_comparator_cleanly_rejected(self):
        doc = self.session(steps=[{"id": "bad", "op": "assert", "checks": [
            {"id": "v", "domain": "RAM", "addr": 0, "cmp": [], "value": 0}]}])
        with self.assertRaises(SchemaError):
            C.normalize(doc, self.base)

    def test_relative_unicode_space_percent_paths_and_no_mutation(self):
        doc = self.session()
        original = deepcopy(doc)
        normalized, program = C.normalize(doc, self.base)
        self.assertEqual(doc, original)
        self.assertEqual(Path(program["rom"]), self.rom)
        self.assertEqual(Path(program["bizhawk"]), self.bh)
        self.assertEqual(normalized["start"], {"kind": "boot"})
        self.assertEqual(program["steps"], doc["steps"])

    def test_multiplayer_input_preserves_distinct_controls(self):
        players = {"1": ["Left", "A"], "2": ["Right", "B"], "3": [], "4": ["Start"]}
        _, program = C.normalize(self.session(steps=[{"id": "pad", "op": "input", "segments": [{"frames": 3, "players": players}]}]), self.base)
        self.assertEqual(program["steps"][0]["segments"], [{"frames": 3, "players": players}])

    def test_patch_width_endian_and_domain_spaces_preserved(self):
        writes = [
            {"id": "byte", "domain": "68K RAM", "addr": "0x10", "width": 1, "value": 255},
            {"id": "word", "domain": "68K RAM", "addr": 17, "width": 2, "endian": "big", "value": 0x1234, "expect": 0xFFFF},
            {"id": "dword", "domain": "Main Memory", "addr": 17, "width": 4, "endian": "little", "value": 0xFFFFFFFF},
        ]
        _, program = C.normalize(self.session(steps=[{"id": "patch", "op": "patch", "writes": writes}]), self.base)
        actual = program["steps"][0]["writes"]
        self.assertEqual([w["width"] for w in actual], [1, 2, 4])
        self.assertEqual([w["endian"] for w in actual], ["little", "big", "little"])
        self.assertEqual(actual[0]["domain"], "68K RAM")
        self.assertEqual(actual[0]["addr"], 16)
        self.assertEqual(actual[1]["value"], 0x1234)
        self.assertEqual(actual[1]["expect"], 0xFFFF)

    def test_patch_overlap_rejected(self):
        writes = [{"domain": "RAM", "addr": 8, "width": 2, "value": 0}, {"domain": "RAM", "addr": 9, "value": 1}]
        with self.assertRaises(SchemaError):
            C.normalize(self.session(steps=[{"id": "p", "op": "patch", "writes": writes}]), self.base)

    def test_patch_word_dword_and_address_plus_width_overflow_rejected(self):
        for width, value, addr in ((2, 0x10000, 0), (4, 0x100000000, 0), (2, 0, 0xFFFFFFFF)):
            with self.subTest(width=width, value=value, addr=addr), self.assertRaises(SchemaError):
                C.normalize(self.session(steps=[{"id": "p", "op": "patch", "writes": [
                    {"domain": "RAM", "addr": addr, "width": width, "value": value}
                ]}]), self.base)

    def test_observe_assert_until_and_completion_keep_memory_contract(self):
        check = {"id": "goal", "domain": "Main Memory", "addr": "0x1234", "width": 2, "endian": "big", "cmp": "ge", "value": 512}
        watch = {k: v for k, v in check.items() if k not in ("cmp", "value")}
        doc = self.session(steps=[
            {"id": "watch", "op": "observe", "watches": [watch]},
            {"id": "until", "op": "until", "checks": [check], "max_frames": 4, "players": {"2": ["A"]}},
            {"id": "assert", "op": "assert", "checks": [check]},
        ])
        doc["completion"] = {"source": "offline documented fixture", "checks": [check]}
        _, program = C.normalize(doc, self.base)
        expected = {**check, "addr": 0x1234}
        self.assertEqual(program["completion"], [expected])
        self.assertEqual(program["steps"][1]["checks"], [expected])
        self.assertEqual(program["steps"][1]["players"], {"2": ["A"]})
        self.assertEqual(program["steps"][0]["watches"][0]["domain"], "Main Memory")
        for field, bad in (("max_frames", True), ("checks", [{**check, "value": True}]),
                           ("checks", [{**check, "cmp": "gt"}]), ("checks", [check, check])):
            with self.subTest(field=field, bad=bad), self.assertRaises(SchemaError):
                wrong = deepcopy(doc)
                wrong["steps"][1][field] = bad
                C.normalize(wrong, self.base)

    def test_checkpoint_load_before_save_rejected(self):
        with self.assertRaises(SchemaError):
            C.normalize(self.session(steps=[{"id": "load", "op": "load", "name": "later"}, {"id": "save", "op": "checkpoint", "name": "later"}]), self.base)

    def test_checkpoint_duplicate_name_rejected(self):
        with self.assertRaises(SchemaError):
            C.normalize(self.session(steps=[{"id": "s1", "op": "checkpoint", "name": "same"}, {"id": "s2", "op": "checkpoint", "name": "same"}]), self.base)

    def test_checkpoint_load_after_save_allowed(self):
        steps = [{"id": "save", "op": "checkpoint", "name": "slot"}, {"id": "load", "op": "load", "name": "slot"}]
        self.assertEqual(C.normalize(self.session(steps=steps), self.base)[1]["steps"], steps)

    def test_checkpoint_ram_range_is_normalized(self):
        step = {"id": "save", "op": "checkpoint", "name": "wram",
                "ram_domain": "System Bus", "ram_addr": "0x7E0000", "ram_bytes": "0x20000"}
        program = C.normalize(self.session(steps=[step]), self.base)[1]
        self.assertEqual(program["steps"][0], {**step, "ram_addr": 0x7E0000, "ram_bytes": 0x20000})

    def test_checkpoint_ram_range_rejects_invalid_values(self):
        bad_fields = [
            {"ram": False, "ram_addr": 0}, {"ram": 0}, {"ram_domain": 3},
            {"ram_addr": True}, {"ram_addr": -1}, {"ram_bytes": 0}, {"ram_bytes": True},
        ]
        for fields in bad_fields:
            with self.subTest(fields=fields), self.assertRaises(SchemaError):
                C.normalize(self.session(steps=[{"id": "save", "op": "checkpoint", "name": "slot", **fields}]), self.base)

    def test_checkpoint_multiple_memory_dumps_are_normalized(self):
        dump = {"name": "cgram", "domain": "CGRAM", "addr": "0x0", "bytes": "0x200"}
        step = {"id": "save", "op": "checkpoint", "name": "ppu", "ram": False,
                "memory_dumps": [dump]}
        program = C.normalize(self.session(steps=[step]), self.base)[1]
        self.assertEqual(program["steps"][0]["memory_dumps"],
                         [{**dump, "addr": 0, "bytes": 0x200}])

    def test_checkpoint_multiple_memory_dumps_reject_invalid_values(self):
        valid = {"name": "vram", "domain": "VRAM", "addr": 0, "bytes": 0x10000}
        bad = [None, {}, [{**valid, "name": "same"}, {**valid, "name": "same"}],
               [{k: v for k, v in valid.items() if k != "domain"}],
               [{**valid, "addr": True}], [{**valid, "bytes": 0}], [{**valid, "extra": 1}]]
        for dumps in bad:
            with self.subTest(dumps=dumps), self.assertRaises(SchemaError):
                C.normalize(self.session(steps=[{"id": "save", "op": "checkpoint", "name": "ppu",
                                                 "memory_dumps": dumps}]), self.base)

    def test_checkpoint_cpu_registers_are_explicit_and_boolean(self):
        doc = self.session(steps=[{"id": "save", "op": "checkpoint", "name": "cpu", "registers": True}])
        _, program = C.normalize(doc, self.base)
        self.assertIs(program["steps"][0]["registers"], True)
        doc["steps"][0]["registers"] = "yes"
        with self.assertRaises(SchemaError):
            C.normalize(doc, self.base)

    def test_seed_ram_is_normalized(self):
        step = {"id": "seed", "op": "seed_ram", "path": "seed.bin", "sha256": "ab" * 32,
                "domain": "CARTRAM", "addr": "0x0", "bytes": "0x20000"}
        program = C.normalize(self.session(steps=[step]), self.base)[1]
        self.assertEqual(program["steps"][0], {**step, "path": str(self.base / "seed.bin"),
                                              "addr": 0, "bytes": 0x20000})

    def test_seed_ram_requires_pre_replay_placement(self):
        seed = {"id": "seed", "op": "seed_ram", "path": "seed.bin", "sha256": "ab" * 32,
                "domain": "CARTRAM", "addr": 0, "bytes": 1}
        replay = {"id": "play", "op": "replay", "frames": 1}
        doc = self.session()
        doc["start"] = {"kind": "movie", "path": str(self.rom), "sha256": "cd" * 32}
        doc["steps"] = [replay, seed]
        with self.assertRaises(SchemaError):
            C.normalize(doc, self.base)

    def test_seed_ram_rejects_invalid_values(self):
        base = {"id": "seed", "op": "seed_ram", "path": "seed.bin", "sha256": "ab" * 32,
                "domain": "CARTRAM", "addr": 0, "bytes": 1}
        for fields in ({"bytes": 0}, {"bytes": True}, {"addr": -1}, {"domain": ""}, {"sha256": "ab"}):
            with self.subTest(fields=fields), self.assertRaises(SchemaError):
                C.normalize(self.session(steps=[{**base, **fields}]), self.base)

    def test_snes_deterministic_core_settings_are_whitelisted(self):
        for core, key, value in (("BSNES", "RandomizedInitialState", False),
                                 ("BSNESv115+", "Entropy", 0)):
            with self.subTest(core=core):
                doc = self.session()
                doc["platform"] = "SNES"
                doc["profile"] = {"bizhawk": str(self.bh), "system": "SNES", "core": core,
                                  "sync_settings": {"LeftPort": 1, "RightPort": 1, key: value}}
                _, program = C.normalize(doc, self.base)
                self.assertEqual(program["sync_settings"], doc["profile"]["sync_settings"])

    def test_snes_core_settings_reject_nondeterminism_and_wrong_platform(self):
        cases = [
            ("BSNES", {"RandomizedInitialState": True}),
            ("BSNESv115+", {"Entropy": 1}),
            ("Snes9x", {"Entropy": 0}),
            ("NesHawk", {"Entropy": 0}),
        ]
        for core, sync in cases:
            with self.subTest(core=core, sync=sync), self.assertRaises(SchemaError):
                doc = self.session()
                doc["platform"] = "SNES"
                doc["profile"] = {"bizhawk": str(self.bh), "system": "SNES", "core": core, "sync_settings": sync}
                C.normalize(doc, self.base)

    def test_bsnes115_fast_ppu_setting_is_explicit_and_boolean(self):
        doc = self.session()
        doc["platform"] = "SNES"
        doc["profile"] = {"bizhawk": str(self.bh), "system": "SNES", "core": "BSNESv115+",
                          "sync_settings": {"Entropy": 0, "FastPPU": False}}
        _, program = C.normalize(doc, self.base)
        self.assertIs(program["sync_settings"]["FastPPU"], False)
        for value in (0, "false", None):
            with self.subTest(value=value), self.assertRaises(SchemaError):
                doc["profile"]["sync_settings"]["FastPPU"] = value
                C.normalize(doc, self.base)

    def test_duplicate_step_id_rejected(self):
        with self.assertRaises(SchemaError):
            C.normalize(self.session(steps=[{"id": "same", "op": "advance", "frames": 1}] * 2), self.base)


# Generate separate test methods, so unittest's count includes each schema gate.
def add_bad_doc_case(name, trail, value):
    def test(self):
        doc = self.session()
        node = doc
        for key in trail[:-1]:
            node = node[key]
        node[trail[-1]] = deepcopy(value)
        with self.assertRaises(SchemaError):
            C.normalize(doc, self.base)
    setattr(NormalizeTests, "test_reject_" + name, test)


for _name, _trail, _value in [
    ("unknown_top", ("surprise",), 1), ("bool_version", ("version",), True),
    ("string_version", ("version",), "1"), ("wrong_version", ("version",), 2),
    ("id_type", ("id",), 123), ("id_path", ("id",), "../escape"),
    ("mode", ("mode",), "other"), ("rom_type", ("rom",), []),
    ("rom_unknown", ("rom", "extra"), 1), ("rom_path_type", ("rom", "path"), 12),
    ("rom_hash_type", ("rom", "sha1"), True), ("rom_hash_length", ("rom", "sha1"), "a" * 39),
    ("platform_unknown", ("platform",), "UNKNOWN"), ("platform_type", ("platform",), []),
    ("profile_type", ("profile",), []), ("profile_unknown", ("profile", "typo"), 1),
    ("core_type", ("profile", "core"), []), ("system_mismatch", ("profile", "system"), "SNES"),
    ("sync_type", ("profile", "sync_settings"), []),
    ("sync_unknown", ("profile", "sync_settings"), {"port": "ControllerNES"}),
    ("start_type", ("start",), []), ("boot_with_path", ("start",), {"kind": "boot", "path": "x"}),
    ("state_without_hash", ("start",), {"kind": "state", "path": "state.bin"}),
    ("macros_type", ("macros",), []), ("steps_type", ("steps",), {}),
    ("steps_empty", ("steps",), []), ("step_type", ("steps", 0), "advance"),
    ("step_unknown", ("steps", 0, "unused"), 1), ("op_unknown", ("steps", 0, "op"), "fly"),
    ("op_type", ("steps", 0, "op"), []), ("frames_bool", ("steps", 0, "frames"), True),
    ("frames_float", ("steps", 0, "frames"), 1.5), ("frames_string", ("steps", 0, "frames"), "1"),
    ("frames_zero", ("steps", 0, "frames"), 0), ("frames_negative", ("steps", 0, "frames"), -1),
    ("completion_type", ("completion",), []),
    ("completion_unknown", ("completion",), {"unknown": True}),
    ("record_type", ("record",), []), ("record_unknown", ("record",), {"codec": "x"}),
    ("video_nonbool", ("record",), {"video": 1}), ("audio_nonbool", ("record",), {"audio": "yes"}),
    ("fps_bool", ("record",), {"fps": True}), ("fps_nan", ("record",), {"fps": float("nan")}),
    ("fps_inf", ("record",), {"fps": float("inf")}), ("fps_zero", ("record",), {"fps": 0}),
]:
    add_bad_doc_case(_name, _trail, _value)


def add_bad_memory_case(name, key, value):
    def test(self):
        write = {"domain": "68K RAM", "addr": 0, "width": 1, "value": 0}
        write[key] = value
        with self.assertRaises(SchemaError):
            C.normalize(self.session(steps=[{"id": "patch", "op": "patch", "writes": [write]}]), self.base)
    setattr(NormalizeTests, "test_memory_reject_" + name, test)


for _name, _key, _value in [
    ("unknown", "surprise", 1), ("width_three", "width", 3), ("width_bool", "width", True),
    ("width_string", "width", "2"), ("width_zero", "width", 0), ("width_eight", "width", 8),
    ("endian", "endian", "native"), ("value_overflow", "value", 256), ("value_bool", "value", True),
    ("expect_overflow", "expect", 256), ("expect_bool", "expect", False), ("negative_value", "value", -1),
    ("addr_bool", "addr", True), ("addr_overflow", "addr", 0x100000000), ("addr_negative", "addr", -1),
    ("domain_blank", "domain", " "), ("domain_newline", "domain", "RAM\n"),
    ("domain_nul", "domain", "RAM\0"), ("domain_type", "domain", []),
]:
    add_bad_memory_case(_name, _key, _value)


class MacroTests(Fixture):
    def test_nested_repeat_and_independent_expansion(self):
        leaf = [{"frames": 2, "players": {"1": ["A"]}}, {"frames": 1}]
        macros = {"leaf": leaf, "nested": [{"use": "leaf", "repeat": 2}]}
        result = C.compile_macro([{"use": "nested", "repeat": 2}], macros, "NES")
        expected = [{"frames": 2, "players": {"1": ["A"]}}, {"frames": 1, "players": {}}] * 4
        self.assertEqual(result, expected)
        result[0]["players"]["1"].append("B")
        self.assertEqual(result[2]["players"]["1"], ["A"])
        self.assertEqual(macros["leaf"], leaf)
        doc = self.session(steps=[{"id": "macro", "op": "macro", "name": "nested", "repeat": 3}])
        doc["macros"] = macros
        self.assertEqual(C.normalize(doc, self.base)[1]["steps"][0]["segments"], expected[:2] * 6)

    def test_numeric_arrows_shorthand_and_mirror(self):
        expected = [["Down"], ["Down", "Right"], ["Right"], ["Right", "A"], ["Right", "A"]]
        for notation in ("236+A", "↓↘→+A", "QCF+A"):
            for facing in ("right", "left"):
                with self.subTest(notation=notation, facing=facing):
                    rows = C.compile_macro([{"notation": notation, "facing": facing, "dir_frames": 1, "attack_hold": 2, "player": 2}], {}, "NES")
                    wanted = [["Left" if b == "Right" else b for b in buttons] for buttons in expected] if facing == "left" else expected
                    self.assertEqual(rows, [{"frames": 1, "players": {"2": b}} for b in wanted])

    def test_neutral_notation_is_one_frame(self):
        self.assertEqual(C.compile_macro([{"notation": "5", "dir_frames": 1}], {}, "NES"),
                         [{"frames": 1, "players": {"1": []}}])

    def test_explicit_neutral_is_one_frame(self):
        self.assertEqual(C.compile_macro([{"frames": 1, "players": {"1": []}}], {}, "NES"),
                         [{"frames": 1, "players": {"1": []}}])

    def test_cycles_direct_and_nested(self):
        for macros in ({"a": [{"use": "a"}]}, {"a": [{"use": "b"}], "b": [{"use": "a"}]}):
            with self.subTest(macros=macros), self.assertRaises(SchemaError):
                C.compile_macro([{"use": "a"}], macros, "NES")

    def test_cross_platform_preset_rejected_even_when_buttons_overlap(self):
        with self.assertRaises(SchemaError):
            C.compile_macro([{"notation": "@KONAMI_CODE_NES"}], {}, "SNES")

    def test_native_platform_preset_allowed(self):
        result = C.compile_macro([{"notation": "@KONAMI_CODE_NES"}], {}, "NES")
        self.assertGreater(len(result), 1)
        self.assertEqual(result[0], {"frames": 1, "players": {"1": ["Up"]}})
        self.assertIn({"frames": 1, "players": {"1": ["Start"]}}, result)

    def test_unknown_notation_not_silently_ignored(self):
        for notation in ("garbage", "236?+A", "↓?→+A", "@UNKNOWN", "QCF+UNKNOWN"):
            with self.subTest(notation=notation), self.assertRaises(SchemaError):
                C.compile_macro([{"notation": notation}], {}, "NES")

    def test_bad_macro_fields_types_and_limits(self):
        for part in ({"use": "missing"}, {"use": "a", "repeat": True}, {"use": "a", "repeat": 0},
                     {"frames": True}, {"frames": 1, "surprise": 2}, {"notation": "236+A", "player": True},
                     {"notation": "236+A", "dir_frames": True}, {"notation": "236+A", "facing": "up"},
                     {"use": "a", "repeat": 100001}):
            with self.subTest(part=part), self.assertRaises(SchemaError):
                C.compile_macro([part], {"a": [{"frames": 1}]}, "NES")

    def test_multiplayer_bad_numbers_buttons_and_duplicates(self):
        for players in ({1: ["A"]}, {"0": []}, {"5": []}, {"1": "A"}, {"1": ["A", "A"]},
                        {"2": ["X"]}, {"2": [True]}, []):
            with self.subTest(players=players), self.assertRaises(SchemaError):
                C.compile_macro([{"frames": 1, "players": players}], {}, "NES")


class MovieTests(Fixture):
    def test_exact_pair_ready_and_end_means_remaining_frames(self):
        for wrapper in (False, True):
            with self.subTest(wrapper=wrapper):
                doc = self.movie_doc(self.movie(wrapper=wrapper), steps=[{"id": "prefix", "op": "replay", "frames": 3}, {"id": "rest", "op": "replay", "frames": "end"}])
                before = deepcopy(doc)
                report = C.plan(doc, self.base)
                self.assertEqual(report["status"], "ready", report["blockers"])
                self.assertEqual(report["program"]["start"]["movie_frames"], 8)
                self.assertEqual([s["frames"] for s in report["program"]["steps"]], [3, 5])
                self.assertEqual(doc, before)
                self.assertEqual(report["verification"]["sync"], "unverified")

    def test_movie_header_mismatches(self):
        for header, code in [({"SHA1": "f" * 40}, "movie_rom_mismatch"), ({"Core": "QuickNES"}, "movie_profile_mismatch"),
                             ({"Platform": "SNES"}, "movie_profile_mismatch"), ({"emuVersion": "2.9"}, "emulator_version_unverified"),
                             ({"emuVersion": "unknown"}, "emulator_version_unverified")]:
            with self.subTest(header=header):
                self.assert_blocked(self.movie_doc(self.movie(header=header)), code)

    def test_movie_hash_changed_rejected(self):
        doc = self.movie_doc()
        doc["start"]["sha256"] = "0" * 64
        self.assert_blocked(doc, "start_mismatch")

    def test_replay_overrun_and_duplicate_end_rejected(self):
        for frames in ([9], [5, 4], ["end", "end"], [8, "end"]):
            with self.subTest(frames=frames):
                self.assert_blocked(self.movie_doc(steps=[{"id": f"r{i}", "op": "replay", "frames": n} for i, n in enumerate(frames)]), "movie_range")

    def test_input_requires_takeover_then_real_run_receives_it(self):
        input_step = {"id": "input", "op": "input", "segments": [{"frames": 1, "players": {"2": ["A"]}}]}
        with self.assertRaises(SchemaError):
            C.normalize(self.movie_doc(steps=[input_step]), self.base)
        steps = [{"id": "replay", "op": "replay", "frames": 3}, {"id": "take", "op": "takeover"}, input_step]
        report = self.run_doc(self.movie_doc(steps=steps))
        self.assertEqual(report["status"], "done")
        self.assertEqual(self.calls[0]["steps"], steps)
        self.assert_artifacts(report)

    def test_replay_after_takeover_or_boot_rejected(self):
        replay = {"id": "r", "op": "replay", "frames": 1}
        for doc in (self.movie_doc(steps=[{"id": "t", "op": "takeover"}, replay]), self.session(steps=[replay])):
            with self.subTest(start=doc.get("start")), self.assertRaises(SchemaError):
                C.normalize(doc, self.base)

    def test_bad_archive_empty_movie_and_ambiguous_wrapper_blocked(self):
        ambiguous = io.BytesIO()
        with zipfile.ZipFile(ambiguous, "w") as z:
            z.writestr("a.bk2", b"not used")
            z.writestr("b.bk2", b"not used")
        for path in (self.put("bad.bk2", b"not a zip"), self.movie(frames=0), self.put("ambiguous.zip", ambiguous.getvalue())):
            with self.subTest(path=path):
                self.assert_blocked(self.movie_doc(path), "movie_format")


class MovieLengthAndVersionTests(Fixture):
    """2026-11-21 实测定口径：子帧核心的行数不是帧数；目录名尾零与 emuVersion 是同一版本。"""

    def test_frame_quantized_core_keeps_row_count(self):
        # 实测 NesHawk 4751/4812/5231 按行数重放，实到帧数与行数逐帧相等，所以行数就是帧数。
        doc = self.movie_doc(self.movie(header={"CycleCount": "1571335974",
                                                "ClockRate": "5369318.18181818"}, frames=8))
        report = C.plan(doc, self.base)
        self.assertEqual(report["status"], "ready", report["blockers"])
        start = report["program"]["start"]
        self.assertEqual(start["movie_frames"], 8)
        self.assertEqual(start["movie_frame_source"], "input_log")

    def test_subframe_core_uses_cycle_or_vblank_instead_of_rows(self):
        # 头里的数都是本地真实电影抄出来的：5273（Dragon Warrior 06:19.507）、4065（L'Empereur 01:52.082）、
        # 4567（SMB3 00:00.216）。折帧用平台自己的 fps（NES 60.0988），9 部带 CycleCount 的全部差 0.000%；
        # 写死 60 会统一偏低 0.14~0.19%，所以 22770/17559 这类数是错的。
        cases = ({"Core": "SubNESHawk", "CycleCount": "2037696222", "ClockRate": "5369318.18181818",
                  "want": 22808, "source": "cycle_count"},
                 # 老 BizHawk 按本机区域把小数点写成逗号（实测 4 部 NES 电影如此）。
                 {"Core": "SubNESHawk", "CycleCount": "2037696222", "ClockRate": "5369318,18181818",
                  "want": 22808, "source": "cycle_count"},
                 {"Core": "SubNESHawk", "VBlankCount": "6736", "want": 6736, "source": "vblank_count"},
                 {"Core": "SubNESHawk", "VBlankCount": "13", "want": 13, "source": "vblank_count"})
        for case in cases:
            header = {k: v for k, v in case.items() if k not in ("want", "source")}
            with self.subTest(header=header):
                doc = self.movie_doc(self.movie(header=header, frames=200))
                doc["profile"]["core"] = "SubNESHawk"
                report = C.plan(doc, self.base)
                self.assertEqual(report["status"], "ready", report["blockers"])
                start = report["program"]["start"]
                self.assertEqual(start["movie_frames"], case["want"])
                self.assertEqual(start["movie_frame_source"], case["source"])
                self.assertEqual(start["movie_input_lines"], 200)
                self.assertEqual([s["frames"] for s in report["program"]["steps"]], [case["want"]])

    def test_subframe_core_without_any_length_source_is_named(self):
        for header, why in (({"Core": "SubNESHawk"}, "没有可确定的帧数来源"),
                            # 折帧需要平台自己的 fps；平台写错就不许猜一个数把它糊过去。
                            ({"Core": "SubNESHawk", "Platform": "NES2",
                              "CycleCount": "2037696222", "ClockRate": "5369318.18181818"}, "不在 PLATFORM_SPECS")):
            with self.subTest(header=header):
                doc = self.movie_doc(self.movie(header=header, frames=200))
                doc["profile"]["core"] = "SubNESHawk"
                report = C.plan(doc, self.base)
                self.assertEqual(report["status"], "blocked", report)
                codes = {b["code"] for b in report["blockers"]}
                self.assertIn("movie_format", codes)
                self.assertIn(why, json.dumps(report["blockers"], ensure_ascii=False))
                self.assertIn("子帧核心", json.dumps(report["blockers"], ensure_ascii=False))

    def test_pal_header_spellings_only_the_real_pal_is_blocked(self):
        # 缺省 / 0 / False 都是 NTSC（本地 391 部 bk2 里 6 部写 "False"，行数与站点帧数 0.000% 相同）；
        # 只有 1/true 是真 PAL（4113 The Lion King、4233 The Smurfs，折算帧率 50.0069）。
        for raw, pal in ((None, False), ("0", False), ("False", False), ("false", False),
                         ("1", True), ("true", True), ("True", True)):
            header = {"Platform": "NES", "Core": "NesHawk"}
            if raw is not None:
                header["PAL"] = raw
            with self.subTest(raw=raw):
                self.assertEqual(C._is_pal(header), pal)

    def test_legacy_member_names_and_undecodable_header_still_parse(self):
        base_header = ("SHA1 %s\r\nPlatform NES\r\nCore NesHawk\r\nemuVersion Version 2.8\r\n"
                       % sha1(self.rom_bytes).upper())
        for raw, names in ((base_header + "Author Th\xfcnder\r\n", ("Header.txt", "Input Log.txt")),
                           (base_header + "Author adelikat\r\n", ("Header", "Input Log"))):
            with self.subTest(names=names):
                path = self.movie(raw_header=raw.encode("latin-1"), names=names, frames=6)
                report = C.plan(self.movie_doc(path), self.base)
                self.assertEqual(report["status"], "ready", report["blockers"])
                self.assertEqual(report["program"]["start"]["movie_frames"], 6)

    def test_emulator_version_trailing_zero_is_the_same_version(self):
        for emu_version, dir_ver, ready in (("Version 2.9.0", "2.9", True),
                                            ("Version 2.8", "2.8.0", True),
                                            ("Version 2.9.1", "2.9", False),
                                            ("Version 2.10", "2.1", False)):
            with self.subTest(emu_version=emu_version, dir_ver=dir_ver):
                for leaf in ("EmuHawk.exe", "core.dll", "config.ini"):
                    self.put(f"emulators/BizHawk/BizHawk-{dir_ver}/{leaf}", b"fixture")
                doc = self.movie_doc(self.movie(header={"emuVersion": emu_version}))
                doc["profile"]["bizhawk"] = str((self.emu_root / f"BizHawk/BizHawk-{dir_ver}")
                                                .relative_to(self.base))
                if ready:
                    self.assertEqual(C.plan(doc, self.base)["status"], "ready",
                                     C.plan(doc, self.base)["blockers"])
                else:
                    self.assert_blocked(doc, "emulator_version_unverified")


class VerifyLengthTests(Fixture):
    """2026-11-21 实测：站点时长折帧要用平台自己的 fps；长度不符或没报帧数，一律不许登记成通关。"""

    def frames_executor(self, advanced, **kwargs):
        inner = self.executor(**kwargs)

        def execute(program, attempt, work, timeout):
            out = inner(program, attempt, work, timeout)
            if advanced is not None:
                out["frames_advanced"] = advanced
            return out
        return execute

    def test_site_time_to_frames_matches_the_measured_pubs(self):
        fps = PLATFORM_SPECS["NES"]["fps"]
        self.assertEqual(fps, 60.0988)
        # 左边是站点时长，右边是这 6 部电影 Input Log 的真实行数（NesHawk/QuickNes 行数=帧数，逐部核对过）。
        for time_text, want in (("10:50.329", 39084),    # 4751 Ninja Gaiden
                                ("11:16.885", 40680),    # 4812 Ninja Gaiden
                                ("12:02.860", 43443),    # 5231 Pac-Man
                                ("01:15.026", 4509),     # 5254 Donkey Kong
                                ("10:08.731", 36584),    # 5441 Ninja Gaiden II（QuickNes）
                                ("11:51.595", 42766),    # 4003 Duck Hunt
                                ("1:03:56.273", 230555)):  # 三段式 HH:MM:SS.mmm
            with self.subTest(time_text=time_text):
                self.assertEqual(C._site_frames(time_text, fps), want)
        # 6012 是子帧核心：行数 5788209 是站点帧数的 329 倍；CycleCount/ClockRate×60.0988 折出 17588，
        # 与站点时长 04:52.651 完全相同，而×60 只得 17559。
        self.assertEqual(C._site_frames("04:52.651", fps), 17588)
        self.assertNotEqual(C._site_frames("04:52.651", 60), 17588)
        for junk in ("", "N/A", "0:00.000", "abc"):
            with self.subTest(time_text=junk):
                self.assertIsNone(C._site_frames(junk, fps))

    def test_site_duration_accepts_exact_nominal_60_rounding_only(self):
        fps = PLATFORM_SPECS["SNES"]["fps"]
        checked = C._site_duration_check("18:55.000", 68100, fps)
        self.assertTrue(checked["accepted"], checked)
        self.assertEqual(checked["basis"], "nominal_60_rounded")
        self.assertEqual(checked["site_frames_platform_fps"], 68212)
        self.assertEqual(checked["delta_frames"], -112)
        self.assertAlmostEqual(checked["nominal_60_delta_seconds"], 0.0)
        for frames in (68099, 68101, 68212):
            with self.subTest(frames=frames):
                checked = C._site_duration_check("18:55.000", frames, fps)
                self.assertEqual(checked["accepted"], frames == 68212, checked)
        self.assertFalse(C._site_duration_check("N/A", 68100, fps)["accepted"])

    def test_verify_length_needs_frames_and_a_bounded_tolerance(self):
        doc = self.session()
        doc["verify"] = {"length": {"frames": 100}}
        self.assertEqual(C.normalize(doc, self.base)[0]["verify"]["length"]["tolerance"], 0.005)
        for bad in ({"frames": 100, "tolerance": 0}, {"frames": 100, "tolerance": 0.5},
                   {"frames": 100, "tolerance": "0.005"}, {"frames": 100, "tolerance": float("nan")},
                   {"frames": 0}, {"frames": "100"}, {"tolerance": 0.005},
                   {"frames": 100, "extra": 1}):
            with self.subTest(bad=bad):
                doc["verify"] = {"length": bad}
                with self.assertRaises(SchemaError):
                    C.normalize(doc, self.base)
        doc["verify"] = {"length": {"frames": 100}, "arms": {}}
        with self.assertRaises(SchemaError):
            C.normalize(doc, self.base)

    def test_short_replay_is_demoted_even_when_execution_passed(self):
        doc = self.movie_doc()
        doc["verify"] = {"length": {"frames": 100, "source": "fixture"}}
        result = self.run_doc(doc, executor=self.frames_executor(90))
        self.assertEqual(result["status"], "failed", result)
        check = result["length_check"]
        self.assertFalse(check["pass"])
        self.assertEqual(check["delta_frames"], -10)
        self.assertEqual(check["expected"], 100)
        self.assertIn("长度核对不通过", result["reason"])
        self.assertEqual(result["verification"]["execution"], "pass")

    def test_exact_length_keeps_the_original_verdict(self):
        doc = self.movie_doc()
        doc["verify"] = {"length": {"frames": 8, "source": "fixture"}}
        result = self.run_doc(doc, executor=self.frames_executor(8))
        self.assertTrue(result["length_check"]["pass"], result["length_check"])
        self.assertEqual(result["length_check"]["source"], "fixture")
        self.assertEqual(result["status"], "done", result)
        # 容差内的误差仍算通过，但不许把差得多的放过去。
        loose = self.run_doc(self.movie_doc(), executor=self.frames_executor(7))
        self.assertNotIn("length_check", loose)

    def test_missing_frames_reported_is_not_a_pass(self):
        doc = self.movie_doc()
        doc["verify"] = {"length": {"frames": 8}}
        result = self.run_doc(doc, executor=self.frames_executor(None))
        self.assertEqual(result["status"], "failed", result)
        self.assertIn("缺少可比较的帧数", result["length_check"]["reason"])

    def truncated_executor(self, advanced, reason, status="failed", **flags):
        inner = self.frames_executor(advanced, execution="fail" if status == "blocked" else "pass")

        def execute(program, attempt, work, timeout):
            out = inner(program, attempt, work, timeout)
            out["status"] = status
            out["reason"] = reason
            out.update(flags)
            return out
        return execute

    def test_deadline_truncation_blames_the_deadline_not_the_movie(self):
        """11-22 实测 4776：--timeout 2400 到点掐在 101,351 帧，头条只写"长度核对不通过"，
        照着这句话去查电影查不到任何东西——真正该改的是 --timeout，所以闸门必须自己开口。"""
        doc = self.movie_doc()
        doc["verify"] = {"length": {"frames": 101485, "tolerance": C._tight_tolerance(101485),
                                    "source": "fixture"}}
        result = self.run_doc(doc, executor=self.truncated_executor(
            101351, "TimeoutError: runtime deadline exceeded", deadline_exceeded=True, timeout_seconds=2400))
        self.assertEqual(result["status"], "failed", result)
        self.assertIn("截止截断了回放，不是电影本身短", result["reason"])
        self.assertIn("TimeoutError", result["runtime"]["reason"])
        hits = [w for w in result.get("warnings") or [] if w["code"] == "runtime_deadline_truncated"]
        self.assertEqual(len(hits), 1, result.get("warnings"))
        for needle in ("2400", "101351"):
            self.assertIn(needle, hits[0]["detail"])

    def test_lock_blocked_run_keeps_the_lock_as_the_cause(self):
        """11-22 实测：残留锁让回放根本没启动（实到 0 帧），旧文案写成"电影短了 101485 帧"，
        把锁的病因说成了片子的问题。"""
        doc = self.movie_doc()
        doc["verify"] = {"length": {"frames": 101485, "tolerance": C._tight_tolerance(101485),
                                    "source": "fixture"}}
        result = self.run_doc(doc, executor=self.truncated_executor(
            0, "RuntimeBlocked: work_root locked; old/unknown lock must be handled by owner", status="blocked"))
        self.assertIn("回放没跑起来，不是电影短了", result["reason"])
        hits = [w for w in result.get("warnings") or [] if w["code"] == "replay_never_started"]
        self.assertEqual(len(hits), 1, result.get("warnings"))
        self.assertIn("work_root locked", hits[0]["detail"])

    def test_setup_timeout_admits_the_replay_never_launched(self):
        """截止也可能掐在启动阶段：EmuHawk 还没拉起就到期，实到 0 帧。
        这时说"截止截断了回放"是错的——回放根本没开始，得点名病因是启动前超时。"""
        doc = self.movie_doc()
        doc["verify"] = {"length": {"frames": 101485, "tolerance": C._tight_tolerance(101485),
                                    "source": "fixture"}}
        result = self.run_doc(doc, executor=self.truncated_executor(
            0, "TimeoutError: runtime setup exceeded timeout", deadline_exceeded=True, timeout_seconds=30))
        self.assertEqual(result["status"], "failed", result)
        self.assertIn("截止在启动前就到、回放没跑起来，不是电影本身短", result["reason"])
        self.assertIn("TimeoutError", result["runtime"]["reason"])
        hits = [w for w in result.get("warnings") or [] if w["code"] == "runtime_deadline_truncated"]
        self.assertEqual(len(hits), 1, result.get("warnings"))
        self.assertIn("在回放启动前就到期", hits[0]["detail"])
        self.assertIn("一帧都没跑", hits[0]["detail"])
        self.assertIn("30", hits[0]["detail"])

    def test_plain_short_replay_still_gets_the_bare_headline(self):
        """恒量反证：没有截止、没有拦锁时，长度文案一个字都不许多加，否则真短片会被推给 --timeout。"""
        doc = self.movie_doc()
        doc["verify"] = {"length": {"frames": 100, "source": "fixture"}}
        result = self.run_doc(doc, executor=self.frames_executor(90))
        self.assertEqual(result["reason"], "长度核对不通过：实到 90 与期望 100 差 -10 帧", result)
        self.assertEqual([w["code"] for w in result.get("warnings") or []], [], result)

    def test_tolerance_is_two_frames_not_half_a_percent(self):
        """0.5% 在 10 万帧片子上等于允许少跑 507 帧；截断 134 帧那次就是这么被放过去的。"""
        self.assertAlmostEqual(C._tight_tolerance(101485), 2.0 / 101485, places=12)
        self.assertLessEqual(C._tight_tolerance(101485) * 101485, 2.0)
        self.assertFalse(C._check_length(101351, 101485, C._tight_tolerance(101485))["pass"])
        self.assertTrue(C._check_length(101484, 101485, C._tight_tolerance(101485))["pass"])
        # 短片夹在 0.05 上限内，不许把 validate 的闸门顶开
        self.assertLessEqual(C._tight_tolerance(13), 0.05)
        self.assertEqual(C._tight_tolerance(0), 0.005)


class DriverStallVersionTests(Fixture):
    """实测：BizHawk 2.3/2.3.1 在本驱动下第一步就不放帧（两个速度档 0 帧、60 秒被杀），
    这类版本必须在启动前 blocked；2.4~2.7 本机没装、没实测，不许顺带拦。"""

    def install(self, name):
        self.put(f"emulators/BizHawk/BizHawk-{name}/EmuHawk.exe", b"fixture-not-executable")
        movie = self.movie(header={"emuVersion": "Version " + name})
        doc = self.movie_doc(movie=movie)
        doc["profile"]["bizhawk"] = f"emulators/BizHawk/BizHawk-{name}"
        return doc

    def codes(self, report):
        return [b["code"] for b in report["blockers"]]

    def test_measured_stalled_versions_are_blocked_before_launch(self):
        for name in ("2.3", "2.3.1", "2.3.0"):
            report = C.plan(self.install(name), self.base)
            self.assertEqual(report["status"], "blocked", (name, report["blockers"]))
            self.assertEqual(self.codes(report), ["driver_stall_measured"], name)
            self.assertIn("不进放映", report["blockers"][0]["reason"], name)

    def test_measured_working_versions_are_not_blocked(self):
        for name in ("2.8", "2.9", "2.9.1", "2.10", "2.11", "2.11.1"):
            report = C.plan(self.install(name), self.base)
            self.assertNotIn("driver_stall_measured", self.codes(report), name)
            self.assertEqual(report["status"], "ready", (name, report["blockers"]))

    def test_untested_versions_are_neither_blocked_nor_claimed_measured(self):
        for name in ("2.4.2", "2.5.2", "2.6.3", "2.7"):
            report = C.plan(self.install(name), self.base)
            self.assertNotIn("driver_stall_measured", self.codes(report), name)
        self.assertIsNone(C.driver_stall_version("BizHawk-win-x64"))
        self.assertEqual(C.driver_stall_version("BizHawk-2.3.1-win-x64"), "2.3.1")

    def test_registry_precheck_uses_the_same_verdict(self):
        ident = {"id": "1", "game": "演示", "title": "演示", "platform_code": "NES",
                 "platform": "NES",
                 "status": "identified", "movie": "m.bk2", "movie_note": "",
                 "required_rom_sha1": sha1(self.rom_bytes), "hash_source": "bk2 Header",
                 "core": "NesHawk", "emulator": "BizHawk 2.3", "blockers": [], "profile": None,
                 "emulator_dir": str(self.emu_root / "BizHawk" / "BizHawk-2.3")}
        idx = {sha1(self.rom_bytes): [str(self.rom)]}
        with mock.patch.object(R, "resolve_identity", return_value=ident):
            row = R.assess({}, None, idx, {}, {})
        self.assertIn("driver_stall_measured", [b["code"] for b in row["blockers"]], row)
        self.assertEqual(row["status"], "blocked")
        ident["emulator_dir"] = str(self.emu_root / "BizHawk" / "BizHawk-2.8")
        ident["emulator"] = "BizHawk 2.8"
        with mock.patch.object(R, "resolve_identity", return_value=ident):
            ok = R.assess({}, None, idx, {}, {})
        self.assertNotIn("driver_stall_measured", [b["code"] for b in ok["blockers"]], ok)


class MemoryWindowTests(Fixture):
    """实测：QuickNes 的 System Bus 读在 $4000-$7FFF 只会拿到恒定总线浮值（同一片电影相隔 2059 帧的两个
    采样点 8192/8192 逐字节相同），NesHawk 同窗口 0/8192 相同=读得到卡带 WRAM。判据地址落进读不到的窗口
    就等于没有判据，跑完 3 万帧才发现是白跑，所以拦在启动前。"""

    def doc(self, core, addr, kind="completion", width=1, domain="System Bus"):
        item = {"id": "goal", "domain": domain, "addr": addr, "width": width}
        doc = self.session()
        if kind == "completion":
            self.with_shot_completion(doc, [dict(item, cmp="eq", value=0)], source="fixture")
        elif kind == "assert":
            doc["steps"] = [{"id": "chk", "op": "assert", "checks": [dict(item, cmp="eq", value=0)]}]
        elif kind == "observe":
            doc["steps"] = [{"id": "watch", "op": "observe", "watches": [item]}]
        else:
            doc["steps"] = [{"id": "set", "op": "patch", "writes": [dict(item, value=1)]}]
        doc["profile"]["core"] = core
        return doc

    def codes(self, report):
        return [b["code"] for b in report["blockers"]]

    def test_wram_backed_address_is_blocked_under_quicknes(self):
        report = C.plan(self.doc("QuickNes", 0x6000), self.base)
        self.assertEqual(report["status"], "blocked", report["blockers"])
        self.assertEqual(self.codes(report), ["memory_window_unreadable"], report["blockers"])
        self.assertIn("6000", report["blockers"][0]["reason"])
        self.assertIn("QuickNes", report["blockers"][0]["reason"])

    def test_same_address_passes_under_a_core_that_exposes_it(self):
        # 恒量反证：拦的是「这个核心读不到」，不是「这个地址有罪」——同一地址换 NesHawk 就放行。
        for addr in (0x4000, 0x6000, 0x7FFF):
            report = C.plan(self.doc("NesHawk", addr), self.base)
            self.assertNotIn("memory_window_unreadable", self.codes(report), hex(addr))
            self.assertEqual(report["status"], "ready", (hex(addr), report["blockers"]))

    def test_work_ram_and_rom_mirror_stay_readable_under_quicknes(self):
        # 正对照：7429 真正用来当判据的地址（0x0081 HUD 计量）必须过闸，否则闸门会杀掉可用方案。
        for addr in (0x0000, 0x0081, 0x1FFF, 0x8000, 0xFFFA):
            report = C.plan(self.doc("QuickNes", addr), self.base)
            self.assertEqual(report["status"], "ready", (hex(addr), report["blockers"]))

    def test_width_that_spills_past_a_readable_window_is_blocked(self):
        self.assertEqual(self.codes(C.plan(self.doc("QuickNes", 0x1FFC, width=4), self.base)), [])
        self.assertEqual(self.codes(C.plan(self.doc("QuickNes", 0x1FFE, width=4), self.base)),
                         ["memory_window_unreadable"])
        self.assertEqual(self.codes(C.plan(self.doc("QuickNes", 0x7FFE, width=4), self.base)),
                         ["memory_window_unreadable"])

    def test_every_memory_bearing_step_is_scanned(self):
        for kind in ("completion", "assert", "observe", "patch"):
            report = C.plan(self.doc("QuickNes", 0x6000, kind=kind), self.base)
            self.assertIn("memory_window_unreadable", self.codes(report), kind)

    def test_domains_that_were_never_measured_are_not_accused(self):
        # 只实测过 System Bus。别的域没量过，不许顺带拦。
        report = C.plan(self.doc("QuickNes", 0x6000, domain="Main RAM"), self.base)
        self.assertNotIn("memory_window_unreadable", self.codes(report))
        self.assertEqual(report["status"], "ready", report["blockers"])

    def test_unmeasured_cores_are_recorded_as_a_gap_not_blocked(self):
        for core in ("quickerNES", "SubNESHawk", "SubQuickNes"):
            self.assertNotIn(core, C.NES_READABLE_WINDOWS, core)
            report = C.plan(self.doc(core, 0x6000), self.base)
            self.assertNotIn("memory_window_unreadable", self.codes(report), core)


class SubframeFrameSourceTests(Fixture):
    """实测：SubNESHawk 的 Input Log 一行是一个时间片（原生 6012 = 5,788,209 行 / 17,588 帧 = 329.1 行每帧），
    帧数只能从 CycleCount÷ClockRate×平台 fps 或 VBlankCount 折。折不出来以前会让 plan 抛 SchemaError，
    整批评估一起崩；现在必须落成 blocker。"""

    def test_missing_frame_source_is_a_blocker_not_a_crash(self):
        doc = self.movie_doc(self.movie(header={"Core": "SubNESHawk"}))
        doc["profile"]["core"] = "SubNESHawk"
        report = C.plan(doc, self.base)
        self.assertEqual(report["status"], "blocked", report["blockers"])
        codes = [b["code"] for b in report["blockers"]]
        self.assertIn("movie_format", codes, codes)
        self.assertIn("CycleCount", json.dumps(report["blockers"], ensure_ascii=False))

    def test_cycle_count_header_folds_the_site_frame_count(self):
        header = {"Core": "SubNESHawk", "CycleCount": "1571335974",
                  "ClockRate": "5369318.18181818"}
        doc = self.movie_doc(self.movie(header=header))
        doc["profile"]["core"] = "SubNESHawk"
        report = C.plan(doc, self.base)
        codes = [b["code"] for b in report["blockers"]]
        self.assertNotIn("movie_format", codes, codes)
        self.assertEqual(report["program"]["start"]["movie_frames"], 17588)
        self.assertEqual(report["program"]["start"]["movie_frame_source"], "cycle_count")

    def test_arm_movie_with_the_same_defect_is_also_a_blocker(self):
        movie = self.movie(header={"Core": "SubNESHawk"})
        doc = self.movie_doc(movie)
        doc["profile"]["core"] = "SubNESHawk"
        entry = {"core": "SubNESHawk", "movie": {"path": str(movie.relative_to(self.base)),
                                                 "sha256": sha256(movie)}}
        doc["verify"] = {"arms": {"samples": ["end"], "entries": [
            dict(entry, label="ref"), dict(entry, label="cand", core="QuickNes", expect="differ")]}}
        report = C.plan(doc, self.base)
        self.assertIn("movie_format", [b["code"] for b in report["blockers"]], report["blockers"])


class CoreIdentityTests(Fixture):
    def test_snes_core_names_map_to_exact_implementation(self):
        self.assertIn("LibsnesCore", core_identity_expectation("SNES", "BSNES")["sync_type"])
        self.assertIn("BsnesCore", core_identity_expectation("SNES", "BSNESv115+")["sync_type"])
        self.assertIn("Snes9x", core_identity_expectation("SNES", "Snes9x")["sync_type"])

    def test_identity_requires_deterministic_bsnes_startup_settings(self):
        for core, key, value in (("BSNES", "RandomizedInitialState", False),
                                 ("BSNESv115+", "Entropy", 0)):
            with self.subTest(core=core):
                expected = core_identity_expectation("SNES", core)
                sync = {"o": {"$type": expected["sync_type"], key: value}}
                mount = f"Mouting `{expected['waterbox']}`\n"
                self.assertEqual(verify_core_identity(expected, sync, mount)["verdict"], "pass")
                for actual in (None, 1 if core == "BSNESv115+" else True):
                    bad = {"o": {"$type": expected["sync_type"], key: actual}}
                    result = verify_core_identity(expected, bad, mount)
                    self.assertEqual(result["verdict"], "fail")
                    self.assertIn(key, result["reason"])

    def test_identity_requires_zero_frame_clr_type_and_matching_waterbox(self):
        expected = core_identity_expectation("SNES", "BSNES")
        sync = {"o": {"$type": expected["sync_type"], "RightPort": 1,
                      "RandomizedInitialState": False}}
        passed = verify_core_identity(expected, sync, "Mouting `libsnes.wbx` @123\n")
        self.assertEqual(passed["verdict"], "pass")
        self.assertTrue(passed.get("reason"), "身份成功分支也必须提供回执原因")
        wrong = {"o": {"$type": core_identity_expectation("SNES", "Snes9x")["sync_type"]}}
        self.assertEqual(verify_core_identity(expected, wrong, "Mouting `libsnes.wbx`\n")["verdict"], "fail")
        self.assertEqual(verify_core_identity(expected, sync, "Mouting `snes9x.wbx`\n")["verdict"], "fail")
        self.assertEqual(verify_core_identity(expected, sync, "Mouting `libsnes.wbx`\nMouting `snes9x.wbx`\n")["verdict"], "fail")
        self.assertEqual(verify_core_identity({}, sync, "Mouting `libsnes.wbx`\n")["verdict"], "unverified")

    def test_state_sync_adoption_preserves_exact_type_and_ports(self):
        path = self.put("identity.state", b"placeholder")
        expected = core_identity_expectation("SNES", "BSNES")["sync_type"]
        sync = {"o": {"$type": expected, "LeftPort": 1, "RightPort": 1}}
        with zipfile.ZipFile(path, "w") as state:
            state.writestr("SyncSettings.json", json.dumps(sync))
        loaded = state_sync_settings(path)
        key, adopted = adopt_state_sync_settings(loaded)
        self.assertEqual(key, "BizHawk.Emulation.Cores.Nintendo.SNES.LibsnesCore")
        self.assertEqual(adopted, sync["o"])
        self.assertEqual(adopted["RightPort"], 1)

    def test_movie_override_establishes_deterministic_settings_without_mutating_source(self):
        expected = core_identity_expectation("SNES", "BSNESv115+")
        original = self.put("source.bk2", b"placeholder")
        with zipfile.ZipFile(original, "w", compression=zipfile.ZIP_DEFLATED) as movie:
            movie.writestr("Header.txt", "Core BSNESv115+\n")
            movie.writestr("Input Log.txt", "|..|........|\n")
            movie.writestr("SyncSettings.json", json.dumps({"o": {
                "$type": expected["sync_type"], "LeftPort": 1, "RightPort": 1}}))
            movie.writestr("Core.bin", b"state-bytes")
        source_digest = sha256(original)
        derived = self.base / "derived.bk2"
        derived.write_bytes(original.read_bytes())
        applied = apply_movie_sync_settings(derived, expected, {"Entropy": 0, "LeftPort": 1, "RightPort": 1})
        self.assertEqual(applied["o"]["Entropy"], 0)
        self.assertEqual(sha256(original), source_digest)
        with zipfile.ZipFile(derived) as movie:
            sync = state_sync_settings(derived)
            self.assertEqual(movie.read("Core.bin"), b"state-bytes")
            self.assertEqual(movie.read("Input Log.txt"), b"|..|........|\n")
        self.assertEqual(sync["o"]["Entropy"], 0)
        self.assertEqual(verify_core_identity(expected, sync, "Mouting `bsnes.wbx`\n")["verdict"], "pass")
        with self.assertRaises(SchemaError):
            apply_movie_sync_settings(derived, expected, {"Entropy": 1})

    def test_identity_admission_restarts_tick_before_movie_replay(self):
        lua = LUA_RUNTIME_SOURCE
        tick = lua.split("local function tick()", 1)[1].split("local function failure", 1)[0]
        admission = tick.index("if identity_gate then")
        replay = tick.index('if current.op == "replay" then')
        self.assertLess(admission, replay)
        self.assertIn('if not identity_poll() then return "yield" end\n        return "continue"', tick,
                      "身份放行后必须重新进入 tick，先建立电影所有权再处理回放步骤")


class ArmsVerifyTests(Fixture):
    """verify.arms：同一份输入在几套核心/版本上重放到同一帧，逐采样点比 RAM 与画面。
    长度闸门只证明「跑满了」，这一层才证明「跑的是同一条时间线」——11-21 的 7429 就是这样分家的。"""

    def movie_rows(self, relative, rows, core="QuickNes", version="2.8"):
        values = {"SHA1": sha1(self.rom_bytes).upper(), "Platform": "NES", "Core": core,
                  "emuVersion": "Version " + version}
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w") as z:
            z.writestr("Header.txt", "\n".join(f"{k} {v}" for k, v in values.items()))
            z.writestr("Input Log.txt", "[Input]\nLogKey:#P1\n" + rows + "[/Input]\n")
        return self.put(relative, content.getvalue())

    def arms_doc(self, cand_core="QuickNes", samples=None, expect="agree", cand_rows=None,
                 cand_frames=8, cand_version="2.8", ref_frames=8, cand_bizhawk=None,
                 cand_header_core=None):
        ref = self.movie(frames=ref_frames, relative="movies/ref.bk2")
        rows = cand_rows if cand_rows is not None else "|..|........|\n" * cand_frames
        cand = self.movie_rows("movies/cand.bk2", rows, core=cand_header_core or cand_core, version=cand_version)
        doc = self.movie_doc(movie=ref)
        entries = [{"label": "ref", "core": "NesHawk", "movie": {"path": str(ref), "sha256": sha256(ref)}}]
        entries.append({"label": "cand", "core": cand_core, "expect": expect,
                        "bizhawk": cand_bizhawk or f"emulators/BizHawk/BizHawk-{cand_version}",
                        "movie": {"path": str(cand), "sha256": sha256(cand)}})
        doc["verify"] = {"arms": {"samples": samples if samples is not None else [4],
                                  "compare": ["ram", "png"], "source": "fixture", "entries": entries}}
        return doc, ref, cand

    def arms_executor(self, ram, png=None):
        """按臂标签发采样字节：值可以是整臂一个 blob，也可以是 {采样点: blob}。"""
        inner = self.executor()

        def pick(table, label, name):
            value = (table or {}).get(label, b"identical")
            return value[name] if isinstance(value, dict) else value

        def execute(program, attempt, work, timeout):
            out = inner(program, attempt, work, timeout)
            if "__arm_" not in program["id"]:
                return out
            label = program["id"].split("__arm_", 1)[1]
            checkpoints, frame = {}, 0
            for step in program["steps"]:
                if step["op"] == "replay" and step["frames"] != "end":
                    frame += step["frames"]
                elif step["op"] == "checkpoint":
                    name = step["name"]
                    ram_path = Path(attempt) / (name + ".ram")
                    ram_path.write_bytes(pick(ram, label, name))
                    png_path = Path(attempt) / (name + ".png")
                    png_path.write_bytes(pick(png, label, name) if png is not None else b"frame")
                    checkpoints[name] = {"frame": frame, "screenshot": str(png_path),
                                        "ram": {"path": str(ram_path), "bytes": ram_path.stat().st_size}}
            out["checkpoints"] = checkpoints
            return out
        return execute

    def codes(self, report):
        return [b["code"] for b in report.get("blockers", [])]

    def test_reference_arm_must_be_the_task_itself(self):
        doc, ref, cand = self.arms_doc()
        doc["verify"]["arms"]["entries"][0]["movie"]["path"] = str(cand)
        with self.assertRaises(C.SchemaError) as caught:
            C.normalize(doc, self.base)
        self.assertIn("参照臂必须就是本任务的初态电影", str(caught.exception))
        doc, ref, cand = self.arms_doc()
        doc["verify"]["arms"]["entries"][0]["core"] = "QuickNes"
        with self.assertRaises(C.SchemaError) as caught:
            C.normalize(doc, self.base)
        self.assertIn("参照臂的核心/版本", str(caught.exception))
        boot = self.session()
        boot["verify"] = deepcopy(self.arms_doc()[0]["verify"])
        with self.assertRaises(C.SchemaError) as caught:
            C.normalize(boot, self.base)
        self.assertIn("start.kind=movie", str(caught.exception))

    def test_schema_rejects_malformed_arms(self):
        cases = {
            "只有一条臂": lambda d: d["verify"]["arms"].update(entries=d["verify"]["arms"]["entries"][:1]),
            "帧号不递增": lambda d: d["verify"]["arms"].update(samples=[5, 4]),
            "end 不在最后": lambda d: d["verify"]["arms"].update(samples=["end", 10]),
            "采样点为空": lambda d: d["verify"]["arms"].update(samples=[]),
            "不可比的维度": lambda d: d["verify"]["arms"].update(compare=["audio"]),
            "维度重复": lambda d: d["verify"]["arms"].update(compare=["ram", "ram"]),
            "标签重复": lambda d: d["verify"]["arms"]["entries"][1].update(label="ref"),
            "非法期望": lambda d: d["verify"]["arms"]["entries"][1].update(expect="same"),
            "臂没给电影": lambda d: d["verify"]["arms"]["entries"][1].pop("movie"),
            "臂电影没摘要": lambda d: d["verify"]["arms"]["entries"][1]["movie"].pop("sha256"),
            "未知字段": lambda d: d["verify"]["arms"].update(tolerance=0.1),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name):
                doc = self.arms_doc()[0]
                mutate(doc)
                self.assertRaises(C.SchemaError, C.normalize, doc, self.base)
        doc = self.arms_doc()[0]
        doc["verify"]["arms"]["samples"] = ["end"]
        self.assertEqual(C.normalize(doc, self.base)[0]["verify"]["arms"]["samples"], ["end"])

    def test_duplicate_core_and_version_candidate_is_rejected(self):
        doc, _, cand = self.arms_doc()
        doc["verify"]["arms"]["entries"][1]["core"] = doc["profile"]["core"]
        doc["verify"]["arms"]["entries"][1]["bizhawk"] = doc["profile"]["bizhawk"]
        with self.assertRaises(SchemaError) as caught:
            C.normalize(doc, self.base)
        self.assertIn("相同核心和相同 BizHawk", str(caught.exception))

    def test_arm_doc_swaps_core_and_injects_samples(self):
        base = self.arms_doc(samples=[4, 8])[0]
        base["record"] = {"video": True, "audio": True, "speed": "unthrottled", "frameskip": 4}
        doc = base
        normalized = C.normalize(doc, self.base)[0]
        cfg = normalized["verify"]["arms"]
        arm = C._arm_doc(normalized, cfg["entries"][1], 1, cfg["samples"])
        self.assertEqual(arm["profile"]["core"], "QuickNes")
        self.assertEqual(arm["id"], doc["id"] + "__arm_cand")
        self.assertEqual(arm["start"]["kind"], "movie")
        self.assertTrue(Path(arm["start"]["path"]).is_file())
        self.assertEqual([s["op"] for s in arm["steps"]], ["replay", "checkpoint", "replay", "checkpoint"])
        self.assertEqual([s.get("frames") for s in arm["steps"] if s["op"] == "replay"], [4, 4])
        self.assertEqual([s["name"] for s in arm["steps"] if s["op"] == "checkpoint"],
                         ["sample_000", "sample_001"])
        self.assertEqual(arm["verify"], {})
        self.assertEqual(arm["completion"], {})
        self.assertEqual(arm["record"], {"speed": "unthrottled", "frameskip": 4},
                         "采样臂只继承速度档：33000 帧按实时走要白等十几分钟，视频/音频则留给主任务")
        reference = C._arm_doc(normalized, cfg["entries"][0], 0, cfg["samples"])
        self.assertEqual(reference["profile"]["core"], "NesHawk")
        self.assertEqual(reference["start"]["sha256"], normalized["start"]["sha256"])
        tail = C._arm_doc(normalized, cfg["entries"][1], 1, ["end"])
        self.assertEqual(tail["steps"][0]["frames"], "end")

    def test_identity_missing_from_any_arm_makes_sync_fail(self):
        normalized = C.normalize(self.arms_doc(samples=[4, 8])[0], self.base)[0]
        from taspipe import fceux
        result = {"verification": {"execution": "pass"},
                  "runtime": {"checkpoints": {}, "events": []}}
        with mock.patch.object(C, "run", return_value=result), \
             mock.patch.object(fceux, "input_log_digest", return_value="a" * 64):
            report = C._run_arms(normalized, self.base, self.base / "sync_identity_absent",
                                 self.base / "sync_work", 1)
        self.assertEqual(report["sync"], "fail")
        self.assertIn("核心身份", report["sync_reason"])

    def test_sync_rejects_different_input_logs_even_when_samples_match(self):
        normalized = C.normalize(self.arms_doc(samples=[4, 8])[0], self.base)[0]
        from taspipe import fceux
        result = {"verification": {"execution": "pass", "core_identity": "pass"},
                  "runtime": {"checkpoints": {}, "events": []}}
        with mock.patch.object(C, "run", return_value=result), \
             mock.patch.object(fceux, "input_log_digest", side_effect=["a" * 64, "b" * 64]):
            report = C._run_arms(normalized, self.base, self.base / "sync_input_mismatch",
                                 self.base / "sync_work", 1)
        self.assertEqual(report["sync"], "fail")
        self.assertFalse(report["input_log_identical"])
        self.assertIn("Input Log.txt", report["sync_reason"])

    def test_plan_checks_arm_identity_before_launch(self):
        doc = self.arms_doc()[0]
        self.assertEqual(C.plan(doc, self.base)["status"], "ready", C.plan(doc, self.base)["blockers"])
        cases = {
            "头部核心与声明不符": (dict(cand_header_core="NesHawk"), ["arm_profile_mismatch"]),
            "版本目录没装": (dict(cand_bizhawk="emulators/BizHawk/BizHawk-9.9"), ["missing_emulator"]),
            "卡核版本": (dict(cand_version="2.3", extra_install="2.3"), ["driver_stall_measured"]),
            "臂根本不同长": (dict(cand_frames=6), ["arm_length_mismatch"]),
            "输入层被改过": (dict(cand_rows="|..|........|\n" * 7 + "|AB|........|\n"),
                            ["arm_input_log_mismatch"]),
            "采样点超出片长": (dict(samples=[99]), ["arm_sample_out_of_range"]),
            "头版本与目录版本不符": (dict(cand_bizhawk="emulators/BizHawk/BizHawk-2.9",
                                         extra_install="2.9"), ["arm_emulator_version_unverified"]),
        }
        for name, (kwargs, want) in cases.items():
            with self.subTest(case=name):
                extra = kwargs.pop("extra_install", None)
                if extra:
                    self.put(f"emulators/BizHawk/BizHawk-{extra}/EmuHawk.exe", b"fixture-not-executable")
                report = C.plan(self.arms_doc(**kwargs)[0], self.base)
                self.assertEqual(report["status"], "blocked", report)
                for code in want:
                    self.assertIn(code, self.codes(report), report["blockers"])
        for kwargs in ({}, dict(cand_rows="|..|........|\n" * 8), dict(samples=[4, 8]), dict(samples=["end"])):
            with self.subTest(control=kwargs):
                self.assertEqual(self.codes(C.plan(self.arms_doc(**kwargs)[0], self.base)), [], kwargs)

    def test_tampered_or_missing_arm_movie_blocks_launch(self):
        doc, ref, cand = self.arms_doc()
        cand.write_bytes(b"replaced after registering")
        self.assertIn("arm_movie_mismatch", self.codes(C.plan(doc, self.base)))
        cand.unlink()
        self.assertIn("missing_arm_movie", self.codes(C.plan(doc, self.base)))

    def test_same_bytes_on_both_arms_is_sync_pass(self):
        report = self.run_doc(self.arms_doc()[0], executor=self.arms_executor({"ref": b"RAM-A", "cand": b"RAM-A"}))
        arms = report["arms"]
        self.assertEqual((report["status"], report["verification"]["sync"]), ("done", "pass"))
        self.assertTrue(arms["input_log_identical"], arms["input_logs"])
        self.assertEqual([a["role"] for a in arms["arms"]], ["reference", "candidate"])
        self.assertEqual([p["comparison"]["agree"] for p in arms["pairs"]], [True])
        self.assertEqual(arms["arms"][1]["samples"]["sample_000"]["frame"], 4)
        self.assertEqual(arms["samples"], [4])

    def test_allow_is_forwarded_to_every_derived_arm(self):
        seen = []

        def run_arm(*args, **kwargs):
            seen.append(tuple(kwargs.get("allow") or ()))
            return REAL_RUN(*args, **kwargs)

        with mock.patch.object(C, "run", side_effect=run_arm):
            report = self.run_doc(
                self.arms_doc()[0], executor=self.arms_executor({"ref": b"RAM-A", "cand": b"RAM-A"}),
                allow=("emulator_version_inherited",))
        self.assertEqual(report["verification"]["sync"], "pass", report.get("arms"))
        self.assertEqual(seen, [("emulator_version_inherited",), ("emulator_version_inherited",)])

    def test_diverging_candidate_fails_sync(self):
        report = self.run_doc(self.arms_doc()[0], executor=self.arms_executor({"ref": b"RAM-A", "cand": b"RAM-B"}))
        pair = report["arms"]["pairs"][0]["comparison"]
        self.assertEqual(report["verification"]["sync"], "fail")
        self.assertEqual(report["status"], "inconclusive", report["status"])
        self.assertEqual(pair["first_divergent_frame"], 4)
        self.assertEqual({d["kind"] for d in pair["divergent"]}, {"ram"}, pair["divergent"])
        self.assertIn("帧 4 起分叉", report["arms"]["sync_reason"])

    def test_png_only_divergence_is_also_caught(self):
        report = self.run_doc(self.arms_doc()[0], executor=self.arms_executor(
            {"ref": b"RAM-A", "cand": b"RAM-A"}, png={"ref": b"pic-a", "cand": b"pic-b"}))
        pair = report["arms"]["pairs"][0]["comparison"]
        self.assertEqual({d["kind"] for d in pair["divergent"]}, {"png"}, pair["divergent"])
        self.assertEqual(report["verification"]["sync"], "fail")

    def test_frame_count_divergence_is_a_desync_not_a_gap(self):
        inner = self.arms_executor({"ref": b"RAM-A", "cand": b"RAM-A"})

        def shifted(program, attempt, work, timeout):
            if "__arm_cand" in program["id"]:
                program = deepcopy(program)
                program["steps"][0]["frames"] = 3
            return inner(program, attempt, work, timeout)
        report = self.run_doc(self.arms_doc()[0], executor=shifted)
        pair = report["arms"]["pairs"][0]["comparison"]
        self.assertEqual(report["verification"]["sync"], "fail", pair)
        self.assertEqual({d["kind"] for d in pair["divergent"]}, {"frame"}, pair["divergent"])
        self.assertEqual(pair["first_divergent_frame"], 4)

    def test_missing_sample_is_a_gap_not_an_agreement(self):
        inner = self.arms_executor({"ref": b"RAM-A", "cand": b"RAM-A"})

        def dropped(program, attempt, work, timeout):
            if "__arm_cand" in program["id"]:
                program = deepcopy(program)
                program["steps"] = [program["steps"][0]]
            return inner(program, attempt, work, timeout)
        report = self.run_doc(self.arms_doc(samples=[4, 8], cand_bizhawk=None)[0], executor=dropped)
        pair = report["arms"]["pairs"][0]["comparison"]
        self.assertEqual(report["verification"]["sync"], "fail", pair)
        self.assertTrue(pair["gaps"], pair)

    def test_inverted_control_blind_judge_cannot_pass(self):
        blind = self.run_doc(self.arms_doc(expect="differ")[0], out=self.base / "out-diff-blind",
                             executor=self.arms_executor({"ref": b"RAM-A", "cand": b"RAM-A"}))
        self.assertEqual(blind["verification"]["sync"], "inconclusive", blind["arms"])
        self.assertIn("看不见差异", blind["arms"]["sync_reason"])
        only_differ = self.run_doc(self.arms_doc(expect="differ")[0], out=self.base / "out-diff-real",
                                   executor=self.arms_executor({"ref": b"RAM-A", "cand": b"RAM-B"}))
        self.assertEqual(only_differ["verification"]["sync"], "inconclusive", only_differ["arms"])
        self.assertIn("一致项", only_differ["arms"]["sync_reason"])

    def test_agree_plus_differ_pair_needs_both_halves(self):
        doc, ref, cand = self.arms_doc()
        self.put("emulators/BizHawk/BizHawk-2.10/EmuHawk.exe", b"fixture-not-executable")
        other = self.movie_rows("movies/other.bk2", "|..|........|\n" * 8, core="quickerNES", version="2.10")
        doc["verify"]["arms"]["entries"].append(
            {"label": "third", "core": "quickerNES", "expect": "differ",
             "bizhawk": "emulators/BizHawk/BizHawk-2.10", "movie": {"path": str(other), "sha256": sha256(other)}})
        blind = self.run_doc(deepcopy(doc), out=self.base / "out-blind", executor=self.arms_executor(
            {"ref": b"RAM-A", "cand": b"RAM-A", "third": b"RAM-A"}))
        self.assertEqual([p["expect"] for p in blind["arms"]["pairs"]], ["agree", "differ"])
        self.assertEqual(blind["verification"]["sync"], "inconclusive", blind["arms"]["sync_reason"])
        good = self.run_doc(deepcopy(doc), out=self.base / "out-good", executor=self.arms_executor(
            {"ref": b"RAM-A", "cand": b"RAM-A", "third": b"RAM-C"}))
        self.assertEqual([p["comparison"]["agree"] for p in good["arms"]["pairs"]], [True, False], good["arms"])
        self.assertEqual(good["verification"]["sync"], "pass", good["arms"]["sync_reason"])
        self.assertEqual(len(good["arms"]["arms"]), 3)

    def test_unrunnable_candidate_blocks_the_task_before_launch(self):
        self.put("emulators/BizHawk/BizHawk-2.3/EmuHawk.exe", b"fixture-not-executable")
        stub = self.arms_executor({"ref": b"RAM-A"})
        report = self.run_doc(self.arms_doc(cand_bizhawk="emulators/BizHawk/BizHawk-2.3")[0], executor=stub)
        self.assertEqual(report["status"], "blocked", report)
        self.assertIn("driver_stall_measured", self.codes(report))
        self.assertNotIn("arms", report)
        self.assertEqual(self.calls, [], "臂跑不成还开主回放，等于白烧一遍片长")

    def test_arm_crash_is_contained_inside_the_report(self):
        inner = self.arms_executor({"ref": b"RAM-A", "cand": b"RAM-A"})

        def boom(program, attempt, work, timeout):
            if "__arm_cand" in program["id"]:
                raise RuntimeError("stub arm crash")
            return inner(program, attempt, work, timeout)
        report = self.run_doc(self.arms_doc()[0], executor=boom)
        self.assertEqual(report["verification"]["sync"], "fail", report["arms"])
        self.assertIn("核心身份", report["arms"]["sync_reason"])
        self.assertIn("stub arm crash", report["arms"]["arms"][1]["reason"])

    def test_no_arms_declared_keeps_sync_unverified(self):
        report = self.run_doc(self.movie_doc(), executor=self.executor())
        self.assertEqual(report["verification"]["sync"], "unverified")
        self.assertNotIn("arms", report)
        self.assertTrue(report["artifacts"])

    def test_arms_change_the_fingerprint_and_reuse_is_per_arm(self):
        doc = self.arms_doc()[0]
        stub = self.arms_executor({"ref": b"RAM-A", "cand": b"RAM-A"})
        first = self.run_doc(deepcopy(doc), executor=stub, out=self.base / "out-a")
        second = self.run_doc(deepcopy(doc), executor=stub, out=self.base / "out-a")
        self.assertTrue(second["reused"], second["status"])
        self.assertEqual(first["fingerprint"], second["fingerprint"])
        doc["verify"]["arms"]["samples"] = [6]
        changed = self.run_doc(deepcopy(doc), executor=stub, out=self.base / "out-a")
        self.assertFalse(changed["reused"], changed)
        self.assertNotEqual(changed["fingerprint"], first["fingerprint"])
        doc["verify"]["arms"]["compare"] = ["ram"]
        narrow = self.run_doc(deepcopy(doc), executor=stub, out=self.base / "out-a")
        self.assertNotEqual(narrow["fingerprint"], changed["fingerprint"], "只比 RAM 必须是另一份指纹")


class RomPatchTests(Fixture):
    def test_original_unchanged_and_exact_bytes_hash_and_length(self):
        original = (self.rom.read_bytes(), self.rom.stat().st_mtime_ns, sha256(self.rom))
        doc = self.rom_patch()
        doc["patches"].append({"offset": "0x3f", "expect": "3f", "value": "ff"})
        report = self.run_doc(doc)
        self.assertEqual(report["status"], "done")
        target = Path(report["artifacts"][0]["uri"])
        expected = self.rom_bytes[:2] + bytes.fromhex("aabbcc") + self.rom_bytes[5:63] + b"\xff"
        self.assertNotEqual(target, self.rom)
        self.assertEqual(target.read_bytes(), expected)
        self.assertEqual(target.stat().st_size, len(self.rom_bytes))
        self.assertEqual(report["modified_rom_sha1"], sha1(expected))
        self.assertEqual(report["source_rom_sha1"], sha1(self.rom_bytes))
        self.assertEqual((self.rom.read_bytes(), self.rom.stat().st_mtime_ns, sha256(self.rom)), original)
        self.assertEqual(self.calls, [])
        self.assert_artifacts(report)

    def test_prevalue_and_range_errors_block_without_products(self):
        for patch in ({"offset": 2, "expect": "dead", "value": "beef"}, {"offset": 63, "expect": "3f00", "value": "aabb"}):
            with self.subTest(patch=patch):
                doc = self.rom_patch()
                doc["patches"] = [patch]
                self.assert_blocked(doc, "patch_precondition")
                result = self.run_doc(doc)
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["artifacts"], [])
                self.assertEqual(list(self.out.glob("attempt_*")), [])
                self.assertEqual(self.rom.read_bytes(), self.rom_bytes)

    def test_wrong_rom_hash_blocked(self):
        doc = self.rom_patch()
        doc["rom"]["sha1"] = "0" * 40
        self.assert_blocked(doc, "rom_mismatch")
        self.assertEqual(self.run_doc(doc)["status"], "blocked")
        self.assertEqual(self.rom.read_bytes(), self.rom_bytes)

    def test_bad_patch_lengths_types_overlap_and_bool_offset(self):
        for patches in ([{"offset": 2, "expect": "0203", "value": "aa"}],
                        [{"offset": True, "expect": "01", "value": "aa"}],
                        [{"offset": 2, "expect": "0", "value": "a"}],
                        [{"offset": 2, "expect": "zz", "value": "aa"}],
                        [{"offset": 2, "expect": "02", "value": ""}],
                        [{"offset": 2, "expect": "0203", "value": "aabb"}, {"offset": 3, "expect": "03", "value": "cc"}]):
            with self.subTest(patches=patches), self.assertRaises(SchemaError):
                doc = self.rom_patch()
                doc["patches"] = patches
                C.normalize(doc, self.base)

    def test_toctou_rom_change_outside_patch_must_not_be_accepted(self):
        def write_then_change(path, value):
            REAL_WRITE_JSON(path, value)
            if Path(path).name == "plan.json":
                changed = bytearray(self.rom.read_bytes())
                changed[-1] ^= 0x80  # expect bytes still match, but SHA1 no longer does.
                self.rom.write_bytes(changed)
        with mock.patch.object(C, "write_json", side_effect=write_then_change):
            report = self.run_doc(self.rom_patch())
        self.assertEqual(report["status"], "failed", "ROM changed after plan: run must revalidate the complete source SHA1")
        self.assertEqual(report["verification"]["execution"], "fail")

    def test_output_manifest_collision_must_not_overwrite_original(self):
        # Valid JSON avoids an incidental JSONDecodeError masking the collision.
        original = b'{"fixture":true}'
        source = self.put("collision/control.json", original)
        doc = self.rom_patch()
        doc["rom"] = {"path": str(source), "sha1": sha1(original)}
        doc["patches"] = [{"offset": 0, "expect": "7b", "value": "5b"}]
        try:
            self.run_doc(doc, out=source.parent)
        except (SchemaError, ValueError):
            pass  # A clean pre-write rejection is also acceptable.
        self.assertEqual(source.read_bytes(), original, "out/control.json aliases the source ROM; original must remain untouched")


class ZipRomTests(Fixture):
    """`包.zip!内部条目` 寻址：只认条目字节的 SHA-1，原包一个字节都不许动。

    11-21 用户点名 F:\\BaiduNetdiskDownload\\rom\\snes\\*.zip 之后才接进生产。魂斗罗3、
    卡比超级之星、洛克人X3 的 ROM 早就在本地，只是当时的 preflight 只会整文件哈希，
    把压缩包整包哈希当成 ROM 哈希，于是要么报 rom_mismatch 要么报 missing_rom。
    """

    def pack(self, entry="内层/演示.sfc", payload=None, name="pools/演示 包.zip"):
        data = self.rom_bytes if payload is None else payload
        blob = io.BytesIO()
        with zipfile.ZipFile(blob, "w") as z:
            z.writestr(entry, data)
            z.writestr("readme.txt", "不是 ROM")
        return self.put(name, blob.getvalue()), entry, data

    def zip_doc(self, archive, entry, digest, platform="GBA", system=None):
        # 默认用 GBA：SNES 在 11-21 已经实测过整片、进了白名单，再拿它当"资源齐但没实测"
        # 的例子就成了假样本。GBA 的 ROM 也在同一个百度池里，寻址形状一样。
        doc = self.session()
        doc["platform"] = platform
        doc["rom"] = {"path": f"{archive}!{entry}", "sha1": digest}
        doc["profile"]["core"] = "bsnes" if platform == "SNES" else "mGBA"
        doc["profile"]["system"] = system or platform
        return doc

    def test_split_rom_spec_forms(self):
        from taspipe.schema import split_rom_spec
        cases = [
            ("d:/池/rom.nes", Path("d:/池/rom.nes"), None),
            ("d:/池/rom.zip!inner/x.sfc", Path("d:/池/rom.zip"), "inner/x.sfc"),
            # 大小写混着写也是 zip；条目名里的 ! 属于条目名，不再切第二刀。
            ("d:/池/ROM.ZIP!a!b.sfc", Path("d:/池/ROM.ZIP"), "a!b.sfc"),
            ("d:/池/rom.7z!x.sfc", Path("d:/池/rom.7z!x.sfc"), None),
        ]
        for spec, want_archive, want_entry in cases:
            with self.subTest(spec=spec):
                self.assertEqual(split_rom_spec(spec), (want_archive, want_entry))

    def test_plan_accepts_the_entry_digest_and_keeps_the_spec(self):
        archive, entry, data = self.pack()
        doc = self.zip_doc(archive, entry, sha1(data))
        report = C.plan(doc, self.base, ("driver_platform_unproven",))
        self.assertEqual(report["status"], "ready", "压缩包内条目哈希命中就必须就绪，不许再当缺 ROM")
        self.assertEqual([b["code"] for b in report["warnings"]], ["driver_platform_unproven"],
                         "降级只改这条的拦法，理由必须原样留在产物里")

    def test_resource_ready_is_not_the_same_as_driver_proven(self):
        archive, entry, data = self.pack()
        report = C.plan(self.zip_doc(archive, entry, sha1(data)), self.base)
        self.assertEqual(report["status"], "blocked")
        self.assertIn("driver_platform_unproven", [b["code"] for b in report["blockers"]],
                      "GBA 资源齐但驱动没实测过，不许登记成能跑")

    def test_run_passes_the_same_spec_to_the_runtime(self):
        archive, entry, data = self.pack()
        report = self.run_doc(self.zip_doc(archive, entry, sha1(data)),
                              allow=("driver_platform_unproven",))
        self.assertEqual(report["status"], "done")
        self.assertEqual([b["code"] for b in report["warnings"]], ["driver_platform_unproven"],
                         "实测跑过的证据里必须写着当时是靠哪条降级跑起来的")
        spec = self.calls[0]["rom"]
        self.assertTrue(spec.startswith(str(archive.resolve())), spec)
        self.assertTrue(spec.endswith("!" + entry), spec)

    def test_whole_package_hash_is_not_the_rom_hash(self):
        archive, entry, data = self.pack()
        report = C.plan(self.zip_doc(archive, entry, sha1(archive.read_bytes())), self.base)
        self.assertEqual(report["status"], "blocked")
        self.assertIn("rom_mismatch", [b["code"] for b in report["blockers"]],
                      "整包哈希当条目哈希用是假命中，必须拦下")

    def test_missing_entry_is_missing_rom_not_mismatch(self):
        archive, _entry, data = self.pack()
        report = C.plan(self.zip_doc(archive, "内层/没有.sfc", sha1(data)), self.base)
        self.assertEqual(report["status"], "blocked")
        self.assertIn("missing_rom", [b["code"] for b in report["blockers"]])

    def test_absent_package_is_missing_rom(self):
        archive, entry, data = self.pack()
        gone = self.base / "pools/不存在.zip"
        report = C.plan(self.zip_doc(gone, entry, sha1(data)), self.base)
        self.assertEqual(report["status"], "blocked")
        self.assertIn("missing_rom", [b["code"] for b in report["blockers"]])

    def test_rom_patch_refuses_a_package_spec(self):
        archive, entry, data = self.pack()
        doc = self.rom_patch()
        doc["rom"] = {"path": f"{archive}!{entry}", "sha1": sha1(data)}
        with self.assertRaises(SchemaError):
            C.plan(doc, self.base)
        self.assertTrue(archive.is_file(), "被拒绝的补丁任务也不许留下半个包外产物")

    def test_package_bytes_untouched_after_a_run(self):
        archive, entry, data = self.pack()
        doc = self.zip_doc(archive, entry, sha1(data))
        before = (archive.stat().st_size, sha1(archive.read_bytes()))
        with mock.patch.object(C, "write_json", wraps=REAL_WRITE_JSON) as sink:
            self.assertEqual(self.run_doc(doc, out=self.out / "zip",
                                          allow=("driver_platform_unproven",))["status"], "done")
        self.assertTrue(sink.called)
        self.assertEqual((archive.stat().st_size, sha1(archive.read_bytes())), before,
                         "模拟器只吃导出的独立文件，原包必须逐字节不变")

    def test_registry_indexes_package_entries_by_content(self):
        lib = self.base / "lib"
        pool = self.base / "pool"
        rom = b"SFC" * 200
        blob = io.BytesIO()
        with zipfile.ZipFile(blob, "w") as z:
            z.writestr(" Contra 3 .sfc", rom)
            z.writestr("cover.png", b"not a rom")
        self.put("pool/魂斗罗 3.zip", blob.getvalue())
        self.put("pool/散文件.sfc", b"loose")
        idx = R.index_roms(lib, extra_roots=(pool,))
        hits = idx.get(sha1(rom).upper(), [])
        self.assertEqual(len(hits), 1, hits)
        self.assertEqual(hits[0], str(pool / "魂斗罗 3.zip") + "! Contra 3 .sfc",
                         "条目寻址必须写成 包!条目，控制层才认得")
        self.assertNotIn(sha1(b"not a rom").upper(), idx, "非 ROM 后缀不许进索引")
        self.assertIn(sha1(b"loose").upper(), idx, "散文件仍按整文件哈希收录")


class DriverProvenTests(Fixture):
    """「资源齐」和「这台机器的驱动在该平台实测过整片」是两件事，闸门必须分开报。

    11-21 找到 F:\\BaiduNetdiskDownload 里的 ROM 之后，SNES 一次性从 0 变成若干部
    replayable；当时台账还不能直接写「能跑」，直到 pub_5628 整片实测（输入全消费
    +Δ1 帧+末帧真看图）才进白名单。现在 GBA 顶替 SNES 当"资源齐但没实测"的样本。
    """

    def session_for(self, platform, system):
        doc = self.session()
        doc["platform"] = platform
        doc["profile"] = {"bizhawk": str(self.bh.relative_to(self.base)),
                          "core": "NesHawk" if system == "NES" else "BSNES", "system": system}
        return doc

    def codes(self, report):
        return [b["code"] for b in report["blockers"]]

    def test_measured_platform_has_no_new_blocker(self):
        self.assertNotIn("driver_platform_unproven", self.codes(C.plan(self.session(), self.base)),
                         "NES 已实测过整片，闸门不许再拦它")

    def test_every_unmeasured_platform_is_named_not_lumped_as_missing_rom(self):
        for platform, system in (("GBA", "GBA"), ("GB", "GB"),
                                 ("GBC", "GBC"), ("MD", "GEN"), ("PCE", "PCE")):
            with self.subTest(platform=platform):
                report = C.plan(self.session_for(platform, system), self.base)
                self.assertEqual(self.codes(report), ["driver_platform_unproven"], report["blockers"])
                self.assertIn(platform, report["blockers"][0]["reason"])

    def test_independent_backends_keep_their_own_code(self):
        self.assertIn("backend_not_wired",
                      self.codes(C.plan(self.session_for("PSP", "PSP"), self.base)),
                      "PPSSPP/FBNeo 是后端没接，不是没实测")

    def test_allow_downgrades_without_erasing_the_gap(self):
        report = C.plan(self.session_for("GBA", "GBA"), self.base, ("driver_platform_unproven",))
        self.assertEqual(report["status"], "ready")
        self.assertEqual([b["code"] for b in report["warnings"]], ["driver_platform_unproven"])
        self.assertIn("实测", report["warnings"][0]["reason"])
        self.assertEqual(self.codes(report), [])

    def test_proven_list_is_the_only_way_to_widen_the_gate(self):
        # 白名单只能靠实测证据加长，界面/配置没有静默放宽的口子。
        # SNES 是 11-21 拿 pub_5628（洛克人X2，111725 输入行全消费、Δ1 帧、末帧看图）加进来的。
        self.assertEqual(C.PLATFORMS_DRIVER_PROVEN, ("NES", "SNES"))
        self.assertTrue(C.platform_driver_proven("NES"))
        self.assertTrue(C.platform_driver_proven("SNES"))
        self.assertFalse(C.platform_driver_proven("nes"))
        self.assertFalse(C.platform_driver_proven("GBA"))
        self.assertFalse(C.platform_driver_proven(""))


class ArmInheritanceTests(Fixture):
    """站点登记的 BizHawk 版本本机没装时，臂可以照抄同 ROM 原生片，但必须留痕、必须拦一次。

    11-21 用户实测口径「跟版本没有关系」：库里 895 部片登记的 1.11.7/2.5.2 本机都没有，
    全报成「版本没装」是台账在骗人——DK 的 3789@2.3.0→5254@2.9 早就靠同 ROM 的另一部片
    走通了。但借来的臂在这个 ROM 上没实测过整片，所以它只能是 emulator_version_inherited，
    不能悄悄变成 replayable。
    """

    def bk2_pub(self, pid, emu_version, emulator=None, frames=8):
        self.movie(header={"SHA1": sha1(self.rom_bytes).upper(), "Platform": "NES",
                           "Core": "NesHawk", "emuVersion": f"Version {emu_version}"},
                   frames=frames, relative=f"movies/NES/{pid}.bk2")
        return {"id": pid, "game": "演示", "title": f"pub{pid}", "platform": "NES",
                "movie_ext": "bk2", "local_movie": f"movies/NES/{pid}.bk2",
                "emulator": emulator or f"BizHawk {emu_version}", "time": "00:00.133",
                "version_id": f"v{pid}"}

    def assess(self, pubs, target, bizhawk=None):
        import taspipe.registry as R
        dirs = bizhawk or {"2.8": self.bh}
        rom_idx = {R.norm_sha1(sha1(self.rom_bytes)): [str(self.rom)]}
        with mock.patch.object(R, "load_publications", return_value=pubs):
            return R.assess(next(p for p in pubs if str(p["id"]) == str(target)),
                             self.base, rom_idx, {}, dirs)

    def codes(self, report):
        return [b["code"] for b in report["blockers"]]

    def test_absent_version_with_a_drivable_sibling_becomes_inherited(self):
        pubs = [self.bk2_pub("5001", "1.11.7", emulator="BizHawk 1.11.7"),
                self.bk2_pub("5002", "2.8")]
        report = self.assess(pubs, "5001")
        self.assertIn("emulator_version_inherited", self.codes(report), report["blockers"])
        self.assertNotIn("emulator_version_absent", self.codes(report),
                         "已经有可驱动的参照臂，就不许再报成『版本没装』")
        self.assertEqual(report["status"], "blocked", "继承来的臂不等于可回放")
        self.assertEqual(Path(report["emulator_dir"]), self.bh, "臂必须落到本机装好的那台")
        inh = report["arm_inherited_from"]
        self.assertEqual((inh["pub_id"], inh["used"], inh["declared"]),
                         ("5002", "2.8", "BizHawk 1.11.7"))

    def test_absent_version_without_sibling_stays_absent(self):
        report = self.assess([self.bk2_pub("5001", "1.11.7", emulator="BizHawk 1.11.7")], "5001")
        self.assertEqual(self.codes(report), ["emulator_version_absent"],
                         "没有同 ROM 参照就是真缺版本，不许编一台臂出来")
        self.assertIsNone(report["arm_inherited_from"])

    def test_inheritance_skips_the_stalled_sibling(self):
        stalled = self.emu_root / "BizHawk/BizHawk-2.3"
        self.put("emulators/BizHawk/BizHawk-2.3/EmuHawk.exe", b"fixture-not-executable")
        pubs = [self.bk2_pub("5001", "1.11.7", emulator="BizHawk 1.11.7"),
                self.bk2_pub("5002", "2.3"), self.bk2_pub("5003", "2.8")]
        report = self.assess(pubs, "5001", bizhawk={"2.3": stalled, "2.8": self.bh})
        self.assertEqual(report["arm_inherited_from"]["pub_id"], "5003",
                         "2.3 实测卡核，继承必须跳过它挑未卡核的那部")

    def inherited_doc(self):
        doc = self.session()
        doc["provenance"] = {"arm_inherited_from": {"pub_id": "5002", "declared": "BizHawk 1.11.7",
                                                   "used": "2.8", "core": "NesHawk"}}
        return doc

    def test_plan_blocks_inherited_arm_until_allowed(self):
        report = C.plan(self.inherited_doc(), self.base)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(self.codes(report), ["emulator_version_inherited"])
        self.assertIn("5002", report["blockers"][0]["reason"])

    def test_allow_downgrades_and_stays_in_the_artifact(self):
        report = self.run_doc(self.inherited_doc(), allow=("emulator_version_inherited",))
        self.assertEqual(report["status"], "done")
        self.assertEqual([b["code"] for b in report["warnings"]], ["emulator_version_inherited"])
        plan_doc = json.loads((Path(report["attempt_dir"]) / "plan.json").read_text(encoding="utf-8"))
        self.assertEqual(plan_doc["spec"]["provenance"]["arm_inherited_from"]["pub_id"], "5002",
                         "跑出来的产物必须写着这台臂是跟谁抄的")

    def test_bom_prefixed_header_still_yields_the_rom_sha1(self):
        """BizHawk 原生 Header.txt 可能带 BOM：剥不掉就静默退回 version 页找哈希。"""
        import taspipe.registry as R
        for bom, label in (("\ufeff", "带 BOM"), ("", "不带 BOM")):
            path = self.movie(raw_header=(bom + "\n".join([
                f"SHA1 {sha1(self.rom_bytes).upper()}", "Platform NES",
                "Core NesHawk", "emuVersion Version 2.8"])).encode("utf-8"),
                relative=f"movies/NES/bom{label}.bk2")
            with self.subTest(header=label):
                self.assertEqual(R.read_bk2_header(path)["SHA1"], sha1(self.rom_bytes).upper())

    def test_provenance_shape_is_enforced(self):
        for bad in ({"arm_inherited_from": {"pub_id": "5002"}},
                    {"arm_inherited_from": {"pub_id": "5002", "declared": "x", "used": "2.8", "extra": 1}},
                    {"unexpected": 1}):
            doc = self.inherited_doc()
            doc["provenance"] = bad
            with self.subTest(provenance=bad), self.assertRaises(SchemaError):
                C.normalize(doc, self.base)


class CompletionLatchTests(Fixture):
    """末帧求值会把"通关后回到标题/重开游戏"的电影判成 fail。

    3232 塞尔达站点标签就写着 "Uses a game restart sequence"，5628 洛克人X2 实测末帧
    是标题画面（片尾按 Start 回标题）。这类片子的通关证据出现在中途某帧，
    所以 latch（逐帧求值 + 记首次成立帧号）是判据的一等模式；而"中途成立"必须
    带帧号和回读值，不能是运行器自报一句话。
    """

    def latch_doc(self, latch=True, frame=5, evidence=True, tolerance=3):
        doc = self.session()
        checks = [{"id": "gauge", "domain": "System Bus", "addr": 129, "cmp": "eq", "value": 0}]
        if evidence:
            self.with_shot_completion(doc, checks, frame=frame, tolerance=tolerance,
                                      source="fixture：击败最终 Boss 后 HUD 计数归零")
        else:
            doc["completion"] = {"source": "fixture：击败最终 Boss 后 HUD 计数归零", "checks": checks}
        if latch is not None:
            doc["completion"]["checks"][0]["latch"] = latch
        return doc

    def executor(self, completion="pass", witness=None, advanced=8):
        def execute(program, attempt, work, timeout):
            output = Path(attempt) / "executor-evidence.json"
            output.write_text(json.dumps({"id": program["id"]}), encoding="utf-8")
            report = {"execution": "pass", "core_identity": "pass", "completion": completion, "artifacts": [str(output)],
                      "reason": "offline fixture", "frames_advanced": advanced}
            if witness is not None:
                report["completion_witness"] = witness
            return self.attach_shots(attempt, report)
        return execute

    def reason(self, report):
        return report.get("reason", "")

    def test_latch_key_survives_only_when_true(self):
        for latch, expect in ((True, True), (False, False), (None, False)):
            with self.subTest(latch=latch):
                item = C.normalize(self.latch_doc(latch), self.base)[1]["completion"][0]
                self.assertEqual(item.get("latch", False), expect)
                if not expect:
                    self.assertNotIn("latch", item, "没开 latch 的老任务 program 字节不许因为新增字段而漂移")

    def test_latch_is_refused_on_step_checks(self):
        doc = self.session(steps=[{"id": "wait", "op": "advance", "frames": 2},
                                  {"id": "hold", "op": "until", "max_frames": 5,
                                   "checks": [{"id": "gauge", "domain": "System Bus", "addr": 129,
                                               "cmp": "eq", "value": 0, "latch": True}]}])
        with self.assertRaises(SchemaError):
            C.normalize(doc, self.base)

    def test_non_bool_latch_is_refused(self):
        for bad in ("yes", 1, None):
            doc = self.latch_doc()
            doc["completion"]["checks"][0]["latch"] = bad
            with self.subTest(latch=bad), self.assertRaises(SchemaError):
                C.normalize(doc, self.base)

    def test_pass_without_witness_frame_is_rejected(self):
        report = self.run_doc(doc=self.latch_doc(), executor=self.executor("pass", None),
                              out=self.base / "latch1")
        self.assertEqual(report["status"], "failed")
        self.assertIn("witness", self.reason(report), "判过就必须给出首次成立的帧号")

    def test_valid_witness_is_accepted(self):
        report = self.run_doc(doc=self.latch_doc(),
                              executor=self.executor("pass", {"gauge": {"frame": 5, "value": 0}}),
                              out=self.base / "latch2")
        self.assertEqual(report["status"], "done", self.reason(report))
        self.assertEqual(report["verification"]["completion"], "pass")

    def test_witness_frame_out_of_range_is_rejected(self):
        for n, frame in enumerate((900, -1)):
            with self.subTest(frame=frame):
                report = self.run_doc(doc=self.latch_doc(),
                                      executor=self.executor("pass", {"gauge": {"frame": frame, "value": 0}},
                                                             advanced=8),
                                      out=self.base / f"latch3_{n}")
                self.assertEqual(report["status"], "failed")
                self.assertIn("越出", self.reason(report))

    def test_witness_value_must_satisfy_the_comparator(self):
        report = self.run_doc(doc=self.latch_doc(),
                              executor=self.executor("pass", {"gauge": {"frame": 3, "value": 7}}),
                              out=self.base / "latch4")
        self.assertEqual(report["status"], "failed")
        self.assertIn("并不满足", self.reason(report))

    def test_fail_verdict_may_have_no_witness(self):
        # latch 一次都没成立 = 判据没过，这是正常结论，不是证据缺失，不许抛"缺 witness"。
        report = self.run_doc(doc=self.latch_doc(), executor=self.executor("fail", None),
                              out=self.base / "latch5")
        self.assertEqual(report["status"], "failed")
        self.assertNotIn("witness", self.reason(report))

    def test_witness_without_latch_checks_is_rejected(self):
        report = self.run_doc(doc=self.latch_doc(None),
                              executor=self.executor("pass", {"gauge": {"frame": 2, "value": 0}}),
                              out=self.base / "latch6")
        self.assertEqual(report["status"], "failed")
        self.assertIn("witness", self.reason(report), "没开 latch 的任务不许凭空带 witness 回来")

    def test_terminal_latch_key_survives_normalize(self):
        item = C.normalize(self.latch_doc("terminal"), self.base)[1]["completion"][0]
        self.assertEqual(item["latch"], "terminal")

    def test_terminal_is_the_only_string_latch_mode(self):
        # once 用布尔 true 表达，两种语义只留一个写法，避免 "once"/true 两套叫法各跑一半。
        for bad in ("once", "TRUE", "", 0):
            doc = self.latch_doc(bad)
            with self.subTest(latch=bad), self.assertRaises(SchemaError):
                C.normalize(doc, self.base)

    def test_terminal_witness_needs_the_fall_back_counts(self):
        # 只报"末帧成立"不够：没有 false_frames / fell_back 就无法核对是不是连续保持到收尾。
        for witness in ({"frame": 5, "value": 0, "fell_back": 1},
                        {"frame": 5, "value": 0, "false_frames": 3},
                        {"frame": 5, "value": 0, "false_frames": 3, "fell_back": -1}):
            with self.subTest(witness=witness):
                report = self.run_doc(doc=self.latch_doc("terminal"),
                                      executor=self.executor("pass", {"gauge": witness}),
                                      out=self.base / "terminal_counts")
                self.assertEqual(report["status"], "failed")
                self.assertIn("witness 缺", self.reason(report))

    def test_terminal_latch_rejects_a_check_that_held_from_the_first_frame(self):
        # false_frames=0 ⇒ 判据恒真（例如挑了个全程不变的字节），不能算通关转折。
        report = self.run_doc(doc=self.latch_doc("terminal"),
                              executor=self.executor("pass", {"gauge": {"frame": 0, "value": 0,
                                                                        "false_frames": 0,
                                                                        "fell_back": 0}}),
                              out=self.base / "terminal_always")
        self.assertEqual(report["status"], "failed")
        self.assertIn("自始成立", self.reason(report))

    def test_terminal_latch_passes_only_with_a_persistent_tail(self):
        report = self.run_doc(doc=self.latch_doc("terminal"),
                              executor=self.executor("pass", {"gauge": {"frame": 5, "value": 0,
                                                                        "false_frames": 3,
                                                                        "fell_back": 1}}),
                              out=self.base / "terminal_ok")
        self.assertEqual(report["status"], "done", self.reason(report))
        self.assertEqual(report["verification"]["completion"], "pass")
        self.assertEqual(report["runtime"]["completion_witness"],
                         {"gauge": {"frame": 5, "value": 0, "false_frames": 3, "fell_back": 1}},
                         "witness 要留在产物里，读 control.json 的人才能自己核对转折帧")

    def test_once_latch_ignores_the_terminal_counts(self):
        # 两种语义互不顶：once 仍然只要求"首次成立"的那两格，多了回落计数也不该改判。
        report = self.run_doc(doc=self.latch_doc(True),
                              executor=self.executor("pass", {"gauge": {"frame": 2, "value": 0,
                                                                        "false_frames": 9,
                                                                        "fell_back": 4}}),
                              out=self.base / "once_with_counts")
        self.assertEqual(report["status"], "done", self.reason(report))

    def test_terminal_evidence_uses_the_hold_interval_not_zero_distance(self):
        """terminal 的 witness 帧是"最后一段保持"的**起点**，跟截图帧本来就不是同一时刻。

        注册件用的 frame_tolerance 是 0（4776/4831 都这么写）。旧写法把起点跟截图帧做
        0 容差比较 ⇒ 只要保持段比检查点早开始一帧，一次真保持也会被降成 inconclusive。
        现在改判"截图帧落在保持段内"，所以起点在第 3 帧、图在第 5 帧、末帧第 8 帧必须算过。
        """
        report = self.run_doc(doc=self.shot_doc(latch="terminal", frame=5, tolerance=0),
                              executor=self.executor("pass", {"gauge": {"frame": 3, "value": 0,
                                                                        "false_frames": 2,
                                                                        "fell_back": 1}},
                                                     advanced=8),
                              out=self.base / "terminal_interval_ok")
        self.assertEqual(report["status"], "done", self.reason(report))
        self.assertEqual(report["verification"]["completion"], "pass")

    def test_terminal_evidence_still_rejects_a_shot_taken_before_the_hold(self):
        # 图拍在保持段开始之前 ⇒ 图上根本没有那句声称对应的局面，照旧降级
        # （证词不齐是"声称作废"，不是"跑失败"：执行本身成功，所以状态走 inconclusive）。
        report = self.run_doc(doc=self.shot_doc(latch="terminal", frame=5, tolerance=0),
                              executor=self.executor("pass", {"gauge": {"frame": 6, "value": 0,
                                                                        "false_frames": 2,
                                                                        "fell_back": 1}},
                                                     advanced=8),
                              out=self.base / "terminal_interval_bad")
        self.assertEqual(report["status"], "inconclusive", self.reason(report))
        self.assertEqual(report["verification"]["completion"], "inconclusive")
        self.assertIn("不在保持段里", report["completion_evidence"]["reason"])

    def test_once_evidence_names_the_first_hit_when_it_precedes_the_shot(self):
        # 全片逐帧探针首次成立落在第 2 帧、图在第 5 帧 ⇒ 说明这个值中途就出现过，
        # 报错必须点出"首次成立"这个语义，人才一眼看得出这是反例而不是时间戳误差。
        report = self.run_doc(doc=self.shot_doc(latch=True, frame=5, tolerance=0),
                              executor=self.executor("pass", {"gauge": {"frame": 2, "value": 0}},
                                                     advanced=8),
                              out=self.base / "once_counterexample")
        self.assertEqual(report["status"], "inconclusive", self.reason(report))
        self.assertIn("首次成立", report["completion_evidence"]["reason"])
        self.assertIn("不是通关旗标", report["completion_evidence"]["reason"])

    def shot_doc(self, **kw):
        """证词闸门只作用在"声称通关"的任务上，所以 fixture 按生产写法带上 purpose。"""
        doc = self.latch_doc(**kw)
        doc["purpose"] = "playthrough"
        return doc

    def test_verdict_without_a_picture_is_blocked_before_launch(self):
        report = C.plan(self.shot_doc(evidence=False), self.base)
        self.assertEqual(report["status"], "blocked", report["blockers"])
        self.assertIn("completion_evidence_missing", [b["code"] for b in report["blockers"]])
        self.assertIn("window", report["blockers"][0]["reason"], "报错要指出下一步：先跑 window 看图")

    def test_evidence_must_point_at_a_checkpoint_step(self):
        doc = self.shot_doc()
        doc["completion"]["checks"][0]["evidence"]["checkpoint"] = "cp_not_a_step"
        report = C.plan(doc, self.base)
        self.assertEqual(report["status"], "blocked", report["blockers"])
        self.assertIn("completion_evidence_step_missing", [b["code"] for b in report["blockers"]])

    def test_evidence_shape_is_enforced_at_normalize(self):
        for i, bend in enumerate((lambda ev: ev.update(sha256="0a12"),
                                  lambda ev: ev.update(sha256="z" * 64),
                                  lambda ev: ev.update(seen="   "),
                                  lambda ev: ev.update(seen="标题画面\n又一行"),
                                  lambda ev: ev.pop("seen"),
                                  lambda ev: ev.pop("sha256"),
                                  lambda ev: ev.pop("checkpoint"),
                                  lambda ev: ev.update(frame_tolerance=5000),
                                  lambda ev: ev.update(frame_tolerance=-1),
                                  lambda ev: ev.update(extra=1))):
            doc = self.shot_doc()
            bend(doc["completion"]["checks"][0]["evidence"])
            with self.subTest(bad=i), self.assertRaises(SchemaError):
                C.normalize(doc, self.base)

    def test_replaced_picture_downgrades_the_verdict(self):
        doc = self.shot_doc()
        # 执行器落盘的字节和任务里登记的摘要不一致＝看的根本不是这张图。
        self.shots["shot_end"] = (5, self.shot_bytes("另一张图"))
        report = self.run_doc(doc=doc, executor=self.executor("pass", {"gauge": {"frame": 5, "value": 0}}),
                              out=self.base / "ev_swapped")
        self.assertEqual(report["verification"]["completion"], "inconclusive")
        self.assertEqual(report["status"], "inconclusive", self.reason(report))
        self.assertIn("图被换过", self.reason(report))

    def test_missing_checkpoint_downgrades_the_verdict(self):
        doc = self.shot_doc()
        self.shots.clear()          # 执行器一个采样点都没留下
        report = self.run_doc(doc=doc, executor=self.executor("pass", {"gauge": {"frame": 5, "value": 0}}),
                              out=self.base / "ev_missing")
        self.assertIn("不存在", self.reason(report), report.get("completion_evidence"))

    def test_shot_from_a_frame_this_run_never_reached_is_rejected(self):
        doc = self.shot_doc(frame=400, tolerance=600)
        # 图号称第 400 帧，可这一趟只推进 8 帧——摘要对得上也不许算证词（图是别处捡的）。
        report = self.run_doc(doc=doc, executor=self.executor("pass", {"gauge": {"frame": 5, "value": 0}}),
                              out=self.base / "ev_borrowed")
        self.assertIn("不可能出自这一趟", self.reason(report))

    def test_picture_far_from_the_witness_frame_is_rejected(self):
        doc = self.shot_doc(frame=40, tolerance=3)
        report = self.run_doc(doc=doc, executor=self.executor("pass", {"gauge": {"frame": 5, "value": 0}},
                                                              advanced=60),
                              out=self.base / "ev_far")
        self.assertEqual(report["verification"]["completion"], "inconclusive")
        self.assertIn("相差", report["completion_evidence"]["reason"])

    def test_wide_tolerance_keeps_the_pass_when_the_picture_lines_up(self):
        doc = self.shot_doc(frame=40, tolerance=35)
        report = self.run_doc(doc=doc, executor=self.executor("pass", {"gauge": {"frame": 5, "value": 0}},
                                                              advanced=60),
                              out=self.base / "ev_far_ok")
        self.assertEqual(report["verification"]["completion"], "pass", self.reason(report))
        self.assertNotIn("completion_evidence", report)

    def test_allow_cannot_buy_a_pass_back(self):
        # 软闸门只放行"这一趟先跑出来看看"；跑完照样不许登记通关，否则 --allow 就是后门。
        doc = self.shot_doc(evidence=False)
        self.shots.clear()
        report = self.run_doc(doc=doc, executor=self.executor("pass", {"gauge": {"frame": 5, "value": 0}}),
                              out=self.base / "ev_allowed", allow=("completion_evidence_missing",))
        self.assertEqual(report["status"], "inconclusive", self.reason(report))
        self.assertEqual(report["verification"]["completion"], "inconclusive")
        self.assertIn("没登记截图证词", report["completion_evidence"]["reason"])

    def test_fail_verdict_needs_no_picture(self):
        # 判据没过是正常结论，不该被证词闸门卡死；否则"看图"就成了只许成功不许失败。
        doc = self.shot_doc(evidence=False)
        self.shots.clear()
        report = self.run_doc(doc=doc, executor=self.executor("fail", None),
                              out=self.base / "ev_fail", allow=("completion_evidence_missing",))
        self.assertEqual(report["verification"]["completion"], "fail")
        self.assertNotIn("completion_evidence", report)

    def test_editing_the_reading_moves_the_fingerprint(self):
        first = C.plan(self.shot_doc(), self.base)
        doc = self.shot_doc()
        doc["completion"]["checks"][0]["evidence"]["seen"] = "读数改了五个字"
        self.assertNotEqual(first["fingerprint"], C.plan(doc, self.base)["fingerprint"],
                            "换了证词就是换了任务，缓存不许把旧判定复用过来")


class TailStasisTests(Fixture):
    """末段画面静止＝这一趟跑完停在结算/菜单画面上，是 3232 那类假通关的机器可查形态。

    11-21 实测：3232 死亡片尾段 74600–75400 共 41 个采样逐字节相同（800 帧静止），
    而战斗过程中每 20 帧就换一个摘要。人眼是在 GAME OVER 那张图上发现的，
    闸门要做的是——静止窗一旦成立，证词就必须出自那张静止屏。
    """

    END_FRAME = 3300
    FREEZE_START = 2700          # 与 END_FRAME 相差 600 帧 = 默认阈值刚好命中

    def reason(self, report):
        return report.get("reason", "")

    def tail_doc(self, evidence_frame, min_frozen=None, enabled=None, stride=None, checks=None):
        checks = checks if checks is not None else [
            {"id": "gauge", "domain": "System Bus", "addr": 129, "cmp": "eq", "value": 0, "latch": True}]
        doc = self.session()
        self.with_shot_completion(doc, checks, frame=evidence_frame, tolerance=0, source="fixture")
        doc["verify"] = {"length": {"frames": self.END_FRAME, "tolerance": 0.005, "source": "fixture"}}
        cfg = {}
        if min_frozen is not None:
            cfg["min_frozen_frames"] = min_frozen
        if enabled is not None:
            cfg["enabled"] = enabled
        if stride is not None:
            cfg["stride"] = stride
        if cfg:
            doc["verify"]["tail_stasis"] = cfg
        step = stride or C.TAIL_STRIDE
        self.set_tail(from_frame=self.END_FRAME - C.TAIL_WINDOW_FRAMES, stride=step,
                      count=C.TAIL_WINDOW_FRAMES // step + 1, frozen_from=self.FREEZE_START)
        return doc

    def tail_executor(self, evidence_frame, completion="pass", advanced=None):
        def execute(program, attempt, work, timeout):
            output = Path(attempt) / "executor-evidence.json"
            output.write_text(json.dumps({"id": program["id"],
                                          "tail_probe": program.get("tail_probe")}), encoding="utf-8")
            report = {"execution": "pass", "core_identity": "pass", "completion": completion, "artifacts": [str(output)],
                      "reason": "offline fixture", "frames_advanced": advanced or self.END_FRAME,
                      "final_frame": advanced or self.END_FRAME,
                      "completion_witness": {"gauge": {"frame": evidence_frame, "value": 0}}}
            return self.attach_shots(attempt, report)
        return execute

    def tail_run(self, evidence_frame, out, allow=(), **kw):
        doc = self.tail_doc(evidence_frame, **kw)
        return self.run_doc(doc=doc, out=self.base / out, allow=allow,
                            executor=self.tail_executor(evidence_frame))

    def test_frozen_tail_rejects_testimony_taken_before_the_freeze(self):
        report = self.tail_run(2400, "stasis1")          # 证词在 2700 之前
        self.assertEqual(report["verification"]["completion"], "inconclusive", self.reason(report))
        self.assertIn("画面逐字节相同", self.reason(report))
        self.assertIn("静止 600 帧", self.reason(report))
        self.assertIn("把 checkpoint 挪到末段", self.reason(report))
        self.assertEqual(report["tail_stasis"]["frozen_samples"],
                         (self.END_FRAME - self.FREEZE_START) // C.TAIL_STRIDE + 1,
                         "静止窗长度要从采样算出来，不是写死的")

    def test_testimony_on_the_frozen_end_screen_still_passes(self):
        report = self.tail_run(3200, "stasis2")          # 正对照：证词就取自末屏那张静止图
        self.assertEqual(report["verification"]["completion"], "pass", self.reason(report))
        self.assertTrue(report["tail_stasis"]["frozen"])
        self.assertNotIn("downgraded", report["tail_stasis"])

    def test_moving_tail_does_not_touch_the_verdict(self):
        doc = self.tail_doc(3200)
        self.tail = [(f, self.shot_bytes("tail-live%03d" % i))
                     for i, f in enumerate(range(self.END_FRAME - C.TAIL_WINDOW_FRAMES,
                                                 self.END_FRAME + 1, C.TAIL_STRIDE))]
        report = self.run_doc(doc=doc, out=self.base / "stasis3", executor=self.tail_executor(3200))
        self.assertEqual(report["verification"]["completion"], "pass", self.reason(report))
        self.assertFalse(report["tail_stasis"]["frozen"])
        self.assertEqual(report["tail_stasis"]["frozen_frames"], 0)
        self.assertEqual(report["tail_stasis"]["distinct"], len(self.tail))

    def test_allow_cannot_buy_back_a_stasis_downgrade(self):
        report = self.tail_run(2400, "stasis4", allow=("completion_evidence_missing", "tail_stasis", "everything"))
        self.assertEqual(report["verification"]["completion"], "inconclusive",
                         "静止窗是跑完才算得出来的度量，任何 --allow 都不该把它买回 pass")

    def test_threshold_is_honoured(self):
        report = self.tail_run(3200, "stasis5", min_frozen=700)   # 同样 600 帧静止，阈值抬到 700
        self.assertFalse(report["tail_stasis"]["frozen"])
        self.assertEqual(report["verification"]["completion"], "pass", self.reason(report))

    def test_sampling_defaults_on_only_for_completion_claims(self):
        with_claim = C.normalize(self.tail_doc(3200), self.base)[1]["tail_probe"]
        self.assertIsInstance(with_claim, dict)
        self.assertEqual(with_claim["from"], self.END_FRAME - C.TAIL_WINDOW_FRAMES)
        doc = self.session()
        doc["verify"] = {"length": {"frames": self.END_FRAME, "tolerance": 0.005, "source": "fixture"}}
        self.assertIsNone(C.normalize(doc, self.base)[1]["tail_probe"],
                          "纯执行任务没有通关声称，不该为它多花几十次截图")
        self.assertIsNone(C.normalize(self.tail_doc(3200, enabled=False), self.base)[1]["tail_probe"])

    def test_probe_end_frame_sources(self):
        """末帧从哪来：verify.length 优先，其次 .bk2 实测帧数；两者都没有就不采样。"""
        checks = [{"id": "gauge"}]
        movie = {"kind": "movie", "movie_frames": 5000}
        self.assertEqual(C._tail_probe({}, movie, checks, None)["from"], 5000 - C.TAIL_WINDOW_FRAMES)
        self.assertEqual(C._tail_probe({}, movie, checks, {"frames": 3300})["from"],
                         3300 - C.TAIL_WINDOW_FRAMES, "声明了 verify.length 就用声明值，不被素材帧数顶掉")
        self.assertIsNone(C._tail_probe({}, {"kind": "boot"}, checks, None),
                          "boot 任务既没声明长度也没素材帧数，量不了末段")
        self.assertIsNone(C._tail_probe({"enabled": False}, movie, checks, None))
        self.assertIsNone(C._tail_probe({}, movie, [], None), "没有通关声称就不该为末段多花截图")

    def test_unmeasured_tail_is_reported_not_silent(self):
        doc = self.tail_doc(3200)
        self.tail = None
        doc["verify"]["tail_stasis"] = {"enabled": False}
        report = self.run_doc(doc=doc, out=self.base / "stasis6", executor=self.tail_executor(3200))
        self.assertFalse(report["tail_stasis"]["measured"])
        self.assertEqual(report["tail_stasis"]["samples"], 0)
        self.assertIn("采样不足", report["tail_stasis"]["reason"])

    def test_single_sample_is_not_a_frozen_window(self):
        doc = self.tail_doc(3200)
        self.tail = self.tail[:1] + [(3250, self.shot_bytes("tail-solo"))]
        report = self.run_doc(doc=doc, out=self.base / "stasis7", executor=self.tail_executor(3200))
        self.assertEqual(report["tail_stasis"]["frozen_frames"], 0)
        self.assertFalse(report["tail_stasis"]["frozen"])

    def test_unreadable_sample_is_not_a_frozen_window(self):
        runtime = {"tail_samples": [{"frame": 10, "screenshot": None}, {"frame": 20, "screenshot": None}]}
        out = C._tail_measurement(runtime, None)
        self.assertFalse(out["measured"], "截图读不到就不许编出静止结论")
        self.assertIn("采样不足", out["reason"])

    def test_schema_bounds(self):
        for bad in ({"stride": 0}, {"stride": 601}, {"window_frames": 0}, {"window_frames": 20001},
                    {"min_frozen_frames": 0}, {"enabled": "yes"}, {"nonsense": 1}):
            doc = self.tail_doc(3200)
            doc["verify"]["tail_stasis"] = bad
            with self.subTest(bad=bad), self.assertRaises(SchemaError):
                C.normalize(doc, self.base)

    def test_fail_verdict_needs_no_tail_testimony(self):
        doc = self.tail_doc(2400)                        # 证词在静止窗之前，但判据本来就没成立
        report = self.run_doc(doc=doc, out=self.base / "stasis8",
                              executor=self.tail_executor(2400, completion="fail"))
        self.assertEqual(report["verification"]["completion"], "fail")
        self.assertTrue(report["tail_stasis"]["frozen"], "静止度照样要量出来")
        self.assertNotIn("downgraded", report["tail_stasis"], "否证不需要证词，闸门不许反过来拦否证")

class ProductionGateTests(Fixture):
    def setUp(self):
        super().setUp()
        self.rom = self.base / "rom.sfc"
        self.rom.write_bytes(b"rom fixture")
        self.movie = self.base / "movie.bk2"
        self.movie.write_bytes(b"movie fixture")
        self.frames = 68100
        self.samples = P.sample_frames(self.frames)
        self.final_shot = self.base / "final.png"
        from PIL import Image
        Image.new("RGB", (256, 224), (224, 32, 16)).save(self.final_shot, format="PNG")
        self.acceptance = {"checkpoint": f"cp_{self.frames:05d}",
                           "seen": "末帧显示真实结局", "sha256": sha256(self.final_shot)}

    def passing_report(self):
        checkpoints = {}
        from PIL import Image
        for frame in self.samples:
            shot = self.base / f"cp_{frame:05d}.png"
            Image.new("RGB", (256, 224), (frame % 256, (frame // 256) % 256, 64)).save(
                shot, format="PNG")
            checkpoints[f"cp_{frame:05d}"] = {"frame": frame, "screenshot": str(shot)}
        checkpoints[f"cp_{self.frames:05d}"]["screenshot"] = str(self.final_shot)
        rows = sorted(((row["frame"], name, row) for name, row in checkpoints.items()),
                      key=lambda item: item[0])
        middle = min(rows, key=lambda item: abs(item[0] - self.frames / 2))
        self.acceptance = {"reviews": [
            {"checkpoint": name, "frame": frame, "sha256": sha256(row["screenshot"]),
             "seen": f"第 {frame} 帧真实画面"} for frame, name, row in (rows[0], middle, rows[-1])
        ]}
        return {"status": "done", "artifacts": [],
                "verification": {"execution": "pass", "core_identity": "pass", "completion": "inconclusive",
                                 "sync": "pass", "visual": "pass"},
                "runtime": {"status": "done", "execution": "pass", "core_identity": "pass", "frames_advanced": self.frames,
                            "movie": {"expected_inputs": self.frames, "consumed_inputs": self.frames},
                            "checkpoints": checkpoints},
                "picture": {"measured": True, "dead_tail": False}}

    def test_identity_is_required_at_both_control_and_runtime_layers(self):
        for layer in ("verification", "runtime"):
            with self.subTest(layer=layer):
                report = self.passing_report()
                report[layer].pop("core_identity")
                checked = P.inspect_result(report, self.frames, len(self.samples), self.acceptance)
                self.assertFalse(checked["pass"])
                self.assertTrue(any("实际核心身份" in error for error in checked["errors"]))

    def test_sampling_and_spec_are_exact_and_normalizable(self):
        self.assertEqual(len(self.samples), 115)
        self.assertEqual((self.samples[0], self.samples[-1]), (1, 68100))
        spec = P.build_spec(self.movie, str(self.rom), self.base / "BizHawk", "Snes9x", "SNES",
                            "SNES", self.frames, FAMOUS_NES)
        _, program = C.normalize(spec, self.base)
        self.assertEqual(spec["verify"]["length"]["tolerance"], 1e-12)
        self.assertEqual(sum(step["frames"] for step in program["steps"] if step["op"] == "replay"),
                         self.frames)
        self.assertTrue(spec["verify"]["tail_stasis"]["enabled"])
        self.assertEqual(spec["record"]["speed"], "unthrottled")
        with self.assertRaises(SchemaError):
            P.build_spec(self.movie, str(self.rom), self.base / "BizHawk", "Snes9x", "SNES",
                         "SNES", self.frames, FAMOUS_NES, speed="turbo")
        for core in ("BSNES", "BSNESv115+"):
            bsnes = P.build_spec(self.movie, str(self.rom), self.base / "BizHawk", core, "SNES",
                                 "SNES", self.frames, FAMOUS_NES)
            for step in bsnes["steps"]:
                if step["op"] == "checkpoint":
                    self.assertEqual((step["ram_domain"], step["ram_addr"], step["ram_bytes"]),
                                     ("System Bus", 0x7E0000, 0x20000))
        self.assertEqual(spec["steps"][1]["ram_domain"], "WRAM")
        self.assertEqual(spec["steps"][1]["ram_bytes"], 0x20000)
        arm = C._arm_doc(bsnes, {"label": "candidate", "core": "BSNES",
                                 "bizhawk": str(self.base / "BizHawk-2.9.1"),
                                 "movie": {"path": str(self.movie), "sha256": sha256(self.movie)}}, 1, [1, "end"])
        for step in arm["steps"]:
            if step["op"] == "checkpoint":
                self.assertEqual((step["ram_domain"], step["ram_addr"], step["ram_bytes"]),
                                 ("System Bus", 0x7E0000, 0x20000))

    def test_seed_is_front_loaded_into_reference_and_candidate_arms(self):
        seed = self.base / "initial_sram.bin"
        seed.write_bytes(b"\x60" * 1024)
        seed_spec = {"path": str(seed), "sha256": sha256(seed), "domain": "CARTRAM",
                     "addr": 0, "bytes": 1024}
        spec = P.build_spec(self.movie, str(self.rom), self.base / "BizHawk", "BSNES", "SNES",
                            "SNES", 10, FAMOUS_NES, interval=4, seed_ram=seed_spec)
        self.assertEqual(spec["steps"][0]["op"], "seed_ram")
        self.assertEqual(sum(step["frames"] for step in spec["steps"] if step["op"] == "replay"), 10)
        normalized = C.normalize(spec, self.base)[0]
        entries = [{"label": "reference", "core": "BSNES",
                    "movie": {"path": str(self.movie), "sha256": sha256(self.movie)}},
                   {"label": "candidate", "core": "BSNES", "bizhawk": str(self.base / "BizHawk-2.9.1"),
                    "movie": {"path": str(self.movie), "sha256": sha256(self.movie)}}]
        for index, entry in enumerate(entries):
            arm = C._arm_doc(normalized, entry, index, [1, "end"])
            self.assertEqual(arm["steps"][0]["op"], "seed_ram")
            self.assertEqual(arm["steps"][0]["sha256"], seed_spec["sha256"])
            self.assertEqual([step["op"] for step in arm["steps"]],
                             ["seed_ram", "replay", "checkpoint", "replay", "checkpoint"])
        seed.write_bytes(b"\x61" * 1024)
        with self.assertRaises(SchemaError):
            P.build_spec(self.movie, str(self.rom), self.base / "BizHawk", "BSNES", "SNES",
                         "SNES", 10, FAMOUS_NES, seed_ram=seed_spec)

    def test_explicit_bk2_seed_is_fingerprinted_and_forwarded_to_production(self):
        seed = self.base / "explicit_wram.bin"
        seed.write_bytes(b"\x55" * 1024)
        seed_spec = {"path": str(seed), "sha256": sha256(seed), "domain": "WRAM",
                     "addr": 0, "bytes": 1024}
        args = (self.movie, str(self.rom), self.base / "production", self.base / "BizHawk",
                "Snes9x", FAMOUS_NES)
        original = P.request_identity(*args, 4, False, None, None, None, seed_ram=None)
        seeded = P.request_identity(*args, 4, False, None, None, None, seed_ram=seed_spec)
        self.assertNotEqual(original, seeded)
        report = self.passing_report()
        report["runtime"]["events"] = [
            {"op": "seed_ram", "kind": "step_started", "step_id": "seed_initial_sram",
             "frame": 0, "frames_advanced": 0, "consumed_inputs": 0},
            {"op": "seed_ram", "kind": "step_done", "step_id": "seed_initial_sram",
             "frame": 0, "frames_advanced": 0, "consumed_inputs": 0,
             "seed_ram": {"domain": "WRAM", "start": 0, "bytes": 1024,
                          "sha256_verified_by_runner": True}}]
        with mock.patch.object(P, "_prepare_movie", return_value=(self.movie, {"status": "reused"})), \
             mock.patch.object(P, "_movie_identity", return_value=({}, self.frames, {}, "SNES", "SNES", "Snes9x")), \
             mock.patch.object(P.control, "run", return_value=report) as run, \
             mock.patch.object(P, "run_regressions", return_value={"pass": True, "tests": []}):
            manifest = P.produce(*args, acceptance=self.acceptance, capture=False, seed_ram=seed_spec)
        self.assertEqual(manifest["status"], "accepted", manifest.get("inspection"))
        spec = run.call_args.args[0]
        self.assertEqual(spec["steps"][0]["op"], "seed_ram")
        self.assertEqual(spec["steps"][0]["domain"], "WRAM")
        self.assertEqual(spec["steps"][0]["sha256"], seed_spec["sha256"])
        seed.write_bytes(b"\x56" * 1024)
        with self.assertRaises(SchemaError):
            P.produce(*args, acceptance=self.acceptance, capture=False, seed_ram=seed_spec)

    def test_seed_readback_evidence_is_mandatory(self):
        report = self.passing_report()
        report["runtime"]["events"] = [
            {"op": "seed_ram", "kind": "step_started", "step_id": "seed_initial_sram",
             "frame": 0, "frames_advanced": 0, "consumed_inputs": 0},
            {"op": "seed_ram", "kind": "step_done", "step_id": "seed_initial_sram",
             "frame": 0, "frames_advanced": 0, "consumed_inputs": 0,
             "seed_ram": {"domain": "WRAM", "start": 0, "bytes": 1024,
                          "sha256_verified_by_runner": True}}]
        seed_spec = {"id": "seed_initial_sram", "domain": "WRAM", "addr": 0, "bytes": 1024}
        self.assertTrue(P.inspect_result(report, self.frames, len(self.samples), self.acceptance,
                                         seed_ram=seed_spec)["pass"])
        report["runtime"]["events"] = report["runtime"]["events"][:1]
        checked = P.inspect_result(report, self.frames, len(self.samples), self.acceptance,
                                   seed_ram=seed_spec)
        self.assertFalse(checked["pass"])
        self.assertTrue(any("初始内存注入缺少完整" in error for error in checked["errors"]))
        done = {"op": "seed_ram", "kind": "step_done", "step_id": "seed_initial_sram",
                "frame": 0, "frames_advanced": 0, "consumed_inputs": 0,
                "seed_ram": {"domain": "WRAM", "start": 0, "bytes": 1024,
                             "sha256_verified_by_runner": False}}
        report["runtime"]["events"].append(done)
        checked = P.inspect_result(report, self.frames, len(self.samples), self.acceptance,
                                   seed_ram=seed_spec)
        self.assertFalse(checked["pass"])
        self.assertTrue(any("零帧全量回读" in error for error in checked["errors"]))
        done["seed_ram"]["sha256_verified_by_runner"] = True
        for field, value in (("domain", "CARTRAM"), ("start", 1), ("bytes", 1023)):
            original = done["seed_ram"][field]
            done["seed_ram"][field] = value
            checked = P.inspect_result(report, self.frames, len(self.samples), self.acceptance,
                                       seed_ram=seed_spec)
            self.assertFalse(checked["pass"], field)
            self.assertTrue(any("域、地址、长度" in error for error in checked["errors"]), field)
            done["seed_ram"][field] = original
        self.assertTrue(P.inspect_result(report, self.frames, len(self.samples), self.acceptance,
                                         seed_ram=seed_spec)["pass"])
        self.assertFalse(P.inspect_result(report, self.frames, len(self.samples), self.acceptance)["pass"])

    def test_snes9x_seed_and_wram_capture_are_supported(self):
        seed = self.base / "wram.bin"
        seed.write_bytes(b"\x55" * 0x20000)
        seed_spec = {"path": str(seed), "sha256": sha256(seed), "domain": "WRAM",
                     "addr": 0, "bytes": len(seed.read_bytes())}
        spec = P.build_spec(self.movie, str(self.rom), self.base / "BizHawk", "Snes9x", "SNES",
                            "SNES", 10, FAMOUS_NES, interval=4, seed_ram=seed_spec)
        self.assertEqual(spec["steps"][0]["domain"], "WRAM")
        for step in spec["steps"]:
            if step["op"] == "checkpoint":
                self.assertEqual((step["ram_domain"], step["ram_addr"], step["ram_bytes"]),
                                 ("WRAM", 0, 0x20000))

    def test_bsnes_seed_patches_only_ram_header_and_checksum(self):
        rom = bytearray(b"\x60" * 0x8000)
        rom[0x7FD5] = 0x21
        rom[0x7FD8] = 2
        rom_path = self.base / "seed_header.sfc"
        rom_path.write_bytes(rom)
        parsed = {"savestate_data": b"\x60" * 2048}
        out = self.base / "seed_conversion"
        out.mkdir()
        effective, evidence = P._prepare_bsnes_seed(parsed, str(rom_path), out)
        self.assertNotEqual(effective, str(rom_path))
        patched = Path(effective).read_bytes()
        self.assertEqual(patched[0x7FD8], 1)
        checksum = sum(patched[:0x7FDC] + patched[0x7FE0:]) & 0xFFFF
        self.assertEqual(int.from_bytes(patched[0x7FDC:0x7FDE], "little"), checksum)
        self.assertEqual(int.from_bytes(patched[0x7FDE:0x7FE0], "little"), checksum ^ 0xFFFF)
        self.assertEqual(evidence["seed_ram"]["bytes"], 2048)
        self.assertEqual(evidence["declared_sram_bytes"], 4096)
        self.assertEqual(Path(effective).stat().st_size, len(rom))

    def test_bsnes_seed_without_cartridge_sram_uses_native_wram_pattern(self):
        rom = bytearray(b"\x60" * 0x8000)
        rom[0x7FD5] = 0x21
        rom[0x7FD8] = 0
        rom_path = self.base / "no_sram.sfc"
        rom_path.write_bytes(rom)
        parsed = {"savestate_data": b"\x60" * 2048,
                  "savestate_sha256": hashlib.sha256(b"\x60" * 2048).hexdigest()}
        out = self.base / "no_sram_conversion"
        out.mkdir()
        effective, evidence = P._prepare_bsnes_seed(parsed, str(rom_path), out)
        self.assertEqual(effective, str(rom_path))
        seed = evidence["seed_ram"]
        self.assertEqual((seed["domain"], seed["addr"], seed["bytes"]),
                         ("System Bus", 0x7E0000, 0x20000))
        self.assertEqual(Path(seed["path"]).read_bytes(), b"\x55" * 0x20000)
        self.assertEqual(evidence["seed_kind"], "snes_wram_power_on")
        self.assertEqual(evidence["patched_header_offsets"], [])

    def test_acceptance_locks_real_final_frame_without_rerunning(self):
        report = self.passing_report()
        checked = P.inspect_result(report, self.frames, len(self.samples), self.acceptance)
        self.assertTrue(checked["pass"], checked["errors"])
        self.assertEqual(checked["completion"], "pass")
        bad = deepcopy(self.acceptance)
        bad["reviews"][-1]["sha256"] = "0" * 64
        checked = P.inspect_result(report, self.frames, len(self.samples), bad)
        self.assertFalse(checked["pass"])
        self.assertTrue(any("SHA-256" in error for error in checked["errors"]))

    def test_execution_pass_cannot_publish_frozen_or_unverified_picture(self):
        report = self.passing_report()
        report["picture"]["dead_tail"] = True
        checked = P.inspect_result(report, self.frames, len(self.samples), self.acceptance)
        self.assertFalse(checked["pass"])
        self.assertTrue(any("死尾" in error for error in checked["errors"]))
        report = self.passing_report()
        report["picture"]["measured"] = False
        self.assertFalse(P.inspect_result(report, self.frames, len(self.samples),
                                          self.acceptance)["pass"])

    def test_review_template_selects_opening_middle_and_ending(self):
        report = self.passing_report()
        out = self.base / "review"
        (out / "control").mkdir(parents=True)
        (out / "control" / "control.json").write_text(json.dumps(report), encoding="utf-8")
        template = P.review_template(out)
        self.assertEqual(len(template["reviews"]), 3)
        self.assertEqual(template["reviews"][0]["frame"], 1)
        self.assertEqual(template["reviews"][-1]["frame"], self.frames)
        self.assertTrue(all(row["seen"] == "" and len(row["sha256"]) == 64
                            for row in template["reviews"]))

    def test_contact_sheets_cover_review_and_all_checkpoints(self):
        from PIL import Image
        report = self.passing_report()
        out = self.base / "sheets"
        out.mkdir()
        artifacts = P.build_contact_sheets(report, out)
        self.assertEqual([Path(row["uri"]).name for row in artifacts],
                         ["review_contact_sheet.png", "checkpoints_contact_sheet.png"])
        self.assertEqual(P.verify_evidence({"artifacts": artifacts}), [])
        with Image.open(artifacts[0]["uri"]) as review:
            self.assertEqual(review.size, (1536, 474))
        with Image.open(artifacts[1]["uri"]) as overview:
            self.assertEqual(overview.size, (1360, 23 * 252))
        self.assertFalse(list(out.glob("*.tmp")))

    def test_decoded_video_gate_detects_interior_and_tail_freezes(self):
        video = self.base / "video.mp4"
        video.write_bytes(b"video fixture")
        report = {"artifacts": [asset(str(video))]}

        def decoded(hashes):
            rows = ["#format: frame checksum"] + [
                f"0, {index}, {index}, 1, 256, 224, 0x{value}"
                for index, value in enumerate(hashes)]
            return mock.Mock(stdout="\n".join(rows))

        hashes = [f"{index % 4:032x}" for index in range(20)]
        hashes[5:16] = ["f" * 32] * 11
        with mock.patch.object(P.subprocess, "run", side_effect=[
                mock.Mock(stdout=json.dumps({"streams": [{"nb_frames": "20"}]})),
                decoded(hashes)]):
            checked = P.inspect_video(report, 20, max_static_frames=10)
        self.assertFalse(checked["pass"])
        self.assertEqual(checked["evidence"]["longest_streak"]["frames"], 11)
        self.assertTrue(any("最长连续静止" in error for error in checked["errors"]))
        with mock.patch.object(P.subprocess, "run", side_effect=[
                mock.Mock(stdout=json.dumps({"streams": [{"nb_frames": "20"}]})),
                decoded([f"{index % 4:032x}" for index in range(20)])]):
            checked = P.inspect_video(report, 20, max_static_frames=10)
        self.assertTrue(checked["pass"], checked["errors"])
        self.assertEqual(checked["evidence"]["decoded_frames"], 20)
        alternate = self.base / "full_capture.mp4"
        alternate.write_bytes(b"video fixture")
        declared = {"artifacts": [{"uri": str(alternate)}],
                    "runtime": {"video": {"path": str(alternate)}}}
        with mock.patch.object(P.subprocess, "run", side_effect=[
                mock.Mock(stdout=json.dumps({"streams": [{"nb_frames": "20"}]})),
                decoded([f"{index % 4:032x}" for index in range(20)])]):
            checked = P.inspect_video(declared, 20, max_static_frames=10)
        self.assertTrue(checked["pass"], checked["errors"])
        self.assertEqual(Path(checked["evidence"]["path"]), alternate)
        self.assertFalse(P.inspect_video({"artifacts": []}, 20)["pass"])

    def test_sync_and_all_artifact_hashes_are_mandatory(self):
        report = self.passing_report()
        report["verification"]["sync"] = "unverified"
        self.assertFalse(P.inspect_result(report, self.frames, len(self.samples),
                                          self.acceptance)["pass"])
        report = self.passing_report()
        evidence = self.base / "evidence.bin"
        evidence.write_bytes(b"evidence")
        report["artifacts"] = [asset(str(evidence))]
        evidence.write_bytes(b"tampered")
        errors = P.verify_evidence(report)
        self.assertTrue(any("SHA-256" in error for error in errors))

    def test_arms_fill_reference_and_require_candidate_movie(self):
        candidate = self.base / "candidate.bk2"
        candidate.write_bytes(b"candidate")
        spec = P.build_spec(self.movie, str(self.rom), self.base / "BizHawk", "Snes9x", "SNES",
                            "SNES", self.frames, FAMOUS_NES,
                            arms=[{"label": "reference", "core": "Snes9x"},
                                  {"label": "candidate", "core": "Snes9x",
                                   "bizhawk": str(self.base / "BizHawk-2.11.1"),
                                   "movie": {"path": str(candidate), "sha256": sha256(candidate)}}])
        C.normalize(spec, self.base)
        self.assertEqual(spec["verify"]["arms"]["entries"][0]["movie"]["path"], str(self.movie))
        with self.assertRaises(SchemaError):
            P.build_spec(self.movie, str(self.rom), self.base / "BizHawk", "Snes9x", "SNES",
                         "SNES", self.frames, FAMOUS_NES,
                         arms=[{"label": "reference", "core": "Snes9x"},
                               {"label": "candidate", "core": "Snes9x"}])
        with self.assertRaises(SchemaError):
            P.build_spec(self.movie, str(self.rom), self.base / "BizHawk", "Snes9x", "SNES",
                         "SNES", self.frames, FAMOUS_NES,
                         arms=[{"label": "reference", "core": "Snes9x"},
                               {"label": "candidate", "core": "Snes9x",
                                "movie": {"path": str(candidate), "sha256": sha256(candidate)}}])

    def test_sync_can_compare_every_production_checkpoint(self):
        arms = [{"label": "reference", "core": "BSNESv115+"},
                {"label": "candidate", "core": "BSNES",
                 "movie": {"path": str(self.movie), "sha256": sha256(self.movie)}}]
        spec = P.build_spec(self.movie, str(self.rom), self.base / "BizHawk", "BSNESv115+", "SNES",
                            "SNES", self.frames, FAMOUS_NES, arms=arms, sync_samples="all")
        self.assertEqual(spec["verify"]["arms"]["samples"],
                         [*self.samples[:-1], "end"])
        normalized, _ = C.normalize(spec, self.base)
        self.assertEqual(len(normalized["verify"]["arms"]["samples"]), 115)
        with self.assertRaises(SchemaError):
            P.build_spec(self.movie, str(self.rom), self.base / "BizHawk", "BSNESv115+", "SNES",
                         "SNES", self.frames, FAMOUS_NES, arms=arms, sync_samples="sparse")

    def test_soft_blocker_allow_is_forwarded_without_bypassing_hard_gates(self):
        out = self.base / "allowed"
        report = self.passing_report()
        with mock.patch.object(P, "_prepare_movie", return_value=(self.movie, {"status": "reused"})), \
             mock.patch.object(P, "_movie_identity", return_value=({}, self.frames, {}, "SNES", "SNES", "Snes9x")), \
             mock.patch.object(P.control, "run", return_value=report) as run, \
             mock.patch.object(P, "run_regressions", return_value={"pass": True, "tests": []}):
            manifest = P.produce(self.movie, str(self.rom), out, self.base / "BizHawk", "Snes9x",
                                 FAMOUS_NES, acceptance=self.acceptance, capture=False,
                                 allow=("title_off_popularity_list",))
        self.assertEqual(manifest["status"], "accepted", manifest.get("inspection"))
        self.assertEqual(run.call_args.kwargs["allow"], ("title_off_popularity_list",))
        self.assertEqual({Path(row["uri"]).name for row in manifest["control"]["artifacts"]},
                         {"movie.bk2", "review_contact_sheet.png", "checkpoints_contact_sheet.png"})
        report["verification"]["visual"] = "fail"
        rejected = self.base / "allowed_but_visual_failed"
        rejected.mkdir()
        (rejected / "control").mkdir()
        (rejected / "control" / "control.json").write_text("{}", encoding="utf-8")
        with mock.patch.object(P, "_prepare_movie", return_value=(self.movie, {"status": "reused"})), \
             mock.patch.object(P, "_movie_identity", return_value=({}, self.frames, {}, "SNES", "SNES", "Snes9x")), \
             mock.patch.object(P.control, "run", return_value=report), \
             mock.patch.object(P, "run_regressions", return_value={"pass": True, "tests": []}):
            manifest = P.produce(self.movie, str(self.rom), rejected, self.base / "BizHawk", "Snes9x",
                                 FAMOUS_NES, acceptance=self.acceptance, capture=False,
                                 allow=("title_off_popularity_list",))
        self.assertEqual(manifest["status"], "rejected")
        self.assertTrue(any("视觉" in error for error in manifest["inspection"]["errors"]))

    def test_manifest_is_atomic_and_rejection_never_publishes(self):
        out = self.base / "production"
        report = self.passing_report()
        with mock.patch.object(P, "_prepare_movie", return_value=(self.movie, {"status": "reused"})), \
             mock.patch.object(P, "_movie_identity", return_value=({}, self.frames, {}, "SNES", "SNES", "Snes9x")), \
             mock.patch.object(P.control, "run", return_value=report), \
             mock.patch.object(P, "run_regressions", return_value={"pass": True, "tests": []}):
            manifest = P.produce(self.movie, str(self.rom), out, self.base / "BizHawk", "Snes9x",
                                 FAMOUS_NES, acceptance=self.acceptance, capture=False)
        self.assertEqual(manifest["status"], "accepted",
                         manifest.get("inspection") or manifest.get("traceback") or manifest.get("reason"))
        self.assertIsNone(manifest["deliverable"])
        self.assertFalse(list(out.glob("*.tmp")))
        report["verification"]["visual"] = "fail"
        rejected = self.base / "rejected"
        rejected.mkdir()
        (rejected / "control").mkdir()
        (rejected / "control" / "control.json").write_text("{}", encoding="utf-8")
        (rejected / "deliverable.mp4").write_bytes(b"stale deliverable")
        with mock.patch.object(P, "_prepare_movie", return_value=(self.movie, {"status": "reused"})), \
             mock.patch.object(P, "_movie_identity", return_value=({}, self.frames, {}, "SNES", "SNES", "Snes9x")), \
             mock.patch.object(P.control, "run", return_value=report), \
             mock.patch.object(P, "run_regressions", return_value={"pass": True, "tests": []}):
            manifest = P.produce(self.movie, str(self.rom), rejected, self.base / "BizHawk", "Snes9x",
                                 FAMOUS_NES, acceptance=self.acceptance, capture=True)
        self.assertEqual(manifest["status"], "rejected")
        self.assertFalse((rejected / "deliverable.mp4").exists())
        quarantined = list(rejected.glob("deliverable.rejected.*.mp4"))
        self.assertEqual(len(quarantined), 1)
        self.assertEqual(quarantined[0].read_bytes(), b"stale deliverable")

    def test_reuse_revalidates_evidence_and_preserves_other_accepted_tasks(self):
        out = self.base / "reuse"
        evidence = self.base / "reuse_evidence.bin"
        evidence.write_bytes(b"accepted evidence")
        report = self.passing_report()
        report["artifacts"] = [asset(str(evidence))]

        def fake_run(spec, base, out_dir, **kwargs):
            control_dir = Path(out_dir)
            control_dir.mkdir(parents=True, exist_ok=True)
            (control_dir / "control.json").write_text("{}", encoding="utf-8")
            return report

        with mock.patch.object(P, "_prepare_movie", return_value=(self.movie, {"status": "reused"})), \
             mock.patch.object(P, "_movie_identity", return_value=({}, self.frames, {}, "SNES", "SNES", "Snes9x")), \
             mock.patch.object(P.control, "run", side_effect=fake_run) as run, \
             mock.patch.object(P, "run_regressions", return_value={"pass": True, "tests": []}):
            accepted = P.produce(self.movie, str(self.rom), out, self.base / "BizHawk", "Snes9x",
                                 FAMOUS_NES, acceptance=self.acceptance, capture=False)
            self.assertEqual(accepted["status"], "accepted", accepted.get("inspection"))
            accepted_bytes = (out / "production_manifest.json").read_bytes()
            different_acceptance = deepcopy(self.acceptance)
            different_acceptance["reviews"][0]["seen"] = "不同任务的验收证词"
            with self.assertRaises(SchemaError):
                P.produce(self.movie, str(self.rom), out, self.base / "BizHawk", "Snes9x",
                          FAMOUS_NES, acceptance=different_acceptance, capture=False)
            self.assertEqual((out / "production_manifest.json").read_bytes(), accepted_bytes)
            self.movie.write_bytes(b"different movie")
            with self.assertRaises(SchemaError):
                P.produce(self.movie, str(self.rom), out, self.base / "BizHawk", "Snes9x",
                          FAMOUS_NES, acceptance=self.acceptance, capture=False)
            self.assertEqual((out / "production_manifest.json").read_bytes(), accepted_bytes)
            self.movie.write_bytes(b"movie fixture")
            evidence.write_bytes(b"tampered evidence")
            rejected = P.produce(self.movie, str(self.rom), out, self.base / "BizHawk", "Snes9x",
                                 FAMOUS_NES, acceptance=self.acceptance, capture=False)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(rejected["status"], "rejected")
        self.assertTrue(any("SHA-256" in error for error in rejected["inspection"]["errors"]))
        self.assertFalse((out / "deliverable.mp4").exists())


class WindowGridAndPictureTests(Fixture):
    """窗口要走到终点、画面死了要点名——两条都是 11-21 夜 8 的实测事故。

    事故一：window --from 1 --to 20000 --step 500 的格子停在 19501，长度闸门拿"格子没走到
    20000"当成片子的问题，12 条里 9 条假失败（-2.495% 超了 0.5% 容差）。
    事故二：6012 SMB 后半段 20 个检查点逐字节相同（黑屏，9220..17561 帧），execution 照样
    pass；tail_stasis 按设计只在有通关声称时采样，观察任务于是无声通过。人是在拼图时看见的。
    """

    def window_base(self, total=20000):
        doc = self.session(steps=[{"id": "full_movie", "op": "replay", "frames": "end"}])
        doc["verify"] = {"length": {"frames": total, "source": "fixture"}}
        return doc

    def cp_frames(self, spec):
        return [int(s["id"].split("_", 1)[1]) for s in spec["steps"] if s["op"] == "checkpoint"]

    def test_window_last_checkpoint_lands_on_the_window_end(self):
        spec = C.window_spec(6012, 1, 20000, 500, None, None, base_spec=self.window_base())
        frames = self.cp_frames(spec)
        self.assertEqual(frames[-1], 20000, "末格必须落在窗口终点，否则长度闸门会假失败")
        self.assertEqual(frames[-2], 19501, "补的那格不许把常规格子挤掉")
        self.assertEqual(len(set(frames)), len(frames), "同一帧不许留两格")
        self.assertEqual(sum(s["frames"] for s in spec["steps"] if s["op"] == "replay"), 20000,
                         "replay 步长加起来就得等于窗口终点——这才是长度闸门量的东西")
        self.assertEqual(spec["verify"]["length"]["frames"], 20000)

    def test_divisible_grid_does_not_get_an_extra_checkpoint(self):
        frames = self.cp_frames(C.window_spec(1, 1, 1001, 500, None, None, base_spec=self.window_base(2000)))
        self.assertEqual(frames, [1, 501, 1001], "整除时补格会变成同帧两格，那是新 bug")

    def test_window_refuses_a_base_without_declared_length(self):
        doc = self.window_base()
        doc["verify"] = {}
        with self.assertRaises(C.SchemaError) as ctx:
            C.window_spec(1, 1, 100, 10, None, None, base_spec=doc)
        self.assertIn("verify.length", str(ctx.exception))

    def pic_doc(self, identical_from=None, count=7):
        """造一串检查点截图：identical_from 及之后逐字节相同（=画面死了），之前每张不同。"""
        for i in range(count):
            tag = "dead" if identical_from is not None and i >= identical_from else "alive%03d" % i
            self.shots["cp%02d" % i] = (1000 + i * 500, self.shot_bytes(tag))
        return self.movie_doc()

    def test_identical_tail_shots_fail_visual_delivery(self):
        report = self.run_doc(doc=self.pic_doc(identical_from=3), out=self.base / "pic-dead")
        pic = report["picture"]
        self.assertTrue(pic["measured"])
        self.assertEqual(pic["runs"]["tail"]["from_frame"], 2500)
        self.assertEqual(pic["identical_tail_frames"], 1500, "跨度要按帧算，不是按格子数")
        self.assertTrue(pic["dead_tail"], self.reason(report))
        self.assertEqual([w["code"] for w in report["warnings"]], ["picture_dead_tail"])
        self.assertIn("必须看图", report["warnings"][0]["detail"])
        self.assertEqual(report["verification"]["execution"], "pass")
        self.assertEqual(report["verification"]["completion"], "inconclusive")
        self.assertEqual(report["verification"]["visual"], "fail")
        self.assertEqual(report["status"], "failed", "画面冻结不得借 execution=pass 交付")
        self.assertIn("视觉验收不通过", report["reason"])

    def test_moving_picture_gets_no_warning(self):
        report = self.run_doc(doc=self.pic_doc(), out=self.base / "pic-alive")
        self.assertTrue(report["picture"]["measured"])
        self.assertFalse(report["picture"]["dead_tail"])
        self.assertEqual(report["picture"]["machine_state"], "not_needed",
                         "画面没死就别假装量过内存")
        self.assertEqual(report["warnings"], [], "画面在动就不该有噪声告警")
        self.assertEqual(report["picture"]["distinct"], report["picture"]["checkpoints"])

    def test_dead_tail_threshold_is_the_same_window_as_tail_stasis(self):
        """静止窗只许有一个权威值，不许 window 侧再定一个数。"""
        report = self.run_doc(doc=self.pic_doc(identical_from=4), out=self.base / "pic-edge")
        self.assertEqual(report["picture"]["identical_tail_frames"], 1000)
        self.assertEqual(report["picture"]["min_dead_frames"], C.TAIL_WINDOW_FRAMES)
        self.assertFalse(report["picture"]["dead_tail"], "差一格就还没到窗，闸门不许自己放宽")

    def test_missing_shots_are_reported_not_silent(self):
        report = self.run_doc(doc=self.movie_doc(), out=self.base / "pic-none")
        self.assertFalse(report["picture"]["measured"])
        self.assertIn("不足 2 张", report["picture"]["reason"])
        self.assertEqual(report["warnings"], [])

    @staticmethod
    def reason(report):
        return json.dumps(report.get("warnings", []), ensure_ascii=False)

    def test_real_6012_shape_is_the_canonical_case(self):
        """6012 的形状：41 格里末段 20 格同一张黑图，跨度 8341 帧（9220..17561）。"""
        cps = {}
        for i in range(21):
            cps["a%02d" % i] = (1 + i * 439, self.shot_bytes("live%02d" % i))
        for i in range(20):
            cps["b%02d" % i] = (9220 + i * 439, self.shot_bytes("black"))
        for name, (frame, data) in cps.items():
            cps[name] = {"frame": frame,
                         "screenshot": str(self.put("6012/%s.png" % name, data))}
        pic = C._picture_health({"checkpoints": cps})
        self.assertEqual(pic["checkpoints"], 41)
        self.assertEqual(pic["runs"]["tail"]["samples"], 20)
        self.assertEqual(pic["identical_tail_frames"], 17561 - 9220)
        self.assertTrue(pic["dead_tail"])

    def ram_cps(self, n_live, n_dead, ram):
        """画面：前 n_live 格各不同，末 n_dead 格同一张黑图。内存：ram 决定末段转储变不变。"""
        cps = {}
        for i in range(n_live):
            cps["a%02d" % i] = {"frame": 1 + i * 439,
                                "screenshot": str(self.put("rm/%d.png" % i, self.shot_bytes("live%02d" % i)))}
        for i in range(n_dead):
            tag = "same" if ram == "static" else "ram%03d" % i
            cps["b%02d" % i] = {"frame": 9220 + i * 439,
                                "screenshot": str(self.put("rm/black.png" if ram == "static" else "rm/b%d.png" % i,
                                                           self.shot_bytes("black"))),
                                "ram": {"domain": "System Bus",
                                        "path": str(self.put("rm/r%d.bin" % i, tag.encode())),
                                        "bytes": len(tag)}}
        return cps

    def test_black_picture_with_changing_ram_says_the_machine_is_alive(self):
        """6012 的真形状：画面 20 格同一张黑图，但 System Bus 转储 20 格全不同。"""
        pic = C._picture_health({"checkpoints": self.ram_cps(21, 20, "moving")})
        self.assertEqual(pic["machine_state"], "changing")
        self.assertIn("System Bus 转储有 20 种", pic["machine_state_detail"])
        self.assertTrue(pic["dead_tail"], "画面层该报还是要报")
        self.assertNotIn("分不开", pic["reason"], "旧措辞会说'黑屏/卡帧分不开'，内存一量就分得开，不许回来")
        self.assertIn("必须看图", pic["reason"])

    def test_black_picture_with_static_ram_is_the_real_freeze(self):
        pic = C._picture_health({"checkpoints": self.ram_cps(21, 20, "static")})
        self.assertEqual(pic["machine_state"], "static")
        self.assertIn("System Bus 转储有 1 种", pic["machine_state_detail"])

    def test_no_ram_dumps_leaves_the_machine_layer_unmeasured(self):
        """只有截图（window 夹具就是这样）时，机器层必须显式说'不判'，不许猜。"""
        cps = {}
        for i in range(26):
            cps["c%02d" % i] = {"frame": 1 + i * 439,
                                "screenshot": str(self.put("nr/%d.png" % i,
                                                           self.shot_bytes("black" if i >= 6 else "l%d" % i)))}
        pic = C._picture_health({"checkpoints": cps})
        self.assertEqual(pic["machine_state"], "unmeasured")
        self.assertIn("没有可读的内存转储", pic["machine_state_detail"])

    def test_missing_ram_files_are_unmeasured_not_a_crash(self):
        cps = self.ram_cps(3, 6, "moving")
        for k in list(cps):
            if k.startswith("b"):
                cps[k]["ram"] = {"domain": "System Bus", "path": str(self.base / "nope.bin"), "bytes": 3}
        pic = C._picture_health({"checkpoints": cps})
        self.assertEqual(pic["machine_state"], "unmeasured")
        self.assertTrue(pic["dead_tail"])

    def test_run_without_ram_artifacts_still_warns_and_says_unmeasured(self):
        report = self.run_doc(doc=self.pic_doc(identical_from=3), out=self.base / "pic-noram")
        self.assertEqual(report["picture"]["machine_state"], "unmeasured")
        self.assertEqual([w["code"] for w in report["warnings"]], ["picture_dead_tail"])


class RunTests(Fixture):
    def test_runtime_receives_empty_dedicated_output(self):
        stub = self.executor()
        def require_empty(program, attempt, work, timeout):
            self.assertEqual(list(Path(attempt).iterdir()), [])
            self.assertTrue((Path(attempt).parent / "plan.json").is_file())
            return stub(program, attempt, work, timeout)
        self.assertEqual(self.run_doc(executor=require_empty)["status"], "done")

    def test_cache_exact_reuse_preserves_all_mtimes_and_hashes(self):
        first = self.run_doc()
        self.assertEqual(first["status"], "done")
        self.assert_artifacts(first)
        before = snapshot(self.out)
        second = self.run_doc()
        self.assertTrue(second["reused"])
        self.assertEqual(second["attempt_dir"], first["attempt_dir"])
        # Directory mtime changes legitimately when the lock is created/deleted.
        before_files = {p: v for p, v in before.items() if v[1] is not None}
        after_files = {p: v for p, v in snapshot(self.out).items() if v[1] is not None}
        self.assertEqual(after_files, before_files)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(second["artifacts"], first["artifacts"])

    def test_cache_same_size_artifact_tampering_invalidates(self):
        first = self.run_doc()
        artifact = Path(first["artifacts"][0]["uri"])
        data, stamp = artifact.read_bytes(), artifact.stat()
        artifact.write_bytes(bytes([data[0] ^ 1]) + data[1:])
        os.utime(artifact, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        second = self.run_doc()
        self.assertFalse(second["reused"])
        self.assertNotEqual(second["attempt_dir"], first["attempt_dir"])
        self.assertEqual(len(self.calls), 2)
        self.assert_artifacts(second)

    def test_cache_deleted_artifact_invalidates(self):
        first = self.run_doc()
        Path(first["artifacts"][0]["uri"]).unlink()
        self.assertFalse(self.run_doc()["reused"])
        self.assertEqual(len(self.calls), 2)

    def test_cache_task_change_invalidates(self):
        first = self.run_doc()
        doc = self.session()
        doc["steps"][0]["frames"] = 3
        second = self.run_doc(doc)
        self.assertFalse(second["reused"])
        self.assertNotEqual(second["fingerprint"], first["fingerprint"])
        self.assertEqual(self.calls[-1]["steps"][0]["frames"], 3)

    def test_cache_emulator_config_change_invalidates(self):
        first = self.run_doc()
        (self.bh / "config.ini").write_bytes(b"changed-config")
        second = self.run_doc()
        self.assertFalse(second["reused"])
        self.assertNotEqual(second["fingerprint"], first["fingerprint"])
        self.assertEqual(len(self.calls), 2)

    def test_cache_source_fingerprint_change_invalidates(self):
        first = self.run_doc()
        self.source_marker.write_bytes(b"changed-source-fingerprint")
        second = self.run_doc()
        self.assertFalse(second["reused"])
        self.assertNotEqual(second["fingerprint"], first["fingerprint"])

    def test_executor_throw_persists_failed_report_and_can_retry(self):
        report = self.run_doc(executor=self.executor(error=RuntimeError("stub boom")))
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["verification"]["execution"], "fail")
        self.assertIn("stub boom", report["reason"])
        self.assertEqual(json.loads((self.out / "control.json").read_text(encoding="utf-8"))["status"], "failed")
        self.assertEqual(json.loads((Path(report["attempt_dir"]) / "result.json").read_text(encoding="utf-8"))["status"], "failed")
        self.assertFalse((self.out / ".control.lock").exists())
        self.assertEqual(self.run_doc()["status"], "done")
        self.assertEqual(len(self.calls), 2)

    def test_prototype_inconclusive_not_playthrough_success_even_cached(self):
        doc = self.session()
        doc["purpose"] = "playthrough"
        first = self.run_doc(doc)
        second = self.run_doc(doc)
        self.assertEqual(first["status"], "inconclusive")
        self.assertEqual(second["status"], "inconclusive")
        self.assertEqual(second["verification"]["completion"], "inconclusive")
        self.assertNotEqual(second["verification"]["sync"], "pass")

    def test_zero_artifacts_cannot_succeed(self):
        report = self.run_doc(executor=self.executor(empty=True))
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["verification"]["execution"], "fail")

    def test_zero_byte_artifact_cannot_succeed(self):
        report = self.run_doc(executor=self.executor(zero_bytes=True))
        self.assertEqual(report["status"], "failed", "empty evidence file is not a delivered output")
        self.assertEqual(report["verification"]["execution"], "fail")

    def test_missing_artifact_cannot_succeed(self):
        def missing(program, attempt, work, timeout):
            return {"execution": "pass", "core_identity": "pass", "artifacts": [str(Path(attempt) / "never-created.bin")]}
        self.assertEqual(self.run_doc(executor=missing)["status"], "failed")

    def test_failure_and_bad_verdict_cannot_succeed(self):
        for execution, completion in (("fail", "inconclusive"), ("pass", "fail"), ("yes", "pass"), ("pass", "unknown")):
            with self.subTest(execution=execution, completion=completion):
                out = self.base / (execution + "_" + completion)
                self.assertEqual(self.run_doc(executor=self.executor(execution, completion), out=out)["status"], "failed")

    def test_existing_output_lock_is_not_stolen_or_deleted(self):
        lock = self.put("output/.control.lock", b"other-owner")
        before = snapshot(self.out)
        with self.assertRaises(SchemaError):
            self.run_doc()
        self.assertEqual(snapshot(self.out), before)
        self.assertEqual(lock.read_bytes(), b"other-owner")
        self.assertEqual(self.calls, [])

    def test_replaced_output_lock_is_not_deleted_by_old_owner(self):
        stub = self.executor()
        lock = self.out / ".control.lock"
        def replace_owner(program, attempt, work, timeout):
            result = stub(program, attempt, work, timeout)
            lock.unlink()
            lock.write_bytes(b"replacement-owner")
            return result
        self.run_doc(executor=replace_owner)
        self.assertTrue(lock.is_file(), "run's finally must not unlink a replacement owner's lock")
        self.assertEqual(lock.read_bytes(), b"replacement-owner")


class BatchCatalogCliTests(Fixture):
    def test_cli_plan_cannot_overwrite_task_or_rom(self):
        path = self.json_file("spec.json", self.session())
        for target in (path, self.rom):
            before = target.read_bytes()
            with redirect_stdout(io.StringIO()):
                code = C.main(["plan", "--spec", str(path), "--out", str(target)])
            self.assertEqual(code, 2)
            self.assertEqual(target.read_bytes(), before)

    def test_batch_summary_cannot_overwrite_rom(self):
        source = self.put("output/batch.json", b"fixture-rom")
        doc = self.session()
        doc["rom"] = {"path": str(source), "sha1": sha1(source.read_bytes())}
        spec = self.json_file("batch_job.json", doc)
        with self.assertRaises(SchemaError):
            C.batch([str(spec)], self.base, self.out, self.work)
        self.assertEqual(source.read_bytes(), b"fixture-rom")

    def injected_run(self, executor):
        def invoke(doc, base, out_dir, work_root=C.DEFAULT_WORK, timeout=300, allow=()):
            return REAL_RUN(doc, base, out_dir, work_root, timeout, executor=executor, allow=allow)
        return mock.patch.object(C, "run", side_effect=invoke)

    def test_batch_each_cell_status_counts_and_persisted_progress(self):
        docs = [self.session("ok"), self.session("blocked"), self.session("throw"), self.session("prototype"), self.session("checkfail")]
        docs[1]["rom"]["path"] = str(self.base / "missing.nes")
        docs[3]["purpose"] = "playthrough"
        paths = [str(self.json_file(d["id"] + ".json", d)) for d in docs]
        normal = self.executor()
        def executor(program, attempt, work, timeout):
            if program["id"] == "throw":
                raise RuntimeError("batch stub boom")
            result = normal(program, attempt, work, timeout)
            if program["id"] == "checkfail":
                result["completion"] = "fail"
            return result
        progress = []
        def tracked_write(path, value):
            REAL_WRITE_JSON(path, value)
            if Path(path).name == "batch.json":
                progress.append(deepcopy(value))
        with self.injected_run(executor), mock.patch.object(C, "write_json", side_effect=tracked_write):
            report = C.batch(paths, self.base, self.out, self.work, 7)
        expected = {"ok": "done", "blocked": "blocked", "throw": "failed", "prototype": "inconclusive", "checkfail": "failed"}
        self.assertEqual({r["id"]: r["status"] for r in report["jobs"]}, expected)
        self.assertEqual(report["counts"], dict(Counter(expected.values())))
        self.assertEqual([len(p["jobs"]) for p in progress], [1, 2, 3, 4, 5])
        for p in progress:
            self.assertEqual(p["counts"], dict(Counter(r["status"] for r in p["jobs"])))
        self.assertEqual(json.loads((self.out / "batch.json").read_text(encoding="utf-8")), report)
        self.assertFalse((self.out / ".control.lock").exists())

    def test_batch_duplicate_id_rejected_before_any_run_or_output(self):
        paths = [str(self.json_file(f"job{i}.json", self.session("duplicate"))) for i in range(2)]
        with self.injected_run(self.executor()) as run_spy, self.assertRaises(SchemaError):
            C.batch(paths, self.base, self.out, self.work, 7)
        run_spy.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_batch_runtime_lock_blocks_the_whole_batch_before_any_attempt(self):
        """11-21 实跑：kill 掉 SNES 那趟留下死锁，13 条 NES 批次全 0 帧失败，每条白写一份 attempt。
        规矩=开工前先问一次锁；跑中途撞上 0 帧 RuntimeBlocked 就就地停。"""
        paths = [str(self.json_file("locky%d.json" % i, self.session("locky%d" % i))) for i in range(3)]
        self.work.mkdir(parents=True, exist_ok=True)
        lock = Path(self.work) / ".control_runtime.lock"

        def fake_run(doc, base, out_dir, work_root, timeout, allow=()):
            return {"id": doc["id"], "status": "done", "runtime": {"frames_advanced": 42}}

        # 判据本身先用已知答案自检：自己=活，999999=死（不许起子进程，tasklist 会被 isolation 闸门抓）
        self.assertIs(C._pid_alive(os.getpid()), True)
        self.assertIs(C._pid_alive(999999), False)
        self.assertIsNone(C._pid_alive("not-a-pid"))

        # 死锁：占位 pid 不存在 ⇒ 一条都不许启动
        lock.write_text(json.dumps({"token": "t", "pid": 999999}), encoding="ascii")
        with mock.patch.object(C, "run", side_effect=fake_run) as spy, self.assertRaises(SchemaError) as boom:
            C.batch(paths, self.base, self.out, self.work, 7)
        spy.assert_not_called()
        self.assertIn("死锁", str(boom.exception))
        self.assertFalse(self.out.exists())

        # 活锁：措辞必须不同，不许把活锁说成死锁
        lock.write_text(json.dumps({"token": "t", "pid": os.getpid()}), encoding="ascii")
        with mock.patch.object(C, "run", side_effect=fake_run), self.assertRaises(SchemaError) as boom2:
            C.batch(paths, self.base, self.out, self.work, 7)
        self.assertIn("还活着", str(boom2.exception))
        self.assertNotIn("死锁", str(boom2.exception))

        # 量不到 ⇒ 说"查不到"，不能默认成死锁（默认成死锁就等于允许清锁）
        with mock.patch.object(C, "_pid_alive", side_effect=OSError("no kernel32")):
            state = C._runtime_lock_state(str(self.work))
        self.assertIsNone(state["pid_alive"])
        self.assertIn("查不到", C._lock_holder_words(state))

        # 不许退回子进程问法（起进程既被闸门禁止，又要跟 GBK 输出搏斗）
        import inspect
        self.assertNotIn("subprocess", inspect.getsource(C._pid_alive))
        self.assertNotIn("tasklist", inspect.getsource(C._runtime_lock_state))

        # 无锁 + 首条 0 帧 RuntimeBlocked ⇒ 后面全部标 blocked，run 只被调一次
        os.remove(lock)
        self.assertIsNone(C._runtime_lock_state(str(self.work)))
        calls = []

        def blocked_run(doc, base, out_dir, work_root, timeout, allow=()):
            calls.append(doc["id"])
            return {"id": doc["id"], "status": "failed",
                    "runtime": {"frames_advanced": 0, "reason": "RuntimeBlocked: work_root locked"},
                    "verification": {"execution": "fail"}}
        with mock.patch.object(C, "run", side_effect=blocked_run):
            report = C.batch(paths, self.base, self.out, self.work, 7)
        self.assertEqual(calls, ["locky0"])
        self.assertEqual([j["status"] for j in report["jobs"]], ["failed", "blocked", "blocked"])
        self.assertEqual(report["counts"], {"failed": 1, "blocked": 2})
        persisted = json.loads((self.out / "batch.json").read_text(encoding="utf-8"))
        self.assertEqual(persisted["counts"], report["counts"])

    def catalog_fixture(self):
        lib = self.base / "library"
        movie = self.movie(relative="library/movies/NES/demo.bk2")
        self.put("library/movies/NES/note.txt", b"inventory only")
        self.put("library/roms_verify/demo.nes", self.rom_bytes)
        self.json_file("library/versions/v1.json", {"SHA-1": sha1(self.rom_bytes), "System Code": "NES"})
        self.json_file("library/publications.json", {"publications": [
            {"id": "1", "game_id": "1", "version_id": "v1", "game": "fixture", "platform": "NES", "emulator": "BizHawk 2.8", "local_movie": str(movie.relative_to(lib)), "movie_ext": ".bk2"},
            {"id": "2", "game_id": "2", "platform": "NES", "emulator": "BizHawk 2.8"},
        ]})
        return lib

    def test_catalog_calls_real_registry_build_readonly_and_no_real_directory_writes(self):
        lib = self.catalog_fixture()
        before = snapshot(lib), snapshot(self.emu_root)
        # Guard covers all writes, including default real library/emulator paths.
        # Snapshot default index metadata as additional non-recursive evidence.
        real_indexes = [R.DEFAULT_LIB / "registry.json", R.DEFAULT_LIB / "publications.json"]
        metadata = {str(p): (p.stat().st_size, p.stat().st_mtime_ns) if p.exists() else None for p in real_indexes}
        with mock.patch.object(R, "build", wraps=R.build) as build:
            report = C.catalog(lib, self.emu_root)
        build.assert_called_once_with(lib, self.emu_root, out=None)
        self.assertEqual((snapshot(lib), snapshot(self.emu_root)), before)
        self.assertEqual({str(p): (p.stat().st_size, p.stat().st_mtime_ns) if p.exists() else None for p in real_indexes}, metadata)
        self.assertFalse((lib / "registry.json").exists())
        self.assertEqual(report["summary"]["total"], 2)
        self.assertEqual(report["summary"]["replayable"], 1)
        self.assertEqual(report["summary"]["blocked"], 1)
        self.assertEqual(report["inventory"], {"files": 2, "formats": {".bk2": 1, ".txt": 1}, "platforms": {"NES": 2}})
        self.assertEqual(report["execution_status"], "not_run")

    def test_cli_plan_run_status_with_real_entrypoints(self):
        spec = self.json_file("task.json", self.session())
        code, report = self.cli(["plan", "--spec", str(spec)])
        self.assertEqual((code, report["status"]), (0, "ready"))
        with self.injected_run(self.executor()):
            code, report = self.cli(["run", "--spec", str(spec), "--out", str(self.out), "--work-root", str(self.work), "--timeout", "7"])
        self.assertEqual((code, report["status"]), (0, "done"))
        code, status = self.cli(["status", "--out", str(self.out)])
        self.assertEqual((code, status["status"]), (0, "done"))
        self.assertEqual(status["artifacts"], report["artifacts"])

    def test_cli_window_slices_observation_task_from_existing_spec(self):
        doc = self.movie_doc(movie=self.movie(frames=100, relative="movies/whole.bk2"),
                             steps=[{"id": "roll", "op": "replay", "frames": "end"}])
        doc["verify"] = {"length": {"frames": 100, "source": "fixture"}}
        doc["completion"] = {"source": "fixture：击败最终 Boss 后 HUD 计数归零",
                             "checks": [{"id": "gauge", "domain": "System Bus", "addr": 129,
                                         "cmp": "eq", "value": 0}]}
        doc["record"] = {"video": True, "audio": True, "fps": 60, "speed": "realtime"}
        base = self.json_file("whole.json", doc)
        target = self.base / "window.json"
        code, report = self.cli(["window", "--spec", str(base), "--from", "20", "--to", "70",
                                 "--step", "10", "--out", str(target)])
        self.assertEqual((code, report["status"]), (0, "created"))
        # 20 起、每 10 帧一屏、到 70 收尾 = 6 个取样点；派生窗口不重扫 ROM 库
        self.assertEqual(report["checkpoints"], 6)
        self.assertEqual(report["id"], "session_window_20_70")
        spec = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(spec["purpose"], "control")
        self.assertEqual(spec["record"], {"video": False, "audio": False, "fps": 60, "speed": "unthrottled"})
        self.assertNotIn("completion", spec)
        self.assertEqual(spec["verify"]["length"],
                         {"frames": 70, "tolerance": C._tight_tolerance(70),
                          "source": "窗口终点 70 帧（整片 100 帧的前缀）"})
        self.assertEqual([s["op"] for s in spec["steps"]], ["replay", "checkpoint"] * 6)
        self.assertEqual(spec["steps"][0]["frames"], 20)
        self.assertEqual(sum(s["frames"] for s in spec["steps"] if s["op"] == "replay"), 70)
        self.assertEqual(spec["start"]["kind"], "movie")
        code, report = self.cli(["plan", "--spec", str(target)])
        self.assertEqual((code, report["status"]), (0, "ready"))

    def test_cli_window_rejects_out_of_range_and_ambiguous_inputs(self):
        doc = self.movie_doc()
        doc["verify"] = {"length": {"frames": 100}}
        base = self.json_file("whole.json", doc)
        blank = self.json_file("no_length.json", self.movie_doc())
        cases = [
            (["window", "--spec", str(base), "--from", "20", "--to", "101", "--out", str(self.base / "w1.json")],
             "越界，电影 session 只有 100 帧"),
            (["window", "--spec", str(base), "--from", "50", "--to", "30", "--out", str(self.base / "w2.json")],
             "窗口 50..30 越界"),
            (["window", "--spec", str(base), "--from", "0", "--to", "50", "--out", str(self.base / "w3.json")],
             "窗口 0..50 越界"),
            (["window", "--spec", str(base), "--from", "1", "--to", "50", "--step", "0",
              "--out", str(self.base / "w4.json")], "--step 必须在 1..600"),
            (["window", "--spec", str(base), "--from", "1", "--to", "50", "--step", "601",
              "--out", str(self.base / "w5.json")], "--step 必须在 1..600"),
            (["window", "--spec", str(base), "--pub", "1", "--from", "1", "--to", "50",
              "--out", str(self.base / "w6.json")], "--spec 或 --pub 二选一"),
            (["window", "--spec", str(blank), "--from", "1", "--to", "50", "--out", str(self.base / "w7.json")],
             "没有 verify.length"),
            (["window", "--spec", str(base), "--from", "1", "--to", "50", "--out", str(base)],
             "不覆盖已有任务"),
        ]
        for args, needle in cases:
            code, report = self.cli(args)
            self.assertEqual((code, report["status"]), (2, "error"), args)
            self.assertIn(needle, report["reason"], args)
        self.assertEqual([p.exists() for p in
                          [self.base / f"w{i}.json" for i in range(1, 8)]], [False] * 7)

    def test_cli_last_real_frame_is_a_legal_window_end(self):
        """101,485 那一格被当成"越界"拒掉过：期望值当时是从站点秒数反推的 101,484。
        末帧可达才谈得上"看过结局屏"。"""
        doc = self.movie_doc()
        doc["verify"] = {"length": {"frames": 100}}
        base = self.json_file("whole.json", doc)
        code, report = self.cli(["window", "--spec", str(base), "--from", "98", "--to", "100",
                                 "--step", "2", "--out", str(self.base / "w_last.json")])
        self.assertEqual((code, report["status"]), (0, "created"), report)
        spec = json.loads((self.base / "w_last.json").read_text(encoding="utf-8"))
        self.assertEqual(spec["verify"]["length"]["frames"], 100)
        self.assertEqual(spec["verify"]["length"]["tolerance"], C._tight_tolerance(100))
        self.assertEqual(sum(s["frames"] for s in spec["steps"] if s["op"] == "replay"), 100)

    def test_cli_plan_reports_the_movie_own_frame_count(self):
        """init 改拿电影自身帧数当期望值的前提：plan 必须把 .bk2 自己的口径原样报出来。"""
        doc = self.movie_doc(movie=self.movie(frames=100))
        doc["steps"] = [{"id": "roll", "op": "replay", "frames": "end"}]
        code, report = self.cli(["plan", "--spec", str(self.json_file("whole.json", doc))])
        self.assertEqual(code, 0, report)
        start = report["program"]["start"]
        self.assertEqual((start.get("movie_frames"), start.get("movie_frame_source")), (100, "input_log"), start)
        self.assertEqual(report["program"]["steps"][0]["frames"], 100)

    def test_cli_inconclusive_exit_three_and_invalid_timeout_two(self):
        doc = self.session()
        doc["purpose"] = "playthrough"
        spec = self.json_file("prototype.json", doc)
        args = ["run", "--spec", str(spec), "--out", str(self.out), "--work-root", str(self.work)]
        with self.injected_run(self.executor()):
            self.assertEqual(self.cli(args + ["--timeout", "7"])[0], 3)
        for timeout in ("nan", "inf", "0", "-1"):
            with self.subTest(timeout=timeout):
                code, report = self.cli(args + ["--timeout", timeout])
                self.assertEqual((code, report["status"]), (2, "error"))

    def test_cli_catalog_and_batch_outputs_are_fixture_only(self):
        lib = self.catalog_fixture()
        catalog_out = self.base / "catalog-output.json"
        code, summary = self.cli(["catalog", "--lib", str(lib), "--emu", str(self.emu_root), "--out", str(catalog_out)])
        self.assertEqual(code, 0)
        self.assertEqual(summary["summary"]["total"], 2)
        self.assertEqual(json.loads(catalog_out.read_text(encoding="utf-8"))["execution_status"], "not_run")
        job = self.json_file("job.json", self.rom_patch())
        batch = self.json_file("batch-spec.json", {"jobs": [str(job)]})
        code, report = self.cli(["batch", "--spec", str(batch), "--out", str(self.out), "--work-root", str(self.work), "--timeout", "7"])
        self.assertEqual((code, report["counts"]), (0, {"done": 1}))
        code, status = self.cli(["status", "--out", str(self.out)])
        self.assertEqual((code, status), (0, report))


class LockReclaimTests(Fixture):
    """残留锁的收口判据（11-22 补）：生产件原先只会拒绝、不会收，清锁只能手搓 ⇒ 违反"结果走生产代码路径"。
    规矩=默认只读；只有把持有者量到「已不存在=死锁」才删，token 不符、内容变了、查不到一律拒。"""

    def runtime_lock(self, token="t", pid=999999):
        self.work.mkdir(parents=True, exist_ok=True)
        lock = self.work / ".control_runtime.lock"
        lock.write_text(json.dumps({"token": token, "pid": pid}), encoding="ascii")
        return lock

    def test_reclaim_clears_only_a_provably_dead_holder(self):
        lock = self.runtime_lock("abc", 999999)
        report = C.reclaim_stale_lock(str(lock), "abc")
        self.assertEqual(report["status"], "stale_cleared")
        self.assertEqual(report["removed"], {"pid": 999999, "token": "abc", "pid_alive": False})
        self.assertFalse(report["still_there"])
        self.assertFalse(lock.exists())

    def test_reclaim_handles_the_output_dir_token_text_format(self):
        """`_lock()` 写的是 "pid:token" 纯文本，别只认 JSON 那一半。"""
        self.out.mkdir(parents=True, exist_ok=True)
        lock = self.out / ".control.lock"
        lock.write_text("999999:deadbeef", encoding="ascii")
        self.assertEqual(C.reclaim_stale_lock(str(lock), "deadbeef")["status"], "stale_cleared")
        self.assertFalse(lock.exists())

    def test_reclaim_refuses_a_live_or_unmeasurable_holder(self):
        for pid, word in ((os.getpid(), "还活着"), (None, "查不到")):
            lock = self.runtime_lock("t", 999999)
            lock.write_text(json.dumps({"token": "t", "pid": pid}), encoding="ascii")
            with self.assertRaises(C.SchemaError) as boom:
                C.reclaim_stale_lock(str(lock))
            self.assertIn(word, str(boom.exception))
            self.assertTrue(lock.exists(), "拒收就不许动锁")

    def test_reclaim_refuses_a_lock_it_did_not_claim(self):
        lock = self.runtime_lock("mine", 999999)
        with self.assertRaises(C.SchemaError) as boom:
            C.reclaim_stale_lock(str(lock), "someone-elses")
        self.assertIn("认领凭据不符", str(boom.exception))
        self.assertTrue(lock.exists())

    def test_reclaim_refuses_when_the_lock_changes_under_it(self):
        """pid 会被复用：核实与删除之间内容变了就必须停手，否则收到别人那趟的锁。"""
        lock = self.runtime_lock("orig", 999999)
        calls = []

        def hijack(pid):
            calls.append(pid)
            if len(calls) == 1:
                lock.write_text(json.dumps({"token": "newcomer", "pid": os.getpid()}), encoding="ascii")
            return False

        with mock.patch.object(C, "_pid_alive", side_effect=hijack):
            with self.assertRaises(C.SchemaError) as boom:
                C.reclaim_stale_lock(str(lock), "orig")
        self.assertIn("锁内容变了", str(boom.exception))
        self.assertTrue(lock.exists())
        self.assertEqual(json.loads(lock.read_text(encoding="utf-8"))["token"], "newcomer")

    def test_cli_locks_is_read_only_unless_told_to_clear(self):
        lock = self.runtime_lock("t", 999999)
        code, state = self.cli(["locks", "--work-root", str(self.work)])
        self.assertEqual(code, 0)
        self.assertEqual(state["runtime_lock"]["pid_alive"], False)
        self.assertNotIn("cleared", state)
        self.assertTrue(lock.exists(), "不带 --clear-stale 一条都不许删")

        code, state = self.cli(["locks", "--work-root", str(self.work), "--clear-stale"])
        self.assertEqual((code, state["cleared"][0]["status"], state["refused"]),
                         (0, "stale_cleared", []))
        self.assertFalse(lock.exists())

    def test_cli_locks_reports_a_refusal_with_a_nonzero_exit(self):
        lock = self.runtime_lock("t", os.getpid())
        code, state = self.cli(["locks", "--work-root", str(self.work), "--clear-stale"])
        self.assertEqual(code, 1)
        self.assertEqual(state["cleared"], [])
        self.assertIn("还活着", state["refused"][0]["reason"])
        self.assertTrue(lock.exists())


class PopularityGateTests(Fixture):
    """选题闸门：只测最有名、大家玩得多的作品（用户 2026-11-22 口径，规则落在仓库根目录说明书）。

    名单是正向白名单而不是黑名单——写不出证据的标题一律当冷门；
    反过来，光有销量行也买不到门票（外设卡、授权体育、用户点名的狮子王都有百万行）。
    """

    def codes(self, report):
        return [b["code"] for b in report["blockers"]]

    def reasons(self, report):
        return " ".join(b["reason"] for b in report["blockers"])

    def doc_for(self, game, platform="NES"):
        doc = self.session()
        doc["game"] = game
        doc["platform"] = platform
        doc["profile"]["system"] = platform
        doc["profile"]["core"] = "NesHawk" if platform == "NES" else "BSNES"
        return doc

    def pop_codes(self, report):
        return [b["code"] for b in report["blockers"]
                if b["code"].startswith(("title_off", "popularity_"))]

    def test_famous_titles_get_through(self):
        for game in ("Super Mario Bros.", "The Legend of Zelda", "Ninja Gaiden",
                     "Metroid", "Duck Hunt", "Contra", "Super Dodge Ball"):
            with self.subTest(game=game):
                report = C.plan(self.doc_for(game), self.base)
                self.assertEqual(self.pop_codes(report), [], report["blockers"])
                self.assertTrue(POP.is_famous(game, "NES"), game)

    def test_obscure_titles_are_blocked_before_any_work(self):
        for game in ("Alwa's Awakening: The 8-Bit Edition", "Nova the Squirrel",
                     "I Wanna Be the Guy", "Battle Kid: Fortress of Peril",
                     "Lester the Unlikely"):
            platform = "SNES" if game == "Lester the Unlikely" else "NES"
            with self.subTest(game=game):
                report = C.plan(self.doc_for(game, platform), self.base)
                self.assertEqual(self.codes(report), ["title_off_popularity_list"], report["blockers"])
                self.assertEqual(report["status"], "blocked")
                self.assertIn("热门名单", self.reasons(report))
                self.assertFalse(POP.is_famous(game, platform))

    def test_a_sales_row_alone_does_not_buy_a_slot(self):
        # 销量行确实在名单上，但 demote 照样拦：外设卡要别的设备、授权体育没有中文怀旧层、
        # 狮子王是用户当场点名的冷门。
        for game, platform, needle in (("The Lion King", "SNES", "用户点名"),
                                       ("Mario Paint", "SNES", "外设"),
                                       ("World Class Track Meet", "NES", "外设"),
                                       ("Tecmo Super Bowl", "NES", "联盟授权")):
            with self.subTest(game=game):
                info = POP.classify(game, platform)
                self.assertGreaterEqual(info["sales"] or 0, 1000000,
                                        f"{game} 本该有百万销量行，否则这条反证不成立")
                self.assertFalse(info["on_list"], game)
                report = C.plan(self.doc_for(game, platform), self.base)
                self.assertEqual(self.codes(report), ["title_off_popularity_list"], report["blockers"])
                self.assertIn(needle, self.reasons(report))

    def test_rom_hacks_cannot_ride_a_famous_series_name(self):
        # 精确匹配（归一化后）才作数；子串一律不算，改版/同人卡蹭不到名作系列。
        for game, platform in (("Super Metroid: Kaizo Edition", "SNES"), ("Rockman Claw", "NES"),
                               ("Nova the Squirrel", "NES"), ("Super Contra 7", "NES"),
                               ("Kirby's Dream Land 2.5", "NES"), ("I Wanna Be the Guy", "NES")):
            with self.subTest(game=game):
                self.assertFalse(POP.is_famous(game, platform), game)
                self.assertIn("title_off_popularity_list",
                              self.codes(C.plan(self.doc_for(game, platform), self.base)))

    def test_the_list_is_scoped_per_platform(self):
        # NES 的超级马里奥兄弟不能替 SNES 说话，反过来也一样（跨平台顶名是设计禁区）。
        self.assertFalse(POP.is_famous("Super Mario Bros.", "SNES"))
        self.assertFalse(POP.is_famous("Super Mario World", "NES"))
        self.assertIn("title_off_popularity_list", self.codes(C.plan(self.doc_for("Super Mario World"), self.base)))
        self.assertEqual(self.codes(C.plan(self.doc_for("Super Mario World", "SNES"), self.base)), [])

    def test_spelling_variants_resolve_but_ambiguity_is_refused(self):
        self.assertTrue(POP.is_famous("RC Pro-Am", "NES"), "去空格写法应命中 R.C. Pro-Am")
        self.assertTrue(POP.is_famous("Excite Bike", "NES"), "连写/分写差异应命中 Excitebike")
        self.assertTrue(POP.is_famous("Super Mario World 2 - Yoshi's Island", "SNES"))
        # Dragon Quest I & II 与 Dragon Quest III 去掉空格后同名：正字各自命中，
        # 但靠去空格才撞上的写法必须拒答（宁漏不错认）。
        self.assertTrue(POP.is_famous("Dragon Quest III", "SNES"))
        self.assertTrue(POP.is_famous("Dragon Quest I & II", "SNES"))
        self.assertFalse(POP.is_famous("DragonQuestI&II", "SNES"))
        report = C.plan(self.doc_for("DragonQuestI&II", "SNES"), self.base)
        self.assertIn("撞上同一个键", self.reasons(report))

    def test_allow_downgrades_the_gate_and_leaves_a_trace(self):
        doc = self.doc_for("Alwa's Awakening: The 8-Bit Edition")
        report = C.plan(doc, self.base, ("title_off_popularity_list",))
        self.assertEqual(report["status"], "ready")
        self.assertEqual(self.codes(report), [])
        self.assertEqual([b["code"] for b in report["warnings"]], ["title_off_popularity_list"])
        self.assertIn("冷门", self.reasons_of(report["warnings"]))

    def reasons_of(self, items):
        return " ".join(i["reason"] for i in items)

    def test_missing_game_name_is_its_own_code_not_an_allow_escapable_one(self):
        doc = self.session()
        doc["game"] = ""
        report = C.plan(doc, self.base)
        self.assertEqual(self.codes(report), ["popularity_game_field_missing"], report["blockers"])
        allowed = C.plan(doc, self.base, ("title_off_popularity_list",))
        self.assertEqual(self.codes(allowed), ["popularity_game_field_missing"],
                         "--allow 冷门不许顺手把「没写名字」也放过去")

    def test_missing_list_file_fails_closed(self):
        gone = self.base / "没有这个名单.json"
        with mock.patch.object(POP, "LIST_PATH", gone):
            report = C.plan(self.session(), self.base)
        self.assertEqual(self.codes(report), ["popularity_list_missing"], report["blockers"])

    def test_window_annotation_is_not_part_of_the_title(self):
        # control 的窗口任务会把「— 只看 x..y 帧」拼在 game 后面；闸门先剥掉这层再看名单，
        # 否则每个窗口任务都会被当成没听过的作品。
        annotated = f"{FAMOUS_NES}{POP.WINDOW_NOTE}0..100 帧（每 25 帧一屏）"
        self.assertEqual(self.pop_codes(C.plan(self.doc_for(annotated), self.base)), [])
        obscure = f"Alwa's Awakening: The 8-Bit Edition{POP.WINDOW_NOTE}0..100 帧"
        report = C.plan(self.doc_for(obscure), self.base)
        self.assertIn("title_off_popularity_list", self.codes(report))
        self.assertNotIn("只看", self.reasons(report), "拦下来的理由要挂干净标题")

    def test_platforms_outside_the_gate_are_not_reported_as_cold(self):
        # GBA 还没实测过整片，拦它的是 driver_platform_unproven，不是选题闸门。
        report = C.plan(self.doc_for("Alwa's Awakening: The 8-Bit Edition", "GBA"), self.base)
        self.assertEqual(self.codes(report), ["driver_platform_unproven"], report["blockers"])

    def test_the_two_authorities_stay_in_step(self):
        # 名单管辖的平台必须和「驱动实测过整片」的平台一致，否则会出现
        # 「闸门说归它管、控制层说没跑过」的双头口径。
        self.assertEqual(sorted(x.upper() for x in POP.load()["platforms_gated"]),
                         sorted(C.PLATFORMS_DRIVER_PROVEN))
        rows = POP.load()["rows"]
        self.assertGreater(len(rows), 150)
        for row in rows:
            with self.subTest(title=row["title"]):
                self.assertIn(row["tier"], ("T1", "T2"))
                self.assertTrue(row.get("basis"), row["title"])
                if row.get("demote") or row.get("under_review"):
                    continue
                self.assertTrue(POP.is_famous(row["title"], row["platform"]),
                                f'{row["platform"]} {row["title"]} 自称可用却匹配不中自己')


class StateFramebufferTests(Fixture):
    def test_plain_framebuffer_decodes_without_zstd(self):
        from PIL import Image
        from taspipe.control_livecheck import decode_framebuffer

        expected = Image.new("RGBA", (3, 2), (12, 34, 56, 255))
        buffer = io.BytesIO()
        expected.save(buffer, format="BMP")
        actual = decode_framebuffer(buffer.getvalue())
        self.assertEqual(actual.size, expected.size)
        self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_zstd_framebuffer_uses_bizhawk_library_and_rejects_bad_magic_payload(self):
        from PIL import Image
        from taspipe import movie_converters as MC
        from taspipe.control_livecheck import decode_framebuffer

        expected = Image.new("RGBA", (2, 3), (90, 80, 70, 255))
        buffer = io.BytesIO()
        expected.save(buffer, format="BMP")
        compressed = MC.ZSTD_FRAME_MAGIC + b"compressed-fixture"
        with mock.patch.object(MC, "_zstd_decompress", return_value=buffer.getvalue()) as decompress:
            actual = decode_framebuffer(compressed, self.bh)
        decompress.assert_called_once_with(compressed, self.bh)
        self.assertEqual(actual.tobytes(), expected.tobytes())
        with mock.patch.object(MC, "_zstd_decompress", side_effect=MC.MovieConvertError("bad frame")):
            with self.assertRaisesRegex(MC.MovieConvertError, "bad frame"):
                decode_framebuffer(compressed, self.bh)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    unittest.main(verbosity=2)

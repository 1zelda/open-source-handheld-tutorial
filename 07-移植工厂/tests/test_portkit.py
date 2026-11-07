from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from portfactory.portkit import builders, gates, portmaster, profiles
from portfactory.portkit.spec import SpecError, validate


def make_spec(**over) -> dict:
    raw = {
        "schema": 1,
        "id": "demo",
        "title": "Demo",
        "family": "source-port",
        "source": {"repo": "https://example.invalid/demo.git", "commit": "a" * 40},
        "data": {"policy": "user-supplied", "required": ["DEMO.DAT"]},
        "targets": {
            "handheld": {
                "profile": "zig-aarch64",
                "build": {"system": "gnumake", "artifact": "demo.bin"},
                "package": {
                    "port_dir": "demo",
                    "launcher_file": "Demo.sh",
                    "binary": "./demo.bin",
                    "zip_name": "Demo.zip",
                    "files": [{"src": "${artifact}", "dst": "demo/demo.bin"}],
                    "license_files": ["licenses/gpl-2.0.txt"],
                    "attr": {
                        "title": "Demo", "desc": "d", "inst": "i", "genres": ["misc"],
                        "porter": ["t"], "image": {}, "rtr": False, "exp": False,
                        "runtime": [], "min_glibc": "2.29", "reqs": [], "arch": ["aarch64"],
                    },
                },
                "gates": ["elf"],
            }
        },
    }
    raw.update(over)
    return raw


def png_header(width: int, height: int) -> bytes:
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
            + struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00")


class SpecCase(unittest.TestCase):
    def test_pins_commit(self):
        raw = make_spec()
        raw["source"]["commit"] = ""
        with self.assertRaises(SpecError):
            validate(raw)

    def test_bundled_needs_rights_proof(self):
        raw = make_spec()
        raw["data"] = {"policy": "bundled", "bundled": ["data/"]}
        with self.assertRaises(SpecError):
            validate(raw)

    def test_user_supplied_gets_default_forbidden(self):
        spec = validate(make_spec())
        self.assertIn("*.grp", spec.forbidden_globs())
        self.assertIn("*.nsp", spec.forbidden_globs())

    def test_unknown_family(self):
        with self.assertRaises(SpecError):
            validate(make_spec(family="magic"))

    def test_free_download_needs_pinned_sha256(self):
        raw = make_spec()
        raw["data"] = {"policy": "free-download", "rights_proof": "作者免费发布",
                       "downloads": [{"url": "https://example.invalid/d.zip", "sha256": "abc"}]}
        with self.assertRaises(SpecError):
            validate(raw)
        raw["data"]["downloads"][0]["sha256"] = "0" * 64
        validate(raw)

    def test_free_download_needs_rights_proof(self):
        raw = make_spec()
        raw["data"] = {"policy": "free-download",
                       "downloads": [{"url": "https://example.invalid/d.zip",
                                      "sha256": "0" * 64}]}
        with self.assertRaises(SpecError):
            validate(raw)


class PackageCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "licenses").mkdir()
        (self.root / "licenses" / "gpl-2.0.txt").write_text("GPL", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def cfg(self) -> dict:
        return {
            "port_dir": "demo",
            "launcher_file": "Demo.sh",
            "binary": "./demo.bin",
            "zip_name": "Demo.zip",
            "data_required": ["DEMO.DAT"],
            "data_message": "缺少 DEMO.DAT",
            "license_files": ["licenses/gpl-2.0.txt"],
            "screenshot": None,
            "attr": make_spec()["targets"]["handheld"]["package"]["attr"],
        }

    def build_zip(self, cfg: dict | None = None) -> tuple[Path, dict]:
        cfg = cfg or self.cfg()
        staging = self.root / "stage"
        (staging / "demo").mkdir(parents=True, exist_ok=True)
        portmaster.stage_launcher(staging, cfg)
        (staging / "demo" / "demo.bin").write_bytes(b"\x7fELF" + b"\0" * 60)
        portmaster.copy_member(self.root / "licenses" / "gpl-2.0.txt",
                               staging / "demo" / "licenses" / "gpl-2.0.txt")
        port_json = portmaster.render_port_json({"zip_name": "Demo.zip", "attr": cfg["attr"]},
                                                ["Demo.sh", "demo"])
        (staging / "demo" / "port.json").write_text(json.dumps(port_json), encoding="utf-8")
        (staging / "demo" / "gameinfo.xml").write_text(
            portmaster.render_gameinfo(cfg, [{"script": "Demo.sh", "name": "Demo"}]),
            encoding="utf-8")
        built = portmaster.build_zip(staging, self.root / "Demo.zip")
        return Path(built["path"]), cfg

    def test_launcher_checks_data_and_uses_portmaster(self):
        cfg = self.cfg()
        script = portmaster.render_launcher(cfg)
        self.assertIn("get_controls", script)
        self.assertIn("pm_finish", script)
        self.assertIn('[ ! -f "$GAMEDIR/DEMO.DAT" ]', script)
        self.assertIn('cd "$GAMEDIR"', script)
        self.assertIn('$ESUDO chmod +x "./demo.bin"', script)

    def test_launcher_subdir(self):
        cfg = {**self.cfg(), "game_sub": "demo"}
        script = portmaster.render_launcher(cfg)
        self.assertIn('GAMESUB="$GAMEDIR/demo"', script)
        self.assertIn('cd "$GAMESUB"', script)

    def test_port_json_needs_all_attr_keys(self):
        attr = dict(make_spec()["targets"]["handheld"]["package"]["attr"])
        attr.pop("min_glibc")
        with self.assertRaises(ValueError):
            portmaster.render_port_json({"zip_name": "Demo.zip", "attr": attr}, ["Demo.sh"])

    def test_zip_is_deterministic_and_executable(self):
        first, _ = self.build_zip()
        one = hashlib.sha256(first.read_bytes()).hexdigest()
        second, cfg = self.build_zip()
        two = hashlib.sha256(second.read_bytes()).hexdigest()
        self.assertEqual(one, two)
        with zipfile.ZipFile(second) as zf:
            info = zf.getinfo("Demo.sh")
            self.assertEqual(info.date_time, portmaster.PACK_EPOCH)
            self.assertTrue((info.external_attr >> 16) & 0o111)

    def test_layout_gate_passes(self):
        pkg, cfg = self.build_zip()
        ctx = {"package": str(pkg), "target": {"package": cfg}}
        self.assertEqual(gates.gate_portmaster_layout(ctx).status, "pass")

    def test_layout_gate_catches_missing_pm_finish(self):
        cfg = self.cfg()
        staging = self.root / "bad"
        (staging / "demo").mkdir(parents=True)
        (staging / "Demo.sh").write_text("#!/bin/bash\nget_controls\n", encoding="utf-8")
        (staging / "demo" / "port.json").write_text(
            json.dumps(portmaster.render_port_json({"zip_name": "Demo.zip", "attr": cfg["attr"]},
                                                   ["Demo.sh", "demo"])), encoding="utf-8")
        (staging / "demo" / "gameinfo.xml").write_text("<gameList/>", encoding="utf-8")
        pkg = portmaster.build_zip(staging, self.root / "Bad.zip")
        outcome = gates.gate_portmaster_layout({"package": pkg["path"],
                                               "target": {"package": cfg}})
        self.assertEqual(outcome.status, "fail")
        self.assertTrue(any("pm_finish" in p for p in outcome.detail["problems"]))

    def test_data_gate_rejects_commercial_data(self):
        pkg, cfg = self.build_zip()
        staging = self.root / "leak"
        (staging / "demo").mkdir(parents=True, exist_ok=True)
        portmaster.stage_launcher(staging, cfg)
        (staging / "demo" / "DUKE3D.GRP").write_bytes(b"data")
        leaked = portmaster.build_zip(staging, self.root / "Leak.zip")
        spec = validate(make_spec())
        outcome = gates.gate_data_policy({"package": leaked["path"], "spec": spec})
        self.assertEqual(outcome.status, "fail")

    def test_screenshot_gate(self):
        pkg, _ = self.build_zip()
        staging = self.root / "shot"
        (staging).mkdir()
        (staging / "screenshot.png").write_bytes(png_header(320, 240))
        good = portmaster.build_zip(staging, self.root / "Shot.zip")
        self.assertEqual(gates.gate_screenshot({"package": good["path"]}).status, "pass")
        (staging / "screenshot.png").write_bytes(png_header(160, 120))
        small = portmaster.build_zip(staging, self.root / "Small.zip")
        self.assertEqual(gates.gate_screenshot({"package": small["path"]}).status, "fail")


class BuildPlanCase(unittest.TestCase):
    def test_gnumake_expands_vars(self):
        target = {"build": {"system": "gnumake", "target": "demo", "artifact": "demo.bin",
                            "make_vars": {"PLATFORM": "LINUX",
                                          "CUSTOMOPT": "-ffile-prefix-map=${src}=."}}}
        profile = profiles.Profile(id="host", vars={"make": "make"})
        plan = builders.plan(target, profile, Path("/w/src"), Path("/w/build"))
        self.assertEqual(len(plan), 1)
        self.assertIn('-ffile-prefix-map=/w/src=.', plan[0].cmd)
        self.assertIn('PLATFORM="LINUX"', plan[0].cmd)

    def test_custom_rejects_unknown_var(self):
        target = {"build": {"system": "custom", "artifact": "x",
                            "commands": ["touch ${nope}"]}}
        with self.assertRaises(ValueError):
            builders.plan(target, profiles.Profile(id="host"), Path("/w/src"), Path("/w/build"))

    def test_unknown_build_system(self):
        with self.assertRaises(ValueError):
            builders.plan({"build": {"system": "wizard"}}, profiles.Profile(id="host"),
                          Path("/w/src"), Path("/w/build"))

    def test_make_var_with_quotes_is_rejected(self):
        # 本机 mingw make 会把带引号的 recipe 拼坏，只能在计划阶段拦下来
        target = {"build": {"system": "gnumake", "artifact": "x",
                            "make_vars": {"TYRIAN_DIR": '"data"'}}}
        with self.assertRaises(ValueError):
            builders.plan(target, profiles.Profile(id="host", vars={"make": "make"}),
                          Path("/w/src"), Path("/w/build"))


class DataDownloadCase(unittest.TestCase):
    def test_strip_root_and_lowercase(self):
        from portfactory.portkit.runner import _extract_zip
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            blob = root / "d.zip"
            with zipfile.ZipFile(blob, "w") as zf:
                zf.writestr("PACK/README.TXT", "hi")
                zf.writestr("PACK/SUB/DATA.DAT", "x")
            out = root / "out"
            _extract_zip(blob, out, lowercase=True, strip_root=True)
            self.assertTrue((out / "readme.txt").is_file())
            self.assertTrue((out / "sub" / "data.dat").is_file())

    def test_rejects_zip_slip(self):
        from portfactory.portkit.runner import _extract_zip
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            blob = root / "evil.zip"
            with zipfile.ZipFile(blob, "w") as zf:
                zf.writestr("../escape.txt", "x")
            with self.assertRaises(OSError):
                _extract_zip(blob, root / "out")

    def test_rejects_zip_sibling_prefix(self):
        from portfactory.portkit.runner import _extract_zip
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            blob = root / "evil.zip"
            with zipfile.ZipFile(blob, "w") as zf:
                zf.writestr("../out-escape/file.txt", "x")
            with self.assertRaises(OSError):
                _extract_zip(blob, root / "out")
            self.assertFalse((root / "out-escape" / "file.txt").exists())


class ElfGateCase(unittest.TestCase):
    def test_rejects_non_elf(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.bin"
            path.write_bytes(b"not an elf")
            outcome = gates.gate_elf({"artifact": str(path), "target": {}})
            self.assertEqual(outcome.status, "fail")

    def test_accepts_minimal_aarch64(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.bin"
            head = b"\x7fELF\x02\x01\x01" + b"\0" * 9
            head += struct.pack("<H", 2) + struct.pack("<H", 183)
            head += struct.pack("<I", 1) + b"\0" * 40
            path.write_bytes(head + b"\0" * 64)
            outcome = gates.gate_elf({"artifact": str(path), "target": {"arch": "aarch64"}})
            self.assertEqual(outcome.status, "pass", outcome.detail)


if __name__ == "__main__":
    unittest.main()

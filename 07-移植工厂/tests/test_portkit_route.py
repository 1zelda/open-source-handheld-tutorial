from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from portfactory import cli
from portfactory.portkit import route


def pe_bytes() -> bytes:
    data = bytearray(512)
    data[0:2] = b"MZ"
    data[0x3C:0x40] = (0x80).to_bytes(4, "little")
    data[0x80:0x84] = b"PE\0\0"
    data[0x84:0x86] = (0x8664).to_bytes(2, "little")
    return bytes(data)


def elf_bytes() -> bytes:
    data = bytearray(64)
    data[0:4] = b"\x7fELF"
    data[4:7] = bytes([2, 1, 1])
    data[16:18] = (3).to_bytes(2, "little")
    data[18:20] = (0xB7).to_bytes(2, "little")
    return bytes(data)


def nro_bytes() -> bytes:
    data = bytearray(64)
    data[0:4] = (0x14000000).to_bytes(4, "little")
    data[0x10:0x14] = b"NRO0"
    return bytes(data)


def xex2_bytes() -> bytes:
    data = bytearray(64)
    data[0:4] = b"XEX2"
    return bytes(data)


class RouteCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def make(self, name: str, data: bytes | str) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            path.write_bytes(data)
        else:
            path.write_text(data, encoding="utf-8")
        return path

    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def snapshot(self, root: Path) -> list[tuple[str, int, int]]:
        records = []
        for base, dirs, names in os.walk(root):
            dirs.sort()
            for name in sorted(names):
                path = Path(base) / name
                stat = path.stat()
                records.append((path.relative_to(root).as_posix(), stat.st_size,
                                stat.st_mtime_ns))
        return records

    # ------------------------------------------------------------ 源码 / 重编译
    def test_cmake_source_tree_is_b_source(self):
        self.make("CMakeLists.txt", "project(game C)\n")
        self.make("src/main.c", "int main(void){return 0;}\n")
        result = route.scan(self.root)
        self.assertEqual(result["route"], "B-source")
        self.assertEqual(result["confidence"], "high")
        self.assertEqual(result["blockers"], [])
        kinds = {item["kind"] for item in result["signals"]}
        self.assertIn("build", kinds)
        self.assertIn("source", kinds)
        self.assertTrue(any("port new" in step for step in result["next_steps"]))
        self.assertIn("B-source", route.render(result))

    def test_decomp_markers_route_to_recomp(self):
        self.make("symbols.txt", "main = 0x80003100;\n")
        self.make("asm/boot.s", ".set noreorder\n")
        self.make("Makefile", "all:\n\t@true\n")
        result = route.scan(self.root)
        self.assertEqual(result["route"], "B-recomp")
        self.assertEqual(result["title"], "反编译重建（B）")
        self.assertTrue(any("反编译" in item for item in result["cautions"]))
        self.assertTrue(any("port new" in step for step in result["next_steps"]))

    def test_source_tree_with_data_warns_about_policy(self):
        self.make("Makefile", "all:\n\t@true\n")
        self.make("src/game.c", "int main(void){return 0;}\n")
        self.make("data/GAME.GRP", b"data")
        result = route.scan(self.root)
        self.assertEqual(result["route"], "B-source")
        self.assertTrue(any("数据政策" in item for item in result["cautions"]))

    # ------------------------------------------------------------ 数据 / 制品
    def test_data_only_directory(self):
        self.make("DUKE3D.GRP", b"grp")
        self.make("DUKE.RTS", b"rts")
        result = route.scan(self.root)
        self.assertEqual(result["route"], "data-only")
        self.assertTrue(result["blockers"])
        self.assertIn("缺少引擎源码", result["blockers"][0])
        self.assertTrue(any("源码" in step for step in result["next_steps"]))

    def test_nro_is_existing_artifact_not_port(self):
        path = self.make("game.nro", nro_bytes())
        result = route.scan(path)
        self.assertEqual(result["route"], "existing-artifact")
        self.assertEqual(result["scanned"]["kind"], "file")
        self.assertTrue(any("game intake" in step for step in result["next_steps"]))
        self.assertTrue(any("不能算移植" in item for item in result["blockers"]))

    # ------------------------------------------------------------ 二进制
    def test_pe_binary_routes_to_a1_with_ghidra_blocker(self):
        path = self.make("game.exe", pe_bytes())
        result = route.scan(path)
        self.assertEqual(result["route"], "A1-ghidra")
        self.assertTrue(any("Ghidra" in item for item in result["blockers"]))
        self.assertTrue(any("research new" in step for step in result["next_steps"]))

    def test_elf_binary_routes_to_a1_and_notes_arch(self):
        path = self.make("game.elf", elf_bytes())
        result = route.scan(path)
        self.assertEqual(result["route"], "A1-ghidra")
        self.assertTrue(any("ELF" in item for item in result["cautions"]))
        notes = " ".join(item["note"] for item in result["signals"])
        self.assertIn("aarch64", notes)

    def test_xex2_routes_to_rexglue(self):
        path = self.make("default.xex", xex2_bytes())
        result = route.scan(path)
        self.assertEqual(result["route"], "A2-rexglue")
        self.assertTrue(any("ReXGlue" in item for item in result["blockers"]))

    def test_rom_routes_to_emulation_and_refuses_native_claim(self):
        path = self.make("game.gba", b"\x00" * 64)
        result = route.scan(path)
        self.assertEqual(result["route"], "emulation")
        self.assertTrue(any("模拟器" in item for item in result["blockers"]))

    # ------------------------------------------------------------ 压缩包
    def test_zip_is_not_unpacked_and_stays_archive(self):
        path = self.root / "source.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("CMakeLists.txt", "project(game C)\n")
            archive.writestr("src/main.c", "int main(void){return 0;}\n")
        result = route.scan(path)
        self.assertEqual(result["route"], "archive")
        self.assertFalse((self.root / "CMakeLists.txt").exists())
        note = " ".join(item.get("note", "") for item in result["signals"])
        self.assertIn("cmakelists.txt", note.lower())
        self.assertTrue(any("解压" in step for step in result["next_steps"]))

    def test_apk_is_android_package(self):
        path = self.root / "game.apk"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("AndroidManifest.xml", "<manifest/>")
            archive.writestr("classes.dex", b"dex\n035\0")
        result = route.scan(path)
        self.assertEqual(result["route"], "android-apk")
        self.assertTrue(any("Android" in item for item in result["blockers"]))

    # ------------------------------------------------------------ 未知 / 边界
    def test_unknown_input_is_unrouted_and_exit_2(self):
        self.make("notes.txt", "nothing here\n")
        result = route.scan(self.root)
        self.assertEqual(result["route"], "unrouted")
        self.assertEqual(result["confidence"], "low")
        code, out = self.cli("port", "route", str(self.root))
        self.assertEqual(code, 2, out)
        self.assertIn("无法判定", out)

    def test_missing_input_is_refused(self):
        code, out = self.cli("port", "route", str(self.root / "missing"))
        self.assertEqual(code, 2, out)
        self.assertIn("输入不存在", out)

    def test_scan_is_read_only(self):
        self.make("CMakeLists.txt", "project(game C)\n")
        self.make("src/main.c", "int main(void){return 0;}\n")
        self.make("data/GAME.GRP", b"grp")
        before = self.snapshot(self.root)
        route.scan(self.root)
        self.assertEqual(self.snapshot(self.root), before)

    def test_cli_json_and_out_file(self):
        self.make("CMakeLists.txt", "project(game C)\n")
        self.make("src/main.c", "int main(void){return 0;}\n")
        out_path = self.root / "reports" / "route.json"
        code, out = self.cli("port", "route", str(self.root), "--json",
                             "--out", str(out_path))
        self.assertEqual(code, 0, out)
        payload = json.loads(out)
        self.assertEqual(payload["route"], "B-source")
        self.assertEqual(payload["schema"], 1)
        written = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(written["route"], "B-source")
        self.assertEqual(written["scanned"]["path"], str(self.root.resolve()))

    def test_markdown_report_written(self):
        self.make("CMakeLists.txt", "project(game C)\n")
        out_path = self.root / "route.md"
        code, out = self.cli("port", "route", str(self.root), "--out", str(out_path))
        self.assertEqual(code, 0, out)
        self.assertIn("路线判定", out)
        written = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(written["route"], "B-source")

    def test_symlinks_are_skipped(self):
        self.make("CMakeLists.txt", "project(game C)\n")
        self.make("src/main.c", "int main(void){return 0;}\n")
        link = self.root / "linked"
        try:
            os.symlink(self.root / "src", link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("当前环境不能创建符号链接")
        result = route.scan(self.root)
        self.assertIn("linked", result["scanned"]["links_skipped"])
        self.assertEqual(result["route"], "B-source")


if __name__ == "__main__":
    unittest.main()

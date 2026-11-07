from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from portfactory import cli
from portfactory.portkit import onboard, route


def pe_bytes() -> bytes:
    data = bytearray(512)
    data[0:2] = b"MZ"
    data[0x3C:0x40] = (0x80).to_bytes(4, "little")
    data[0x80:0x84] = b"PE\0\0"
    data[0x84:0x86] = (0x8664).to_bytes(2, "little")
    return bytes(data)


def nro_bytes() -> bytes:
    data = bytearray(64)
    data[0:4] = (0x14000000).to_bytes(4, "little")
    data[0x10:0x14] = b"NRO0"
    return bytes(data)


class OnboardCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "game-src"
        self.out = self.root / "specs"
        self.snapshot: list[tuple[str, int, int]] = []

    def make(self, base: Path, name: str, data: bytes | str) -> Path:
        path = base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            path.write_bytes(data)
        else:
            path.write_text(data, encoding="utf-8")
        return path

    def source_tree(self) -> Path:
        self.make(self.source, "CMakeLists.txt", "project(game C)\n")
        self.make(self.source, "src/main.c", "int main(void){return 0;}\n")
        self.make(self.source, "LICENSE", "GNU GENERAL PUBLIC LICENSE Version 2\n")
        return self.source

    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def new(self, path: Path, spec_id: str = "mygame", *extra):
        return self.cli("port", "new", str(path), "--id", spec_id,
                        "--out-dir", str(self.out), *extra)

    def draft(self, spec_id: str = "mygame") -> dict:
        return json.loads((self.out / f"{spec_id}.draft.json").read_text(encoding="utf-8"))

    def record(self, base: Path) -> list[tuple[str, int, int]]:
        records = []
        for dirpath, dirs, names in os.walk(base):
            dirs.sort()
            for name in sorted(names):
                path = Path(dirpath) / name
                stat = path.stat()
                records.append((path.relative_to(base).as_posix(), stat.st_size,
                                stat.st_mtime_ns))
        return records

    # ------------------------------------------------------------ 生成草稿
    def test_source_tree_creates_draft_bound_to_decision(self):
        tree = self.source_tree()
        code, out = self.new(tree)
        self.assertEqual(code, 0, out)
        draft_spec = self.draft()
        self.assertEqual(draft_spec["id"], "mygame")
        self.assertEqual(draft_spec["family"], "source-port")
        self.assertEqual(draft_spec["_draft"]["route"]["id"], "B-source")
        decision_path = Path(draft_spec["_draft"]["route"]["decision"])
        self.assertTrue(decision_path.is_file())
        digest = hashlib.sha256(decision_path.read_bytes()).hexdigest()
        self.assertEqual(digest, draft_spec["_draft"]["route"]["decision_sha256"])
        self.assertIn("port plan", out)

    def test_list_skips_draft_and_decision_sidecars(self):
        self.new(self.source_tree())
        code, out = self.cli("port", "list", "--dir", str(self.out))
        self.assertEqual(code, 0, out)
        self.assertNotIn("无效", out)
        self.assertIn("跳过 2 个待填草稿与判定记录", out)

    def test_recomp_tree_sets_recomp_family(self):
        self.make(self.source, "symbols.txt", "main = 0x80003100;\n")
        self.make(self.source, "asm/boot.s", ".set noreorder\n")
        self.make(self.source, "Makefile", "all:\n\t@true\n")
        code, out = self.new(self.source)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.draft()["family"], "recomp")
        self.assertEqual(self.draft()["_draft"]["route"]["id"], "B-recomp")

    def test_out_dir_is_respected(self):
        tree = self.source_tree()
        other = self.root / "custom"
        code, out = self.cli("port", "new", str(tree), "--id", "elsewhere",
                             "--out-dir", str(other))
        self.assertEqual(code, 0, out)
        self.assertTrue((other / "elsewhere.draft.json").is_file())
        self.assertTrue((other / "elsewhere.route.json").is_file())

    # ------------------------------------------------------------ 拒收
    def assert_refused(self, path: Path, phrase: str, spec_id: str = "mygame"):
        code, out = self.new(path, spec_id)
        self.assertEqual(code, 2, out)
        self.assertIn("未生成 spec", out)
        self.assertIn(phrase, out)
        self.assertNotIn("草稿只表示", out)
        self.assertFalse((self.out / f"{spec_id}.draft.json").exists())
        self.assertFalse((self.out / f"{spec_id}.route.json").exists())

    def test_data_only_is_refused(self):
        data = self.root / "data"
        self.make(data, "GAME.GRP", b"grp")
        self.make(data, "GAME.RTS", b"rts")
        self.assert_refused(data, "不是可重建的源码工程")

    def test_binary_is_refused_with_ghidra_blocker(self):
        path = self.make(self.root, "game.exe", pe_bytes())
        self.assert_refused(path, "Ghidra")

    def test_nro_artifact_is_refused(self):
        path = self.make(self.root, "game.nro", nro_bytes())
        self.assert_refused(path, "不能算移植")

    def test_archive_is_refused(self):
        path = self.root / "src.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("CMakeLists.txt", "project(game C)\n")
        self.assert_refused(path, "压缩包未被解压")

    def test_single_source_file_is_refused(self):
        path = self.make(self.root, "lonely.c", "int main(void){return 0;}\n")
        self.assert_refused(path, "需要源码目录")

    # ------------------------------------------------------------ 参数与覆盖
    def test_existing_draft_is_not_overwritten_silently(self):
        tree = self.source_tree()
        self.assertEqual(self.new(tree)[0], 0)
        code, out = self.new(tree)
        self.assertEqual(code, 2, out)
        self.assertIn("已存在", out)
        code, out = self.new(tree, "mygame", "--force")
        self.assertEqual(code, 0, out)

    def test_bad_spec_id_is_rejected(self):
        tree = self.source_tree()
        code, out = self.new(tree, "Bad Id")
        self.assertEqual(code, 2, out)
        self.assertIn("id 只能是小写字母", out)
        self.assertFalse(self.out.exists())

    def test_missing_input_is_rejected(self):
        code, out = self.new(self.root / "nope")
        self.assertEqual(code, 2, out)
        self.assertIn("输入不存在", out)

    def test_scanned_tree_is_untouched(self):
        tree = self.source_tree()
        before = self.record(tree)
        self.assertEqual(self.new(tree)[0], 0)
        self.assertEqual(self.record(tree), before)

    def test_direct_call_reports_refusal_without_files(self):
        data = self.root / "only-data"
        self.make(data, "GAME.WAD", b"wad")
        result = onboard.create(data, "refused", out_dir=self.root / "unused")
        self.assertTrue(result["refused"])
        self.assertEqual(result["created"], {})
        self.assertFalse((self.root / "unused").exists())

    def test_render_explains_route(self):
        tree = self.source_tree()
        result = onboard.create(tree, "rendered", out_dir=self.out)
        text = onboard.render(result)
        self.assertIn("接单：B-source", text)
        self.assertIn("不代表能编译、能玩或能发布", text)
        self.assertEqual(result["route"], route.scan(tree)["route"])


if __name__ == "__main__":
    unittest.main()

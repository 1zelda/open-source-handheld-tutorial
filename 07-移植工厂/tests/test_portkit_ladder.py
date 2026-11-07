from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from portfactory import cli
from portfactory.portkit import cache, gates


ARTIFACT = '''import os, sys


def say(name):
    print("[PF] " + name, flush=True)


mode = os.environ.get("MODE", "ok")
if mode == "win":
    say("boot")
    sys.exit(0)
say("boot")
say("menu")
sys.exit(0)
'''


class LadderCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "artifact.py").write_text(ARTIFACT, encoding="utf-8")
        (self.source / "build.py").write_text(
            "from pathlib import Path\nimport sys\n"
            "Path(sys.argv[1]).write_text(Path('artifact.py').read_text(encoding='utf-8'),"
            " encoding='utf-8')\n", encoding="utf-8")
        self.spec_path = self.root / "spec.json"
        self.work = self.root / "work"
        self.plans = self.root / "plans"
        self.plans.mkdir()
        self.raw = {
            "schema": 1, "id": "ladder-test", "title": "Ladder test",
            "family": "open-engine", "source": {"local": str(self.source)},
            "data": {"policy": "none"},
            "targets": {"host": {"profile": "host", "build": {
                "system": "custom", "artifact": "artifact.py",
                "commands": [f'"{Path(sys.executable).as_posix()}" "${{src}}/build.py" '
                             f'"${{build}}/artifact.py"'],
            },
                "package": {"platform": "nro-zip", "zip_name": "fixture.zip",
                            "nro_name": "artifact.py"},
                "gates": ["deterministic_zip"]}}}
        self.write_spec()
        mock = patch.object(cache, "tool_identity",
                            return_value={"complete": True, "tools": {"fixture": "v1"}})
        mock.start()
        self.addCleanup(mock.stop)

    def write_spec(self):
        self.spec_path.write_text(json.dumps(self.raw), encoding="utf-8")

    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def build(self):
        return self.cli("port", "build", str(self.spec_path), "--target", "host",
                        "--work", str(self.work))

    def plan(self, name: str = "pass", mode: str = "ok", checkpoints=None) -> Path:
        data = {"schema": 1, "id": "plan-" + name, "timeout": 30,
                "checkpoints": checkpoints or ["boot", "menu"], "checkpoint_prefix": "[PF] ",
                "args": ["${artifact}"], "env": {"MODE": mode}, "program": sys.executable,
                "kind": "host", "copy": [], "output_limit": 65536,
                "require_exit": 0, "ordered": True}
        path = self.plans / f"{name}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def run_plan(self, plan: Path):
        return self.cli("port", "run", str(self.spec_path), "--target", "host",
                        "--work", str(self.work), "--plan", str(plan))

    def status(self, *extra):
        return self.cli("port", "status", str(self.spec_path), "--target", "host",
                        "--work", str(self.work), *extra)

    # ------------------------------------------------------------ 等级
    def test_build_alone_reaches_r3(self):
        code, out = self.build()
        self.assertEqual(code, 0, out)
        code, out = self.status()
        self.assertEqual(code, 0, out)
        self.assertIn("当前等级：**R3 静态闸门**", out)
        self.assertIn("还没有主机运行证据", out)
        self.assertIn("P3-B 未实现", out)
        self.assertIn("发布资格：禁止", out)

    def test_runtime_pass_reaches_r4_but_not_device_or_release(self):
        self.assertEqual(self.build()[0], 0)
        code, out = self.run_plan(self.plan())
        self.assertEqual(code, 0, out)
        code, out = self.status()
        self.assertEqual(code, 0, out)
        self.assertIn("当前等级：**R4 主机运行**", out)
        for row in out.splitlines():
            if row.startswith("| R5 "):
                self.assertIn("blocked", row)
            if row.startswith("| R6 "):
                self.assertIn("blocked", row)
        self.assertNotIn("当前等级：**R5", out)

    def test_failed_runtime_keeps_r3_with_reason(self):
        self.assertEqual(self.build()[0], 0)
        code, _ = self.run_plan(self.plan("short", mode="win",
                                          checkpoints=["boot", "menu"]))
        self.assertEqual(code, 2)
        code, out = self.status()
        self.assertEqual(code, 0, out)
        self.assertIn("当前等级：**R3", out)
        self.assertIn("运行证据未通过", out)

    def test_artifact_change_blocks_r2(self):
        self.assertEqual(self.build()[0], 0)
        artifact = Path(json.loads((self.work / "ladder-test" / "state.json")
                                   .read_text(encoding="utf-8"))
                        ["targets"]["host"]["stages"]["build"]["detail"]["artifact"])
        artifact.write_text(artifact.read_text(encoding="utf-8") + "# x\n", encoding="utf-8")
        code, out = self.status()
        self.assertEqual(code, 0, out)
        self.assertIn("当前等级：**R1 源码冻结**", out)
        self.assertIn("产物在构建之后被改动或删除", out)

    def test_spec_change_blocks_admission(self):
        self.assertEqual(self.build()[0], 0)
        self.raw["title"] = "Ladder test v2"
        self.write_spec()
        code, out = self.status()
        self.assertEqual(code, 0, out)
        self.assertIn("未达到 R0", out)
        self.assertIn("spec 在构建之后被改动", out)

    def test_gate_failure_stops_at_r2(self):
        self.raw["targets"]["host"]["gates"] = ["ladder_fail"]
        self.write_spec()
        gates.GATES["ladder_fail"] = lambda ctx: gates.Result("fail", {"reason": "fixture"})
        self.addCleanup(gates.GATES.pop, "ladder_fail", None)
        code, _ = self.build()
        self.assertEqual(code, 2)
        code, out = self.status()
        self.assertEqual(code, 0, out)
        self.assertIn("当前等级：**R2 可构建**", out)
        self.assertIn("package 或 verify 未通过", out)

    # ------------------------------------------------------------ 查询行为
    def test_status_without_build_creates_nothing(self):
        code, out = self.status()
        self.assertEqual(code, 0, out)
        self.assertIn("未达到 R0", out)
        self.assertIn("还没有构建记录", out)
        self.assertFalse((self.work / "ladder-test").exists())

    def test_require_flag_gates_exit_code(self):
        self.assertEqual(self.build()[0], 0)
        code, out = self.status("--require", "R4")
        self.assertEqual(code, 2, out)
        self.assertIn("未达到要求等级 R4", out)
        self.assertEqual(self.run_plan(self.plan())[0], 0)
        code, out = self.status("--require", "R4")
        self.assertEqual(code, 0, out)
        code, out = self.status("--require", "R5")
        self.assertEqual(code, 2, out)

    def test_report_file_is_written(self):
        self.assertEqual(self.build()[0], 0)
        target = self.root / "reports" / "ladder.md"
        code, out = self.status("--out", str(target))
        self.assertEqual(code, 0, out)
        self.assertIn("当前等级：**R3", target.read_text(encoding="utf-8"))

    def test_unknown_require_level_is_rejected(self):
        self.assertEqual(self.build()[0], 0)
        code, out = self.status("--require", "R9")
        self.assertEqual(code, 2, out)
        self.assertIn("未知等级", out)


if __name__ == "__main__":
    unittest.main()

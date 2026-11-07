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
from portfactory.portkit import cache


ARTIFACT = '''import os, sys, time


def say(name):
    print("[PF] " + name, flush=True)


mode = os.environ.get("MODE", "ok")
if mode == "hang":
    say("boot")
    time.sleep(60)
    say("menu")
    sys.exit(0)
if mode == "reverse":
    say("menu")
    say("boot")
    sys.exit(0)
if mode == "exit3":
    say("boot")
    say("menu")
    sys.exit(3)
if mode == "asset":
    with open("asset.txt", encoding="utf-8") as handle:
        assert handle.read() == "asset"
    say("boot")
    say("menu")
    sys.exit(0)
if mode == "chatty":
    sys.stdout.write("x" * 5000 + "\\n")
say("boot")
say("menu")
sys.exit(0)
'''


class RuntimeCase(unittest.TestCase):
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
        (self.root / "asset.txt").write_text("asset", encoding="utf-8")
        self.spec_path = self.root / "spec.json"
        self.work = self.root / "work"
        self.plans = self.root / "plans"
        self.plans.mkdir()
        self.raw = {
            "schema": 1, "id": "runtime-test", "title": "Runtime session test",
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
        self.spec_path.write_text(json.dumps(self.raw), encoding="utf-8")
        mock = patch.object(cache, "tool_identity",
                            return_value={"complete": True, "tools": {"fixture": "v1"}})
        mock.start()
        self.addCleanup(mock.stop)

    # ------------------------------------------------------------ 工具
    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def build(self):
        code, out = self.cli("port", "build", str(self.spec_path), "--target", "host",
                             "--work", str(self.work))
        self.assertEqual(code, 0, out)
        return self.state()

    def state(self) -> dict:
        return json.loads((self.work / "runtime-test" / "state.json").read_text(encoding="utf-8"))

    def artifact(self) -> Path:
        return Path(self.state()["targets"]["host"]["stages"]["build"]["detail"]["artifact"])

    def plan(self, name: str = "plan", **overrides) -> Path:
        data = {"schema": 1, "id": "plan-" + name, "timeout": 60,
                "checkpoints": ["boot", "menu"], "checkpoint_prefix": "[PF] ",
                "args": ["${artifact}"], "env": {}, "program": sys.executable,
                "kind": "host", "copy": [], "output_limit": 65536,
                "require_exit": 0, "ordered": True}
        data.update(overrides)
        path = self.plans / f"{name}.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def run_plan(self, plan: Path, work: Path | None = None, dry: bool = False):
        argv = ["port", "run", str(self.spec_path), "--target", "host",
                "--work", str(work or self.work), "--plan", str(plan)]
        if dry:
            argv.append("--dry-run")
        return self.cli(*argv)

    def record(self) -> dict:
        return json.loads(Path(self.state()["targets"]["host"]["runtime"]["record"])
                          .read_text(encoding="utf-8"))

    # ------------------------------------------------------------ 通过路径
    def test_pass_records_checkpoints_and_qualification(self):
        self.build()
        code, out = self.run_plan(self.plan())
        self.assertEqual(code, 0, out)
        record = self.record()
        self.assertEqual(record["status"], "pass", record)
        self.assertEqual([c["name"] for c in record["checkpoints"]], ["boot", "menu"])
        self.assertTrue(record["artifact_unchanged"])
        self.assertEqual(record["whole_game_behavior"], "not_run")
        self.assertEqual(record["device_test"], "not_run")
        self.assertFalse(record["release_allowed"])
        self.assertEqual(record["stdout"]["size"] > 0, True)
        self.assertEqual(self.state()["targets"]["host"]["runtime"]["status"], "pass")

    def test_missing_checkpoint_fails(self):
        self.build()
        code, out = self.run_plan(self.plan(checkpoints=["boot", "menu", "win"]))
        self.assertEqual(code, 2, out)
        self.assertIn("缺少检查点", out)
        record = self.record()
        self.assertEqual(record["status"], "fail")
        self.assertEqual(record["missing"], ["win"])

    def test_out_of_order_rejected_when_ordered(self):
        self.build()
        code, out = self.run_plan(self.plan(env={"MODE": "reverse"}))
        self.assertEqual(code, 2, out)
        self.assertIn("顺序", out)
        self.assertEqual(self.record()["status"], "fail")

    def test_order_ignored_when_ordered_false(self):
        self.build()
        code, out = self.run_plan(self.plan(env={"MODE": "reverse"}, ordered=False))
        self.assertEqual(code, 0, out)
        self.assertEqual([c["name"] for c in self.record()["checkpoints"]], ["menu", "boot"])

    def test_wrong_exit_code_fails(self):
        self.build()
        code, out = self.run_plan(self.plan(env={"MODE": "exit3"}))
        self.assertEqual(code, 2, out)
        self.assertIn("退出码", out)
        self.assertEqual(self.record()["exit"], 3)

    def test_timeout_kills_tree_and_fails(self):
        self.build()
        code, out = self.run_plan(self.plan(timeout=1, env={"MODE": "hang"}))
        self.assertEqual(code, 2, out)
        record = self.record()
        self.assertTrue(record["timed_out"])
        self.assertEqual(record["status"], "fail")
        self.assertLess(record["seconds"], 30)

    def test_copy_from_spec_is_visible_in_run_dir(self):
        self.build()
        plan = self.plan(copy=[{"src": "${spec}/asset.txt", "dst": "asset.txt"}],
                         env={"MODE": "asset"})
        code, out = self.run_plan(plan)
        self.assertEqual(code, 0, out)
        run_dir = Path(self.record()["cwd"])
        self.assertEqual((run_dir / "asset.txt").read_text(encoding="utf-8"), "asset")

    def test_output_truncation_keeps_scanning_checkpoints(self):
        self.build()
        code, out = self.run_plan(self.plan(output_limit=1024, env={"MODE": "chatty"}))
        self.assertEqual(code, 0, out)
        record = self.record()
        self.assertIn("stdout", record["truncated"])
        self.assertEqual(record["stdout"]["size"], 1024)
        self.assertEqual([c["name"] for c in record["checkpoints"]], ["boot", "menu"])

    # ------------------------------------------------------------ 前置拒绝
    def test_artifact_change_after_build_is_refused(self):
        self.build()
        artifact = self.artifact()
        artifact.write_text(artifact.read_text(encoding="utf-8") + "# changed\n",
                            encoding="utf-8")
        code, out = self.run_plan(self.plan())
        self.assertEqual(code, 2, out)
        self.assertIn("发生了变化", out)

    def test_run_without_build_is_refused(self):
        code, out = self.run_plan(self.plan(), work=self.root / "empty")
        self.assertEqual(code, 2, out)
        self.assertIn("先执行 port build", out)

    def test_rebuild_clears_runtime_evidence_only_when_artifact_changes(self):
        self.build()
        code, out = self.run_plan(self.plan())
        self.assertEqual(code, 0, out)
        self.assertIn("runtime", self.state()["targets"]["host"])

        self.build()
        self.assertIn("runtime", self.state()["targets"]["host"])

        (self.source / "artifact.py").write_text(ARTIFACT + "\n# v2\n", encoding="utf-8")
        self.build()
        self.assertNotIn("runtime", self.state()["targets"]["host"])

    def test_device_plan_is_refused(self):
        self.build()
        code, out = self.run_plan(self.plan(kind="device"))
        self.assertEqual(code, 2, out)
        self.assertIn("设备执行器", out)

    def test_copy_source_outside_spec_and_work_is_refused(self):
        self.build()
        outside_dir = tempfile.TemporaryDirectory()
        self.addCleanup(outside_dir.cleanup)
        outside = Path(outside_dir.name) / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        code, out = self.run_plan(self.plan(copy=[{"src": str(outside), "dst": "x.txt"}]))
        self.assertEqual(code, 2, out)
        self.assertIn("不在 spec/工作目录内", out)

    def test_dry_run_executes_nothing(self):
        self.build()
        before = json.loads((self.work / "runtime-test" / "state.json").read_text(encoding="utf-8"))
        code, out = self.run_plan(self.plan(), dry=True)
        self.assertEqual(code, 0, out)
        self.assertIn("命令", out)
        after = self.state()
        self.assertNotIn("runtime", after["targets"]["host"])
        self.assertEqual(before["targets"]["host"], after["targets"]["host"])
        self.assertFalse((self.work / "runtime-test" / "host" / "runtime").exists())

    # ------------------------------------------------------------ 计划校验
    def test_plan_validation_rejects_bad_schemas(self):
        cases = [
            ({"checkpoints": []}, "至少需要一个检查点"),
            ({"timeout": 0}, "timeout"),
            ({"checkpoins": ["boot"]}, "未知字段"),
            ({"copy": [{"src": "${run}/x", "dst": "x"}]}, "不能引用 ${run}"),
            ({"copy": [{"src": "${spec}/asset.txt", "dst": "../evil.txt"}]}, "copy.dst"),
            ({"copy": [{"src": "${spec}/asset.txt", "dst": "a.txt"},
                       {"src": "${spec}/asset.txt", "dst": "a.txt"}]}, "重复"),
        ]
        for index, (overrides, expected) in enumerate(cases):
            with self.subTest(case=index):
                plan = self.plan(name=f"bad{index}", **overrides)
                code, out = self.run_plan(plan, work=self.root / "empty")
                self.assertEqual(code, 2, out)
                self.assertIn(expected, out)


if __name__ == "__main__":
    unittest.main()

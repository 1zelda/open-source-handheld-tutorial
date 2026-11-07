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
from portfactory.portkit import cache, gates, repair, runner
from portfactory.portkit.spec import load_spec


PATCH_FIX = """diff --git a/input.txt b/input.txt
--- a/input.txt
+++ b/input.txt
@@ -1 +1 @@
-broken
+good
"""

PATCH_GATE_BAIT = """diff --git a/input.txt b/input.txt
--- a/input.txt
+++ b/input.txt
@@ -1 +1 @@
-broken
+bad
"""

PATCH_NO_PROGRESS = """diff --git a/input.txt b/input.txt
--- a/input.txt
+++ b/input.txt
@@ -1 +1 @@
-broken
+broken2
"""


class RepairCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "input.txt").write_text("broken\n", encoding="utf-8")
        (self.source / "build.py").write_text(
            "from pathlib import Path\nimport sys\n"
            "text = Path('input.txt').read_text()\n"
            "if 'broken' in text:\n"
            "    print('error: input is broken', file=sys.stderr)\n"
            "    sys.exit(1)\n"
            "Path(sys.argv[1]).write_text(text)\n", encoding="utf-8")
        self.spec_path = self.root / "spec.json"
        self.work = self.root / "work"
        self.raw = {
            "schema": 1, "id": "repair-test", "title": "Repair loop test",
            "family": "open-engine", "source": {"local": str(self.source)},
            "data": {"policy": "none"},
            "targets": {"host": {"profile": "host", "build": {
                "system": "custom", "artifact": "result.bin",
                "commands": [f'"{Path(sys.executable).as_posix()}" "${{src}}/build.py" "${{build}}/result.bin"'],
                },
                "package": {"platform": "nro-zip", "zip_name": "chosen.zip", "nro_name": "result.bin"},
                "gates": ["deterministic_zip", "test_content"]}}}
        self.spec_path.write_text(json.dumps(self.raw), encoding="utf-8")
        mock = patch.object(cache, "tool_identity", return_value={"complete": True, "tools": {"fixture": "v1"}})
        mock.start()
        self.addCleanup(mock.stop)
        gates.GATES["test_content"] = lambda ctx: gates.Result(
            "pass" if Path(ctx["artifact"]).read_text(encoding="utf-8").strip() == "good" else "fail",
            {"artifact_text": Path(ctx["artifact"]).read_text(encoding="utf-8").strip()})
        self.addCleanup(gates.GATES.pop, "test_content", None)

    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def request_path(self, attempt: int = 1) -> Path:
        return self.work / "repair-test" / "repair" / "requests" / f"attempt-{attempt:02d}.json"

    def make_request(self, budget: int = 3):
        code, out = self.cli("port", "repair-request", str(self.spec_path),
                             "--target", "host", "--work", str(self.work),
                             "--budget", str(budget))
        self.assertEqual(code, 2, out)
        return json.loads(self.request_path().read_text(encoding="utf-8"))

    def submit(self, patch_text: str, request: dict | None = None, name: str = "p.diff"):
        path = self.root / name
        path.write_text(patch_text, encoding="utf-8")
        return self.cli("port", "repair-submit", str(self.request_path(request["attempt"] if request else 1)),
                        "--patch", str(path), "--producer", "fixture-model")

    def history(self) -> dict:
        return repair.load_history(self.work / "repair-test")

    # ------------------------------------------------------------ 正常闭环
    def test_failure_to_request_to_verified_patch(self):
        request = self.make_request()
        self.assertEqual(request["failing_stage"], "build")
        self.assertIn("git apply", request["prompt"])
        self.assertIn("不许碰 .git", request["prompt"])
        self.assertEqual(request["files"][0]["path"], "build.py")
        self.assertIn("included", request)

        code, out = self.submit(PATCH_FIX, request)
        self.assertEqual(code, 0, out)
        accepted = list((self.work / "repair-test" / "repair" / "accepted").glob("*.diff"))
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0].read_text(encoding="utf-8"), PATCH_FIX)
        self.assertEqual((self.source / "input.txt").read_text(encoding="utf-8"), "broken\n")

        entry = self.history()["attempts"][-1]
        self.assertEqual(entry["outcome"], "accepted")
        self.assertEqual(entry["patch"]["files"], ["input.txt"])
        self.assertEqual(entry["gates"], {"deterministic_zip": "pass", "test_content": "pass"})
        self.assertEqual(entry["device_test"], "not_run")
        self.assertFalse(entry["release_allowed"])

        code, out = self.cli("port", "build", str(self.spec_path), "--target", "host",
                             "--work", str(self.work), "--repair-patch", str(accepted[0]))
        self.assertEqual(code, 0, out)

    # ------------------------------------------------------------ 拒绝路径
    def test_duplicate_patch_is_refused(self):
        request = self.make_request()
        code, _ = self.submit(PATCH_NO_PROGRESS, request, "first.diff")
        self.assertEqual(code, 2)
        code, out = self.submit(PATCH_NO_PROGRESS, request, "again.diff")
        self.assertEqual(code, 2)
        self.assertIn("完全相同", out)

    def test_budget_exhaustion_stops_and_keeps_history(self):
        self.make_request(budget=1)
        code, out = self.submit(PATCH_NO_PROGRESS)
        self.assertEqual(code, 2)
        self.assertIn("预算已用完", out)
        self.assertEqual(len(self.history()["attempts"]), 1)
        self.assertEqual(list(self.work.rglob("attempt-02.json")), [])

    def test_patch_that_breaks_apply_is_rejected_at_fetch(self):
        broken = """diff --git a/input.txt b/input.txt
--- a/input.txt
+++ b/input.txt
@@ -1 +1 @@
-not-in-the-file
+good
"""
        request = self.make_request()
        code, out = self.submit(broken, request)
        self.assertEqual(code, 2)
        entry = self.history()["attempts"][-1]
        self.assertEqual(entry["outcome"], "rejected")
        self.assertEqual(entry["stage_status"]["fetch"], "fail")
        self.assertIn("补丁打不上", entry["reason"])

    def test_greens_build_but_fails_gate_is_not_accepted(self):
        request = self.make_request()
        code, out = self.submit(PATCH_GATE_BAIT, request)
        self.assertEqual(code, 2)
        entry = self.history()["attempts"][-1]
        self.assertEqual(entry["outcome"], "rejected")
        self.assertEqual(entry["gates"]["test_content"], "fail")
        self.assertIn("verify", entry["reason"])
        self.assertTrue(self.request_path(2).is_file())

    # ------------------------------------------------------------ 补丁边界
    def test_path_escape_and_spec_edit_are_refused(self):
        with self.assertRaises(repair.RepairError):
            repair.parse_patch("diff --git a/../evil.c b/../evil.c\n"
                               "--- a/../evil.c\n+++ b/../evil.c\n@@ -1 +1 @@\n-a\n+b\n",
                               project_root=self.source)
        with self.assertRaises(repair.RepairError):
            repair.parse_patch(PATCH_FIX, project_root=self.source,
                               spec_path=self.source / "input.txt")
        with self.assertRaises(repair.RepairError):
            repair.parse_patch("diff --git a/.git/config b/.git/config\n"
                               "--- a/.git/config\n+++ b/.git/config\n@@ -1 +1 @@\n-a\n+b\n",
                               project_root=self.source)

    def test_binary_mode_change_and_deletion_are_refused(self):
        for text in ("GIT binary patch\nliteral 5\n",
                     "diff --git a/x.sh b/x.sh\nold mode 100644\nnew mode 100755\n"
                     "--- a/x.sh\n+++ b/x.sh\n@@ -1 +1 @@\n-a\n+b\n",
                     "diff --git a/x.c b/x.c\ndeleted file mode 100644\n"
                     "--- a/x.c\n+++ /dev/null\n@@ -1 +0,0 @@\n-a\n"):
            with self.assertRaises(repair.RepairError):
                repair.parse_patch(text)

    def test_size_limits_are_enforced(self):
        files = []
        for i in range(repair.MAX_FILES + 1):
            files.append(f"diff --git a/f{i}.c b/f{i}.c\n--- a/f{i}.c\n+++ b/f{i}.c\n"
                         f"@@ -1 +1 @@\n-a\n+b\n")
        with self.assertRaises(repair.RepairError):
            repair.parse_patch("".join(files))
        long_patch = ("diff --git a/x.c b/x.c\n--- a/x.c\n+++ b/x.c\n@@ -1,0 +1,%d @@\n"
                      % (repair.MAX_CHANGED_LINES + 1)
                      + "".join(f"+line {i}\n" for i in range(repair.MAX_CHANGED_LINES + 1)))
        with self.assertRaises(repair.RepairError):
            repair.parse_patch(long_patch)
        with self.assertRaises(repair.RepairError):
            repair.parse_patch("diff --git a/x.c b/x.c\n--- a/x.c\n+++ b/x.c\n@@ -1 +1 @@\n-a\n+b\n"
                               + "x" * repair.MAX_PATCH_BYTES)

    def test_compiler_diagnostics_point_back_to_sources(self):
        absolute = f"{self.source.as_posix()}/input.txt:3:1: error: nope"
        self.assertEqual(repair._hint_files(absolute, self.source), ["input.txt"])
        self.assertEqual(repair._hint_files("input.txt:3:1: error: nope", self.source), ["input.txt"])
        self.assertEqual(repair._hint_files("/elsewhere/input.txt:3:1: error", self.source), [])

    def test_request_refuses_when_spec_changed_after_request(self):
        request = self.make_request()
        self.raw["title"] = "changed after the request"
        self.spec_path.write_text(json.dumps(self.raw), encoding="utf-8")
        code, out = self.submit(PATCH_FIX, request)
        self.assertEqual(code, 2)
        self.assertIn("spec 在生成请求之后变了", out)

    def test_repair_patch_is_bound_into_fetch_identity(self):
        first = runner.PortRunner(load_spec(self.spec_path), self.work).run("host")
        self.assertEqual(first["status"], "fail")
        patch_path = self.root / "fix.diff"
        patch_path.write_text(PATCH_FIX, encoding="utf-8")
        second = runner.PortRunner(load_spec(self.spec_path), self.work,
                                   repair_patches=[patch_path]).run("host")
        self.assertEqual(second["status"], "pass", second)
        self.assertEqual(second["repair_patches"][0]["sha256"], cache.stamp(patch_path)["sha256"])
        self.assertFalse(second["release_allowed"])
        self.assertEqual(second["device_test"], "not_run")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from portfactory import cli, handoff
from portfactory.portkit import cache, gates, runner
from portfactory.portkit.spec import load_spec


class ResumeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "input.txt").write_text("one", encoding="utf-8")
        (self.source / "build.py").write_text(
            "from pathlib import Path\nimport sys\n"
            "Path(sys.argv[1]).write_bytes(Path('input.txt').read_bytes())\n", encoding="utf-8")
        self.sdk = self.root / "sdk.txt"
        self.sdk.write_text("sdk1", encoding="utf-8")
        self.spec_path = self.root / "spec.json"
        self.work = self.root / "work"
        self.raw = {
            "schema": 1, "id": "cache-test", "title": "Synthetic scheduling test",
            "family": "open-engine", "source": {"local": str(self.source)},
            "data": {"policy": "none"},
            "targets": {"host": {"profile": "host", "build": {
                "system": "custom", "artifact": "result.bin",
                "commands": [f'"{Path(sys.executable).as_posix()}" "${{src}}/build.py" "${{build}}/result.bin"'],
                "cache_inputs": [str(self.sdk), sys.executable]},
                "package": {"platform": "nro-zip", "zip_name": "chosen.zip", "nro_name": "result.bin"},
                "gates": ["deterministic_zip"]}}}
        self.save()
        mock = patch.object(cache, "tool_identity", return_value={"complete": True, "tools": {"fixture": "v1"}})
        self.identity = mock.start()
        self.addCleanup(mock.stop)

    def save(self):
        self.spec_path.write_text(json.dumps(self.raw), encoding="utf-8")

    def run_factory(self, **kwargs):
        result = runner.PortRunner(load_spec(self.spec_path), self.work, **kwargs).run("host")
        self.assertEqual(result["status"], "pass", result)
        return {stage["id"]: stage for stage in result["stages"]}

    def test_repeat_reuses_bound_outputs_and_keeps_gate_details(self):
        first = self.run_factory()
        second = self.run_factory()
        for stage in ("fetch", "build", "package"):
            self.assertTrue(second[stage]["detail"]["cached"], second)
        self.assertEqual(first["package"]["detail"]["path"], second["package"]["detail"]["path"])
        self.assertEqual(second["verify"]["detail"]["gates"]["deterministic_zip"]["status"], "pass")

    def test_local_source_change_refreshes_snapshot_without_deleting_old(self):
        first = self.run_factory()
        old = Path(first["build"]["detail"]["artifact"])
        (self.source / "input.txt").write_text("two", encoding="utf-8")
        second = self.run_factory()
        self.assertNotIn("cached", second["fetch"]["detail"])
        self.assertEqual(old.read_bytes(), b"one")
        self.assertEqual(Path(second["build"]["detail"]["artifact"]).read_bytes(), b"two")

    def test_tool_dependency_change_rebuilds_without_refetch(self):
        self.run_factory()
        previous = self.sdk.stat()
        self.sdk.write_text("sdk2", encoding="utf-8")
        os.utime(self.sdk, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        second = self.run_factory()
        self.assertTrue(second["fetch"]["detail"]["cached"])
        self.assertNotIn("cached", second["build"]["detail"])

    def test_tool_identity_change_rebuilds(self):
        self.run_factory()
        self.identity.return_value = {"complete": True, "tools": {"fixture": "v2"}}
        self.assertNotIn("cached", self.run_factory()["build"]["detail"])

    def test_package_only_change_does_not_rebuild(self):
        self.run_factory()
        self.raw["targets"]["host"]["package"]["readme_text"] = "updated"
        self.save()
        second = self.run_factory()
        self.assertTrue(second["build"]["detail"]["cached"])
        self.assertNotIn("cached", second["package"]["detail"])

    def test_artifact_tamper_or_deletion_rebuilds(self):
        first = self.run_factory()
        artifact = Path(first["build"]["detail"]["artifact"])
        artifact.write_bytes(b"tampered")
        second = self.run_factory()
        self.assertNotIn("cached", second["build"]["detail"])
        self.assertEqual(artifact.read_bytes(), b"tampered")
        Path(second["build"]["detail"]["artifact"]).unlink()
        self.assertNotIn("cached", self.run_factory()["build"]["detail"])

    def test_package_tamper_repackages(self):
        first = self.run_factory()
        package = Path(first["package"]["detail"]["path"])
        package.write_bytes(b"wrong zip")
        second = self.run_factory()
        self.assertTrue(second["build"]["detail"]["cached"])
        self.assertNotIn("cached", second["package"]["detail"])
        self.assertEqual(package.read_bytes(), b"wrong zip")

    def test_verify_uses_exact_package_even_with_decoy(self):
        original = runner._Package.run
        expected = []
        observed = []

        def package(stage):
            status, detail = original(stage)
            (stage.paths["dist"] / "000-old.zip").write_bytes(b"decoy")
            expected.append(detail["path"])
            return status, detail

        def gate(ctx):
            observed.append(ctx["package"])
            return gates.Result("pass", {})

        self.raw["targets"]["host"]["gates"] = ["exact-package"]
        self.save()
        with patch.object(runner._Package, "run", package), patch.dict(gates.GATES, {"exact-package": gate}):
            self.run_factory()
        self.assertEqual(observed, expected)

    def test_verify_rejects_tamper_between_package_and_gate(self):
        original = runner._Verify.run

        def verify(stage):
            Path(stage.runner.current["package"].detail["path"]).write_bytes(b"tampered")
            return original(stage)

        with patch.object(runner._Verify, "run", verify):
            result = runner.PortRunner(load_spec(self.spec_path), self.work).run("host")
        self.assertEqual(result["status"], "fail")

    def test_no_dependency_declaration_disables_build_reuse(self):
        del self.raw["targets"]["host"]["build"]["cache_inputs"]
        self.save()
        self.run_factory()
        self.assertIn("cache_disabled", self.run_factory()["build"]["detail"])

    def test_old_status_only_record_does_not_skip_work(self):
        location = self.work / "cache-test"
        location.mkdir(parents=True)
        old = location / "host" / "src"
        old.mkdir(parents=True)
        (old / "keep.txt").write_text("keep", encoding="utf-8")
        (location / "state.json").write_text(json.dumps({"targets": {"host": {"stages": {
            stage: {"status": "pass"} for stage in ("prepare", "fetch", "build", "package", "verify")}}}}), encoding="utf-8")
        result = self.run_factory()
        self.assertNotIn("cached", result["build"]["detail"])
        self.assertEqual((old / "keep.txt").read_text(), "keep")

    def test_failed_upstream_invalidates_downstream_status(self):
        self.run_factory()
        self.sdk.unlink()
        result = runner.PortRunner(load_spec(self.spec_path), self.work).run("host")
        self.assertEqual(result["status"], "blocked")
        state = json.loads((self.work / "cache-test" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["targets"]["host"]["stages"]["verify"]["status"], "not_run")

    def test_plan_does_not_touch_source_or_cached_state(self):
        first = self.run_factory()
        state = self.work / "cache-test" / "state.json"
        before = state.read_bytes()
        package = Path(first["package"]["detail"]["path"])
        package_before = package.read_bytes()
        self.run_factory(dry_run=True)
        self.assertEqual(state.read_bytes(), before)
        self.assertEqual(package.read_bytes(), package_before)

    def test_force_uses_new_workspaces(self):
        first = self.run_factory()
        second = self.run_factory(force=True)
        self.assertNotEqual(first["build"]["detail"]["artifact"], second["build"]["detail"]["artifact"])
        self.assertTrue(Path(first["build"]["detail"]["artifact"]).is_file())

    def test_handoff_is_consumed_by_build_and_rejects_wrong_kind(self):
        manifest = self.root / "handoff.json"
        handoff.write(manifest, handoff.create(self.source, self.spec_path,
                      kind="buildable_project", producer="test", source_platform="source"))
        self.run_factory(handoff_path=manifest)
        handoff.write(manifest, handoff.create(self.source, self.spec_path,
                      kind="module_source", producer="test", source_platform="x86"))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["port", "build", str(self.spec_path), "--target", "host",
                             "--work", str(self.work), "--handoff", str(manifest)])
        self.assertEqual(code, 2)

    def test_handoff_source_is_used_instead_of_spec_source(self):
        other = self.root / "approved"
        other.mkdir()
        for path in self.source.iterdir():
            (other / path.name).write_bytes(path.read_bytes())
        (other / "input.txt").write_text("approved", encoding="utf-8")
        manifest = self.root / "other-handoff.json"
        handoff.write(manifest, handoff.create(other, self.spec_path,
                      kind="buildable_project", producer="test", source_platform="source"))
        result = self.run_factory(handoff_path=manifest)
        self.assertEqual(Path(result["build"]["detail"]["artifact"]).read_bytes(), b"approved")
        self.assertEqual((self.source / "input.txt").read_text(), "one")

    def test_bad_admission_clears_old_success_and_records_block(self):
        self.run_factory()
        manifest = self.root / "module.json"
        handoff.write(manifest, handoff.create(self.source, self.spec_path,
                      kind="analysis_only", producer="test", source_platform="x86"))
        result = runner.PortRunner(load_spec(self.spec_path), self.work, handoff_path=manifest).run("host")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stages"][0]["id"], "admit")
        self.assertFalse(result["release_allowed"])
        state = json.loads((self.work / "cache-test" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["targets"]["host"]["stages"]["verify"]["status"], "not_run")

    def test_dependency_changed_during_build_is_not_accepted(self):
        original = runner._Build.run

        def build(stage):
            outcome = original(stage)
            self.sdk.write_text("sdk2", encoding="utf-8")
            return outcome

        with patch.object(runner._Build, "run", build):
            result = runner.PortRunner(load_spec(self.spec_path), self.work).run("host")
        self.assertEqual(result["status"], "blocked")
        self.assertIn("输入发生变化", result["stages"][-1]["detail"]["reason"])

    def test_changed_gate_is_actually_run_on_resume(self):
        self.run_factory()
        with patch.dict(gates.GATES, {"deterministic_zip": lambda ctx: gates.Result("fail", {})}):
            result = runner.PortRunner(load_spec(self.spec_path), self.work).run("host")
        self.assertEqual(result["status"], "fail")

    def test_patch_content_change_invalidates_fetch(self):
        patch_file = self.root / "change.patch"
        patch_file.write_text("first", encoding="utf-8")
        self.raw["source"]["patches"] = [str(patch_file)]
        self.save()
        with patch.object(runner._Fetch, "_apply", return_value=("pass", "", {"state": "fixture"})):
            self.run_factory()
            patch_file.write_text("second", encoding="utf-8")
            second = self.run_factory()
        self.assertNotIn("cached", second["fetch"]["detail"])

    def test_missing_fresh_build_output_does_not_accept_old_artifact(self):
        first = self.run_factory()
        self.raw["targets"]["host"]["build"]["commands"] = ["true"]
        self.save()
        result = runner.PortRunner(load_spec(self.spec_path), self.work).run("host")
        self.assertEqual(result["status"], "fail")
        self.assertTrue(Path(first["build"]["detail"]["artifact"]).is_file())


class ToolIdentityCase(unittest.TestCase):
    def test_actual_tool_content_is_bound_even_if_version_name_is_unchanged(self):
        from portfactory.portkit.profiles import Profile
        with tempfile.TemporaryDirectory() as tmp:
            tool = Path(tmp) / "compiler.exe"
            tool.write_bytes(b"version1")
            profile = Profile(id="host")
            target = {"build": {"system": "gnumake"}}
            with patch.object(cache, "resolve_tool", return_value=tool) as resolve:
                first = cache.tool_identity(profile, target, str(tool))
                selected = [call.args[0] for call in resolve.call_args_list]
                self.assertIn(os.environ.get("CC") or "cc", selected)
                previous = tool.stat()
                tool.write_bytes(b"version2")
                os.utime(tool, ns=(previous.st_atime_ns, previous.st_mtime_ns))
                second = cache.tool_identity(profile, target, str(tool))
            self.assertNotEqual(first["tools"]["cc"]["sha256"], second["tools"]["cc"]["sha256"])


if __name__ == "__main__":
    unittest.main()

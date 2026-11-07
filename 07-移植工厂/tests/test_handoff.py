from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from portfactory import handoff
from portfactory.portkit import cache


class HandoffCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / "main.c").write_text("int main(void) { return 0; }", encoding="utf-8")
        self.spec = self.root / "spec.json"
        self.spec.write_text("{}", encoding="utf-8")
        self.output = self.root / "handoff.json"

    def manifest(self, kind="buildable_project", **kwargs):
        return handoff.create(self.project, self.spec, kind=kind, producer="test",
                              source_platform="source", **kwargs)

    def write_raw(self, data, resign=True):
        if resign:
            data["id"] = cache.digest({k: v for k, v in data.items() if k != "id"})
        self.output.write_text(json.dumps(data), encoding="utf-8")

    def test_valid_manifest_does_not_change_source(self):
        before = (self.project / "main.c").read_bytes()
        manifest = self.manifest()
        handoff.write(self.output, manifest)
        self.assertEqual(handoff.load(self.output, require_buildable=True), manifest)
        self.assertEqual((self.project / "main.c").read_bytes(), before)
        self.assertFalse(manifest["qualification"]["release_allowed"])

    def test_module_and_analysis_are_not_buildable(self):
        for kind in ("module_source", "analysis_only"):
            with self.subTest(kind=kind):
                handoff.write(self.output, self.manifest(kind))
                handoff.load(self.output)
                with self.assertRaises(handoff.HandoffError):
                    handoff.load(self.output, require_buildable=True)

    def test_unresolved_aot_is_blocked(self):
        handoff.write(self.output, self.manifest("aot_project", unresolved=["kernel import"]))
        with self.assertRaises(handoff.HandoffError):
            handoff.load(self.output, require_buildable=True)

    def test_changed_spec_is_rejected(self):
        handoff.write(self.output, self.manifest())
        self.spec.write_text('{"changed": true}', encoding="utf-8")
        with self.assertRaises(handoff.HandoffError):
            handoff.load(self.output)

    def test_changed_source_is_rejected(self):
        handoff.write(self.output, self.manifest())
        (self.project / "main.c").write_text("changed", encoding="utf-8")
        with self.assertRaises(handoff.HandoffError):
            handoff.load(self.output)

    def test_added_file_is_rejected(self):
        handoff.write(self.output, self.manifest())
        (self.project / "extra.c").write_text("extra", encoding="utf-8")
        with self.assertRaises(handoff.HandoffError):
            handoff.load(self.output)

    def test_removed_file_is_rejected(self):
        handoff.write(self.output, self.manifest())
        (self.project / "main.c").unlink()
        with self.assertRaises(handoff.HandoffError):
            handoff.load(self.output)

    def test_unsafe_and_duplicate_paths_are_rejected(self):
        original = self.manifest()
        for rel in ("../main.c", "C:/outside.c", "/outside.c", "a\\b.c", "./main.c", ".git/config"):
            with self.subTest(path=rel):
                data = copy.deepcopy(original)
                data["project"]["files"][0]["path"] = rel
                self.write_raw(data)
                with self.assertRaises(handoff.HandoffError):
                    handoff.load(self.output)
        data = copy.deepcopy(original)
        data["project"]["files"].append(data["project"]["files"][0])
        self.write_raw(data)
        with self.assertRaises(handoff.HandoffError):
            handoff.load(self.output)

    def test_identity_and_qualification_are_checked(self):
        data = self.manifest()
        data["producer"] = "changed"
        self.write_raw(data, resign=False)
        with self.assertRaises(handoff.HandoffError):
            handoff.load(self.output)
        for value in (True, "false", 0):
            data = self.manifest()
            data["qualification"]["release_allowed"] = value
            self.write_raw(data)
            with self.assertRaises(handoff.HandoffError):
                handoff.load(self.output)

    def test_manifest_cannot_overwrite_project_or_spec(self):
        for path in (self.project / "manifest.json", self.spec):
            with self.assertRaises(handoff.HandoffError):
                handoff.write(path, self.manifest())

    def test_bad_json_and_fields_are_domain_errors(self):
        for data in (None, [], {}, {"schema": 1, "kind": []}):
            self.output.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(handoff.HandoffError):
                handoff.load(self.output)

    def test_empty_project_is_rejected(self):
        (self.project / "main.c").unlink()
        with self.assertRaises(handoff.HandoffError):
            self.manifest()


if __name__ == "__main__":
    unittest.main()

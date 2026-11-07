from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path

from portfactory import db, engine, intake, packaging
from portfactory.factory import Factory
from portfactory.gates import gate_manual_attestation
from portfactory.models import count_by_status
from portfactory.report import write_report
from portfactory.server import Handler
from portfactory.sniff import sniff_bytes


class FactoryCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.factory = Factory(self.root)
        self.factory.init()
        self.add_device("dev", "test-family", [])
        self.source = self.root / "game.bin"
        self.source.write_bytes(b"game data" * 32)
        self.game = intake.record_game(self.factory, self.source, "Test Game", "full")

    def tearDown(self):
        self.tmp.cleanup()

    def add_device(self, device_id: str, family: str, capabilities: list[str]):
        with self.factory.connect() as conn:
            conn.execute(
                "INSERT INTO devices(id, name, family, os, arch, capabilities, verified, "
                "notes, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (device_id, device_id, family, "test", "aarch64",
                 db.dump_json(capabilities), 0, "", db.now()),
            )

    def add_recipe(self, recipe_id: str, stages: list[dict], families=None,
                   release_stage: str | None = None) -> dict:
        recipe = {
            "id": recipe_id,
            "title": recipe_id,
            "device_families": families or ["test-family"],
            "stages": stages,
        }
        if release_stage:
            recipe["release_stage"] = release_stage
        path = self.factory.recipes_dir / "test" / f"{recipe_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(recipe, ensure_ascii=False), encoding="utf-8")
        return recipe

    def job(self, recipe_id: str, device="dev", source=None) -> str:
        created = engine.create_job(self.factory, self.game["id"], device, recipe_id,
                                    str(source or self.source))
        return created["id"]

    def summary(self, job_id: str) -> dict:
        with self.factory.connect() as conn:
            return engine.job_summary(conn, job_id)


class SniffTests(unittest.TestCase):
    def test_pe(self):
        data = bytearray(0x200)
        data[0:2] = b"MZ"
        data[0x3C:0x40] = (0x80).to_bytes(4, "little")
        data[0x80:0x84] = b"PE\0\0"
        data[0x84:0x86] = (0x8664).to_bytes(2, "little")
        info = sniff_bytes(bytes(data), len(data))
        self.assertEqual(info["format"], "pe")
        self.assertEqual(info["arch"], "x86-64")

    def test_nro(self):
        data = bytearray(0x400)
        data[0:4] = (0x14000000).to_bytes(4, "little")
        data[0x10:0x14] = b"NRO0"
        info = sniff_bytes(bytes(data), len(data))
        self.assertEqual(info["format"], "switch-nro")
        self.assertTrue(info["detail"]["entry_branch"])

    def test_elf_aarch64(self):
        data = bytearray(0x100)
        data[:4] = b"\x7fELF"
        data[4] = 2
        data[5] = 1
        data[16:18] = (3).to_bytes(2, "little")
        data[18:20] = (0xB7).to_bytes(2, "little")
        info = sniff_bytes(bytes(data), len(data))
        self.assertEqual(info["format"], "elf")
        self.assertEqual(info["arch"], "aarch64")


class DirectoryIntakeTests(unittest.TestCase):
    def test_signals_and_key_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "starcraft.exe").write_bytes(b"MZ" + b"\0" * 30)
            (root / "stardat.mpq").write_bytes(b"mpq" * 100)
            (root / "readme.txt").write_text("notes", encoding="utf-8")
            fp = intake.directory_fingerprint(root, "full")
            self.assertEqual(fp["file_count"], 3)
            labels = [s["label"] for s in fp["signals"]]
            self.assertTrue(any("星际争霸" in label for label in labels))
            paths = {h["path"] for h in fp["key_file_hashes"]}
            self.assertIn("starcraft.exe", paths)
            self.assertIn("stardat.mpq", paths)


class CountTests(unittest.TestCase):
    def test_counts_every_status(self):
        values = ["pass", "pass", "fail", "blocked", "not_run", "not_applicable", "pending"]
        counts = count_by_status([{"status": v} for v in values])
        self.assertEqual(counts["pass"], 2)
        self.assertEqual(counts["fail"], 1)
        self.assertEqual(counts["blocked"], 1)
        self.assertEqual(counts["not_run"], 1)
        self.assertEqual(counts["not_applicable"], 1)
        self.assertEqual(counts["pending"], 1)
        self.assertEqual(sum(counts.values()), len(values))


class EngineTests(FactoryCase):
    def test_release_when_required_gates_pass(self):
        self.add_recipe("basic", [
            {"id": "check", "title": "check", "gates": [
                {"id": "src", "type": "file_exists", "path": "${input}"}]},
            {"id": "release", "title": "release", "gates": [
                {"id": "ready", "type": "release_ready"}]},
        ], release_stage="release")
        job_id = self.job("basic")
        result = engine.run_job(self.factory, job_id)
        self.assertEqual(result["status"], "released")
        summary = self.summary(job_id)
        self.assertEqual(summary["counts_required"]["pass"], 5)
        self.assertEqual(summary["counts_required"]["blocked"], 0)

    def test_device_gate_blocks_until_evidence(self):
        self.add_recipe("device", [
            {"id": "check", "title": "check", "gates": [
                {"id": "src", "type": "file_exists", "path": "${input}"}]},
            {"id": "device", "title": "device", "gates": [
                {"id": "proof", "type": "manual_attestation",
                 "path": "${evidence_dir}/device_test.json",
                 "evidence_dir": "${evidence_dir}",
                 "required_checks": ["boots"]}]},
            {"id": "release", "title": "release", "gates": [
                {"id": "ready", "type": "release_ready"}]},
        ], release_stage="release")
        job_id = self.job("device")
        result = engine.run_job(self.factory, job_id)
        self.assertEqual(result["status"], "blocked")
        summary = self.summary(job_id)
        statuses = {s["stage_id"]: s["status"] for s in summary["stages"]}
        self.assertEqual(statuses["check"], "pass")
        self.assertEqual(statuses["device"], "blocked")
        self.assertEqual(statuses["release"], "pending")

        evidence = Path(summary["job"]["workdir"]) / "evidence"
        (evidence / "shot.txt").write_text("real device screenshot", encoding="utf-8")
        record = {
            "job_id": job_id,
            "tester": "tester",
            "device": "switch",
            "date": "2026-10-29",
            "checks": [{"id": "boots", "result": "pass", "evidence": "shot.txt"}],
        }
        (evidence / "device_test.json").write_text(
            json.dumps(record, ensure_ascii=False), encoding="utf-8")
        result = engine.run_job(self.factory, job_id)
        self.assertEqual(result["status"], "released")
        summary = self.summary(job_id)
        statuses = {s["stage_id"]: s["status"] for s in summary["stages"]}
        self.assertEqual(statuses["device"], "pass")
        self.assertEqual(statuses["release"], "pass")

    def test_claimed_pass_without_evidence_fails(self):
        self.add_recipe("device", [
            {"id": "device", "title": "device", "gates": [
                {"id": "proof", "type": "manual_attestation",
                 "path": "${evidence_dir}/device_test.json",
                 "evidence_dir": "${evidence_dir}",
                 "required_checks": ["boots"]}]},
        ])
        job_id = self.job("device")
        engine.run_job(self.factory, job_id)
        summary = self.summary(job_id)
        evidence = Path(summary["job"]["workdir"]) / "evidence"
        record = {
            "job_id": job_id, "tester": "tester", "device": "switch", "date": "2026-10-29",
            "checks": [{"id": "boots", "result": "pass", "evidence": "missing.jpg"}],
        }
        (evidence / "device_test.json").write_text(json.dumps(record), encoding="utf-8")
        result = engine.run_job(self.factory, job_id)
        self.assertEqual(result["status"], "failed")
        gates = [g for g in self.summary(job_id)["gates"] if g["gate_id"] == "proof"]
        self.assertEqual(gates[-1]["status"], "fail")

    def test_resume_does_not_rerun_passed_stage(self):
        counter = self.root / "counter.txt"
        code = ("from pathlib import Path; p=Path(r'%s'); "
                "p.write_text(str(int(p.read_text()) + 1 if p.exists() else 1))" % counter)
        self.add_recipe("resume", [
            {"id": "inc", "title": "inc", "steps": [
                {"id": "count", "type": "command", "command": [sys.executable, "-c", code]}],
             "gates": [{"id": "counter", "type": "file_exists", "path": str(counter)}]},
            {"id": "release", "title": "release", "gates": [
                {"id": "ready", "type": "release_ready"}]},
        ], release_stage="release")
        job_id = self.job("resume")
        self.assertEqual(engine.run_job(self.factory, job_id)["status"], "released")
        self.assertEqual(counter.read_text(), "1")
        self.assertEqual(engine.run_job(self.factory, job_id)["status"], "released")
        self.assertEqual(counter.read_text(), "1")

    def test_family_mismatch_blocks_before_stages(self):
        self.add_recipe("other", [
            {"id": "check", "title": "check", "gates": [
                {"id": "src", "type": "file_exists", "path": "${input}"}]},
        ], families=["another-family"])
        job_id = self.job("other")
        result = engine.run_job(self.factory, job_id)
        self.assertEqual(result["status"], "blocked")
        gates = [g for g in self.summary(job_id)["gates"] if g["gate_id"] == "device_family"]
        self.assertEqual(gates[0]["status"], "blocked")

    def test_report_is_written(self):
        self.add_recipe("basic", [
            {"id": "check", "title": "check", "gates": [
                {"id": "src", "type": "file_exists", "path": "${input}"}]},
            {"id": "release", "title": "release", "gates": [
                {"id": "ready", "type": "release_ready"}]},
        ], release_stage="release")
        job_id = self.job("basic")
        engine.run_job(self.factory, job_id)
        path = write_report(self.factory, job_id)
        text = path.read_text(encoding="utf-8")
        self.assertIn("已发布", text)
        self.assertIn("未测试", text)
        self.assertIn("逐项计数", text)


class PackageTests(unittest.TestCase):
    def test_build_and_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "a.nro"
            src.write_bytes(b"NRO" * 100)
            out = root / "pkg.zip"
            built = packaging.build_package(out, [{"src": str(src), "arcname": "a.nro"}],
                                            "job", "recipe")
            self.assertTrue(out.exists())
            detail = packaging.verify_package(out)
            self.assertEqual(detail["file_count"], 1)
            self.assertEqual(detail["files"][0]["sha256"], built["manifest"]["files"][0]["sha256"])

    def test_extra_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "a.bin"
            src.write_bytes(b"x")
            out = root / "pkg.zip"
            packaging.build_package(out, [{"src": str(src), "arcname": "a.bin"}], "job", "r")
            with zipfile.ZipFile(out, "a") as zf:
                zf.writestr("extra.bin", b"y")
            with self.assertRaises(packaging.PackageError):
                packaging.verify_package(out)


class ServerTests(FactoryCase):
    def test_dashboard_and_api(self):
        self.add_recipe("basic", [
            {"id": "check", "title": "check", "gates": [
                {"id": "src", "type": "file_exists", "path": "${input}"}]},
            {"id": "release", "title": "release", "gates": [
                {"id": "ready", "type": "release_ready"}]},
        ], release_stage="release")
        job_id = self.job("basic")
        engine.run_job(self.factory, job_id)
        handler = type("TestHandler", (Handler,), {"factory": self.factory})
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        try:
            page = urllib.request.urlopen(base + "/", timeout=5).read().decode("utf-8")
            self.assertIn(job_id, page)
            payload = json.loads(urllib.request.urlopen(
                base + f"/api/job/{job_id}", timeout=5).read().decode("utf-8"))
            self.assertEqual(payload["job"]["status"], "released")
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)


class AttestationTests(unittest.TestCase):
    def test_job_binding_and_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "evidence"
            evidence.mkdir()
            (evidence / "ok.txt").write_text("ok", encoding="utf-8")
            gate = {
                "type": "manual_attestation",
                "path": str(evidence / "att.json"),
                "evidence_dir": str(evidence),
                "required_checks": ["boots"],
            }
            ctx = {"job_id": "job1", "job_dir": str(root)}
            record = {"job_id": "job1", "tester": "t", "device": "d", "date": "2026-10-29",
                      "checks": [{"id": "boots", "result": "pass", "evidence": "ok.txt"}]}
            (evidence / "att.json").write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(gate_manual_attestation(gate, ctx).status, "pass")
            record["checks"][0]["evidence"] = "../outside.txt"
            (evidence / "att.json").write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(gate_manual_attestation(gate, ctx).status, "fail")


if __name__ == "__main__":
    unittest.main()

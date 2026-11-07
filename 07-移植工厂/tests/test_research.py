from __future__ import annotations

import hashlib
import json
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from portfactory import db, research
from portfactory.factory import Factory


class ResearchTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parent / "_tmp"
        base.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.root = Path(self.temp.name)
        self.factory = Factory(self.root / "factory")
        self.factory.init()
        self.source = self.root / "fixture.bin"
        self.source.write_bytes(b"\x8b\x44\x24\x04\x83\xc0\x01\xc3")

    def tearDown(self):
        self.temp.cleanup()

    def new(self, **kwargs):
        return research.create_run(self.factory, self.source, "switch-homebrew", self.root / "work", **kwargs)

    def seed(self, run):
        folder = Path(run["workdir"]) / "analysis"
        research.write_json(folder / "analysis.json", {"fixture": True})
        module = {"id": "fn_00401000", "address": 0x401000, "arg_count": 1,
                  "code_hex": self.source.read_bytes().hex(), "source_sha256": run["source_sha256"],
                  "instructions": [{"address": 0x401000, "mnemonic": "mov", "op_str": "eax, [esp+4]"}],
                  "eligibility": {"eligible": True, "reason": "test fixture"}}
        path = folder / "modules" / "fn_00401000.json"
        research.write_json(path, module)
        with self.factory.connect() as conn:
            conn.execute("UPDATE research_runs SET status='analysis_ready',analysis_sha256=? WHERE id=?",
                         (research.digest(folder / "analysis.json"), run["id"]))
            conn.execute("INSERT INTO research_modules(run_id,id,address,module_path,module_sha256,status) VALUES(?,?,?,?,?,?)",
                         (run["id"], module["id"], module["address"], str(path), research.digest(path), "pending"))
        return module

    def request(self, run):
        self.seed(run)
        result = research.work(self.factory, run["id"], Path("unused-compiler"))
        self.assertEqual(result["run"]["status"], "waiting_ai")
        return result["requests"][0]

    def response(self, run, attempt, ir=None):
        request = research.read_json(Path(attempt["request_path"]))
        response = {"request_id": attempt["id"], "request_sha256": attempt["request_sha256"],
                    "source_sha256": run["source_sha256"], "module_sha256": request["module_sha256"],
                    "ir": ir or {"locals": [], "body": [{"return": {"op": "add", "args": ["a0", 1]}}]},
                    "summary": "test candidate"}
        path = self.root / "response.json"
        research.write_json(path, response)
        return path

    def test_snapshot_is_separate_and_unchanged(self):
        run = self.new()
        self.assertNotEqual(Path(run["snapshot_path"]), self.source)
        self.assertEqual(research.digest(self.source), research.digest(Path(run["snapshot_path"])))
        self.assertFalse(research.status(self.factory, run["id"])["release_allowed"])

    def test_source_change_invalidates_resume(self):
        run = self.new()
        self.seed(run)
        self.source.write_bytes(b"changed")
        with self.assertRaises(research.ResearchError):
            research.work(self.factory, run["id"], Path("unused"))
        self.assertEqual(research.get_run(self.factory, run["id"])["status"], "failed")

    def test_budget_blocks_before_creating_request(self):
        run = self.new(max_context_bytes=1)
        self.seed(run)
        result = research.work(self.factory, run["id"], Path("unused"))
        self.assertEqual(result["run"]["status"], "budget_exhausted")
        self.assertEqual(result["budget"]["requests_charged"], 0)
        self.assertEqual(result["counts"]["pending"], 1)

    def test_pending_request_not_reissued(self):
        run = self.new()
        attempt = self.request(run)
        result = research.work(self.factory, run["id"], Path("unused"))
        self.assertEqual([a["id"] for a in result["requests"]], [attempt["id"]])
        self.assertEqual(result["budget"]["requests_charged"], 1)

    def test_response_binding_and_duplicate_rejected(self):
        run = self.new()
        attempt = self.request(run)
        path = self.response(run, attempt)
        value = research.read_json(path)
        value["source_sha256"] = "incorrect"
        research.write_json(path, value)
        with self.assertRaises(research.ResearchError):
            research.submit(self.factory, run["id"], path)
        path = self.response(run, attempt)
        research.submit(self.factory, run["id"], path)
        with self.assertRaises(research.ResearchError):
            research.submit(self.factory, run["id"], path)

    def test_identical_failed_ir_stops_without_recompile(self):
        run = self.new()
        attempt = self.request(run)
        research.submit(self.factory, run["id"], self.response(run, attempt))
        with patch("portfactory.behavior.compare_module", return_value={"status": "fail", "reason": "mismatch"}) as compare:
            result = research.work(self.factory, run["id"], Path("unused"))
            retry = next(a for a in result["requests"] if a["status"] == "waiting_ai")
            research.submit(self.factory, run["id"], self.response(run, retry))
            result = research.work(self.factory, run["id"], Path("unused"))
        self.assertEqual(compare.call_count, 1)
        self.assertEqual(result["counts"]["stopped"], 1)
        self.assertEqual(result["run"]["status"], "needs_research")
        self.assertEqual(result["budget"]["requests_charged"], 2)

    def test_retry_feedback_preserves_late_counterexample(self):
        run = self.new()
        attempt = self.request(run)
        research.submit(self.factory, run["id"], self.response(run, attempt))
        failure = {"index": 127, "args": [4294967295], "expected": 0, "actual": 1,
                   "reason": "return value mismatch"}
        comparison = {"status": "fail", "reason": "comparison completed", "passed": 127,
                      "failed": 1, "not_run": 0, "total": 128,
                      "cases": [{"status": "pass", "diagnostic": "x" * 256}] * 127 + [failure],
                      "counterexamples": [failure]}
        with patch("portfactory.behavior.compare_module", return_value=comparison):
            result = research.work(self.factory, run["id"], Path("unused"))
        retry = next(a for a in result["requests"] if a["status"] == "waiting_ai")
        request = research.read_json(Path(retry["request_path"]))
        feedback = json.loads(request["prompt"])["previous_validation"]
        self.assertEqual(feedback["counterexamples"], [failure])
        self.assertEqual(feedback["failed"], 1)
        self.assertEqual(feedback["passed"], 127)
        self.assertNotIn("cases", feedback)
        self.assertLess(len(json.dumps(feedback)), 6000)
        self.assertEqual(retry["context_charge"], len(request["prompt"].encode("utf-8")) + research.RESPONSE_LIMIT)

    def test_attempt_limit_and_reservation_survive_failure(self):
        run = self.new(max_attempts=1)
        attempt = self.request(run)
        research.submit(self.factory, run["id"], self.response(run, attempt))
        with patch("portfactory.behavior.compare_module", return_value={"status": "fail"}):
            result = research.work(self.factory, run["id"], Path("unused"))
        self.assertEqual(result["counts"]["stopped"], 1)
        self.assertGreater(result["budget"]["context_bytes_reserved"], 12000)

    def test_interrupted_validation_retains_charge(self):
        run = self.new(max_attempts=1)
        attempt = self.request(run)
        with self.factory.connect() as conn:
            conn.execute("UPDATE research_attempts SET status='validating' WHERE id=?", (attempt["id"],))
            conn.execute("UPDATE research_modules SET status='validating' WHERE run_id=?", (run["id"],))
        result = research.work(self.factory, run["id"], Path("unused"))
        self.assertEqual(result["requests"][0]["status"], "interrupted")
        self.assertEqual(result["budget"]["requests_charged"], 1)
        self.assertEqual(result["counts"]["stopped"], 1)

    def test_modified_module_is_rejected(self):
        run = self.new()
        self.seed(run)
        module_path = Path(run["workdir"]) / "analysis/modules/fn_00401000.json"
        module_path.write_text("{}", encoding="utf-8")
        with self.assertRaises(research.ResearchError):
            research.work(self.factory, run["id"], Path("unused"))
        self.assertEqual(research.status(self.factory, run["id"])["budget"]["requests_charged"], 0)

    def test_composed_callee_ranges_are_bound_to_snapshot(self):
        caller = bytes.fromhex("8b44240450e81600000083c404c3")
        leaf = bytes.fromhex("8b44240440c3")
        snapshot = caller + b"\xcc" * (0x20 - len(caller)) + leaf
        module = {"file_offset": 0x200, "size": len(caller), "code_hex": caller.hex(),
                  "code_ranges": [
                      {"file_offset": 0x200, "size": len(caller), "code_hex": caller.hex()},
                      {"file_offset": 0x200 + 0x20, "size": len(leaf), "code_hex": leaf.hex()}]}
        core = {"source_sha256": "a" * 64}
        research.verify_module_bytes([(None, {**core, **module})], b"\0" * 0x200 + snapshot, "a" * 64)
        with self.assertRaises(research.ResearchError):
            research.verify_module_bytes(
                [(None, {**core, **module, "code_ranges": [module["code_ranges"][0],
                  {**module["code_ranges"][1], "file_offset": 0x201}]})],
                b"\0" * 0x200 + snapshot, "a" * 64)
        with self.assertRaises(research.ResearchError):
            research.verify_module_bytes([(None, {**core, "file_offset": 0x200, "size": len(caller),
                                                  "code_hex": caller.hex()})],
                                         b"\0" * 0x200 + snapshot, "b" * 64)

    def test_prompt_includes_proven_callee_disassembly(self):
        run = {"source_sha256": "a" * 64, "target": "switch"}
        caller = {"id": "fn_00401000", "address": 0x401000, "arg_count": 1, "instructions": [],
                  "composition": {"status": "proven",
                                  "callee_argument_slots": {"fn_00401020": [1]},
                                  "members": [
                                      {"id": "fn_00401000", "address": 0x401000,
                                       "arg_count": 1, "instructions": [{"mnemonic": "push"}]},
                                      {"id": "fn_00401020", "address": 0x401020, "arg_count": 1,
                                       "instructions": [{"address": 0x401020, "mnemonic": "inc",
                                                         "op_str": "eax"}]}]}}
        prompt = json.loads(research.build_prompt(run, caller, {}))
        self.assertEqual(prompt["composition"]["callees"],
                         [{"id": "fn_00401020", "address": 0x401020, "arg_count": 1,
                           "instructions": [{"address": 0x401020, "mnemonic": "inc",
                                             "op_str": "eax"}]}])
        self.assertEqual(prompt["composition"]["callee_argument_slots"], {"fn_00401020": [1]})
        plain = {"id": "fn_00401030", "address": 0x401030, "arg_count": 1, "instructions": []}
        self.assertNotIn("composition", json.loads(research.build_prompt(run, plain, {})))

    def test_prompt_includes_fixed_trip_loop_evidence(self):
        run = {"source_sha256": "b" * 64, "target": "switch"}
        looped = {"id": "fn_00401040", "address": 0x401040, "arg_count": 1, "instructions": [],
                  "loops": [{"back_edge": 0x40104d, "target": 0x401049, "iterations": 3}]}
        prompt = json.loads(research.build_prompt(run, looped, {}))
        self.assertEqual(prompt["loops"], looped["loops"])
        self.assertIn("repeating its statements", prompt["loops_note"])
        plain = {"id": "fn_00401050", "address": 0x401050, "arg_count": 1, "instructions": []}
        self.assertNotIn("loops", json.loads(research.build_prompt(run, plain, {})))

    def test_os_lock_prevents_second_owner(self):
        run = self.new()
        with research.run_lock(Path(run["workdir"])):
            with self.assertRaises(research.ResearchError):
                with research.run_lock(Path(run["workdir"])):
                    self.fail("lock should not be reentrant")

    def test_interrupted_time_lease_is_charged(self):
        run = self.new(max_active_seconds=30)
        self.seed(run)
        with self.factory.connect() as conn:
            conn.execute("UPDATE research_runs SET active_lease_seconds=30 WHERE id=?", (run["id"],))
        result = research.work(self.factory, run["id"], Path("unused"))
        self.assertEqual(result["run"]["status"], "budget_exhausted")
        self.assertGreaterEqual(result["budget"]["active_seconds"], 30)
        self.assertEqual(result["budget"]["active_seconds_reserved"], 0)
        self.assertEqual(result["budget"]["requests_charged"], 0)

    def test_received_response_resumes_without_model_call(self):
        run = self.new(max_attempts=1)
        attempt = self.request(run)
        path = self.response(run, attempt)
        with self.factory.connect() as conn:
            conn.execute("UPDATE research_attempts SET status='received',response_path=? WHERE id=?", (str(path), attempt["id"]))
        with patch("portfactory.behavior.compare_module", return_value={"status": "fail"}), patch("portfactory.research._local_request") as remote:
            result = research.work(self.factory, run["id"], Path("unused"), provider="local")
        remote.assert_not_called()
        self.assertEqual(result["budget"]["requests_charged"], 1)
        self.assertEqual(result["counts"]["stopped"], 1)

    def test_changed_request_cannot_redirect_provider_output(self):
        run = self.new()
        attempt = self.request(run)
        path = Path(attempt["request_path"])
        changed = research.read_json(path)
        changed["response_path"] = str(self.source)
        research.write_json(path, changed)
        before = research.digest(self.source)
        with patch("portfactory.research.worker_process") as worker:
            result = research.work(self.factory, run["id"], Path("unused"), provider="local", endpoint="http://127.0.0.1:9/v1", model="fixture")
        worker.assert_not_called()
        self.assertEqual(result["run"]["status"], "provider_failed")
        self.assertEqual(research.digest(self.source), before)

    def test_launcher_preserves_environment_exit_code(self):
        launcher = Path(__file__).resolve().parents[1] / "工厂.py"
        with patch.object(sys, "executable", str(self.root / "other-python.exe")), \
                patch.object(sys, "argv", [str(launcher), "--invalid-option"]), \
                patch.object(Path, "is_file", return_value=True), \
                patch("subprocess.call", return_value=2) as child:
            with self.assertRaises(SystemExit) as caught:
                runpy.run_path(str(launcher), run_name="__main__")
        self.assertEqual(caught.exception.code, 2)
        child.assert_called_once()
        self.assertEqual(child.call_args.args[0][1:], [str(launcher), "--invalid-option"])

    def test_budget_validation(self):
        for budget in (0, -1, float("nan")):
            with self.assertRaises(research.ResearchError):
                self.new(max_active_seconds=budget)


if __name__ == "__main__":
    unittest.main()

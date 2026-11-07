from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from portfactory import behavior as b


ADDRESS = 0x00401000
IDENTITY = "8b442404c3"
ADD = "8b44240403442408c3"
SNAPSHOT = hashlib.sha256(b"synthetic test snapshot, no commercial bytes").hexdigest()
HAVE_EMULATION = all(importlib.util.find_spec(name) is not None
                     for name in ("unicorn", "capstone", "elftools"))


def op(name, *args):
    return {"op": name, "args": list(args)}


def ir_return(value):
    return {"locals": [], "body": [{"return": value}]}


def module(code=IDENTITY, arg_count=1):
    return {"id": "synthetic_scalar", "address": ADDRESS, "code_hex": code,
            "arg_count": arg_count, "source_sha256": SNAPSHOT,
            "eligibility": {"eligible": True, "reason": "self-authored scalar x86 fixture"}}


def image(code):
    data = bytes.fromhex(code)
    segments = [(ADDRESS, data, len(data), 5)]
    b._check_segments(segments)
    return b._Image(ADDRESS, data, segments, b._decode(data, ADDRESS))


def find_compiler():
    configured = os.environ.get("PORTFACTORY_TEST_COMPILER")
    candidates = ([configured] if configured else
                  [shutil.which("zig"), "F:/_scratch/zigwin/zig.exe"])
    for name in candidates:
        if name and Path(name).is_file() and Path(name).name.lower() in {"zig", "zig.exe"}:
            return Path(name).resolve()
    return None


class IRTests(unittest.TestCase):
    def test_valid_locals_branch_and_fallthrough(self):
        ir = {"locals": ["v0"], "body": [
            {"if": "a0", "then": [{"set": "v0", "value": 1}], "else": []},
            {"return": "v0"}]}
        self.assertIsNone(b.validate_ir(ir, 1))
        source = b.render_c(ir, 1)
        self.assertIn("uint32_t v0 = 0u;", source)
        self.assertIn("__attribute__((cdecl, used))", source)
        self.assertNotIn("#include", source)
        self.assertNotIn("main(", source)

    def test_all_operators_and_fixed_semantics(self):
        for name in b._BINARY:
            with self.subTest(name=name):
                b.validate_ir(ir_return(op(name, "a0", 0xFFFFFFFF)), 1)
        for name in b._UNARY:
            b.validate_ir(ir_return(op(name, "a0")), 1)
        self.assertIn("& 31u", b.render_c(ir_return(op("shl", "a0", 32)), 1))
        self.assertIn("int32_t", b.render_c(ir_return(op("slt", "a0", 0)), 1))
        self.assertIn("~(", b.render_c(ir_return(op("not", "a0")), 1))

    def test_injection_unknown_fields_and_types(self):
        invalid = [
            ir_return("a0); system(\"calc\"); /*"),
            ir_return({"op": "system", "args": ["a0"]}),
            ir_return({"op": "add", "args": ["a0", 1], "c": "malicious"}),
            ir_return({"op": "add", "args": ("a0", 1)}),
            ir_return({"op": ["add"], "args": [1, 2]}),
            ir_return(op("add", "a0")), ir_return(op("not", 1, 2)),
            ir_return(True), ir_return(-1), ir_return(2**32), ir_return(1.0),
            ir_return(None), ir_return("a1"), ir_return("v0"),
            ir_return({"call": "a0", "args": []}),
            {"locals": [], "body": [{"return": 0, "include": "stdlib.h"}]},
            {"locals": [], "body": [{"set": "a0", "value": 1}, {"return": 0}]},
            {"locals": [], "body": [{"while": 1, "body": []}, {"return": 0}]},
            {"locals": [], "body": [{"return": 0}], "args": ["int (*a0)()"]},
            {"locals": [], "body": [{"return": 0}], "source": "arbitrary C"},
        ]
        for ir in invalid:
            with self.subTest(ir=ir), self.assertRaises(ValueError):
                b.validate_ir(ir, 1)

    def test_reserved_and_duplicate_names(self):
        for names in (["a0"], ["pf_module"], ["uint32_t"], ["int"], ["__x"],
                      ["v0;evil"], ["v00"], ["v0", "v0"], [True], ["v1000"]):
            with self.subTest(names=names), self.assertRaises(ValueError):
                b.validate_ir({"locals": names, "body": [{"return": 0}]}, 1)

    def test_all_paths_return_and_unreachable_rejected(self):
        for body in ([], [{"if": "a0", "then": [{"return": 1}], "else": []}],
                     [{"return": 1}, {"return": 2}]):
            with self.subTest(body=body), self.assertRaises(ValueError):
                b.validate_ir({"locals": [], "body": body}, 1)
        b.validate_ir({"locals": [], "body": [
            {"if": "a0", "then": [{"return": 1}], "else": [{"return": 0}]}]}, 1)

    def test_limits_and_cycles(self):
        deep = 0
        for _ in range(b.MAX_DEPTH):
            deep = op("neg", deep)
        cycle = op("not", 0)
        cycle["args"][0] = cycle
        oversized = {"locals": ["v0"], "body": [
            {"set": "v0", "value": 0} for _ in range(b.MAX_NODES)] + [{"return": 0}]}
        for ir in (ir_return(deep), ir_return(cycle), oversized,
                   {"locals": [f"v{i}" for i in range(65)], "body": [{"return": 0}]}):
            with self.assertRaises(ValueError):
                b.validate_ir(ir, 1)
        with mock.patch.object(b, "MAX_IR_BYTES", 5), self.assertRaises(ValueError):
            b.validate_ir(ir_return(0), 1)

    def test_argument_limits(self):
        for count in (0, 5, True, 1.0, "1"):
            with self.subTest(count=count), self.assertRaises(ValueError):
                b.validate_ir(ir_return(0), count)

    def test_fixed_seed_boundaries_and_minimum(self):
        for count in range(1, 5):
            cases = b._cases(count, 0)
            self.assertGreaterEqual(len(cases), 128)
            self.assertEqual(cases, b._cases(count, 0))
            self.assertLess(len(cases), 256)
            for edge in (0, 1, 0xFFFFFFFF, 0x7FFFFFFF, 0x80000000):
                self.assertIn([edge] * count, cases)
            if count >= 2:
                self.assertIn([0xFFFFFFFF, 0x80000000] + [0] * (count - 2), cases)


class BlockedReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pf-behavior-")
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name)
        self.compiler = self.output / "missing" / "zig.exe"

    def compare(self, m=None, ir=None, **kwargs):
        return b.compare_module(m if m is not None else module(),
                                ir if ir is not None else ir_return("a0"),
                                self.output, self.compiler, **kwargs)

    def assert_blocked(self, report):
        self.assertEqual(report["status"], "blocked", report["reason"])
        self.assertEqual(report["passed"], 0)
        self.assertEqual(report["failed"], 0)
        self.assertEqual(report["not_run"], report["total"])
        saved = json.loads((self.output / "comparison.json").read_text(encoding="utf-8"))
        self.assertEqual(report, saved)

    def test_missing_compiler_never_passes(self):
        result = self.compare(random_cases=0)
        self.assert_blocked(result)
        self.assertGreaterEqual(result["total"], 128)
        self.assertEqual(result["original_code_sha256"], hashlib.sha256(bytes.fromhex(IDENTITY)).hexdigest())
        self.assertEqual(result["source_sha256"], SNAPSHOT)
        self.assertTrue((self.output / "source.c").is_file())
        self.assertEqual(result["scope"], "scalar_function_only")

    def test_injection_rejected_before_compilation(self):
        with mock.patch.object(b, "_compile") as compiler:
            result = self.compare(ir=ir_return("a0; shell()"))
        compiler.assert_not_called()
        self.assert_blocked(result)
        self.assertFalse((self.output / "source.c").exists())

    def test_eligibility_is_not_truthiness(self):
        for eligible in (False, 1, "true"):
            m = module()
            m["eligibility"]["eligible"] = eligible
            self.assert_blocked(self.compare(m=m))

    def test_module_inputs_bounded_and_hex_contiguous(self):
        for key, value in (("address", True), ("address", 0x100000000),
                           ("code_hex", "8b 44 24 04 c3"), ("code_hex", "0"),
                           ("code_hex", ""), ("code_hex", "ff" * (b.MAX_CODE_BYTES + 1)),
                           ("source_sha256", "missing"), ("arg_count", 0)):
            with self.subTest(key=key, value=str(value)[:30]):
                m = module()
                m[key] = value
                self.assert_blocked(self.compare(m=m))

    def test_invalid_limits_and_zero_work_never_pass(self):
        for kwargs in ({"random_cases": -1}, {"random_cases": True},
                       {"random_cases": 4097}, {"timeout": 0}, {"timeout": float("nan")}):
            self.assert_blocked(self.compare(**kwargs))

    def test_stale_artifacts_cannot_create_false_pass(self):
        (self.output / "rewritten.elf").write_bytes(b"stale output")
        self.assert_blocked(self.compare())
        self.assertFalse((self.output / "rewritten.elf").exists())


class OriginalRangeTests(unittest.TestCase):
    def test_ranges_bind_root_digest_bytes_and_disjointness(self):
        base = module()
        digest = hashlib.sha256(bytes.fromhex(IDENTITY)).hexdigest()
        good = {"address": ADDRESS, "size": 5, "code_hex": IDENTITY, "code_sha256": digest}
        self.assertEqual(b._original_ranges({**base, "code_ranges": [good]})[0]["data"],
                         bytes.fromhex(IDENTITY))
        for bad in ({**good, "code_sha256": "0" * 64},
                    {**good, "code_hex": "90" * 5},
                    {**good, "size": 6},
                    {**good, "address": ADDRESS + 4}):
            with self.subTest(bad=bad), self.assertRaises(b._Blocked):
                b._original_ranges({**base, "code_ranges": [bad]})
        overlap = {"address": ADDRESS + 2, "size": 3, "code_hex": "909090",
                   "code_sha256": hashlib.sha256(b"\x90\x90\x90").hexdigest()}
        with self.assertRaises(b._Blocked):
            b._original_ranges({**base, "code_ranges": [good, overlap]})
        with self.assertRaises(b._Blocked):
            b._original_ranges({**base, "code_ranges": []})

    def test_zero_filled_gap_is_never_executed(self):
        root = bytes.fromhex(IDENTITY)
        leaf = bytes.fromhex("8b44240440c3")
        spans = [{"address": ADDRESS, "data": root},
                 {"address": ADDRESS + 0x1000, "data": leaf}]
        composed = b._original_image(ADDRESS, spans)
        self.assertEqual(composed.instructions[ADDRESS + 0x1000].mnemonic, "mov")
        self.assertFalse(ADDRESS + 0x40 in composed.instructions)
        self.assertEqual([(start, size) for start, _, size, _ in composed.segments],
                         [(ADDRESS & -b.PAGE, 2 * b.PAGE)])
        self.assertEqual(composed.segments[0][1][0x40], 0)


@unittest.skipUnless(HAVE_EMULATION, "requires Unicorn, Capstone, and pyelftools; not a behavioral pass")
class EmulatorTests(unittest.TestCase):
    def run_code(self, code, args=(0xFFFFFFFF,), seed=123):
        return b._execute(image(code), list(args), seed)

    def test_unsigned_overflow_and_independent_engines(self):
        import unicorn
        with mock.patch.object(unicorn, "Uc", wraps=unicorn.Uc) as engines:
            for arg in (0, 1, 0xFFFFFFFF, 0x80000000):
                result = self.run_code("8b44240483c001c3", [arg])
                self.assertEqual(result["status"], "pass", result)
                self.assertEqual(result["value"], (arg + 1) & 0xFFFFFFFF)
        self.assertEqual(engines.call_count, 4)

    def test_internal_jump_call_and_stack_frame(self):
        codes = ["eb0190" + IDENTITY,
                 "e801000000c38b442408c3",
                 "5589e583ec088b45088945fc8b45fcc9c3"]
        for code in codes:
            with self.subTest(code=code):
                result = self.run_code(code)
                self.assertEqual(result["status"], "pass", result)
                self.assertEqual(result["value"], 0xFFFFFFFF)

    def test_callee_saved_and_cdecl_stack(self):
        codes = ["31db" + IDENTITY, "31f6" + IDENTITY, "31ff" + IDENTITY,
                 "31ed" + IDENTITY, "8b442404c20400", "585950c3"]
        for code in codes:
            with self.subTest(code=code):
                result = self.run_code(code)
                self.assertEqual(result["status"], "fail", result)

    def test_extra_memory_and_uninitialized_stack_rejected(self):
        for address in (0, ADDRESS, ADDRESS + 0x100, b.STACK_BASE - 4, b.ENTRY_SP + 8):
            code = "a1" + struct.pack("<I", address).hex() + "c3"
            with self.subTest(address=address):
                self.assertEqual(self.run_code(code)["status"], "fail")
        for code in ("c744240401000000" + IDENTITY,
                     "c7042400000000c3", "83ec048b042483c404c3", "8b4424fcc3",
                     "c605" + struct.pack("<I", ADDRESS).hex() + "90c3"):
            with self.subTest(code=code):
                self.assertEqual(self.run_code(code)["status"], "fail")

    def test_forbidden_instructions_and_non_scalar_registers(self):
        for code in ("cd80c3", "0f05c3", "0f34c3", "0fa2c3", "0f31c3", "f4c3",
                     "0f20c0c3", "648b042500000000c3", "f3a4c3"):
            with self.subTest(code=code):
                result = self.run_code(code)
                self.assertEqual(result["status"], "fail", result)

    def test_outside_mid_instruction_indirect_and_sentinel_jumps(self):
        sentinel_jump = "e9" + struct.pack("<i", b.SENTINEL - ADDRESS - 5).hex()
        for code in ("e900100000", "eb01b801000000c3", "ffe0", sentinel_jump):
            with self.subTest(code=code):
                self.assertEqual(self.run_code(code)["status"], "fail")

    def test_infinite_loop_is_bounded(self):
        result = self.run_code("ebfe")
        self.assertEqual(result["status"], "fail")
        self.assertLessEqual(result["instructions"], b.MAX_INSTRUCTIONS)
        self.assertIn("limit", result["error"])

    def test_mapping_collisions_and_wx_rejected(self):
        for segments in ([(b.STACK_BASE, b"\xc3", 1, 5)],
                         [(b.SENTINEL, b"\xc3", 1, 5)],
                         [(ADDRESS, b"\xc3", 1, 7)],
                         [(ADDRESS, b"\xc3", 1, 5), (ADDRESS + 1, b"\xc3", 1, 4)]):
            with self.assertRaises(b._Blocked):
                b._check_segments(segments)


@unittest.skipUnless(HAVE_EMULATION, "requires Unicorn, Capstone, and pyelftools; not a behavioral pass")
class RealCompilerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = find_compiler()
        if cls.compiler is None:
            raise unittest.SkipTest("no Zig compiler: set PORTFACTORY_TEST_COMPILER; compilation NOT verified")
        cls.tmp = tempfile.TemporaryDirectory(prefix="pf-real-compiler-")
        cls.output = Path(cls.tmp.name)
        cls.addClassCleanup(cls.tmp.cleanup)

    def compare(self, code, ir, count=1):
        result = b.compare_module(module(code, count), ir, self.output, self.compiler,
                                  random_cases=0, timeout=120)
        self.assertEqual(result["total"], result["passed"] + result["failed"] + result["not_run"])
        return result

    def assert_pass(self, result):
        diagnostic = result["reason"]
        if (self.output / "compile.log").exists():
            diagnostic += "\n" + (self.output / "compile.log").read_text(encoding="utf-8", errors="replace")[:8000]
        self.assertEqual(result["status"], "pass", diagnostic + str(result["counterexamples"][:1]))
        self.assertGreaterEqual(result["passed"], 128)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["not_run"], 0)
        self.assertTrue(result["compile_command"])
        self.assertIn("-O2", result["compile_command"])
        for filename in ("source.c", "rewritten.elf", "comparison.json", "compile.log", "compiler-version.log"):
            self.assertTrue((self.output / filename).is_file())
        self.assertEqual(result["rewritten_elf_sha256"], hashlib.sha256((self.output / "rewritten.elf").read_bytes()).hexdigest())
        for case in result["cases"]:
            self.assertEqual(case["expected"], case["actual"])
            self.assertEqual(case["tool_versions"], result["tool_versions"])
            self.assertEqual(case["original_code_sha256"], result["original_code_sha256"])
        self.assertEqual(result, json.loads((self.output / "comparison.json").read_text(encoding="utf-8")))

    def test_correct_rewrite_wraparound_and_four_arguments(self):
        cases = [(ADD, ir_return(op("add", "a0", "a1")), 2),
                 ("8b44240483c001c3", ir_return(op("add", "a0", 1)), 1),
                 ("8b442404034424083344240c0faf442410c3",
                  ir_return(op("mul", op("xor", op("add", "a0", "a1"), "a2"), "a3")), 4)]
        for code, ir, count in cases:
            with self.subTest(count=count, code=code):
                self.assert_pass(self.compare(code, ir, count))

    def composed_module(self):
        caller, leaf = "8b44240450e81600000083c404c3", "8b44240440c3"

        def span(address, code):
            data = bytes.fromhex(code)
            return {"address": address, "size": len(data), "code_hex": code,
                    "code_sha256": hashlib.sha256(data).hexdigest()}

        return {"id": "synthetic_composed", "address": ADDRESS, "code_hex": caller,
                "arg_count": 1, "source_sha256": SNAPSHOT,
                "eligibility": {"eligible": True, "reason": "proven_scalar_composition"},
                "composition": {"status": "proven", "functions": 2},
                "code_ranges": [span(ADDRESS, caller), span(ADDRESS + 0x20, leaf)]}

    def test_composed_caller_runs_callee_range_and_passes(self):
        report = b.compare_module(self.composed_module(), ir_return(op("add", "a0", 1)),
                                  self.output, self.compiler, random_cases=0, timeout=120)
        self.assert_pass(report)
        self.assertEqual([item["address"] for item in report["original_ranges"]],
                         [ADDRESS, ADDRESS + 0x20])
        self.assertEqual(report["original_ranges"][1]["code_sha256"],
                         hashlib.sha256(bytes.fromhex("8b44240440c3")).hexdigest())
        self.assertEqual(report["composition"]["functions"], 2)

    def test_composed_caller_without_callee_bytes_fails_every_case(self):
        module = self.composed_module()
        module["code_ranges"] = module["code_ranges"][:1]
        report = b.compare_module(module, ir_return(op("add", "a0", 1)),
                                  self.output, self.compiler, random_cases=0, timeout=120)
        self.assertEqual(report["status"], "fail", report["reason"])
        self.assertEqual(report["failed"], report["total"])
        self.assertIn("branch", report["counterexamples"][0]["reason"])

    def test_fixed_trip_original_loop_matches_unrolled_ir(self):
        # mov eax,[esp+4]; mov ecx,3; L: add eax,1; dec ecx; jnz L; ret
        code = "8b442404b90300000083c0014975fac3"
        ir = {"locals": ["v0"], "body": [
            {"set": "v0", "value": op("add", "a0", 1)},
            {"set": "v0", "value": op("add", "v0", 1)},
            {"set": "v0", "value": op("add", "v0", 1)},
            {"return": "v0"}]}
        self.assert_pass(self.compare(code, ir))
        short = {"locals": ["v0"], "body": [
            {"set": "v0", "value": op("add", "a0", 1)},
            {"set": "v0", "value": op("add", "v0", 1)},
            {"return": "v0"}]}
        result = self.compare(code, short)
        self.assertEqual(result["status"], "fail", result["reason"])
        self.assertGreater(len(result["counterexamples"]), 0)

    def test_shift_mask_signed_unsigned_and_unary_semantics(self):
        cases = [
            ("8b4424048b4c2408d3e0c3", op("shl", "a0", "a1"), 2),
            ("8b4424048b4c2408d3e8c3", op("shr", "a0", "a1"), 2),
            ("8b4424043b4424080f9cc00fb6c0c3", op("slt", "a0", "a1"), 2),
            ("8b4424043b4424080f92c00fb6c0c3", op("ult", "a0", "a1"), 2),
            ("8b442404f7d0c3", op("not", "a0"), 1),
            ("8b442404f7d8c3", op("neg", "a0"), 1),
        ]
        for code, expr, count in cases:
            with self.subTest(expr=expr):
                self.assert_pass(self.compare(code, ir_return(expr), count))

    def test_branches_and_zero_initialized_locals(self):
        ir = {"locals": ["v0"], "body": [
            {"if": op("slt", "a0", 0),
             "then": [{"set": "v0", "value": op("neg", "a0")}],
             "else": [{"set": "v0", "value": "a0"}]}, {"return": "v0"}]}
        self.assert_pass(self.compare("8b44240485c07902f7d8c3", ir))
        self.assert_pass(self.compare("31c0c3", {"locals": ["v0"], "body": [{"return": "v0"}]}))

    def test_wrong_rewrite_has_counterexamples(self):
        result = self.compare(ADD, ir_return(op("sub", "a0", "a1")), 2)
        self.assertEqual(result["status"], "fail", result["reason"])
        self.assertGreater(result["failed"], 0)
        self.assertGreater(len(result["counterexamples"]), 0)
        self.assertNotEqual(result["counterexamples"][0]["expected"], result["counterexamples"][0]["actual"])
        self.assertEqual(result["not_run"], 0)

    def test_original_abi_violation_cannot_pass_matching_return(self):
        result = self.compare("31db" + IDENTITY, ir_return("a0"))
        self.assertEqual(result["status"], "fail", result["reason"])
        self.assertEqual(result["failed"], result["total"])
        self.assertIn("callee-saved", result["counterexamples"][0]["reason"])

    def test_compile_failure_and_timeout_cannot_reuse_old_elf(self):
        self.assert_pass(self.compare(IDENTITY, ir_return("a0")))
        real_run = b._run_process

        def fail_compile(command, *args, **kwargs):
            if "cc" in command:
                return 1
            return real_run(command, *args, **kwargs)

        with mock.patch.object(b, "_run_process", side_effect=fail_compile):
            result = self.compare(IDENTITY, ir_return("a0"))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["passed"], 0)
        self.assertEqual(result["not_run"], result["total"])
        self.assertFalse((self.output / "rewritten.elf").exists())
        with mock.patch.object(b, "_run_process", side_effect=subprocess.TimeoutExpired(["zig"], 1)):
            result = self.compare(IDENTITY, ir_return("a0"))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["passed"], 0)

    def test_non_i386_elf_rejected(self):
        self.assert_pass(self.compare(IDENTITY, ir_return("a0")))
        path = self.output / "rewritten.elf"
        data = bytearray(path.read_bytes())
        data[18:20] = (62).to_bytes(2, "little")  # EM_X86_64, deliberately inconsistent.
        path.write_bytes(data)
        with self.assertRaises(b._Blocked):
            b._load_elf(path)


class ProcessContainmentTests(unittest.TestCase):
    @staticmethod
    def alive(pid):
        if os.name == "nt":
            import ctypes as ct
            from ctypes import wintypes as wt
            kernel = ct.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
            kernel.OpenProcess.restype = wt.HANDLE
            kernel.GetExitCodeProcess.argtypes = [wt.HANDLE, ct.POINTER(wt.DWORD)]
            kernel.CloseHandle.argtypes = [wt.HANDLE]
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            try:
                code = wt.DWORD()
                return bool(kernel.GetExitCodeProcess(handle, ct.byref(code))) and code.value == 259
            finally:
                kernel.CloseHandle(handle)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        stat = Path(f"/proc/{pid}/stat")
        return not stat.exists() or stat.read_text().split(")", 1)[1].split()[0] != "Z"

    def test_timeout_kills_own_descendants_not_bystander(self):
        with tempfile.TemporaryDirectory(prefix="pf-process-test-") as tmp:
            output = Path(tmp)
            env = b._compiler_environment(output)
            # Trusted test code, never model-provided code. Both processes just wait.
            bystander = subprocess.Popen([sys.executable, "-B", "-c", "import time; time.sleep(60)"],
                                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
            try:
                child_script = "import time; time.sleep(60)"
                parent_script = (
                    "import subprocess,sys,os,time; from pathlib import Path; "
                    f"child=subprocess.Popen([sys.executable,'-B','-c',{child_script!r}]); "
                    "Path('pids.json').write_text(str(os.getpid())+' '+str(child.pid)); time.sleep(60)"
                )
                with self.assertRaises(subprocess.TimeoutExpired):
                    b._run_process([sys.executable, "-B", "-c", parent_script],
                                   output / "process.log", output, env, 2)
                pids = [int(pid) for pid in (output / "pids.json").read_text().split()]
                self.assertTrue(self.alive(bystander.pid), "unrelated process was killed")
                for pid in pids:
                    self.assertFalse(self.alive(pid), f"owned descendant {pid} survived timeout")
            finally:
                bystander.terminate()
                bystander.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()

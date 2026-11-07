"""Self-authored x86 fixtures only: no game bytes and no original EXE execution."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from portfactory import reverse

HAVE_CAPSTONE = importlib.util.find_spec("capstone") is not None
HAVE_PEFILE = importlib.util.find_spec("pefile") is not None
BASE = 0x400000
TEXT = BASE + 0x1000
LEAF = bytes.fromhex("8b44240403442408c3")  # uint32 a + b
LEAF_CALLED = bytes.fromhex("8b44240440c3")  # uint32 a + 1


def synthetic_pe(code=LEAF, *, entry=0x1000, flags=0x60000020,
                 name=b".text", machine=0x14c, magic=0x10b,
                 rdata=None, directories=None):
    """Minimal, file-aligned PE, with exact VirtualSize (padding is not code)."""
    align = lambda value: (value + 0x1ff) & ~0x1ff
    text_size = align(len(code))
    count = 2 if rdata is not None else 1
    raw = bytearray(0x200 + text_size + (align(len(rdata)) if rdata is not None else 0))
    raw[:2] = b"MZ"
    struct.pack_into("<I", raw, 0x3c, 0x80)
    raw[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", raw, 0x84, machine, count, 0, 0, 0, 224, 0x102)
    optional = 0x98
    struct.pack_into("<H", raw, optional, magic)
    struct.pack_into("<I", raw, optional + 4, text_size)
    struct.pack_into("<III", raw, optional + 16, entry, 0x1000, 0x2000)
    struct.pack_into("<III", raw, optional + 28, BASE, 0x1000, 0x200)
    struct.pack_into("<HH", raw, optional + 40, 4, 0)
    struct.pack_into("<HH", raw, optional + 48, 4, 0)
    struct.pack_into("<II", raw, optional + 56, 0x3000 if count == 2 else 0x2000, 0x200)
    struct.pack_into("<H", raw, optional + 68, 3)
    struct.pack_into("<IIIII", raw, optional + 72, 0x100000, 0x1000, 0x100000, 0x1000, 0)
    struct.pack_into("<I", raw, optional + 92, 16)
    for index, (rva, size) in (directories or {}).items():
        struct.pack_into("<II", raw, optional + 96 + index * 8, rva, size)
    table = optional + 224
    struct.pack_into("<8sIIIIIIHHI", raw, table, name, len(code), 0x1000,
                     text_size, 0x200, 0, 0, 0, 0, flags)
    raw[0x200:0x200 + len(code)] = code
    if rdata is not None:
        struct.pack_into("<8sIIIIIIHHI", raw, table + 40, b".rdata", len(rdata),
                         0x2000, align(len(rdata)), 0x200 + text_size, 0, 0, 0, 0, 0x40000040)
        raw[0x200 + text_size:0x200 + text_size + len(rdata)] = rdata
    return bytes(raw)


@unittest.skipUnless(HAVE_CAPSTONE, "capstone is an optional analysis dependency")
class FunctionTests(unittest.TestCase):
    def module(self, hex_code):
        return reverse.analyze_function(bytes.fromhex(hex_code))

    def eligible(self, hex_code, args):
        module = self.module(hex_code)
        self.assertTrue(module["eligibility"]["eligible"], module["eligibility"])
        self.assertEqual(module["arg_count"], args)
        self.assertEqual(module["size"], len(bytes.fromhex(module["code_hex"])))
        return module

    def rejected(self, hex_code, reason=None):
        module = self.module(hex_code)
        self.assertFalse(module["eligibility"]["eligible"], module)
        self.assertIsNone(module["arg_count"])
        if reason:
            self.assertEqual(module["eligibility"]["reason"], reason)
        return module

    def test_esp_two_arguments(self):
        module = self.eligible(LEAF.hex(), 2)
        self.assertEqual(module["id"], "fn_00401000")
        self.assertEqual(module["source_sha256"], hashlib.sha256(LEAF).hexdigest())
        self.assertEqual(module["observed_argument_slots"], [1, 2])

    def test_frame_locals_leave(self):
        # push ebp; mov ebp,esp; sub esp,4; save/reload arg; add arg2; leave; ret
        self.eligible("5589e583ec048b45088945fc8b45fc03450cc9c3", 2)

    def test_saved_register_push_pop_changes_argument_offset(self):
        self.eligible("538b4424080344240c5bc3", 2)
        self.eligible("5589e58b450889ec5dc3", 1)

    def test_sub_and_add_esp(self):
        self.eligible("83ec088b44240c0344241083c408c3", 2)

    def test_four_contiguous_uint32_arguments(self):
        self.eligible("8b442404034424080344240c03442410c3", 4)
        self.rejected("8b442414c3", "more_than_four_arguments")
        self.rejected("8b442408c3", "noncontiguous_argument_evidence")

    def test_branch_fixture_retains_contiguous_gap_and_both_returns(self):
        # mov eax,[esp+4]; test eax,eax; je second; inc eax; ret;
        # three bytes of skipped data; second: neg eax; ret
        code = "8b44240485c0740540c30f0bfff7d8c3"
        module = self.eligible(code, 1)
        self.assertEqual(module["code_hex"], code)
        self.assertEqual(len(module["return_addresses"]), 2)
        self.assertNotIn(TEXT + 10, [i["address"] for i in module["instructions"]])
        self.assertEqual(module["branches"][0]["target"], TEXT + 13)

    def test_diamond_merge_preserves_input_dependency(self):
        # cmp eax,0; je else; eax += 1; jmp join; else: eax -= 1; ret
        self.eligible("8b44240483f800740583c001eb0383e801c3", 1)

    def test_branch_control_dependency_and_constant_return(self):
        self.eligible("8b44240485c07406b801000000c3b802000000c3", 1)
        self.rejected("8b44240485c07406b801000000c3b801000000c3", "no_input_dependent_return")

    def test_branch_stack_mismatch_is_not_guessed(self):
        self.rejected("8b44240485c074015083c404c3", "uncertain_branch_stack")

    def test_global_and_pointer_access_rejected(self):
        self.rejected("a100204000c3", "global_or_pointer_memory")
        self.rejected("8b4424048b00c3", "global_or_pointer_memory")
        self.rejected("8b442404a300204000c3", "global_or_pointer_memory")
        self.rejected("8b442404648b0000000000c3")
        self.rejected("8b442404890424c3", "return_address_access")
        self.rejected("8b44240489442404c3", "argument_write")

    def test_call_indirect_and_system_are_not_candidates(self):
        call = self.rejected("8b442404e800000000c3", "contains_call")
        self.assertEqual(call["calls"][0]["target"], TEXT + 9)
        self.rejected("ff15a0204000c3", "contains_call")
        self.rejected("8b442404ffe0", "indirect_branch")
        self.rejected("8b442404cd80c3")

    def test_float_simd_and_partial_registers_rejected(self):
        self.rejected("8b442404d9e8c3", "floating_point_or_simd")
        self.rejected("8b4424040f57c0c3", "floating_point_or_simd")
        self.rejected("8a442404c3", "unsupported_register_width_or_simd")

    def test_constant_or_dead_input_not_main_sample(self):
        self.rejected("c3", "uninitialized_or_register_input")
        self.rejected("b82a000000c3", "no_stack_arguments")
        self.rejected("8b44240431c0c3", "no_input_dependent_return")
        self.rejected("8b44240429c0c3", "no_input_dependent_return")
        self.rejected("8b44240483e000c3", "no_input_dependent_return")
        self.rejected("8b442404b807000000c3", "no_input_dependent_return")

    def test_nonconstancy_witness_rejects_cancelled_and_dead_path_inputs(self):
        self.rejected("8b442404c1e01fc1e001c3", "input_dependence_not_demonstrated")
        self.rejected("8b44240489c1f7d121c8c3", "input_dependence_not_demonstrated")
        self.rejected("8b44240439c0740240c331c0c3", "input_dependence_not_demonstrated")
        self.rejected("31c08b4c24040fafc1c3", "no_input_dependent_return")
        module = self.eligible(LEAF.hex(), 2)
        first, second = module["input_dependency_witness"]
        self.assertNotEqual(first["return_value"], second["return_value"])
        for witness in (first, second):
            self.assertEqual(witness["return_value"], sum(witness["args"]) & 0xffffffff)

    def test_scalar_witness_signed_unsigned_overflow_and_parity_conditions(self):
        # cmp arg1,arg2; conditional return 2, otherwise return 1.
        conditions = {0x74: lambda a, b, r: a == b, 0x75: lambda a, b, r: a != b,
                      0x72: lambda a, b, r: a < b, 0x73: lambda a, b, r: a >= b,
                      0x76: lambda a, b, r: a <= b, 0x77: lambda a, b, r: a > b,
                      0x78: lambda a, b, r: bool(r & 0x80000000),
                      0x79: lambda a, b, r: not r & 0x80000000,
                      0x7a: lambda a, b, r: (r & 255).bit_count() % 2 == 0,
                      0x7b: lambda a, b, r: (r & 255).bit_count() % 2 != 0,
                      0x70: lambda a, b, r: bool((a ^ b) & (a ^ r) & 0x80000000),
                      0x71: lambda a, b, r: not ((a ^ b) & (a ^ r) & 0x80000000)}
        signed = lambda x: x if x < 0x80000000 else x - 0x100000000
        conditions.update({0x7c: lambda a, b, r: signed(a) < signed(b),
                           0x7d: lambda a, b, r: signed(a) >= signed(b),
                           0x7e: lambda a, b, r: signed(a) <= signed(b),
                           0x7f: lambda a, b, r: signed(a) > signed(b)})
        for opcode, expected in conditions.items():
            code = bytes.fromhex("8b4424043b442408") + bytes([opcode, 6]) + bytes.fromhex("b801000000c3b802000000c3")
            decoded = reverse._decode(code, TEXT, reverse._capstone(), [100])
            for a in (0, 1, 0x7fffffff, 0x80000000, 0xffffffff):
                for b in (0, 1, 0x7fffffff, 0x80000000, 0xffffffff):
                    actual = reverse._scalar_output(decoded, TEXT, [a, b])
                    self.assertEqual(actual, 2 if expected(a, b, (a - b) & 0xffffffff) else 1)

    def test_non_cdecl_uninitialized_and_unbalanced_stack(self):
        self.rejected("8b442404c20400", "not_plain_cdecl_return")
        self.rejected("8b44240401c8c3", "uninitialized_or_register_input")
        self.rejected("83ec048b442408c3", "unbalanced_stack_at_return")
        self.rejected("83ec048b04240344240883c404c3", "uninitialized_stack_read")
        self.rejected("8b5c240489d8c3", "callee_saved_register_not_restored")
        self.rejected("8b44240489e0c3", "stack_address_escape")

    def test_freed_local_is_not_initialized_when_reallocated(self):
        self.rejected("6a0183c40483ec048b04240344240883c404c3", "uninitialized_stack_read")

    def test_input_dependent_loop_and_implicit_flags_rejected(self):
        # do { eax--; } while (eax != 0): the trip count depends on the argument.
        self.rejected("8b4424044883f80075fac3", "unproven_loop_condition")
        self.rejected("8b442404740140c3", "unproven_branch_flags")
        self.rejected("8b44240440720140c3", "unproven_branch_flags")

    def test_fixed_trip_loop_is_eligible_with_iteration_evidence(self):
        # mov eax,[esp+4]; mov ecx,3; L: add eax,1; dec ecx; jnz L; ret
        module = self.eligible("8b442404b90300000083c0014975fac3", 1)
        self.assertEqual(module["loops"], [{"back_edge": TEXT + 13, "target": TEXT + 9,
                                            "iterations": 3}])
        for case in module["input_dependency_witness"]:
            self.assertEqual(case["return_value"], (case["args"][0] + 3) & 0xffffffff)

    def test_loop_carry_after_dec_and_unbounded_loop_rejected(self):
        # jb right after dec depends on the caller's incoming CF.
        self.rejected("8b4424044872fdc3", "unproven_branch_flags")
        # inc/jnz with no exit: unrolling stops at the iteration bound.
        self.rejected("31c04075fdc3", "loop_iteration_limit")

    def test_loop_with_global_access_is_still_rejected(self):
        # mov ecx,3; L: add eax,[0x402000]; dec ecx; jnz L
        self.rejected("b9030000000305202040004975f7c3", "global_or_pointer_memory")

    def test_ret_stops_discovery_and_truncated_instruction_rejected(self):
        module = self.eligible(LEAF.hex() + "0f", 2)
        self.assertEqual(module["code_hex"], LEAF.hex())
        bad = self.rejected("8b4424040f")
        self.assertIn("invalid_or_truncated_instruction", bad["boundary_errors"])
        bad = self.rejected("8b442404")
        self.assertIn("truncated_or_external_control_flow", bad["boundary_errors"])

    def test_jump_into_instruction_and_outside_span(self):
        bad = self.rejected("8b44240485c074ffb801000000c3")
        self.assertIn("overlapping_instructions", bad["boundary_errors"])
        self.rejected("8b442404eb7f")

    def test_instruction_and_address_limits(self):
        with patch.object(reverse, "MAX_FUNCTION_INSTRUCTIONS", 2):
            bad = self.rejected("8b442404404040c3")
            self.assertIn("function_instruction_limit", bad["boundary_errors"])
        with self.assertRaisesRegex(ValueError, "address_out_of_x86_range"):
            reverse.analyze_function(LEAF, 0xfffffffc)


@unittest.skipUnless(HAVE_CAPSTONE and HAVE_PEFILE, "PE analysis requires capstone and pefile")
class BinaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "synthetic.exe"
        self.output = self.root / "analysis"

    def analyze(self, data=None, **kwargs):
        self.source.write_bytes(synthetic_pe() if data is None else data)
        before = self.source.read_bytes()
        result = reverse.analyze_binary(self.source, self.output, **kwargs)
        self.assertEqual(before, self.source.read_bytes())
        self.assertEqual(result["source_sha256"], hashlib.sha256(before).hexdigest())
        return result

    def test_pe_metadata_artifacts_and_sha_binding(self):
        result = self.analyze()
        self.assertEqual(result["status"], "ok", result["blocked_reason"])
        self.assertTrue(result["not_full_game_analysis"])
        self.assertEqual(result["image_base"], BASE)
        self.assertEqual(result["entry_point"], TEXT)
        self.assertEqual(result["candidate_count"], 1)
        module = result["modules"][0]
        self.assertEqual(module["code_hex"], LEAF.hex())
        self.assertEqual(module["boundary_evidence"][0]["kind"], "entry_point")
        self.assertEqual(module["file_offset"], 0x200)
        saved = json.loads((self.output / "modules" / "fn_00401000.json").read_text(encoding="utf-8"))
        self.assertEqual(module, saved)
        self.assertEqual(saved["source_sha256"], result["source_sha256"])
        self.assertEqual(json.loads((self.output / "analysis.json").read_text(encoding="utf-8")), result)
        for ins in module["instructions"]:
            offset = ins["address"] - module["address"]
            raw = bytes.fromhex(ins["bytes"])
            self.assertEqual(bytes.fromhex(module["code_hex"])[offset:offset + len(raw)], raw)

    def test_declared_header_can_cover_raw_code_without_table_overlap(self):
        raw = bytearray(synthetic_pe())
        raw.extend(bytes(4096 - len(raw)))
        struct.pack_into("<I", raw, 0x98 + 60, 4096)
        result = self.analyze(bytes(raw))
        self.assertEqual(result["status"], "ok", result["blocked_reason"])
        self.assertEqual(result["candidate_count"], 1)
        self.assertIn("declared_headers_overlap_raw_section:.text", result["mapping_notes"])

    def test_linear_call_sweep_is_marked_heuristic(self):
        code = b"\xc3" + b"\xcc" * 15 + bytes.fromhex("e80b000000c3")
        code += b"\xcc" * (32 - len(code)) + LEAF
        result = self.analyze(synthetic_pe(code))
        module = next(m for m in result["modules"] if m["address"] == TEXT + 32)
        self.assertTrue(module["heuristic_seed"])
        self.assertTrue(module["eligibility"]["eligible"])
        self.assertTrue(result["not_full_game_analysis"])

    def test_direct_calls_discover_only_reachable_seed(self):
        # Caller -> offset 16. A third unreferenced function at offset 32 is NOT scanned.
        code = bytes.fromhex("e80b000000c3") + b"\xcc" * 10 + LEAF
        code += b"\xcc" * (32 - len(code)) + LEAF
        result = self.analyze(synthetic_pe(code))
        self.assertEqual([m["address"] for m in result["modules"]], [TEXT, TEXT + 16])
        self.assertEqual(result["candidates"], ["fn_00401010"])
        self.assertEqual(result["direct_call_graph"][0]["target"], TEXT + 16)
        self.assertEqual(result["statistics"]["exclusion_reasons"], {"contains_call": 1})

    @staticmethod
    def calling_code(target, source=TEXT + 5):
        # mov eax,[esp+4]; push eax; call target; add esp,4; ret
        return (bytes.fromhex("8b44240450") + b"\xe8"
                + struct.pack("<i", target - (source + 5)) + bytes.fromhex("83c404c3"))

    def test_direct_call_composition_proves_caller(self):
        caller = self.calling_code(TEXT + 0x20)
        code = caller + b"\xcc" * (0x20 - len(caller)) + LEAF_CALLED
        result = self.analyze(synthetic_pe(code))
        self.assertEqual(result["status"], "ok", result["blocked_reason"])
        module = next(m for m in result["modules"] if m["address"] == TEXT)
        self.assertEqual(module["eligibility"],
                         {"eligible": True, "reason": "proven_scalar_composition"})
        self.assertEqual(module["arg_count"], 1)
        self.assertEqual(module["observed_argument_slots"], [1])
        self.assertEqual([span["address"] for span in module["code_ranges"]], [TEXT, TEXT + 0x20])
        self.assertEqual(module["composition"]["callee_argument_slots"],
                         {f"fn_{TEXT + 0x20:08x}": [1]})
        self.assertEqual(module["input_dependency_witness"],
                         [{"args": [0], "return_value": 1}, {"args": [1], "return_value": 2}])
        self.assertEqual(result["composition"]["proven"], 1)
        self.assertEqual(result["candidates"], ["fn_00401000", "fn_00401020"])

    def test_composition_rejects_call_cycles(self):
        first = self.calling_code(TEXT + 0x20)
        second = self.calling_code(TEXT, source=TEXT + 0x25)
        code = first + b"\xcc" * (0x20 - len(first)) + second
        result = self.analyze(synthetic_pe(code))
        for module in result["modules"]:
            self.assertFalse(module["eligibility"]["eligible"], module)
            self.assertEqual(module["composition"]["reason"], "recursive_call_cycle")
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["composition"]["rejected"], {"recursive_call_cycle": 2})

    def test_composition_requires_an_independently_valid_callee(self):
        caller = self.calling_code(TEXT + 0x20)
        global_read = bytes.fromhex("a1" + struct.pack("<I", TEXT + 0x1000).hex() + "c3")
        code = caller + b"\xcc" * (0x20 - len(caller)) + global_read
        result = self.analyze(synthetic_pe(code))
        module = next(m for m in result["modules"] if m["address"] == TEXT)
        self.assertEqual(module["eligibility"]["reason"], "contains_call")
        self.assertEqual(module["composition"]["reason"], "callee_not_independently_validated")
        self.assertEqual(result["candidates"], [])

    def test_composition_limits_and_truncation_disable_upgrade(self):
        caller = self.calling_code(TEXT + 0x20)
        code = caller + b"\xcc" * (0x20 - len(caller)) + LEAF_CALLED
        with patch.object(reverse, "MAX_COMPOSED_FUNCTIONS", 1):
            result = self.analyze(synthetic_pe(code))
        module = next(m for m in result["modules"] if m["address"] == TEXT)
        self.assertEqual(module["eligibility"]["reason"], "contains_call")
        self.assertEqual(module["composition"]["reason"], "composition_function_limit")
        result = self.analyze(synthetic_pe(code), max_functions=1)
        self.assertTrue(result["discovery_truncated"])
        self.assertEqual(result["composition"], {"attempted": False, "proven": 0, "rejected": {},
                                                 "reason": "discovery_limit_reached"})

    def test_export_seed_without_entry_and_forwarder_skipped(self):
        rdata = bytearray(0x100)
        struct.pack_into("<IIHHIIIIIII", rdata, 0, 0, 0, 0, 0, 0x2080, 1, 2, 0,
                         0x2040, 0, 0)
        struct.pack_into("<II", rdata, 0x40, 0x1000, 0x2050)
        rdata[0x50:0x50 + 13] = b"other.export\0"
        rdata[0x80:0x80 + 9] = b"test.dll\0"
        result = self.analyze(synthetic_pe(entry=0, rdata=rdata, directories={0: (0x2000, 0x70)}))
        self.assertEqual(result["status"], "ok", result["blocked_reason"])
        self.assertEqual(len(result["modules"]), 1)
        self.assertEqual(result["modules"][0]["boundary_evidence"][0]["kind"], "export")
        self.assertEqual(result["exports"][1]["forwarder"], "other.export")

    def test_import_metadata_extracted_not_executed(self):
        rdata = bytearray(0x100)
        struct.pack_into("<IIIII", rdata, 0, 0x2040, 0, 0, 0x2060, 0x2050)
        struct.pack_into("<II", rdata, 0x40, 0x2080, 0)
        struct.pack_into("<II", rdata, 0x50, 0x2080, 0)
        rdata[0x60:0x60 + 13] = b"KERNEL32.dll\0"
        rdata[0x80:0x80 + 14] = b"\0\0ExitProcess\0"
        result = self.analyze(synthetic_pe(rdata=rdata, directories={1: (0x2000, 40)}))
        self.assertEqual(result["status"], "ok", result["blocked_reason"])
        self.assertEqual(result["imports"][0]["name"], "ExitProcess")
        self.assertEqual(result["imports"][0]["address"], BASE + 0x2050)

    def test_data_section_and_writable_code_never_trusted(self):
        blocked = self.analyze(synthetic_pe(flags=0x40000040))
        self.assertEqual(blocked["status"], "blocked")
        blocked = self.analyze(synthetic_pe(flags=0x60000040))
        self.assertEqual(blocked["candidate_count"], 0)
        result = self.analyze(synthetic_pe(flags=0xe0000020))
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["modules"][0]["eligibility"]["reason"], "untrusted_executable_section")

    def test_call_to_data_does_not_create_module(self):
        displacement = (BASE + 0x2000) - (TEXT + 5)
        code = b"\xe8" + struct.pack("<i", displacement) + b"\xc3"
        result = self.analyze(synthetic_pe(code, rdata=LEAF))
        self.assertEqual(len(result["modules"]), 1)
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["rejected_seeds"][0]["reason"], "not_file_backed_executable_code")

    def test_raw_truncation_and_virtual_padding_rejected(self):
        result = self.analyze(synthetic_pe()[:-1])
        self.assertEqual(result["status"], "blocked")
        self.assertIn("truncated", result["blocked_reason"])
        result = self.analyze(synthetic_pe(bytes.fromhex("8b4424040f")))
        self.assertEqual(result["candidate_count"], 0)
        self.assertIn("invalid_or_truncated_instruction", result["modules"][0]["boundary_errors"])
        result = self.analyze(synthetic_pe(entry=0x1000 + len(LEAF)))
        self.assertEqual(result["status"], "blocked")

    def test_function_limit_disables_candidates_when_discovery_incomplete(self):
        code = bytes.fromhex("e80b000000c3") + b"\xcc" * 10 + LEAF
        result = self.analyze(synthetic_pe(code), max_functions=1)
        self.assertEqual(len(result["modules"]), 1)
        self.assertTrue(result["discovery_truncated"])
        self.assertIn("function_count_limit", result["discovery_limits"])
        self.assertEqual(result["candidate_count"], 0)

    def test_total_instruction_budget_is_shared_and_candidates_disabled(self):
        with patch.object(reverse, "MAX_TOTAL_INSTRUCTIONS", 4):
            result = self.analyze()
        self.assertLessEqual(result["instructions_decoded"], 4)
        self.assertTrue(result["discovery_truncated"])
        self.assertEqual(result["candidate_count"], 0)

    def test_total_code_span_budget_is_enforced(self):
        with patch.object(reverse, "MAX_TOTAL_CODE_BYTES", 4):
            result = self.analyze()
        self.assertLessEqual(result["total_module_code_bytes"], 4)
        self.assertIn("total_function_bytes_limit", result["discovery_limits"])
        self.assertEqual(result["candidate_count"], 0)

    def test_invalid_alignment_is_not_silently_remapped(self):
        data = bytearray(synthetic_pe())
        struct.pack_into("<I", data, 0x178 + 20, 0x201)
        result = self.analyze(bytes(data))
        self.assertEqual(result["blocked_reason"], "invalid_section_alignment")

    def test_unsupported_formats_and_protected_signals_blocked(self):
        samples = [b"\x7fELF" + b"\0" * 60,
                   synthetic_pe(machine=0x8664), synthetic_pe(magic=0x20b),
                   synthetic_pe(name=b"UPX0"), b"MZ" + b"\0" * 10]
        for data in samples:
            with self.subTest(prefix=data[:4]):
                result = self.analyze(data)
                self.assertEqual(result["status"], "blocked")
                self.assertTrue(result["blocked_reason"])
                self.assertEqual(result["candidate_count"], 0)
                self.assertTrue((self.output / "analysis.json").exists())

    def test_late_call_target_inside_instruction_invalidates_boundary(self):
        result = self.analyze(synthetic_pe(bytes.fromhex("e802000000b801000000c3")))
        self.assertEqual(result["candidate_count"], 0)
        self.assertIn("seed_inside_instruction", result["modules"][0]["boundary_errors"])
        self.assertIn("overlapping_function_spans", result["modules"][0]["boundary_errors"])

    def test_high_entropy_and_section_count_limit(self):
        result = self.analyze(synthetic_pe(bytes(range(256)) * 16))
        self.assertIn("high_entropy", result["blocked_reason"])
        raw = bytearray(synthetic_pe())
        struct.pack_into("<H", raw, 0x86, reverse.MAX_SECTIONS + 1)
        result = self.analyze(bytes(raw))
        self.assertEqual(result["blocked_reason"], "section_count_limit_or_empty")

    def test_managed_image_and_overlapping_sections_blocked(self):
        result = self.analyze(synthetic_pe(rdata=b"\0" * 0x100, directories={14: (0x2000, 72)}))
        self.assertIn("managed", result["blocked_reason"])
        raw = bytearray(synthetic_pe(rdata=b"\0" * 0x100))
        struct.pack_into("<I", raw, 0x178 + 40 + 12, 0x1000)
        result = self.analyze(bytes(raw))
        self.assertEqual(result["blocked_reason"], "overlapping_section_mappings")

    def test_oversize_still_gets_full_digest_without_parsing(self):
        data = synthetic_pe()
        with patch.object(reverse, "MAX_INPUT_BYTES", 64):
            result = self.analyze(data)
        self.assertEqual(result["blocked_reason"], "input_exceeds_64_mib")
        self.assertEqual(result["source_size"], len(data))

    def test_input_cannot_be_overwritten_by_report_or_module(self):
        self.output.mkdir()
        source = self.output / "analysis.json"
        data = synthetic_pe()
        source.write_bytes(data)
        result = reverse.analyze_binary(source, self.output)
        self.assertEqual(result["blocked_reason"], "output_would_overwrite_input")
        self.assertEqual(source.read_bytes(), data)
        modules = self.output / "modules"
        modules.mkdir()
        source = modules / "fn_00401000.json"
        source.write_bytes(data)
        result = reverse.analyze_binary(source, self.output)
        self.assertEqual(result["blocked_reason"], "output_would_overwrite_input")
        self.assertEqual(source.read_bytes(), data)

    def test_invalid_max_functions_and_section_address_limit(self):
        for value in (0, -1, True, "2"):
            result = self.analyze(max_functions=value)
            self.assertEqual(result["blocked_reason"], "invalid_max_functions")
        data = bytearray(synthetic_pe())
        struct.pack_into("<I", data, 0x98 + 28, 0xfffff000)
        result = self.analyze(bytes(data))
        self.assertEqual(result["blocked_reason"], "image_address_or_size_limit")


class DependencyTests(unittest.TestCase):
    def test_importing_analyzer_does_not_require_optional_packages(self):
        self.assertTrue(callable(reverse.analyze_binary))

    def test_missing_dependency_is_an_explicit_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "test.exe"
            source.write_bytes(synthetic_pe())
            with patch.object(reverse, "_parse_pe", side_effect=ModuleNotFoundError("missing", name="pefile")):
                result = reverse.analyze_binary(source, root / "out")
            self.assertEqual(result["blocked_reason"], "missing_dependency:pefile")
            self.assertEqual(result["source_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertTrue((root / "out" / "analysis.json").exists())


if __name__ == "__main__":
    unittest.main()

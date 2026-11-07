"""Auditable scalar-only differential execution; no PE/DLL or generated native loading.

IR arithmetic is modulo 2**32, ``not`` is bitwise complement, shifts mask their
count by 31, and signed comparisons interpret two's-complement int32 values.
A pass is finite test evidence for one cdecl function, NOT a proof of equivalence
or a claim about a complete game. The caller supplies a trusted Zig executable.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import itertools
import json
import math
import os
from pathlib import Path
import random
import re
import signal
import struct
import subprocess
import sys
import time
from dataclasses import dataclass


U32_MAX = 0xFFFFFFFF
MAX_DEPTH = 32
MAX_NODES = 2048
MAX_IR_BYTES = 65536
MAX_LOCALS = 64
MAX_CODE_BYTES = 65536
MAX_ELF_BYTES = 8 * 1024 * 1024
MAX_LOAD_BYTES = 4 * 1024 * 1024
MAX_INSTRUCTIONS = 10000
CASE_TIMEOUT_SECONDS = 0.5
MIN_CASES = 128
SEED = 0x50464331
PAGE = 4096
STACK_BASE = 0x70000000
STACK_SIZE = 0x10000
ENTRY_SP = STACK_BASE + STACK_SIZE - 0x100 + 12
SENTINEL = 0x7FF00000
_BINARY = {
    "add": "+", "sub": "-", "mul": "*", "and": "&", "or": "|", "xor": "^",
    "eq": "==", "ne": "!=", "ult": "<", "ule": "<=", "ugt": ">", "uge": ">=",
    "slt": "<", "sle": "<=", "sgt": ">", "sge": ">=", "shl": "<<", "shr": ">>",
}
_UNARY = {"not", "neg"}
_LOCAL = re.compile(r"v(?:0|[1-9][0-9]{0,2})\Z")
_SHA = re.compile(r"[0-9a-fA-F]{64}\Z")


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("ascii")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _check_arg_count(arg_count: int) -> None:
    if type(arg_count) is not int or not 1 <= arg_count <= 4:
        raise ValueError("arg_count must be an integer in 1..4")


def validate_ir(ir: dict, arg_count: int) -> None:
    """Reject anything outside the bounded JSON IR. Raises ValueError on rejection."""
    _check_arg_count(arg_count)
    if type(ir) is not dict or set(ir) != {"locals", "body"}:
        raise ValueError("IR must contain exactly locals and body")
    locals_ = ir["locals"]
    if type(locals_) is not list or len(locals_) > MAX_LOCALS:
        raise ValueError("locals must be a bounded list")
    for name in locals_:
        if type(name) is not str or not _LOCAL.fullmatch(name):
            raise ValueError("local names must be v0..v999 (no reserved identifiers)")
    if len(set(locals_)) != len(locals_):
        raise ValueError("duplicate local")
    names = set(locals_) | {f"a{i}" for i in range(arg_count)}
    nodes = len(locals_) + 1

    def visit(depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if depth > MAX_DEPTH or nodes > MAX_NODES:
            raise ValueError("IR depth/node limit exceeded")

    def expr(value, depth: int) -> None:
        visit(depth)
        if type(value) is int:
            if not 0 <= value <= U32_MAX:
                raise ValueError("integer literal is not uint32")
        elif type(value) is str:
            if value not in names:
                raise ValueError("unknown variable or non-IR string")
        elif type(value) is dict and set(value) == {"op", "args"}:
            op, args = value["op"], value["args"]
            if type(op) is not str or op not in _BINARY.keys() | _UNARY:
                raise ValueError("unsupported operator")
            arity = 1 if op in _UNARY else 2
            if type(args) is not list or len(args) != arity:
                raise ValueError("invalid operator arity")
            for arg in args:
                expr(arg, depth + 1)
        else:
            raise ValueError("expression is not uint32, variable, or operator")

    def block(body, depth: int) -> bool:
        visit(depth)
        if type(body) is not list or len(body) > MAX_NODES:
            raise ValueError("body must be a bounded statement list")
        returns = False
        for statement in body:
            visit(depth + 1)
            if returns:
                raise ValueError("unreachable statement after unconditional return")
            if type(statement) is not dict:
                raise ValueError("statement must be an object")
            keys = set(statement)
            if keys == {"set", "value"}:
                name = statement["set"]
                if type(name) is not str or name not in locals_:
                    raise ValueError("assignment target must be a declared local")
                expr(statement["value"], depth + 2)
            elif keys == {"if", "then", "else"}:
                expr(statement["if"], depth + 2)
                yes = block(statement["then"], depth + 2)
                no = block(statement["else"], depth + 2)
                returns = yes and no
            elif keys == {"return"}:
                expr(statement["return"], depth + 2)
                returns = True
            else:
                raise ValueError("unsupported statement or extra keys")
        return returns

    if not block(ir["body"], 1):
        raise ValueError("every path must return")
    if len(_canonical(ir)) > MAX_IR_BYTES:
        raise ValueError("IR serialized size limit exceeded")


def render_c(ir: dict, arg_count: int) -> str:
    """Validate then render fixed C syntax; no model-supplied text is interpolated."""
    validate_ir(ir, arg_count)

    def expr(value) -> str:
        if type(value) is int:
            return f"{value}u"
        if type(value) is str:
            return value
        op = value["op"]
        args = [expr(arg) for arg in value["args"]]
        if op == "not":
            return f"((uint32_t)(~({args[0]})))"
        if op == "neg":
            return f"((uint32_t)(0u - ({args[0]})))"
        left, right = args
        if op in {"slt", "sle", "sgt", "sge"}:
            left, right = f"((int32_t)({left}))", f"((int32_t)({right}))"
        if op in {"shl", "shr"}:
            right = f"(({right}) & 31u)"
        return f"((uint32_t)(({left}) {_BINARY[op]} ({right})))"

    lines = [
        "/* Generated only from the validated uint32 scalar IR. */",
        "typedef unsigned int uint32_t;",
        "typedef signed int int32_t;",
        "typedef char pf_check_width[(sizeof(uint32_t) == 4) ? 1 : -1];",
        "__attribute__((cdecl, used))",
        "uint32_t pf_module(" + ", ".join(f"uint32_t a{i}" for i in range(arg_count)) + ")",
        "{",
    ]
    lines += [f"    uint32_t {name} = 0u;" for name in ir["locals"]]

    def block(body: list, indent: int) -> None:
        pad = "    " * indent
        for statement in body:
            if "set" in statement:
                lines.append(f"{pad}{statement['set']} = {expr(statement['value'])};")
            elif "return" in statement:
                lines.append(f"{pad}return {expr(statement['return'])};")
            else:
                lines.append(f"{pad}if ({expr(statement['if'])}) {{")
                block(statement["then"], indent + 1)
                lines.append(f"{pad}}} else {{")
                block(statement["else"], indent + 1)
                lines.append(f"{pad}}}")

    block(ir["body"], 1)
    return "\n".join(lines + ["}", ""])


class _Blocked(Exception):
    pass


class _WindowsJob:
    """Own one suspended child and its descendants, never a system-wide kill."""

    def __init__(self):
        import ctypes as ct
        from ctypes import wintypes as wt

        class Basic(ct.Structure):
            _fields_ = [("ProcessTime", ct.c_int64), ("JobTime", ct.c_int64),
                        ("Flags", wt.DWORD), ("MinWS", ct.c_size_t),
                        ("MaxWS", ct.c_size_t), ("Active", wt.DWORD),
                        ("Affinity", ct.c_size_t), ("Priority", wt.DWORD),
                        ("Scheduling", wt.DWORD)]

        class Extended(ct.Structure):
            _fields_ = [("Basic", Basic), ("IO", ct.c_uint64 * 6),
                        ("ProcessMemory", ct.c_size_t), ("JobMemory", ct.c_size_t),
                        ("PeakProcess", ct.c_size_t), ("PeakJob", ct.c_size_t)]

        self.ct = ct
        self.kernel = ct.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ct.c_void_p, wt.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wt.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wt.HANDLE, ct.c_int, ct.c_void_p, wt.DWORD]
        self.kernel.SetInformationJobObject.restype = wt.BOOL
        self.kernel.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
        self.kernel.AssignProcessToJobObject.restype = wt.BOOL
        self.kernel.CloseHandle.argtypes = [wt.HANDLE]
        self.kernel.CloseHandle.restype = wt.BOOL
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ct.get_last_error(), "CreateJobObjectW failed")
        limits = Extended()
        limits.Basic.Flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ct.byref(limits), ct.sizeof(limits)):
            self.close()
            raise OSError(ct.get_last_error(), "SetInformationJobObject failed")

    def attach_and_resume(self, process: subprocess.Popen) -> None:
        from ctypes import wintypes as wt
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise OSError(self.ct.get_last_error(), "Cannot safely contain compiler process")
        ntdll = self.ct.WinDLL("ntdll")
        ntdll.NtResumeProcess.argtypes = [wt.HANDLE]
        ntdll.NtResumeProcess.restype = self.ct.c_long
        if ntdll.NtResumeProcess(int(process._handle)) < 0:
            raise OSError("Cannot resume contained compiler process")

    def close(self) -> None:
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def _run_process(command: list[str], log: Path, cwd: Path,
                 env: dict[str, str], timeout: float) -> int:
    """Trusted tool only: bounded wait, disk logs, and scoped process-tree cleanup."""
    job = _WindowsJob() if os.name == "nt" else None
    process = None
    try:
        with log.open("wb") as stream:
            options = ({"creationflags": 0x00000004 | 0x08000000} if job else
                       {"start_new_session": True})  # CREATE_SUSPENDED | CREATE_NO_WINDOW
            process = subprocess.Popen(command, cwd=str(cwd), env=env, shell=False,
                                       stdin=subprocess.DEVNULL, stdout=stream,
                                       stderr=subprocess.STDOUT, **options)
            if job:
                job.attach_and_resume(process)
            return process.wait(timeout=max(0.001, timeout))
    finally:
        if job:
            job.close()  # Also closes descendant processes after a normal compiler exit.
        elif process and process.returncode is None:
            # A not-yet-reaped group leader pins its PID. Never target the group
            # of an already-reaped successful process (its PID could be reused).
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process and process.poll() is None:
            # Covers failure to assign the still-suspended Windows child to its job.
            process.kill()
            process.wait(timeout=10)


def _compiler_environment(output: Path) -> dict[str, str]:
    env = dict(os.environ)
    for key in ("CC", "CXX", "CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS",
                "CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH", "LIBRARY_PATH"):
        env.pop(key, None)
    paths = {"ZIG_LOCAL_CACHE_DIR": "zig-local-cache", "ZIG_GLOBAL_CACHE_DIR": "zig-global-cache",
             "TMP": "tmp", "TEMP": "tmp", "TMPDIR": "tmp", "XDG_CACHE_HOME": "cache",
             "HOME": "home", "USERPROFILE": "home"}
    for key, directory in paths.items():
        path = output / directory
        path.mkdir(exist_ok=True)
        env[key] = str(path)
    return env


def _compile(source: Path, elf: Path, compiler: Path, output: Path,
             deadline: float, report: dict) -> None:
    if not compiler.is_file() or compiler.name.lower() not in {"zig", "zig.exe"}:
        raise _Blocked("compiler must be a trusted, existing Zig executable path")
    env = _compiler_environment(output)
    version_log = output / "compiler-version.log"
    code = _run_process([str(compiler), "version"], version_log, output, env,
                        min(10, deadline - time.monotonic()))
    with version_log.open("rb") as stream:
        version = stream.read(4096).decode("utf-8", errors="replace").strip()
    report["tool_versions"]["compiler"] = version
    if code or not version:
        raise _Blocked("compiler version probe failed; see compiler-version.log")
    command = [str(compiler), "cc", "-target", "x86-linux-musl", "-march=i386",
               "-ffreestanding", "-fno-builtin", "-nostdlib", "-static", "-fno-pie", "-no-pie",
               "-fno-stack-protector", "-fno-unwind-tables", "-fno-asynchronous-unwind-tables",
               "-mno-sse", "-mno-sse2", "-msoft-float", "-O2",
               "-Wl,-e,pf_module", "-Wl,--build-id=none", "-Wl,-z,noexecstack",
               str(source), "-o", str(elf)]
    report["compile_command"] = command
    if deadline <= time.monotonic():
        raise _Blocked("overall timeout before compilation")
    code = _run_process(command, output / "compile.log", output, env,
                        deadline - time.monotonic())
    report["compile_returncode"] = code
    if code != 0 or not elf.is_file():
        raise _Blocked("compilation failed or produced no ELF; see compile.log")


@dataclass
class _Image:
    entry: int
    code: bytes
    # Each PT_LOAD (or the original RX blob): vaddr, file bytes, memory size, ELF PF flags.
    segments: list[tuple[int, bytes, int, int]]
    instructions: dict


def _decode(code: bytes, entry: int) -> dict:
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
    decoder = Cs(CS_ARCH_X86, CS_MODE_32)
    decoder.detail = True
    result = {}
    cursor = entry
    for insn in decoder.disasm(code, entry):
        if insn.address != cursor:
            raise _Blocked("non-contiguous instruction decoding")
        result[insn.address] = insn
        cursor += insn.size
    if cursor != entry + len(code) or not result:
        raise _Blocked("function bytes cannot be completely decoded as x86-32")
    return result


def _check_segments(segments: list[tuple[int, bytes, int, int]]) -> None:
    mapped = []
    total = 0
    for address, data, size, flags in segments:
        if (size <= 0 or len(data) > size or address < PAGE or address + size > 2**32
                or not flags & 4 or flags & ~7 or flags & 3 == 3):
            raise _Blocked("invalid segment, unreadable memory, or writable executable memory")
        lo, hi = address & -PAGE, (address + size + PAGE - 1) & -PAGE
        total += hi - lo
        if total > MAX_LOAD_BYTES:
            raise _Blocked("ELF mapping size limit exceeded")
        for left, right in mapped + [(STACK_BASE, STACK_BASE + STACK_SIZE), (SENTINEL, SENTINEL + PAGE)]:
            if lo < right and left < hi:
                raise _Blocked("overlapping or reserved segment mapping")
        mapped.append((lo, hi))


MAX_RANGES = 8


def _original_ranges(module: dict) -> list[dict]:
    """Validated root span plus any proven callee spans from the same snapshot.

    Callers proven by inline composition carry contiguous byte ranges for every
    function in their bounded call closure. Bytes are supplied evidence; they are
    never read from a PE/DLL here and are re-hashed by the caller before use.
    """
    address, hex_code = module.get("address"), module.get("code_hex")
    if type(address) is not int or not PAGE <= address <= U32_MAX:
        raise _Blocked("original address must be an i386 address above the null page")
    if (type(hex_code) is not str or not 0 < len(hex_code) <= 2 * MAX_CODE_BYTES
            or len(hex_code) % 2 or not re.fullmatch(r"[0-9a-fA-F]+", hex_code)):
        raise _Blocked("code_hex must be bounded contiguous original x86 bytes")
    root = {"address": address, "data": bytes.fromhex(hex_code)}
    ranges = module.get("code_ranges")
    if ranges is None:
        return [root]
    if type(ranges) is not list or not 1 <= len(ranges) <= MAX_RANGES:
        raise _Blocked("code_ranges must be a bounded nonempty list")
    spans = []
    total = 0
    for item in ranges:
        if type(item) is not dict:
            raise _Blocked("code_ranges entries must be objects")
        start, size, data_hex, data_sha = (item.get("address"), item.get("size"),
                                           item.get("code_hex"), item.get("code_sha256"))
        if (type(start) is not int or not PAGE <= start < 2**32 or type(size) is not int
                or not 0 < size <= MAX_CODE_BYTES or type(data_hex) is not str
                or len(data_hex) != 2 * size or not re.fullmatch(r"[0-9a-fA-F]+", data_hex)):
            raise _Blocked("invalid code range address, size, or bytes")
        data = bytes.fromhex(data_hex)
        if type(data_sha) is not str or not _SHA.fullmatch(data_sha) or _sha(data) != data_sha.lower():
            raise _Blocked("code range digest does not match its bytes")
        total += size
        if total > MAX_CODE_BYTES:
            raise _Blocked("total code range bytes limit exceeded")
        spans.append({"address": start, "data": data})
    if not any(span["address"] == address and span["data"] == root["data"] for span in spans):
        raise _Blocked("code_ranges must contain the module's own byte range")
    ordered = sorted((span["address"], span["address"] + len(span["data"])) for span in spans)
    if any(left[1] > right[0] for left, right in zip(ordered, ordered[1:])):
        raise _Blocked("overlapping code ranges")
    return spans


def _original_image(address: int, spans: list[dict]) -> _Image:
    """Page-merge disjoint spans; gap bytes are zero-filled and never executed."""
    intervals = sorted(((span["address"] & -PAGE,
                         (span["address"] + len(span["data"]) + PAGE - 1) & -PAGE)
                        for span in spans))
    merged = []
    for lo, hi in intervals:
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    segments = []
    for lo, hi in merged:
        data = bytearray(hi - lo)
        for span in spans:
            start = span["address"] - lo
            if 0 <= start and start + len(span["data"]) <= len(data):
                data[start:start + len(span["data"])] = span["data"]
        segments.append((lo, bytes(data), hi - lo, 5))
    _check_segments(segments)
    instructions = {}
    for span in spans:
        decoded = _decode(span["data"], span["address"])
        if instructions.keys() & decoded.keys():
            raise _Blocked("overlapping instruction addresses across code ranges")
        instructions.update(decoded)
    root = next(span["data"] for span in spans if span["address"] == address)
    return _Image(address, root, segments, instructions)


def _load_elf(path: Path) -> _Image:
    from elftools.elf.elffile import ELFFile
    if not 0 < path.stat().st_size <= MAX_ELF_BYTES:
        raise _Blocked("ELF file size limit exceeded")
    with path.open("rb") as stream:
        elf = ELFFile(stream)
        if (elf.elfclass != 32 or not elf.little_endian or elf["e_machine"] != "EM_386"
                or elf["e_type"] != "ET_EXEC"):
            raise _Blocked("expected a static little-endian i386 ET_EXEC ELF")
        segments = []
        for segment in elf.iter_segments():
            kind = segment["p_type"]
            if kind in {"PT_INTERP", "PT_DYNAMIC"}:
                raise _Blocked("dynamic ELF is forbidden")
            if kind == "PT_GNU_STACK" and segment["p_flags"] & 1:
                raise _Blocked("executable stack is forbidden")
            if kind == "PT_LOAD" and segment["p_memsz"]:
                if segment["p_filesz"] > MAX_ELF_BYTES or segment["p_memsz"] > MAX_LOAD_BYTES:
                    raise _Blocked("ELF segment size limit exceeded")
                data = segment.data()
                if len(data) != segment["p_filesz"]:
                    raise _Blocked("truncated ELF segment")
                segments.append((segment["p_vaddr"], data, segment["p_memsz"], segment["p_flags"]))
        _check_segments(segments)
        symtab = elf.get_section_by_name(".symtab")
        symbols = symtab.get_symbol_by_name("pf_module") if symtab else None
        if not symbols or len(symbols) != 1:
            raise _Blocked("ELF must define exactly one pf_module symbol")
        symbol = symbols[0]
        entry, size = symbol["st_value"], symbol["st_size"]
        if (symbol["st_info"]["type"] != "STT_FUNC" or symbol["st_shndx"] == "SHN_UNDEF"
                or entry != elf["e_entry"] or not 0 < size <= MAX_CODE_BYTES):
            raise _Blocked("invalid pf_module entry or size")
        for address, data, _, flags in segments:
            if flags & 1 and address <= entry and entry + size <= address + len(data):
                code = data[entry - address:entry - address + size]
                return _Image(entry, code, segments, _decode(code, entry))
        raise _Blocked("pf_module is outside executable file bytes")


_JUMPS = {"jmp", "je", "jne", "ja", "jae", "jb", "jbe", "jg", "jge", "jl", "jle",
          "js", "jns", "jo", "jno", "jp", "jnp", "jecxz"}
_CONDITIONS = {"e", "ne", "a", "ae", "b", "be", "g", "ge", "l", "le", "s", "ns", "o", "no", "p", "np"}
_ALLOWED = {"mov", "movzx", "movsx", "lea", "add", "sub", "imul", "mul", "and", "or", "xor",
            "not", "neg", "shl", "shr", "sar", "sal", "cmp", "test", "inc", "dec", "adc", "sbb",
            "push", "pop", "leave", "ret", "nop", "bswap", "rol", "ror", "cdq", "cwde", "call"}
_ALLOWED |= _JUMPS | {"set" + c for c in _CONDITIONS} | {"cmov" + c for c in _CONDITIONS}
_REG_NAMES = {"eax", "ebx", "ecx", "edx", "esi", "edi", "ebp", "esp", "ax", "bx", "cx", "dx",
              "si", "di", "bp", "sp", "al", "ah", "bl", "bh", "cl", "ch", "dl", "dh"}


def _execute(image: _Image, args: list[int], state_seed: int,
             time_limit: float = CASE_TIMEOUT_SECONDS) -> dict:
    """A new engine per invocation; all data accesses must stay in its live stack.

    Caller argument slots are read-only, and stack locals must have been written
    before being read. Internal direct calls/jumps are allowed; indirect transfers,
    segment overrides, privileged instructions, and accesses to code/data are not.
    """
    import unicorn as uc
    from unicorn import x86_const as xr
    from capstone import x86_const as xc

    engine = uc.Uc(uc.UC_ARCH_X86, uc.UC_MODE_32)
    error = None
    count = 0
    last = None
    hooks = []
    current_sp = ENTRY_SP
    start = 0.0
    regs = {name: getattr(xr, "UC_X86_REG_" + name.upper())
            for name in ("eax", "ebx", "ecx", "edx", "esi", "edi", "ebp", "esp")}
    rng = random.Random(state_seed)
    initial = {name: rng.getrandbits(32) for name in regs if name != "esp"}
    written = bytearray(STACK_SIZE)
    arg_end = ENTRY_SP + 4 + 4 * len(args)
    written[ENTRY_SP - STACK_BASE:arg_end - STACK_BASE] = b"\x01" * (arg_end - ENTRY_SP)

    def stop(message: str) -> None:
        nonlocal error
        if error is None:
            error = message
        engine.emu_stop()

    def on_code(_engine, address, size, _user):
        nonlocal count, last, current_sp
        count += 1
        if count > MAX_INSTRUCTIONS or time.monotonic() - start > time_limit:
            stop("instruction/time limit exceeded")
            return
        insn = image.instructions.get(address)
        if insn is None or insn.size != size:
            stop("execution outside instruction boundaries")
            return
        last = insn
        current_sp = engine.reg_read(regs["esp"])
        if not STACK_BASE <= current_sp <= ENTRY_SP:
            stop("stack pointer outside active cdecl frame")
            return
        if insn.mnemonic not in _ALLOWED or any(p not in (0, 0x66, 0x67) for p in insn.prefix):
            stop("forbidden instruction: " + insn.mnemonic)
            return
        for operand in insn.operands:
            if operand.type == xc.X86_OP_REG and insn.reg_name(operand.reg) not in _REG_NAMES:
                stop("non-scalar register access")
                return
            if operand.type == xc.X86_OP_MEM and operand.mem.segment:
                stop("segment override is forbidden")
                return
        if insn.mnemonic in _JUMPS | {"call"}:
            operands = insn.operands
            if (len(operands) != 1 or operands[0].type != xc.X86_OP_IMM
                    or operands[0].imm not in image.instructions):
                stop("indirect or out-of-function branch")
                return
        if insn.mnemonic == "ret":
            if insn.bytes != b"\xc3":
                stop("cdecl requires an unprefixed ret without stack cleanup")
                return
            target = struct.unpack("<I", engine.mem_read(current_sp, 4))[0]
            if target != SENTINEL and target not in image.instructions:
                stop("return outside function/sentinel")
        if insn.mnemonic in {"push", "pop"} and insn.operands[0].size != 4:
            stop("only 32-bit stack operations are allowed")

    def on_memory(_engine, access, address, size, value, _user):
        lower = current_sp
        if last and last.mnemonic in {"push", "call"}:
            lower -= 4
        # leave reads the old EBP frame slot, above current ESP.
        if size <= 0 or address < max(STACK_BASE, lower) or address + size > arg_end:
            stop("extra/out-of-frame memory access")
            return
        lo, hi = address - STACK_BASE, address + size - STACK_BASE
        if access == uc.UC_MEM_WRITE:
            if address + size > ENTRY_SP:
                stop("write to caller arguments/return address")
                return
            written[lo:hi] = b"\x01" * size
        elif not all(written[lo:hi]):
            stop("uninitialized stack read")

    def on_invalid(_engine, access, address, size, value, _user):
        stop(f"unmapped/protected memory access at 0x{address:08x}")
        return False

    def on_interrupt(_engine, number, _user):
        stop(f"interrupt/system call {number} is forbidden")

    try:
        for address, data, size, flags in image.segments:
            base = address & -PAGE
            length = ((address + size + PAGE - 1) & -PAGE) - base
            permissions = ((uc.UC_PROT_READ if flags & 4 else 0)
                           | (uc.UC_PROT_WRITE if flags & 2 else 0)
                           | (uc.UC_PROT_EXEC if flags & 1 else 0))
            engine.mem_map(base, length, permissions)
            engine.mem_write(address, data)
        engine.mem_map(STACK_BASE, STACK_SIZE, uc.UC_PROT_READ | uc.UC_PROT_WRITE)
        engine.mem_map(SENTINEL, PAGE, uc.UC_PROT_READ | uc.UC_PROT_EXEC)
        engine.mem_write(SENTINEL, b"\x0f\x0b")  # Never executed: emu_start's end address.
        engine.mem_write(ENTRY_SP, struct.pack("<" + "I" * (len(args) + 1), SENTINEL, *args))
        for name, value in initial.items():
            engine.reg_write(regs[name], value)
        engine.reg_write(regs["esp"], ENTRY_SP)
        # Random arithmetic flags, but IF=1 and DF=0 as required by the ABI.
        engine.reg_write(xr.UC_X86_REG_EFLAGS, 0x202 | (rng.getrandbits(32) & 0x8D5))
        hooks.append(engine.hook_add(uc.UC_HOOK_CODE, on_code))
        hooks.append(engine.hook_add(uc.UC_HOOK_MEM_READ | uc.UC_HOOK_MEM_WRITE, on_memory))
        hooks.append(engine.hook_add(uc.UC_HOOK_MEM_INVALID, on_invalid))
        hooks.append(engine.hook_add(uc.UC_HOOK_INTR, on_interrupt))
        # The per-call deadline bounds guest execution only; engine construction
        # and page mapping above must not count against a 50 ms case budget.
        start = time.monotonic()
        engine.emu_start(image.entry, SENTINEL, timeout=max(1, int(time_limit * 1_000_000)),
                         count=MAX_INSTRUCTIONS)
        if error is None:
            if engine.reg_read(xr.UC_X86_REG_EIP) != SENTINEL or not last or last.mnemonic != "ret":
                error = "did not return to sentinel (instruction/time limit or invalid exit)"
            elif engine.reg_read(regs["esp"]) != ENTRY_SP + 4:
                error = "cdecl stack restoration failed"
            elif any(engine.reg_read(regs[name]) != initial[name] for name in ("ebx", "esi", "edi", "ebp")):
                error = "callee-saved register corruption"
            elif engine.reg_read(xr.UC_X86_REG_EFLAGS) & 0x400:
                error = "direction flag is not clear on return"
        value = engine.reg_read(regs["eax"]) & U32_MAX
        return {"status": "fail" if error else "pass", "value": value,
                "error": error, "instructions": count, "state_seed": state_seed}
    except uc.UcError as exc:
        return {"status": "fail", "value": None, "error": error or str(exc),
                "instructions": count, "state_seed": state_seed}
    finally:
        # Explicitly release callback references (callbacks close over engine).
        for handle in hooks:
            engine.hook_del(handle)


def _cases(arg_count: int, random_cases: int) -> list[list[int]]:
    edges = (0, 1, U32_MAX, 0x7FFFFFFF, 0x80000000)
    cases = []
    seen = set()

    def add(values):
        key = tuple(values)
        if key not in seen:
            seen.add(key)
            cases.append(list(key))

    for edge in edges:
        add([edge] * arg_count)
    for index in range(arg_count):
        for edge in edges:
            values = [0] * arg_count
            values[index] = edge
            add(values)
    for left, right in itertools.combinations(range(arg_count), 2):
        for a, b in itertools.product(edges, repeat=2):
            values = [0] * arg_count
            values[left], values[right] = a, b
            add(values)
    rng = random.Random(SEED)
    for _ in range(random_cases):
        cases.append([rng.getrandbits(32) for _ in range(arg_count)])
    while len(cases) < MIN_CASES:
        cases.append([rng.getrandbits(32) for _ in range(arg_count)])
    return cases


def compare_module(module: dict, ir: dict, output_dir: Path, compiler: Path,
                   random_cases: int = 128, timeout: float = 120) -> dict:
    """Compile restricted IR with Zig, compare independent Unicorn engines, audit.

    pass: every case and both ABIs passed (at least MIN_CASES).
    fail: a return-value, ABI, instruction, or memory violation was observed.
    blocked: invalid inputs, missing tooling, failed compilation, or incomplete run.
    Infrastructure failures never turn into passes. All tool products/caches are
    beneath output_dir; existing named artifacts there are replaced for this run.
    """
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    compiler = Path(compiler).resolve()
    report = {
        "status": "blocked", "reason": None, "scope": "scalar_function_only",
        "claim": "Finite scalar test evidence only; not full-game validation or an equivalence proof.",
        "module_id": None, "composition": None, "original_code_sha256": None, "ir_sha256": None,
        "source_sha256": None, "generated_source_sha256": None, "rewritten_code_sha256": None,
        "rewritten_elf_sha256": None, "compiler": str(compiler), "tool_versions": {"python": sys.version.split()[0]},
        "seed": SEED, "minimum_cases": MIN_CASES,
        "limits": {"instructions_per_call": MAX_INSTRUCTIONS, "seconds_per_call": CASE_TIMEOUT_SECONDS,
                   "ast_depth": MAX_DEPTH, "ast_nodes": MAX_NODES, "ir_bytes": MAX_IR_BYTES},
        "passed": 0, "failed": 0, "not_run": 0, "total": 0,
        "cases": [], "counterexamples": [],
        "artifacts": {name: str(output / name) for name in
                      ("source.c", "rewritten.elf", "comparison.json", "compile.log", "compiler-version.log")},
    }
    try:
        for name in ("source.c", "rewritten.elf", "comparison.json", "compile.log", "compiler-version.log"):
            (output / name).unlink(missing_ok=True)
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
            raise _Blocked("timeout must be finite and in (0, 3600]")
        deadline = time.monotonic() + timeout
        if type(random_cases) is not int or not 0 <= random_cases <= 4096:
            raise _Blocked("random_cases must be an integer in 0..4096")
        if type(module) is not dict:
            raise _Blocked("module must be a dictionary")
        arg_count = module.get("arg_count")
        _check_arg_count(arg_count)
        report["arg_count"] = arg_count
        report["requested_random_cases"] = random_cases
        vectors = _cases(arg_count, random_cases)
        report["cases"] = [{"index": i, "args": args, "expected": None, "actual": None,
                            "status": "not_run", "reason": "not executed"} for i, args in enumerate(vectors)]
        module_id, snapshot = module.get("id"), module.get("source_sha256")
        if type(module_id) is not str or not 0 < len(module_id) <= 256:
            raise _Blocked("module id must be a bounded nonempty string")
        report["module_id"] = module_id
        if type(snapshot) is not str or not _SHA.fullmatch(snapshot):
            raise _Blocked("source_sha256 must identify the original snapshot")
        report["source_sha256"] = snapshot.lower()
        spans = _original_ranges(module)
        address = module["address"]
        original_bytes = next(span["data"] for span in spans if span["address"] == address)
        report["original_code_sha256"] = _sha(original_bytes)
        report["address"] = address
        report["original_ranges"] = [{"address": span["address"], "size": len(span["data"]),
                                      "code_sha256": _sha(span["data"])} for span in spans]
        eligibility = module.get("eligibility")
        if (type(eligibility) is not dict or type(eligibility.get("eligible")) is not bool
                or type(eligibility.get("reason")) is not str or len(eligibility["reason"]) > 4096):
            raise _Blocked("eligibility must contain a boolean eligible and bounded reason")
        report["eligibility"] = {"eligible": eligibility["eligible"], "reason": eligibility["reason"]}
        report["composition"] = module.get("composition")
        if not eligibility["eligible"]:
            raise _Blocked("original module ineligible: " + eligibility["reason"])
        source = render_c(ir, arg_count)
        report["ir_sha256"] = _sha(_canonical(ir))
        source_path, elf_path = output / "source.c", output / "rewritten.elf"
        source_path.write_text(source, encoding="utf-8", newline="\n")
        report["generated_source_sha256"] = _sha(source.encode("utf-8"))
        for package in ("unicorn", "capstone", "pyelftools"):
            report["tool_versions"][package] = importlib.metadata.version(package)
        original = _original_image(address, spans)
        _compile(source_path, elf_path, compiler, output, deadline, report)
        rewritten = _load_elf(elf_path)
        report["rewritten_code_sha256"] = _sha(rewritten.code)
        report["rewritten_elf_sha256"] = _sha(elf_path.read_bytes())
        for case in report["cases"]:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                report["reason"] = "overall comparison timeout; remaining cases not run"
                break
            state_seed = SEED + case["index"]
            expected = _execute(original, case["args"], state_seed, min(CASE_TIMEOUT_SECONDS, remaining))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                case["original_execution"] = expected
                case["expected"] = expected["value"]
                report["reason"] = "overall comparison timeout before rewritten execution"
                break
            actual = _execute(rewritten, case["args"], state_seed, min(CASE_TIMEOUT_SECONDS, remaining))
            passed = expected["status"] == actual["status"] == "pass" and expected["value"] == actual["value"]
            case.update({"expected": expected["value"], "actual": actual["value"],
                         "status": "pass" if passed else "fail", "original_execution": expected,
                         "rewritten_execution": actual,
                         "reason": None if passed else (expected["error"] or actual["error"] or "return value mismatch")})
        if not report["reason"]:
            report["reason"] = "comparison completed"
    except (ValueError, TypeError, OSError, ImportError, _Blocked, subprocess.SubprocessError) as exc:
        report["reason"] = f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        # Parser/emulator failures are auditable infrastructure blocks, not silent successes.
        report["reason"] = f"infrastructure error ({type(exc).__name__}): {exc}"
    for case in report["cases"]:
        case["original_code_sha256"] = report["original_code_sha256"]
        case["rewritten_code_sha256"] = report["rewritten_code_sha256"]
        case["rewritten_elf_sha256"] = report["rewritten_elf_sha256"]
        case["tool_versions"] = report["tool_versions"]
        if case["status"] == "not_run":
            case["reason"] = report["reason"]
    report["total"] = len(report["cases"])
    report["passed"] = sum(case["status"] == "pass" for case in report["cases"])
    report["failed"] = sum(case["status"] == "fail" for case in report["cases"])
    report["not_run"] = sum(case["status"] == "not_run" for case in report["cases"])
    report["counts"] = {key: report[key] for key in ("passed", "failed", "not_run", "total")}
    report["counterexamples"] = [case for case in report["cases"] if case["status"] == "fail"][:32]
    if report["failed"]:
        report["status"] = "fail"
    elif report["passed"] >= MIN_CASES and not report["not_run"]:
        report["status"] = "pass"
    report["limitations"] = ["Only supplied contiguous original byte ranges are executed, never the original PE/DLL.",
                             "Only initialized live-stack data reads and local stack writes are permitted.",
                             "Snapshot hash is supplied provenance, not independently reverified from a commercial file.",
                             "No graphics, audio, filesystem, networking, device, or full-game claims."]
    (output / "comparison.json").write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    return report

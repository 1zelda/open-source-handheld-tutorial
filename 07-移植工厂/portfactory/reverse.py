"""Read-only, bounded PE32/x86 function discovery, not a whole-game decompiler.

Only entry/export/direct-call seeds are used. No loader, unpacker, emulator or
original executable is run here. Eligibility is deliberately narrower than x86:
scalar, cdecl-compatible leaves with proven stack-relative inputs and either no
back edges or loops that unroll to a fixed trip count (every conditional branch
decidable from constants alone), plus bounded callers whose direct callees are
each proven leaves/compositions (the callee is summarized atomically, never
re-interpreted as the caller's own frame). Loops whose continuation depends on
an argument, memory or an unknown flag are rejected, never approximated.
``arg_count`` is the observed contiguous input prefix, NOT debug-signature
recovery (unused trailing parameters cannot be inferred from machine code).
"""
from __future__ import annotations

import hashlib
import heapq
import json
import math
import os
import stat
import struct
import tempfile
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path

MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_SECTIONS = 96
MAX_IMAGE_BYTES = 512 * 1024 * 1024
MAX_EXECUTABLE_BYTES = 32 * 1024 * 1024
MAX_FUNCTIONS = 12000
MAX_FUNCTION_BYTES = 16384
MAX_FUNCTION_INSTRUCTIONS = 2048
MAX_TOTAL_INSTRUCTIONS = 1000000
MAX_SWEEP_INSTRUCTIONS = 500000
MAX_TOTAL_CODE_BYTES = 32 * 1024 * 1024  # sum of spans, including branch-skipped gaps
MAX_COMPOSED_FUNCTIONS = 6
MAX_COMPOSED_INSTRUCTIONS = 160
MAX_COMPOSED_BYTES = 8192
MAX_CONCRETE_STEPS = 4096
MAX_LOOP_ITERATIONS = 64
MAX_BLOCK_VISITS = 512
MAX_ABSTRACT_STEPS = 16384
MAX_STACK_BYTES = 4096
MAX_IMPORTS = 8192
MAX_IMPORT_DLLS = 256
MAX_DIRECTORY_BYTES = 1024 * 1024
ADDRESS_END = 1 << 32

_REGS = frozenset({"eax", "ebx", "ecx", "edx", "esi", "edi", "ebp", "esp"})
_SAVED = ("ebx", "esi", "edi", "ebp")
_JCC = frozenset({"je", "jne", "ja", "jae", "jb", "jbe", "jg", "jge",
                  "jl", "jle", "js", "jns", "jo", "jno", "jp", "jnp"})
_BINARY = frozenset({"add", "sub", "and", "or", "xor", "imul", "shl", "shr", "sar"})
_UNARY = frozenset({"inc", "dec", "neg", "not"})
_SYSTEM = frozenset({"int", "int1", "int3", "into", "syscall", "sysenter",
                     "sysexit", "sysret", "hlt", "ud2", "iret", "iretd",
                     "in", "out", "insb", "insd", "outsb", "outsd", "cli", "sti"})


class _Blocked(Exception):
    pass


class _Reject(Exception):
    pass


def _capstone():
    import capstone
    engine = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    engine.detail = True
    engine.skipdata = False
    return engine


def _target(ins):
    # X86_OP_IMM == 2. Far transfers deliberately do not qualify.
    if len(ins.operands) == 1 and ins.operands[0].type == 2:
        return int(ins.operands[0].imm) & 0xffffffff
    return None


@dataclass
class _Decoded:
    instructions: dict = field(default_factory=dict)
    successors: dict = field(default_factory=dict)
    calls: list = field(default_factory=list)
    branches: list = field(default_factory=list)
    errors: set = field(default_factory=set)
    returns: list = field(default_factory=list)
    loops: list = field(default_factory=list)
    size: int = 0


def _decode(code, address, engine, budget, seeds=()):
    """Follow reachable instructions; retain the *original contiguous* span.

    No linear resynchronization after invalid bytes, returns or indirect jumps.
    Branch-skipped bytes remain in code_hex, but are never invented instructions.
    """
    import capstone
    result = _Decoded()
    available = min(len(code), MAX_FUNCTION_BYTES)
    pending = deque([address])
    queued = {address}
    owner = {}
    seeds = set(seeds)
    while pending:
        pc = pending.popleft()
        offset = pc - address
        if pc in result.instructions:
            continue
        if pc in seeds and pc != address:
            result.errors.add("crosses_function_boundary")
            continue
        if offset < 0 or offset >= available:
            result.errors.add("function_byte_limit" if offset >= MAX_FUNCTION_BYTES
                              else "truncated_or_external_control_flow")
            continue
        if pc in owner:
            result.errors.add("overlapping_instructions")
            continue
        if len(result.instructions) >= MAX_FUNCTION_INSTRUCTIONS:
            result.errors.add("function_instruction_limit")
            break
        if budget[0] <= 0:
            result.errors.add("total_instruction_limit")
            break
        budget[0] -= 1
        ins = next(engine.disasm(code[offset:min(offset + 15, available)], pc, count=1), None)
        if ins is None:
            result.size = max(result.size, min(offset + 15, available))
            result.errors.add("invalid_or_truncated_instruction")
            continue
        if any(a in owner for a in range(pc, pc + ins.size)):
            result.errors.add("overlapping_instructions")
            continue
        if any(a in seeds for a in range(pc + 1, pc + ins.size)):
            result.errors.add("seed_inside_instruction")
        for a in range(pc, pc + ins.size):
            owner[a] = pc
        result.instructions[pc] = ins
        result.size = max(result.size, offset + ins.size)
        next_pc = pc + ins.size
        successors = []
        if ins.group(capstone.CS_GRP_CALL):
            result.calls.append({"address": pc, "target": _target(ins),
                                 "direct": _target(ins) is not None})
            successors = [next_pc]
        elif ins.group(capstone.CS_GRP_RET):
            result.returns.append(pc)
        elif ins.group(capstone.CS_GRP_JUMP):
            target = _target(ins)
            unconditional = ins.mnemonic in {"jmp", "ljmp"}
            result.branches.append({"address": pc, "target": target,
                                    "direct": target is not None,
                                    "kind": "unconditional" if unconditional else "conditional"})
            if target is None:
                result.errors.add("indirect_branch")
            else:
                successors.append(target)
            if not unconditional:
                successors.append(next_pc)
        elif ins.mnemonic in _SYSTEM or ins.group(capstone.CS_GRP_IRET):
            result.errors.add("system_or_privileged_instruction")
        else:
            successors = [next_pc]
        result.successors[pc] = successors
        for target in successors:
            if target not in queued:
                queued.add(target)
                pending.append(target)
    if not result.returns:
        result.errors.add("no_normal_return")
    return result


@dataclass(frozen=True)
class _Value:
    kind: str
    token: object
    deps: frozenset = frozenset()


class _Values:
    """Interned expressions avoid exponential trees at control-flow joins."""
    def __init__(self):
        self.nodes = {}

    @staticmethod
    def const(n):
        return _Value("const", n & 0xffffffff)

    def expression(self, op, values, control=frozenset()):
        values = tuple(values)
        if op == "phi" and all(v == values[0] for v in values):
            return values[0]
        if op in {"sub", "xor"} and values[0] == values[1]:
            return self.const(0)
        if op in {"or", "and"} and values[0] == values[1]:
            return values[0]
        if len(values) == 2 and op in {"add", "and", "or", "xor", "imul"} and values[0].kind == "const" and values[1].kind != "const":
            values = (values[1], values[0])
        if len(values) == 2 and values[1].kind == "const":
            rhs = values[1].token
            if rhs == 0 and op in {"add", "sub", "or", "xor", "shl", "shr", "sar"}:
                return values[0]
            if (op in {"and", "imul"} and rhs == 0) or (op == "or" and rhs == 0xffffffff):
                return self.const(rhs)
            if (op == "and" and rhs == 0xffffffff) or (op == "imul" and rhs == 1):
                return values[0]
        if all(v.kind == "const" for v in values) and op != "phi":
            a = values[0].token
            b = values[1].token if len(values) > 1 else 0
            signed = a if a < 0x80000000 else a - ADDRESS_END
            operations = {"add": lambda: a + b, "sub": lambda: a - b,
                          "xor": lambda: a ^ b, "and": lambda: a & b,
                          "or": lambda: a | b, "imul": lambda: a * b,
                          "shl": lambda: a << (b & 31), "shr": lambda: a >> (b & 31),
                          "sar": lambda: signed >> (b & 31), "not": lambda: ~a,
                          "neg": lambda: -a, "inc": lambda: a + 1, "dec": lambda: a - 1}
            if op in operations:
                return self.const(operations[op]())
        deps = frozenset().union(control, *(v.deps for v in values))
        key = (op, values, control)
        node = self.nodes.setdefault(key, len(self.nodes))
        kind = "unknown" if any(v.kind in {"initial", "unknown"} for v in values) else "expr"
        return _Value(kind, node, deps)


@dataclass
class _State:
    sp: int = 0
    regs: dict = field(default_factory=lambda: {r: _Value("initial", r) for r in _REGS - {"esp"}})
    stack: dict = field(default_factory=dict)
    flags: _Value | None = None
    flag_ops: tuple | None = None
    control: frozenset = frozenset()

    def copy(self):
        return _State(self.sp, self.regs.copy(), self.stack.copy(), self.flags, self.flag_ops, self.control)


def _scalar(value):
    if value.kind in {"initial", "unknown"}:
        raise _Reject("uninitialized_or_register_input")
    if value.kind == "stack_address":
        raise _Reject("stack_address_escape")
    return value


def _stack_slot(ins, operand, state):
    mem = operand.mem
    if mem.segment or mem.index or ins.reg_name(mem.base) not in {"esp", "ebp"}:
        raise _Reject("global_or_pointer_memory")
    if operand.size != 4:
        raise _Reject("non_uint32_memory_access")
    base = state.sp if ins.reg_name(mem.base) == "esp" else state.regs["ebp"]
    if isinstance(base, _Value):
        if base.kind != "stack_address":
            raise _Reject("unproven_frame_pointer")
        base = base.token
    offset = base + mem.disp
    if offset % 4:
        raise _Reject("unaligned_stack_access")
    if offset == 0:
        raise _Reject("return_address_access")
    if offset > 16:
        raise _Reject("more_than_four_arguments")
    if offset < state.sp or offset < -MAX_STACK_BYTES:
        raise _Reject("outside_own_stack")
    return offset


def _reg(ins, operand):
    name = ins.reg_name(operand.reg)
    if operand.size != 4 or name not in _REGS:
        raise _Reject("unsupported_register_width_or_simd")
    return name


def _read(ins, operand, state, args):
    if operand.type == 2:
        return _Values.const(operand.imm)
    if operand.type == 1:
        reg = _reg(ins, operand)
        return _Value("stack_address", state.sp) if reg == "esp" else state.regs[reg]
    if operand.type == 3:
        offset = _stack_slot(ins, operand, state)
        if offset > 0:
            arg = offset // 4
            args.add(arg)
            return _Value("arg", arg, frozenset({arg}))
        if offset not in state.stack:
            raise _Reject("uninitialized_stack_read")
        return state.stack[offset]
    raise _Reject("unsupported_operand")


def _write(ins, operand, value, state):
    if operand.type == 1:
        reg = _reg(ins, operand)
        if reg == "esp":
            raise _Reject("unproven_stack_adjustment")
        if value.kind == "stack_address":
            raise _Reject("stack_address_escape")
        state.regs[reg] = value
    elif operand.type == 3:
        offset = _stack_slot(ins, operand, state)
        if offset > 0:
            raise _Reject("argument_write")
        if value.kind == "stack_address":
            raise _Reject("stack_address_escape")
        state.stack[offset] = value
    else:
        raise _Reject("unsupported_destination")


def _set_sp(state, new_sp):
    if new_sp % 4 or new_sp > 0 or new_sp < -MAX_STACK_BYTES:
        raise _Reject("unproven_stack_adjustment")
    # Discard freed slots; a later sub/push cannot resurrect initialized memory.
    state.stack = {k: v for k, v in state.stack.items() if k >= new_sp}
    state.sp = new_sp


def _merge(left, right, values):
    if left.sp != right.sp or left.regs["ebp"] != right.regs["ebp"]:
        raise _Reject("uncertain_branch_stack")
    out = left.copy()
    out.control |= right.control
    for reg in out.regs:
        out.regs[reg] = values.expression("phi", [left.regs[reg], right.regs[reg]], out.control)
    out.stack = {k: values.expression("phi", [left.stack[k], right.stack[k]], out.control)
                 for k in left.stack.keys() & right.stack.keys()}
    out.flags = (values.expression("phi", [left.flags, right.flags], out.control)
                 if left.flags is not None and right.flags is not None else None)
    # A merged branch never reuses either side's operand pair: the phi result
    # cannot be resolved as if it were one concrete comparison.
    out.flag_ops = left.flag_ops if left.flag_ops == right.flag_ops else None
    return out


_CARRY_BRANCHES = frozenset({"ja", "jae", "jb", "jbe"})


def _flag_bits(kind, left, right):
    """(carry, zero, sign, overflow, parity) for known operands, or None.

    ``carry`` is None for inc/dec because those instructions leave CF unchanged.
    """
    if kind in {"cmp", "sub"}:
        result = (left - right) & 0xffffffff
        carry = left < right
        overflow = bool((left ^ right) & (left ^ result) & 0x80000000)
    elif kind == "add":
        result = (left + right) & 0xffffffff
        carry = result < left
        overflow = bool((left ^ result) & (right ^ result) & 0x80000000)
    elif kind == "test":
        result = left & right
        carry = overflow = False
    elif kind in {"and", "or", "xor"}:
        result = {"and": left & right, "or": left | right, "xor": left ^ right}[kind]
        carry = overflow = False
    elif kind in {"inc", "dec"}:
        result = (left + 1) & 0xffffffff if kind == "inc" else (left - 1) & 0xffffffff
        carry = None
        overflow = left == (0x7fffffff if kind == "inc" else 0x80000000)
    else:
        return None
    return (carry, result == 0, bool(result & 0x80000000), overflow,
            (result & 0xff).bit_count() % 2 == 0)


def _branch_taken(op, flag_ops):
    """Resolve a conditional branch; None means both outcomes remain possible."""
    if flag_ops is None:
        return None
    kind, lhs, rhs = flag_ops
    if kind in {"inc", "dec"} and op in _CARRY_BRANCHES:
        # CF is unchanged by inc/dec, so its incoming value is not an argument
        # and cannot be reconstructed; merging both successors would be unsound.
        raise _Reject("unproven_branch_flags")
    if lhs.kind != "const" or rhs.kind != "const":
        return None
    bits = _flag_bits(kind, lhs.token & 0xffffffff, rhs.token & 0xffffffff)
    if bits is None:
        return None
    carry, zero, sign, overflow, parity = bits
    if carry is None:
        if op in _CARRY_BRANCHES:
            raise _Reject("unproven_branch_flags")
        carry = False
    return {"je": zero, "jne": not zero, "ja": not carry and not zero,
            "jae": not carry, "jb": carry, "jbe": carry or zero,
            "jg": not zero and sign == overflow, "jge": sign == overflow,
            "jl": sign != overflow, "jle": zero or sign != overflow,
            "js": sign, "jns": not sign, "jo": overflow, "jno": not overflow,
            "jp": parity, "jnp": not parity}[op]


def _eligibility(decoded, address, call_summaries=None):
    """Conservative abstract interpretation over a bounded worklist.

    Constant branch conditions are resolved exactly. A function containing a
    back edge is unrolled; it is accepted only when every conditional branch is
    decidable from constants alone (a fixed trip count), and rejected with
    ``unproven_loop_condition`` when control depends on an argument. Carry
    conditions after inc/dec remain unknown because those instructions leave CF
    unchanged, so such branches are rejected rather than merged. Only cmp/test,
    add/sub, and/or/xor and inc/dec establish flags; partial registers, variable
    shifts, division, imul flags and unknown ABI inputs are excluded, rather
    than guessed. The expression check proves structural output dependency, not
    a recovered C type/signature or complete mathematical nonconstancy proof.

    ``call_summaries`` maps an allowed direct-call target to the argument slot
    numbers its own analysis proved. A call then reads the already-pushed
    argument values and contributes their dependencies; the callee body itself
    was validated separately, so it is modeled atomically, not re-interpreted.
    """
    if decoded.calls:
        targets = [call["target"] for call in decoded.calls]
        if call_summaries is None or any(t is None or t not in call_summaries for t in targets):
            return {"eligible": False, "reason": "contains_call"}, None, []
    if decoded.errors:
        return {"eligible": False, "reason": sorted(decoded.errors)[0]}, None, []
    looped = any(target <= pc for pc, targets in decoded.successors.items() for target in targets)
    values = _Values()
    states = {address: _State()}
    # Address order keeps forward-only functions in topological order (the
    # original single-pass behavior) while still unrolling back edges.
    pending = [address]
    queued = {address}
    visits = Counter()
    back_edges = {}
    iterations = Counter()
    args = set()
    returns = []
    steps = 0
    try:
        while pending:
            pc = heapq.heappop(pending)
            queued.discard(pc)
            if pc not in decoded.instructions:
                raise _Reject("unproven_control_flow")
            visits[pc] += 1
            if visits[pc] > MAX_BLOCK_VISITS:
                raise _Reject("loop_iteration_limit")
            steps += 1
            if steps > MAX_ABSTRACT_STEPS:
                raise _Reject("loop_iteration_limit")
            ins = decoded.instructions[pc]
            state = states[pc].copy()
            op = ins.mnemonic
            operands = ins.operands
            next_pc = pc + ins.size
            targets = [next_pc]
            if any(ins.prefix):
                raise _Reject("unsupported_instruction_prefix")
            if op in _SYSTEM:
                raise _Reject("system_or_privileged_instruction")
            if op in {"ret", "retf", "retfq"}:
                if op != "ret" or operands or bytes(ins.bytes) != b"\xc3":
                    raise _Reject("not_plain_cdecl_return")
                if state.sp != 0:
                    raise _Reject("unbalanced_stack_at_return")
                if any(state.regs[r] != _Value("initial", r) for r in _SAVED):
                    raise _Reject("callee_saved_register_not_restored")
                returns.append((_scalar(state.regs["eax"]), state.control))
                targets = []
            elif op == "push" and len(operands) == 1:
                value = _read(ins, operands[0], state, args)
                if value.kind == "stack_address":
                    raise _Reject("stack_address_escape")
                _set_sp(state, state.sp - 4)
                state.stack[state.sp] = value
            elif op == "pop" and len(operands) == 1:
                if operands[0].type != 1 or _reg(ins, operands[0]) == "esp":
                    raise _Reject("unsupported_pop")
                if state.sp not in state.stack:
                    raise _Reject("uninitialized_stack_read")
                value = state.stack[state.sp]
                _set_sp(state, state.sp + 4)
                _write(ins, operands[0], value, state)
            elif op == "leave":
                frame = state.regs["ebp"]
                if frame.kind != "stack_address" or frame.token < state.sp:
                    raise _Reject("unproven_frame_pointer")
                _set_sp(state, frame.token)
                if state.sp not in state.stack:
                    raise _Reject("uninitialized_stack_read")
                value = state.stack[state.sp]
                _set_sp(state, state.sp + 4)
                state.regs["ebp"] = value
            elif op in {"add", "sub"} and len(operands) == 2 and operands[0].type == 1 and ins.reg_name(operands[0].reg) == "esp":
                if operands[1].type != 2:
                    raise _Reject("unproven_stack_adjustment")
                delta = operands[1].imm
                if delta < 0 or delta > MAX_STACK_BYTES:
                    raise _Reject("unproven_stack_adjustment")
                _set_sp(state, state.sp + (delta if op == "add" else -delta))
                state.flags = state.flag_ops = None
            elif op == "mov" and len(operands) == 2:
                dst, src = operands
                dst_reg = _reg(ins, dst) if dst.type == 1 else None
                src_reg = _reg(ins, src) if src.type == 1 else None
                if dst_reg == "ebp" and src_reg == "esp":
                    state.regs["ebp"] = _Value("stack_address", state.sp)
                elif dst_reg == "esp" and src_reg == "ebp":
                    frame = state.regs["ebp"]
                    if frame.kind != "stack_address" or frame.token < state.sp:
                        raise _Reject("unproven_frame_pointer")
                    _set_sp(state, frame.token)
                else:
                    _write(ins, dst, _read(ins, src, state, args), state)
            elif op in _BINARY and len(operands) in {2, 3}:
                if len(operands) == 3 and op != "imul":
                    raise _Reject("unsupported_operands")
                lhs = _read(ins, operands[0 if len(operands) == 2 else 1], state, args)
                rhs = _read(ins, operands[-1], state, args)
                # xor/sub reg,reg define a value even if the incoming register is unknown.
                zeroing = op in {"xor", "sub"} and operands[0].type == 1 and operands[-1].type == 1 and operands[0].reg == operands[-1].reg
                if not zeroing:
                    _scalar(lhs)
                    _scalar(rhs)
                if op in {"shl", "shr", "sar"} and (operands[-1].type != 2 or not 0 <= operands[-1].imm <= 31):
                    raise _Reject("variable_or_unsupported_shift")
                if zeroing:
                    # xor/sub of a register with itself: CF=OF=0, ZF=1, PF=1,
                    # independently of the incoming value, exactly like "test 0,0".
                    result = values.const(0)
                    state.flags, state.flag_ops = result, ("test", result, result)
                else:
                    result = values.expression(op, [lhs, rhs])
                    if op in {"add", "sub", "and", "or", "xor"}:
                        state.flags, state.flag_ops = result, (op, lhs, rhs)
                    else:
                        state.flags = state.flag_ops = None
                _write(ins, operands[0], result, state)
            elif op in _UNARY and len(operands) == 1:
                value = _scalar(_read(ins, operands[0], state, args))
                result = values.expression(op, [value])
                _write(ins, operands[0], result, state)
                if op in {"inc", "dec"}:
                    state.flags, state.flag_ops = result, (op, value, values.const(1))
                elif op != "not":
                    state.flags = state.flag_ops = None
            elif op in {"cmp", "test"} and len(operands) == 2:
                inputs = [_scalar(_read(ins, operand, state, args)) for operand in operands]
                state.flags = values.expression("sub" if op == "cmp" else "and", inputs)
                state.flag_ops = (op, inputs[0], inputs[1])
            elif op in _JCC:
                if state.flags is None:
                    raise _Reject("unproven_branch_flags")
                state.control |= state.flags.deps
                taken = _branch_taken(op, state.flag_ops)
                if taken is None:
                    if looped:
                        raise _Reject("unproven_loop_condition")
                    targets = list(decoded.successors[pc])
                else:
                    targets = [_target(ins) if taken else next_pc]
            elif op == "jmp":
                if _target(ins) is None:
                    raise _Reject("indirect_branch")
                targets = [_target(ins)]
            elif op == "call" and len(operands) == 1 and operands[0].type == 2:
                target = _target(ins)
                if call_summaries is None or target not in call_summaries:
                    raise _Reject("contains_call")
                passed = []
                for slot in call_summaries[target]:
                    slot_off = state.sp + 4 * (slot - 1)
                    if slot_off not in state.stack:
                        raise _Reject("callee_argument_not_provided")
                    passed.append(_scalar(state.stack[slot_off]))
                state.regs["eax"] = values.expression("call", [values.const(target), *passed])
                state.regs["ecx"] = _Value("unknown", "call_clobber")
                state.regs["edx"] = _Value("unknown", "call_clobber")
                state.flags = state.flag_ops = None
            elif op == "nop":
                # Memory-form nops do not dereference memory, but keep the whitelist narrow.
                if operands:
                    raise _Reject("unsupported_nop_form")
            else:
                if op.startswith("f") or any(ins.reg_name(r).startswith(("xmm", "ymm", "zmm", "mm", "st")) for r in ins.regs_access()[0] + ins.regs_access()[1]):
                    raise _Reject("floating_point_or_simd")
                raise _Reject("unsupported_instruction:" + op)
            for target in targets:
                if target not in decoded.instructions:
                    raise _Reject("unproven_control_flow")
                if target <= pc:
                    back_edges.setdefault(pc, target)
                    iterations[pc] += 1
                    if iterations[pc] > MAX_LOOP_ITERATIONS:
                        raise _Reject("loop_iteration_limit")
                if target not in states:
                    states[target] = state.copy()
                    changed = True
                elif looped:
                    # With every branch resolved from constants the path is
                    # deterministic, so a revisited block has exactly one live
                    # state per iteration; no phi is needed or meaningful.
                    changed = states[target] != state
                    if changed:
                        states[target] = state.copy()
                else:
                    merged = _merge(states[target], state, values)
                    changed = merged != states[target]
                    if changed:
                        states[target] = merged
                if changed and target not in queued:
                    heapq.heappush(pending, target)
                    queued.add(target)
        if not returns:
            raise _Reject("no_normal_return")
        if not args:
            raise _Reject("no_stack_arguments")
        if args != set(range(1, max(args) + 1)):
            raise _Reject("noncontiguous_argument_evidence")
        result = values.expression("phi", [v for v, _ in returns],
                                   frozenset().union(*(c for _, c in returns)))
        if not result.deps:
            raise _Reject("no_input_dependent_return")
        if iterations:
            # A taken back edge closes one iteration, so the loop body ran
            # exactly one more time than the edge was traversed.
            decoded.loops = [{"back_edge": pc, "target": back_edges[pc],
                              "iterations": iterations[pc] + 1} for pc in sorted(iterations)]
        return {"eligible": True, "reason": "proven_scalar_stack_leaf"}, max(args), sorted(args)
    except _Reject as exc:
        return {"eligible": False, "reason": str(exc)}, None, sorted(args)


def _evaluate(functions, address, inputs, budget, depth=0):
    """Evaluate already-validated scalar semantics in Python, never native code.

    ``functions`` maps an address to its decoded instructions and proven argument
    count; direct calls are followed with those arguments. This is only a
    nonconstancy witness, not an emulator/loader or differential oracle. The
    abstract pass has already rejected external state, memory, unknown flags,
    input-dependent loops and everything outside this deliberately small subset.
    """
    if depth > MAX_COMPOSED_FUNCTIONS:
        raise _Reject("composition_depth_limit")
    entry = functions.get(address)
    if entry is None:
        raise _Reject("call_target_not_analyzed")
    decoded = entry["decoded"]
    regs = dict.fromkeys(_REGS, 0)
    stack = {}
    flags = None

    def slot(ins, operand):
        return regs[ins.reg_name(operand.mem.base)] + operand.mem.disp

    def read(ins, operand):
        if operand.type == 1:
            return regs[ins.reg_name(operand.reg)]
        if operand.type == 2:
            return operand.imm & 0xffffffff
        offset = slot(ins, operand)
        return inputs[offset // 4 - 1] if offset > 0 else stack[offset]

    def write(ins, operand, value):
        if operand.type == 1:
            regs[ins.reg_name(operand.reg)] = value
        else:
            stack[slot(ins, operand)] = value

    pc = address
    values = _Values()
    while True:
        if budget[0] <= 0:
            raise _Reject("concrete_step_limit")
        budget[0] -= 1
        ins = decoded.instructions.get(pc)
        if ins is None:
            raise _Reject("unproven_control_flow")
        op, operands = ins.mnemonic, ins.operands
        next_pc = pc + ins.size
        if op == "ret":
            return regs["eax"] & 0xffffffff
        if op == "push":
            value = read(ins, operands[0])
            regs["esp"] -= 4
            stack[regs["esp"]] = value
        elif op == "pop":
            value = stack.pop(regs["esp"])
            regs["esp"] += 4
            write(ins, operands[0], value)
        elif op == "leave":
            regs["esp"] = regs["ebp"]
            regs["ebp"] = stack.pop(regs["esp"])
            regs["esp"] += 4
        elif op == "mov":
            write(ins, operands[0], read(ins, operands[1]))
        elif op in _BINARY:
            if operands[0].type == 1 and ins.reg_name(operands[0].reg) == "esp":
                delta = operands[1].imm
                regs["esp"] += delta if op == "add" else -delta
            else:
                left = read(ins, operands[0 if len(operands) == 2 else 1])
                right = read(ins, operands[-1])
                result = values.expression(op, [values.const(left), values.const(right)])
                write(ins, operands[0], result.token)
                flags = (_flag_bits(op, left & 0xffffffff, right & 0xffffffff)
                         if op in {"add", "sub", "and", "or", "xor"} else None)
        elif op in _UNARY:
            operand = read(ins, operands[0]) & 0xffffffff
            result = values.expression(op, [values.const(operand)])
            write(ins, operands[0], result.token)
            if op in {"inc", "dec"}:
                bits = _flag_bits(op, operand, 1)
                carry = flags[0] if flags else None  # inc/dec leave CF unchanged
                flags = (carry, bits[1], bits[2], bits[3], bits[4])
            elif op != "not":
                flags = None
        elif op in {"cmp", "test"}:
            left, right = (read(ins, operand) & 0xffffffff for operand in operands)
            result = ((left - right) if op == "cmp" else (left & right)) & 0xffffffff
            carry = op == "cmp" and left < right
            overflow = op == "cmp" and bool((left ^ right) & (left ^ result) & 0x80000000)
            flags = (carry, result == 0, bool(result & 0x80000000), overflow,
                     (result & 0xff).bit_count() % 2 == 0)
        elif op in _JCC:
            if flags is None:
                raise _Reject("unproven_branch_flags")
            carry, zero, sign, overflow, parity = flags
            if carry is None and op in _CARRY_BRANCHES:
                raise _Reject("unproven_branch_flags")
            conditions = {"je": zero, "jne": not zero, "ja": not carry and not zero,
                          "jae": not carry, "jb": carry, "jbe": carry or zero,
                          "jg": not zero and sign == overflow, "jge": sign == overflow,
                          "jl": sign != overflow, "jle": zero or sign != overflow,
                          "js": sign, "jns": not sign, "jo": overflow, "jno": not overflow,
                          "jp": parity, "jnp": not parity}
            if conditions[op]:
                next_pc = _target(ins)
        elif op == "jmp":
            next_pc = _target(ins)
        elif op == "call":
            target = _target(ins)
            callee = functions.get(target)
            if callee is None:
                raise _Reject("call_target_not_analyzed")
            count = callee.get("arg_count")
            if type(count) is not int or not 1 <= count <= 4:
                raise _Reject("unproven_callee_argument_count")
            passed = []
            for index in range(count):
                offset = regs["esp"] + 4 * index
                if offset not in stack:
                    raise _Reject("callee_argument_not_provided")
                passed.append(stack[offset])
            regs["eax"] = _evaluate(functions, target, passed, budget, depth + 1)
        elif op != "nop":
            raise _Reject("input_dependency_semantics_unavailable")
        pc = next_pc


def _scalar_output(decoded, address, inputs):
    """Single-function convenience wrapper; no calls are expected."""
    functions = {address: {"decoded": decoded, "arg_count": len(inputs)}}
    return _evaluate(functions, address, inputs, [MAX_CONCRETE_STEPS])


def _dependency_witness(decoded, address, count, functions=None):
    # Finding two differing outputs proves this supported scalar function is
    # nonconstant. Failure to find them is NOT proof of constancy: exclude it.
    functions = functions or {address: {"decoded": decoded, "arg_count": count}}
    baseline = (0,) * count
    first = _evaluate(functions, address, baseline, [MAX_CONCRETE_STEPS])
    interesting = (1, 2, 0x7fffffff, 0x80000000, 0xffffffff, 0x55555555, 0xaaaaaaaa)
    vectors = [(value,) * count for value in interesting]
    for index in range(count):
        for value in interesting:
            vector = [0] * count
            vector[index] = value
            vectors.append(tuple(vector))
    for vector in vectors:
        result = _evaluate(functions, address, vector, [MAX_CONCRETE_STEPS])
        if result != first:
            return [{"args": list(baseline), "return_value": first},
                    {"args": list(vector), "return_value": result}]
    return None


def _module(code, address, decoded, source_sha256, evidence, trusted=True):
    eligibility, arg_count, args = _eligibility(decoded, address)
    witness = None
    if not trusted:
        eligibility = {"eligible": False, "reason": "untrusted_executable_section"}
        arg_count = None
    if eligibility["eligible"]:
        witness = _dependency_witness(decoded, address, arg_count)
        if witness is None:
            eligibility = {"eligible": False, "reason": "input_dependence_not_demonstrated"}
            arg_count = None
    raw = bytes(code[:decoded.size])
    return {
        "id": f"fn_{address:08x}", "address": address, "size": len(raw),
        "code_hex": raw.hex(), "code_sha256": hashlib.sha256(raw).hexdigest(),
        "source_sha256": source_sha256,
        "instructions": [{"address": ins.address, "mnemonic": ins.mnemonic,
                          "op_str": ins.op_str, "bytes": bytes(ins.bytes).hex()}
                         for _, ins in sorted(decoded.instructions.items())],
        "calls": decoded.calls, "branches": decoded.branches, "loops": decoded.loops,
        "confidence": "conservative_candidate" if eligibility["eligible"] else "structural_only",
        "boundary_evidence": evidence,
        "boundary_complete": not decoded.errors,
        "boundary_errors": sorted(decoded.errors), "return_addresses": sorted(decoded.returns),
        "heuristic_seed": any(item.get("heuristic") for item in evidence),
        "eligibility": eligibility, "arg_count": arg_count,
        "observed_argument_slots": args,
        "input_dependency_witness": witness,
        "arg_count_evidence": "contiguous_observed_uint32_stack_inputs; unused_trailing_parameters_unknown" if arg_count else None,
        "calling_convention": "cdecl_compatible" if arg_count else None,
        "return_type": "uint32_t" if arg_count else None,
        "not_full_game_analysis": True,
    }


def _compose_modules(modules, decoded_by_address, trusted_by_address):
    """Prove bounded callers by summarizing callees bottom-up, never executing them.

    A callee is used atomically: its own pass proved balanced cdecl stack
    behavior, no callee-saved clobbering and scalar return dependence on its
    contiguous stack arguments, and every callee it calls obeys the same rules.
    The caller's pass then reads the pushed argument values and models the
    return as one expression. Cycles, untrusted sections, incomplete spans and
    the compositional limits are rejected; nothing is guessed.
    """
    by_address = {module["address"]: module for module in modules}
    structural = {"overlapping_function_spans", "untrusted_executable_section",
                  "total_function_bytes_limit", "discovery_limit_reached"}
    memo = {}
    proven = []
    rejected = Counter()

    def reject(address, reason):
        memo[address] = {"status": "blocked", "reason": reason}
        return memo[address]

    def summarize(address, active):
        if address in memo:
            return memo[address]
        if address in active:
            return {"status": "blocked", "reason": "recursive_call_cycle"}
        module, decoded = by_address.get(address), decoded_by_address.get(address)
        if module is None or decoded is None:
            return reject(address, "call_target_not_analyzed")
        if not trusted_by_address.get(address):
            return reject(address, "untrusted_callee")
        if (module["eligibility"]["reason"] in structural or not module["boundary_complete"]
                or decoded.errors):
            return reject(address, "incomplete_callee_boundary")
        if not decoded.calls and not module["eligibility"]["eligible"]:
            return reject(address, "callee_not_independently_validated")
        active.add(address)
        try:
            summaries, members = {}, {address}
            instructions, size = len(decoded.instructions), decoded.size
            failure = None
            for call in decoded.calls:
                if not call["direct"] or call["target"] is None:
                    failure = "indirect_call"
                    break
                sub = summarize(call["target"], active)
                if sub["status"] != "ok":
                    failure = sub["reason"]
                    break
                summaries[call["target"]] = sub["arg_slots"]
                members |= sub["members"]
                instructions += sub["instructions"]
                size += sub["size"]
            if failure is None and len(members) > MAX_COMPOSED_FUNCTIONS:
                failure = "composition_function_limit"
            if failure is None and instructions > MAX_COMPOSED_INSTRUCTIONS:
                failure = "composition_instruction_limit"
            if failure is None and size > MAX_COMPOSED_BYTES:
                failure = "composition_byte_limit"
            if failure is None:
                eligibility, arg_count, slots = _eligibility(
                    decoded, address, summaries if decoded.calls else None)
                if not eligibility["eligible"]:
                    failure = eligibility["reason"]
            if failure is not None:
                return reject(address, failure)
            result = {"status": "ok", "reason": None, "arg_count": arg_count,
                      "arg_slots": slots, "members": members, "callees": summaries,
                      "instructions": instructions, "size": size}
            memo[address] = result
            return result
        finally:
            active.discard(address)

    for module in modules:
        address = module["address"]
        decoded = decoded_by_address.get(address)
        if decoded is None or not decoded.calls:
            continue
        result = summarize(address, set())
        if result["status"] != "ok":
            module["composition"] = {"status": "rejected", "reason": result["reason"]}
            rejected[result["reason"]] += 1
            continue
        members = sorted(result["members"])
        spans = sorted((by_address[member]["address"], by_address[member]["size"])
                       for member in members)
        if any(left[0] + left[1] > right[0] for left, right in zip(spans, spans[1:])):
            module["composition"] = {"status": "rejected", "reason": "overlapping_composition_spans"}
            rejected["overlapping_composition_spans"] += 1
            continue
        functions = {}
        for member in members:
            entry = memo.get(member)
            if entry is None or entry["status"] != "ok":
                functions = None
                break
            functions[member] = {"decoded": decoded_by_address[member],
                                 "arg_count": entry["arg_count"]}
        try:
            witness = (_dependency_witness(decoded, address, result["arg_count"], functions)
                       if functions else None)
        except _Reject:
            witness = None
        if witness is None:
            module["composition"] = {"status": "rejected", "reason": "input_dependence_not_demonstrated"}
            rejected["input_dependence_not_demonstrated"] += 1
            continue
        module["confidence"] = "conservative_composition"
        module["eligibility"] = {"eligible": True, "reason": "proven_scalar_composition"}
        module["arg_count"] = result["arg_count"]
        module["observed_argument_slots"] = result["arg_slots"]
        module["input_dependency_witness"] = witness
        module["calling_convention"] = "cdecl_compatible"
        module["return_type"] = "uint32_t"
        module["arg_count_evidence"] = "contiguous_observed_uint32_stack_inputs; unused_trailing_parameters_unknown"
        module["composed_functions"] = [f"fn_{member:08x}" for member in members]
        module["code_ranges"] = [
            {"address": by_address[member]["address"], "size": by_address[member]["size"],
             "code_hex": by_address[member]["code_hex"],
             "code_sha256": by_address[member]["code_sha256"],
             "file_offset": by_address[member]["file_offset"]}
            for member in members]
        module["composition"] = {
            "status": "proven", "functions": len(members),
            "instructions": result["instructions"], "bytes": result["size"],
            "callee_argument_slots": {f"fn_{target:08x}": slots
                                      for target, slots in sorted(result["callees"].items())},
            "members": [{"id": by_address[member]["id"], "address": by_address[member]["address"],
                         "size": by_address[member]["size"], "arg_count": by_address[member]["arg_count"],
                         "instructions": by_address[member]["instructions"]}
                        for member in members]}
        proven.append(address)
    return {"attempted": True, "proven": len(proven),
            "rejected": dict(sorted(rejected.items())),
            "limits": {"functions": MAX_COMPOSED_FUNCTIONS,
                       "instructions": MAX_COMPOSED_INSTRUCTIONS, "bytes": MAX_COMPOSED_BYTES,
                       "concrete_steps": MAX_CONCRETE_STEPS}}


def analyze_function(code: bytes, address: int = 0x401000,
                     source_sha256: str | None = None) -> dict:
    """Analyze self-authored machine-code fixtures, not arbitrary file seeds.

    The returned code_hex includes branch-skipped gaps through the last reachable
    instruction. When no source digest is supplied, the full fixture is hashed.
    This helper does not establish that code originates in an executable section.
    """
    if not isinstance(address, int) or address < 0 or address >= ADDRESS_END or address + len(code) > ADDRESS_END:
        raise ValueError("address_out_of_x86_range")
    if len(code) > MAX_INPUT_BYTES:
        raise ValueError("input_exceeds_64_mib")
    decoded = _decode(code, address, _capstone(), [MAX_TOTAL_INSTRUCTIONS])
    module = _module(code, address, decoded, source_sha256 or hashlib.sha256(code).hexdigest(),
                     [{"kind": "synthetic_helper", "address": address}])
    module["source_kind"] = "machine_code_fixture"
    return module


def _read_source(path):
    if not stat.S_ISREG(path.stat().st_mode):
        raise _Blocked("input_not_regular_file")
    digest = hashlib.sha256()
    chunks = []
    length = 0
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise _Blocked("input_not_regular_file")
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            length += len(chunk)
            if length <= MAX_INPUT_BYTES:
                chunks.append(chunk)
            else:
                chunks.clear()
        after = os.fstat(stream.fileno())
    changed = (before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns
               or length != after.st_size)
    return b"".join(chunks), digest.hexdigest(), length, changed


def _parse_pe(data, report):
    """Validate mappings before pefile directory parsing or Capstone decoding."""
    if data[:2] != b"MZ":
        kind = "elf" if data[:4] == b"\x7fELF" else "non_pe"
        raise _Blocked("unsupported_format:" + kind + "; only_unencrypted_pe32_x86")
    if len(data) < 64:
        raise _Blocked("truncated_dos_header")
    pe_offset = struct.unpack_from("<I", data, 60)[0]
    if pe_offset < 64 or pe_offset + 24 > len(data) or data[pe_offset:pe_offset + 4] != b"PE\0\0":
        raise _Blocked("invalid_or_truncated_pe_header")
    machine, nsections = struct.unpack_from("<HH", data, pe_offset + 4)
    optional_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
    optional = pe_offset + 24
    if machine != 0x14c:
        raise _Blocked(f"unsupported_machine:0x{machine:04x}; only_pe32_x86")
    if optional_size < 96 or optional + optional_size > len(data):
        raise _Blocked("truncated_optional_header")
    if struct.unpack_from("<H", data, optional)[0] != 0x10b:
        raise _Blocked("unsupported_optional_header; only_pe32_x86")
    if not 1 <= nsections <= MAX_SECTIONS:
        raise _Blocked("section_count_limit_or_empty")
    if optional + optional_size + nsections * 40 > len(data):
        raise _Blocked("truncated_section_table")
    directory_count = struct.unpack_from("<I", data, optional + 92)[0]
    if directory_count > 16 or optional_size < 96 + 8 * directory_count:
        raise _Blocked("invalid_data_directory_count")
    import pefile
    try:
        pe = pefile.PE(data=data, fast_load=True, max_symbol_exports=MAX_FUNCTIONS)
    except pefile.PEFormatError as exc:
        raise _Blocked("invalid_pe:" + str(exc)) from exc
    try:
        imagebase = int(pe.OPTIONAL_HEADER.ImageBase)
        image_size = int(pe.OPTIONAL_HEADER.SizeOfImage)
        headers = int(pe.OPTIONAL_HEADER.SizeOfHeaders)
        section_alignment = int(pe.OPTIONAL_HEADER.SectionAlignment)
        file_alignment = int(pe.OPTIONAL_HEADER.FileAlignment)
        if image_size <= 0 or image_size > MAX_IMAGE_BYTES or imagebase + image_size > ADDRESS_END:
            raise _Blocked("image_address_or_size_limit")
        if (section_alignment < 4096 or not 512 <= file_alignment <= 65536
                or section_alignment < file_alignment
                or section_alignment & (section_alignment - 1)
                or file_alignment & (file_alignment - 1)):
            raise _Blocked("unsupported_or_invalid_pe_alignment")
        if imagebase % 65536 or image_size % section_alignment or headers % file_alignment:
            raise _Blocked("invalid_image_alignment")
        if int(pe.OPTIONAL_HEADER.AddressOfEntryPoint) >= image_size:
            raise _Blocked("entry_address_outside_image")
        if headers < optional + optional_size + nsections * 40 or headers > len(data):
            raise _Blocked("invalid_header_mapping")
        if len(pe.sections) != nsections:
            raise _Blocked("incomplete_section_table")
        sections = []
        raw_ranges, virtual_ranges = [], []
        executable_bytes = 0
        for section in pe.sections:
            raw = int(section.PointerToRawData)
            raw_size = int(section.SizeOfRawData)
            rva = int(section.VirtualAddress)
            virtual_size = int(section.Misc_VirtualSize)
            span = max(virtual_size, raw_size)
            flags = int(section.Characteristics)
            name = section.Name.rstrip(b"\0").decode("ascii", "replace")
            if rva % section_alignment or (raw_size and (raw % file_alignment or raw_size % file_alignment)):
                raise _Blocked("invalid_section_alignment")
            if span and (rva < headers or rva + span > image_size):
                raise _Blocked("invalid_section_virtual_range")
            table_end = optional + optional_size + nsections * 40
            minimum_raw = (table_end + file_alignment - 1) // file_alignment * file_alignment
            if raw_size and (raw < minimum_raw or raw + raw_size > len(data)):
                raise _Blocked("truncated_or_invalid_section_raw_range")
            if raw_size and raw < headers:
                report.setdefault("mapping_notes", []).append("declared_headers_overlap_raw_section:" + name)
            if raw_size:
                raw_ranges.append((raw, raw + raw_size))
            if span:
                virtual_ranges.append((rva, rva + span))
            # Do not use file-alignment padding beyond VirtualSize as code.
            backed_size = min(raw_size, virtual_size) if virtual_size else raw_size
            executable = bool(flags & 0x20000000)
            code_section = bool(flags & 0x20)
            writable = bool(flags & 0x80000000)
            executable_bytes += backed_size if executable else 0
            item = {"name": name, "address": imagebase + rva, "rva": rva,
                    "virtual_size": virtual_size, "raw_offset": raw, "raw_size": raw_size,
                    "file_backed_size": backed_size, "characteristics": flags,
                    "executable": executable, "contains_code": code_section, "writable": writable}
            sections.append(item)
            lower = name.lower()
            if any(lower.startswith(prefix) for prefix in ("upx", ".upx", ".aspack", ".adata", ".vmp", ".themida", ".enigma", ".mpress", "pec1", "pec2")):
                raise _Blocked("suspected_packed_encrypted_or_protected_section:" + name + "; no_unpacking_or_drm_bypass")
            if executable and backed_size >= 4096:
                counts = Counter(data[raw:raw + backed_size])
                entropy = -sum((n / backed_size) * math.log2(n / backed_size) for n in counts.values())
                item["entropy"] = round(entropy, 4)
                if entropy >= 7.6:
                    raise _Blocked("suspected_packed_or_encrypted_high_entropy_code; heuristic_no_unpacking")
        for ranges in (raw_ranges, virtual_ranges):
            ordered = sorted(ranges)
            if any(left[1] > right[0] for left, right in zip(ordered, ordered[1:])):
                raise _Blocked("overlapping_section_mappings")
        if executable_bytes > MAX_EXECUTABLE_BYTES:
            raise _Blocked("executable_section_bytes_limit")
        if not executable_bytes:
            raise _Blocked("no_file_backed_executable_section")

        def file_range(rva, size):
            for section in sections:
                start = section["rva"]
                if start <= rva and rva + size <= start + section["file_backed_size"]:
                    return section["raw_offset"] + rva - start
            raise _Blocked("unbacked_or_cross_section_data_directory")

        directories = pe.OPTIONAL_HEADER.DATA_DIRECTORY
        if len(directories) > 14 and directories[14].VirtualAddress:
            raise _Blocked("unsupported_managed_pe; only_native_pe32_x86")
        for index in (0, 1, 13):
            if index >= len(directories):
                continue
            directory = directories[index]
            if not directory.VirtualAddress and not directory.Size:
                continue
            if not directory.VirtualAddress or not directory.Size or directory.Size > MAX_DIRECTORY_BYTES:
                raise _Blocked("invalid_or_oversized_data_directory")
            offset = file_range(directory.VirtualAddress, directory.Size)
            if index == 0:
                if directory.Size < 40:
                    raise _Blocked("truncated_export_directory")
                count, named = struct.unpack_from("<II", data, offset + 20)
                if count > MAX_FUNCTIONS or named > MAX_FUNCTIONS:
                    raise _Blocked("export_count_limit")
                for ptr, size in zip(struct.unpack_from("<III", data, offset + 28), (count * 4, named * 4, named * 2)):
                    if size:
                        file_range(ptr, size)
            else:
                stride = 20 if index == 1 else 32
                terminated = False
                for n in range(min(directory.Size // stride, MAX_IMPORT_DLLS + 1)):
                    descriptor = data[offset + n * stride:offset + (n + 1) * stride]
                    if not any(descriptor):
                        terminated = True
                        break
                if not terminated:
                    raise _Blocked("import_descriptor_limit_or_missing_terminator")
        pe.parse_data_directories(directories=[0, 1, 13])
        imports = []
        for attr, delayed in (("DIRECTORY_ENTRY_IMPORT", False), ("DIRECTORY_ENTRY_DELAY_IMPORT", True)):
            for dll in getattr(pe, attr, []):
                for symbol in dll.imports:
                    if len(imports) >= MAX_IMPORTS:
                        raise _Blocked("import_symbol_limit")
                    if not imagebase <= int(symbol.address) < imagebase + image_size:
                        raise _Blocked("import_address_outside_image")
                    imports.append({"dll": dll.dll.decode("ascii", "replace"),
                                    "name": symbol.name.decode("ascii", "replace") if symbol.name else None,
                                    "ordinal": symbol.ordinal, "address": int(symbol.address), "delayed": delayed})
        exports = []
        directory = getattr(pe, "DIRECTORY_ENTRY_EXPORT", None)
        if directory:
            for symbol in directory.symbols:
                if len(exports) >= MAX_FUNCTIONS:
                    raise _Blocked("export_count_limit")
                if not 0 <= int(symbol.address) < image_size:
                    raise _Blocked("export_address_outside_image")
                exports.append({"name": symbol.name.decode("ascii", "replace") if symbol.name else None,
                                "ordinal": symbol.ordinal, "address": imagebase + int(symbol.address),
                                "forwarder": symbol.forwarder.decode("ascii", "replace") if symbol.forwarder else None})
        report.update(format="pe32", arch="x86", machine=machine, image_base=imagebase,
                      image_size=image_size, entry_point=imagebase + int(pe.OPTIONAL_HEADER.AddressOfEntryPoint),
                      entry_rva=int(pe.OPTIONAL_HEADER.AddressOfEntryPoint), sections=sections,
                      imports=imports, exports=exports, pe_warnings=pe.get_warnings()[:100])
        return sections
    except pefile.PEFormatError as exc:
        raise _Blocked("invalid_pe_directories:" + str(exc)) from exc
    finally:
        pe.close()


def _discover(data, report, sections, maximum):
    engine = _capstone()
    budget = [MAX_TOTAL_INSTRUCTIONS]
    seeds = {}
    pending = deque()
    discovery_limits = set()
    rejected_seeds = []

    def section_at(address):
        return next((s for s in sections if s["executable"] and s["contains_code"]
                     and s["address"] <= address < s["address"] + s["file_backed_size"]), None)

    def seed(address, evidence):
        if section_at(address) is None:
            if len(rejected_seeds) < MAX_FUNCTIONS:
                rejected_seeds.append({"address": address, "evidence": evidence,
                                       "reason": "not_file_backed_executable_code"})
            return
        if address not in seeds:
            if len(seeds) >= maximum:
                discovery_limits.add("function_count_limit")
                return
            seeds[address] = []
            pending.append(address)
        if evidence not in seeds[address] and len(seeds[address]) < 16:
            seeds[address].append(evidence)

    if report["entry_rva"]:
        seed(report["entry_point"], {"kind": "entry_point", "address": report["entry_point"]})
    for export in report["exports"]:
        if not export["forwarder"] and export["address"] != report["image_base"]:
            seed(export["address"], {"kind": "export", "address": export["address"], "name": export["name"]})
    if not seeds:
        raise _Blocked("no_valid_entry_or_export_seed_in_executable_code")
    sweep_count = 0
    sweep_engine = _capstone()
    sweep_engine.skipdata = True
    for section in sections:
        if not section["executable"] or not section["contains_code"] or section["writable"]:
            continue
        raw = section["raw_offset"]
        code = data[raw:raw + section["file_backed_size"]]
        for pc, size, mnemonic, _ in sweep_engine.disasm_lite(code, section["address"]):
            sweep_count += 1
            if sweep_count > MAX_SWEEP_INSTRUCTIONS:
                discovery_limits.add("linear_sweep_instruction_limit")
                break
            offset = pc - section["address"]
            if mnemonic == "call" and size == 5 and code[offset] == 0xe8:
                target = pc + 5 + struct.unpack_from("<i", code, offset + 1)[0]
                seed(target, {"kind": "linear_sweep_direct_call", "address": pc, "heuristic": True})
        if sweep_count > MAX_SWEEP_INSTRUCTIONS:
            break
    report["linear_sweep_instructions"] = min(sweep_count, MAX_SWEEP_INSTRUCTIONS)
    report["coverage"] = "entry_export_direct_call_and_heuristic_RX_sweep_not_full_game_analysis; bounded_direct_call_caller_composition"

    def get_code(address):
        section = section_at(address)
        offset = section["raw_offset"] + address - section["address"]
        length = min(MAX_FUNCTION_BYTES, section["address"] + section["file_backed_size"] - address)
        return data[offset:offset + length], section, offset

    while pending:
        address = pending.popleft()
        if budget[0] <= 0:
            discovery_limits.add("total_instruction_limit")
            break
        code, _, _ = get_code(address)
        decoded = _decode(code, address, engine, budget, seeds)
        for call in decoded.calls:
            if call["direct"]:
                seed(call["target"], {"kind": "direct_call", "address": call["address"], "caller": address})
    # Re-extract with the final seed set; late-discovered seeds may split spans.
    modules = []
    decoded_by_address, trusted_by_address = {}, {}
    remaining_code_bytes = MAX_TOTAL_CODE_BYTES
    for address, evidence in sorted(seeds.items()):
        code, section, offset = get_code(address)
        decoded = _decode(code, address, engine, budget, seeds)
        if "total_instruction_limit" in decoded.errors:
            discovery_limits.add("total_instruction_limit")
        if decoded.size > remaining_code_bytes:
            discovery_limits.add("total_function_bytes_limit")
            decoded = _Decoded(errors={"total_function_bytes_limit"})
        remaining_code_bytes -= decoded.size
        decoded_by_address[address] = decoded
        trusted_by_address[address] = not section["writable"]
        module = _module(code, address, decoded, report["source_sha256"], evidence,
                         trusted=not section["writable"])
        module.update(file_offset=offset, section=section["name"], source_kind="pe32_x86")
        modules.append(module)
    # Even a branch-skipped gap intersecting another seed makes ownership ambiguous.
    high = None
    for module in modules:
        if high and module["address"] < high["address"] + high["size"]:
            for overlap in (high, module):
                overlap["eligibility"] = {"eligible": False, "reason": "overlapping_function_spans"}
                overlap["arg_count"] = None
                overlap["boundary_complete"] = False
                if "overlapping_function_spans" not in overlap["boundary_errors"]:
                    overlap["boundary_errors"].append("overlapping_function_spans")
        if high is None or module["address"] + module["size"] > high["address"] + high["size"]:
            high = module
    # A truncated discovery could have mis-decoded callees, so composition is only
    # attempted on complete analysis and never upgrades an excluded module.
    composition = ({"attempted": False, "proven": 0, "rejected": {},
                    "reason": "discovery_limit_reached"}
                   if discovery_limits else
                   _compose_modules(modules, decoded_by_address, trusted_by_address))
    for module in modules:
        if discovery_limits and module["eligibility"]["eligible"]:
            module["eligibility"] = {"eligible": False, "reason": "discovery_limit_reached"}
            module["arg_count"] = None
        if not module["eligibility"]["eligible"]:
            module["confidence"] = "structural_only"
            module["calling_convention"] = None
            module["return_type"] = None
            module["arg_count_evidence"] = None
    report.update(modules=modules, rejected_seeds=rejected_seeds,
                  discovery_limits=sorted(discovery_limits),
                  discovery_truncated=bool(discovery_limits),
                  composition=composition,
                  instructions_decoded=MAX_TOTAL_INSTRUCTIONS - budget[0],
                  total_module_code_bytes=MAX_TOTAL_CODE_BYTES - remaining_code_bytes,
                  direct_call_graph=[{"caller": m["address"], "call_address": c["address"],
                                      "target": c["target"], "target_id": f"fn_{c['target']:08x}" if c["target"] in seeds else None}
                                     for m in modules for c in m["calls"] if c["direct"]])


def _write_report(report, source, output_dir):
    """Atomic writes never follow an existing output-file symlink/hardlink."""
    output_dir = output_dir.resolve()
    destinations = [(output_dir / "analysis.json", report)]
    for module in report["modules"]:
        target = output_dir / "modules" / (module["id"] + ".json")
        module["path"] = str(target)
        module["file"] = "modules/" + module["id"] + ".json"
        destinations.append((target, module))
    # Check all destinations before writing any of them. Protect even oddly named
    # inputs and output-directory symlinks. The source is always opened read-only.
    for target, _ in destinations:
        if target.resolve() == source.resolve() or (target.exists() and source.exists() and os.path.samefile(target, source)):
            raise _Blocked("output_would_overwrite_input")
    for target, value in destinations[1:] + destinations[:1]:
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent,
                                             prefix=".analysis-", suffix=".tmp", delete=False) as stream:
                temp_name = stream.name
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(temp_name, target)
        finally:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)


def analyze_binary(path: Path, output_dir: Path, max_functions=12000) -> dict:
    """Analyze an unencrypted native PE32/x86 snapshot and write JSON artifacts.

    Returns status='ok' or 'blocked', a stable blocked_reason, full source_sha256,
    module dictionaries (also modules/<id>.json), candidate IDs and exclusion
    counts. analysis.json is authoritative on reuse: old unlisted module files
    are not candidates. Packed/protected heuristics only reject; nothing is
    decrypted, unpacked, executed or fetched. Their absence does not prove that
    an arbitrary commercial binary contains no protection.
    """
    path, output_dir = Path(path), Path(output_dir)
    report = {
        "schema_version": 1, "status": "blocked", "blocked_reason": None,
        "source_path": str(path.resolve()), "source_sha256": None, "source_size": None,
        "not_full_game_analysis": True,
        "coverage": "limited_entry_export_direct_call_discovery_and_bounded_caller_composition_not_full_game_analysis",
        "protection_detection": "conservative_heuristics_not_proof_of_absence; no_drm_bypass",
        "modules": [], "candidates": [], "candidate_count": 0,
        "sections": [], "imports": [], "exports": [], "direct_call_graph": [],
        "discovery_limits": [], "discovery_truncated": False,
        "composition": {"attempted": False, "proven": 0, "rejected": {}, "reason": "not_run"},
        "limits": {"input_bytes": MAX_INPUT_BYTES, "sections": MAX_SECTIONS,
                   "image_bytes": MAX_IMAGE_BYTES, "address_bits": 32,
                   "executable_bytes": MAX_EXECUTABLE_BYTES, "functions": MAX_FUNCTIONS,
                   "function_bytes": MAX_FUNCTION_BYTES, "function_instructions": MAX_FUNCTION_INSTRUCTIONS,
                   "total_code_bytes": MAX_TOTAL_CODE_BYTES,
                   "total_instructions": MAX_TOTAL_INSTRUCTIONS, "stack_bytes": MAX_STACK_BYTES,
                   "composed_functions": MAX_COMPOSED_FUNCTIONS,
                   "composed_instructions": MAX_COMPOSED_INSTRUCTIONS,
                   "composed_bytes": MAX_COMPOSED_BYTES,
                   "arguments": 4},
        "limitations": ["Function discovery is not complete coverage, game identity or game semantics.",
                        "Executable section flags and seed provenance are structural evidence, not a proof against embedded data.",
                        "Input dependency requires data-flow evidence and differing outputs under bounded Python scalar evaluation; this is not a native/differential oracle.",
                        "cdecl-compatible observed argument prefix only; unused trailing parameters remain unknown.",
                        "Composed callers inline proven direct callees only; the summary size is bounded, not a general inliner.",
                        "No prologue scanning, indirect-call recovery, unpacking, loader or original EXE execution."],
    }
    try:
        data, digest, size, changed = _read_source(path)
        report.update(source_sha256=digest, source_size=size)
        if changed:
            raise _Blocked("source_changed_during_read")
        if size > MAX_INPUT_BYTES:
            raise _Blocked("input_exceeds_64_mib")
        if not isinstance(max_functions, int) or isinstance(max_functions, bool) or max_functions <= 0:
            raise _Blocked("invalid_max_functions")
        maximum = min(max_functions, MAX_FUNCTIONS)
        report["limits"]["functions"] = maximum
        sections = _parse_pe(data, report)
        _discover(data, report, sections, maximum)
        report["status"] = "ok"
    except ImportError as exc:
        report["blocked_reason"] = "missing_dependency:" + (exc.name or str(exc))
    except _Blocked as exc:
        report["blocked_reason"] = str(exc)
    except (OSError, ValueError, struct.error, OverflowError) as exc:
        report["blocked_reason"] = "invalid_or_unreadable_input:" + type(exc).__name__ + ":" + str(exc)
    excluded = Counter(m["eligibility"]["reason"] for m in report["modules"] if not m["eligibility"]["eligible"])
    report["candidates"] = [m["id"] for m in report["modules"] if m["eligibility"]["eligible"]]
    report["candidate_count"] = len(report["candidates"])
    report["statistics"] = {"discovered_modules": len(report["modules"]),
                            "candidate_count": report["candidate_count"],
                            "excluded_count": sum(excluded.values()),
                            "exclusion_reasons": dict(sorted(excluded.items()))}
    report["analysis_path"] = str((output_dir / "analysis.json").resolve())
    try:
        _write_report(report, path, output_dir)
    except (_Blocked, OSError, ValueError) as exc:
        report["status"] = "blocked"
        report["blocked_reason"] = str(exc) if isinstance(exc, _Blocked) else "output_write_failed:" + str(exc)
        report["output_written"] = False
    return report

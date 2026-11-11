# -*- coding: utf-8 -*-
"""M0：统一 schema / 状态机 / 错误码（依据 _scratch/强模型方案回复.md §4）。

原则：不完整配置、错误引用、未知枚举不能进入执行；证据不足不是通过。
所有记录带 schema_version；引用产物用内容指纹（sha256）。
"""
import hashlib
import os
import re
from dataclasses import dataclass, field, asdict
from enum import Enum

SCHEMA_VERSION = 1


class SchemaError(ValueError):
    """配置/引用/枚举不合法，禁止进入执行。"""


class Platform(str, Enum):
    NES = "NES"
    ARCADE_FBNEO = "ARCADE_FBNEO"
    ARCADE_MAME = "ARCADE_MAME"
    PS1 = "PS1"
    PSP = "PSP"
    SNES = "SNES"


class ClockUnit(str, Enum):
    EMU_FRAME = "emu_frame"
    INPUT_SAMPLE = "input_sample"
    EMU_TIME = "emu_time"


class StateOrigin(str, Enum):
    NORMAL_PREFIX = "normal_prefix"      # 正常输入构造
    TAS_CHECKPOINT = "tas_checkpoint"    # 已有 TAS 检查点分支
    DISPLAY_PATCH = "display_patch"      # 展示用状态修改（不冒充正常获得）


class Verdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"        # 证据不足，不是通过


class Stage(str, Enum):
    PROFILE = "profile"
    STATE = "state"
    GENERATE = "generate"
    VERIFY = "verify"
    CAPTURE = "capture"
    CUT = "cut"
    EXPORT = "export"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"


class FailureCode(str, Enum):
    MISSING_RESOURCE = "missing_resource"          # 补资源，不进入搜索
    PROFILE_MISMATCH = "profile_mismatch"          # 切换候选 profile
    DETERMINISTIC_DIVERGENCE = "deterministic_divergence"  # 同配置同处失败，定位分歧
    NONDETERMINISM = "nondeterminism"              # 同配置多次结果不同
    CAPTURE_WRONG_SEGMENT = "capture_wrong_segment"  # 只重做采集，不重搜输入
    SEARCH_BUDGET_EXHAUSTED = "search_budget_exhausted"  # 不是"证明无解"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    SCHEMA_INVALID = "schema_invalid"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def asset(path):
    return {"uri": path.replace("\\", "/"), "sha256": sha256_file(path),
            "byte_size": os.path.getsize(path)}


def _enum(val, cls, ctx):
    if isinstance(val, cls):
        return val
    try:
        return cls(val)
    except ValueError:
        raise SchemaError(f"{ctx}: 未知枚举 {val!r}，允许 {[e.value for e in cls]}")


def _req(d, keys, ctx):
    for k in keys:
        v = d.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            raise SchemaError(f"{ctx}: 缺必需字段 {k}")


@dataclass
class CheckSpec:
    check_id: str
    plugin_id: str
    params: dict = field(default_factory=dict)
    required: bool = True

    def validate(self):
        _req(vars(self), ["check_id", "plugin_id"], "CheckSpec")
        if not re.fullmatch(r"[a-z0-9_]+", self.plugin_id):
            raise SchemaError(f"CheckSpec.plugin_id 非法: {self.plugin_id}")
        return self


@dataclass
class CheckResult:
    check_id: str
    verdict: Verdict
    evidence_refs: list = field(default_factory=list)
    event_position: object = None
    reason: str = ""

    def validate(self):
        _req(vars(self), ["check_id"], "CheckResult")
        self.verdict = _enum(self.verdict, Verdict, "CheckResult.verdict")
        return self


@dataclass
class Profile:
    profile_id: str
    game_revision_id: str
    backend_id: str
    platform: Platform
    emulator_fingerprint: str = ""
    core: str = ""
    firmware_fingerprints: list = field(default_factory=list)
    settings_fingerprint: str = ""
    controller_spec: dict = field(default_factory=dict)
    initial_data_fingerprint: str = ""
    rom_sha1: str = ""
    capability_report: dict = field(default_factory=dict)

    def validate(self):
        _req(vars(self), ["profile_id", "game_revision_id", "backend_id"], "Profile")
        self.platform = _enum(self.platform, Platform, "Profile.platform")
        return self


@dataclass
class Element:
    element_id: str
    game_revision_id: str
    kind: str
    sources: list = field(default_factory=list)
    preconditions: list = field(default_factory=list)   # CheckSpec
    state_recipe_ref: str = ""
    action_recipe_ref: str = ""
    success_checks: list = field(default_factory=list)  # CheckSpec
    negative_cases: list = field(default_factory=list)

    def validate(self):
        _req(vars(self), ["element_id", "game_revision_id", "kind"], "Element")
        for c in self.preconditions + self.success_checks:
            c.validate()
        for nc in self.negative_cases:
            if not isinstance(nc, dict) or not nc.get("case_id"):
                raise SchemaError("Element.negative_cases 每项须为含 case_id 的 fixture")
        return self


@dataclass
class State:
    state_id: str
    profile_id: str
    origin: StateOrigin
    blob: object = None
    rebuild_recipe_ref: str = ""
    parent_refs: list = field(default_factory=list)
    clock_position: int = 0
    patches: list = field(default_factory=list)
    precondition_evidence: list = field(default_factory=list)

    def validate(self):
        _req(vars(self), ["state_id", "profile_id"], "State")
        self.origin = _enum(self.origin, StateOrigin, "State.origin")
        return self


@dataclass
class InputPlan:
    plan_id: str
    profile_id: str
    start_ref: str
    clock_unit: ClockUnit = ClockUnit.EMU_FRAME
    segments: list = field(default_factory=list)
    native_events: list = field(default_factory=list)
    source_refs: list = field(default_factory=list)

    def validate(self):
        _req(vars(self), ["plan_id", "profile_id", "start_ref"], "InputPlan")
        self.clock_unit = _enum(self.clock_unit, ClockUnit, "InputPlan.clock_unit")
        return self


@dataclass
class Verification:
    verification_id: str
    subject_ref: str
    stage: Stage
    checks: list = field(default_factory=list)  # CheckResult

    def validate(self):
        _req(vars(self), ["verification_id", "subject_ref"], "Verification")
        self.stage = _enum(self.stage, Stage, "Verification.stage")
        for c in self.checks:
            c.validate()
        return self

    @property
    def verdict(self):
        # 任一 required fail => fail；无 fail 但有 inconclusive/缺证据 => inconclusive
        vs = [c.verdict for c in self.checks]
        if not vs:
            return Verdict.INCONCLUSIVE
        if Verdict.FAIL in vs:
            return Verdict.FAIL
        if Verdict.INCONCLUSIVE in vs:
            return Verdict.INCONCLUSIVE
        return Verdict.PASS


@dataclass
class LedgerJob:
    job_id: str
    stage: Stage
    status: JobStatus = JobStatus.PENDING
    dependency_ids: list = field(default_factory=list)
    idempotency_key: str = ""
    attempt: int = 0
    artifact_refs: list = field(default_factory=list)
    failure_code: object = None
    timestamps: dict = field(default_factory=dict)

    def validate(self):
        _req(vars(self), ["job_id"], "LedgerJob")
        self.stage = _enum(self.stage, Stage, "LedgerJob.stage")
        self.status = _enum(self.status, JobStatus, "LedgerJob.status")
        if self.failure_code is not None:
            self.failure_code = _enum(self.failure_code, FailureCode, "LedgerJob.failure_code")
        return self


def to_dict(obj):
    d = asdict(obj)
    d["schema_version"] = SCHEMA_VERSION
    return d
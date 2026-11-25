# -*- coding: utf-8 -*-
"""M0：统一 schema / 状态机 / 错误码（依据 _scratch/强模型方案回复.md §4）。

原则：不完整配置、错误引用、未知枚举不能进入执行；证据不足不是通过。
所有记录带 schema_version；引用产物用内容指纹（sha256）。
"""
import hashlib
import json
import os
import re
import zipfile
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path


def split_rom_spec(spec):
    """把 `压缩.zip!内部条目` 拆成 (包路径, 条目名)；普通路径返回 (路径, None)。

    ROM 池里大量文件是压缩包内的单条目，逐条寻址才能不改写原包又拿到明文件给模拟器。
    只按最后一个 `.zip!` 切，条目名里再出现的 `!` 保持原样。
    """
    text = str(spec)
    low = text.lower()
    i = low.rfind(".zip!")
    if i < 0:
        return Path(spec), None
    return Path(text[:i + 4]), text[i + 5:]

SCHEMA_VERSION = 1

SNES_CORE_IDENTITIES = {
    "BSNES": {
        "sync_type": "BizHawk.Emulation.Cores.Nintendo.SNES.LibsnesCore+SnesSyncSettings, BizHawk.Emulation.Cores",
        "waterbox": "libsnes.wbx",
    },
    "BSNESv115+": {
        "sync_type": "BizHawk.Emulation.Cores.Nintendo.BSNES.BsnesCore+SnesSyncSettings, BizHawk.Emulation.Cores",
        "waterbox": "bsnes.wbx",
    },
    "Snes9x": {
        "sync_type": "BizHawk.Emulation.Cores.Nintendo.SNES9X.Snes9x+SyncSettings, BizHawk.Emulation.Cores",
        "waterbox": "snes9x.wbx",
    },
}


def core_identity_expectation(system, core):
    identity = SNES_CORE_IDENTITIES.get(core) if system == "SNES" else None
    return dict(identity or {})


def state_sync_settings(path):
    with zipfile.ZipFile(path) as state:
        names = {name.lower(): name for name in state.namelist()}
        if "syncsettings.json" not in names:
            return None
        try:
            value = json.loads(state.read(names["syncsettings.json"]))
        except (ValueError, UnicodeError) as exc:
            raise SchemaError(f"state SyncSettings.json is invalid: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("o"), dict):
        raise SchemaError("state SyncSettings.json must contain an object under o")
    sync_type = value["o"].get("$type")
    if not isinstance(sync_type, str) or not sync_type or "+" not in sync_type or "," not in sync_type:
        raise SchemaError("state SyncSettings.json has no valid CLR $type")
    return value


def adopt_state_sync_settings(sync):
    value = sync["o"]
    sync_type = value["$type"]
    return sync_type.split("+", 1)[0], json.loads(json.dumps(value, allow_nan=False))


def verify_core_identity(expectation, sync, log_text):
    expected_type = expectation.get("sync_type")
    if not expected_type:
        return {"verdict": "unverified", "reason": "requested core has no exact identity expectation"}
    actual_type = (sync or {}).get("o", {}).get("$type")
    if actual_type is not None and actual_type != expected_type:
        return {"verdict": "fail", "expected": expectation, "actual_sync_type": actual_type,
                "reason": "zero-frame state CLR type does not match requested core"}
    waterbox = expectation.get("waterbox")
    mounts = re.findall(r"(?im)^\s*Mouting\s+`([^`]+\.wbx)`", log_text or "")
    if waterbox and waterbox not in mounts:
        return {"verdict": "fail", "expected": expectation, "actual_sync_type": actual_type,
                "waterbox_mounts": mounts, "reason": "runtime log does not prove the expected Waterbox core loaded"}
    conflicting = sorted(set(mounts) - {waterbox})
    if conflicting:
        return {"verdict": "fail", "expected": expectation, "actual_sync_type": actual_type,
                "waterbox_mounts": mounts, "reason": "runtime log contains a different Waterbox core mount"}
    if actual_type is None and not waterbox:
        return {"verdict": "fail", "expected": expectation, "reason": "zero-frame state has no CLR identity"}
    return {"verdict": "pass", "expected": expectation, "actual_sync_type": actual_type,
            "waterbox_mounts": mounts, "evidence": "state CLR type and runtime Waterbox mount",
            "reason": "zero-frame CLR type and runtime Waterbox mount match the requested core"}


class SchemaError(ValueError):
    """配置/引用/枚举不合法，禁止进入执行。"""


class Platform(str, Enum):
    NES = "NES"
    ARCADE_FBNEO = "ARCADE_FBNEO"
    ARCADE_MAME = "ARCADE_MAME"
    PS1 = "PS1"
    PSP = "PSP"
    SNES = "SNES"
    # 下面五个和 retro_platforms.PLATFORM_SPECS 的键一一对应（帧量化/按键表已经写好），
    # 之前 enum 里没有，站点 display name "Genesis"/"GBA"/"GB" 只能落到"平台未建模"。
    GB = "GB"
    GBC = "GBC"
    GBA = "GBA"
    MD = "MD"
    PCE = "PCE"


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
    DRIVER_STALL_MEASURED = "driver_stall_measured"  # 该模拟器版本实测不进放映，连启动都不必试
    EMULATOR_VERSION_ABSENT = "emulator_version_absent"  # 登记的 BizHawk 版本本地没装（不是缺 ROM）
    EMULATOR_VERSION_UNVERIFIED = "emulator_version_unverified"  # bk2 但版本写法不是 BizHawk，需按核心实测选臂
    DRIVER_PLATFORM_UNPROVEN = "driver_platform_unproven"  # 资源齐但控制运行器在该平台没跑过整片，不等于能跑
    EMULATOR_VERSION_INHERITED = "emulator_version_inherited"  # 登记版本没装，改用同 ROM 原生片的臂，待实测确认
    SCHEMA_INVALID = "schema_invalid"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _resource_digest(path, algorithm):
    archive, entry = split_rom_spec(path)
    h = hashlib.new(algorithm)
    if entry is None:
        with open(archive, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    with zipfile.ZipFile(archive) as z, z.open(entry) as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_resource(path):
    return _resource_digest(path, "sha256")


def sha1_resource(path):
    return _resource_digest(path, "sha1")


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
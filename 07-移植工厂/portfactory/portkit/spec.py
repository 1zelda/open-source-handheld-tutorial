from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

FAMILIES = {
    # 开源引擎重编：源码 + 自由素材，玩家拿到就能玩
    "open-engine",
    # 源码级重制/源码移植：引擎自由，商业数据由玩家自备
    "source-port",
    # 官方/社区反编译重建（decomp/recomp）：源码自由，数据自备
    "recomp",
    # 模拟器核心 + 原版镜像：镜像不能随包
    "emulation",
    # 只有商业二进制：走逆向研发，不出成品包
    "binary-research",
}

DATA_POLICIES = {"bundled", "free-download", "user-supplied", "none"}

BUILD_SYSTEMS = {"cmake", "gnumake", "autotools", "meson", "custom"}
PROFILES = {"host", "zig-aarch64", "zig-mingw", "mingw64", "devkitpro"}

# 用户自备数据的默认禁入名单：包内出现就是红线
DEFAULT_FORBIDDEN = [
    "*.grp", "*.rts", "*.mix", "*.mpq", "*.mpq.*", "*.wad", "*.pk3", "*.pk4",
    "*.bsa", "*.ba2", "*.iso", "*.bin", "*.cue", "*.nsp", "*.xci", "*.cia",
    "*.dat", "*.sav", "*.lng.bak",
]

_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class SpecError(ValueError):
    pass


def check_id(value: str) -> str:
    if not _ID.match(str(value or "")):
        raise SpecError(f"id 只能是小写字母/数字/._-：{value!r}")
    return value


def _need(cond: bool, where: str, message: str) -> None:
    if not cond:
        raise SpecError(f"{where}: {message}")


@dataclass
class PortSpec:
    raw: dict
    path: Path | None = None
    warnings: list[str] = field(default_factory=list)

    # ---- 基础字段 ----
    @property
    def id(self) -> str:
        return self.raw["id"]

    @property
    def title(self) -> str:
        return self.raw["title"]

    @property
    def family(self) -> str:
        return self.raw["family"]

    @property
    def source(self) -> dict:
        return self.raw.get("source", {})

    @property
    def data(self) -> dict:
        return self.raw.get("data", {"policy": "none"})

    @property
    def license(self) -> dict:
        return self.raw.get("license", {})

    @property
    def targets(self) -> dict:
        return self.raw["targets"]

    def target(self, name: str) -> dict:
        if name not in self.targets:
            raise SpecError(f"{self.id}: 没有目标 {name}（有：{sorted(self.targets)}）")
        return self.targets[name]

    def forbidden_globs(self) -> list[str]:
        data = self.data
        globs = list(data.get("forbidden", []))
        if data.get("policy") == "user-supplied":
            globs += DEFAULT_FORBIDDEN
        return sorted({g.lower() for g in globs})

    def as_dict(self) -> dict:
        return self.raw


def validate(raw: dict, where: str = "<memory>") -> PortSpec:
    _need(isinstance(raw, dict), where, "spec 必须是对象")
    _need(int(raw.get("schema", 0)) == 1, where, "只支持 schema 1")
    for key in ("id", "title", "family", "targets"):
        _need(key in raw, where, f"缺少字段 {key}")
    check_id(raw["id"])
    _need(raw["family"] in FAMILIES, where, f"未知 family {raw['family']!r}")

    data = raw.get("data", {"policy": "none"})
    _need(data.get("policy") in DATA_POLICIES, where,
          f"data.policy 必须是 {sorted(DATA_POLICIES)}")
    if data["policy"] == "bundled":
        _need(bool(data.get("bundled")), where, "policy=bundled 必须列出 data.bundled")
        _need(bool(data.get("rights_proof")), where,
              "policy=bundled 必须写明 rights_proof（许可/自由版来源）")
    if data["policy"] == "free-download":
        _need(bool(data.get("downloads")), where,
              "policy=free-download 必须列出 data.downloads")
        _need(bool(data.get("rights_proof")), where,
              "policy=free-download 必须写明 rights_proof（为什么可以随包分发）")
        for i, item in enumerate(data["downloads"]):
            w = f"{where}/data.downloads[{i}]"
            _need(bool(item.get("url")), w, "缺 url")
            digest = str(item.get("sha256", "")).lower()
            _need(bool(re.fullmatch(r"[0-9a-f]{64}", digest)), w,
                  "sha256 必须是 64 位十六进制（不钉哈希就不可复现，也不能确认拿到的不是被换过的文件）")
            _need(item.get("format", "zip") in ("zip", "raw"), w, "format 只能是 zip/raw")

    src = raw.get("source", {})
    if raw["family"] in ("open-engine", "source-port", "recomp"):
        _need(bool(src.get("repo") or src.get("local")), where, "需要 source.repo 或 source.local")
        if src.get("repo") or (src.get("local") and (Path(src["local"]) / ".git").exists()):
            _need(bool(re.fullmatch(r"[0-9a-fA-F]{40}", str(src.get("commit", "")))), where,
                  "需要 source.commit（完整的 40 位提交哈希）")

    _need(isinstance(raw["targets"], dict) and raw["targets"], where, "targets 不能为空")
    for name, target in raw["targets"].items():
        w = f"{where}/{name}"
        _need(bool(_ID.fullmatch(name)), w, "目标名称只能是小写字母/数字/._-")
        _need(target.get("profile") in PROFILES, w,
              f"profile 必须是 {sorted(PROFILES)}")
        build = target.get("build") or {}
        _need(build.get("system") in BUILD_SYSTEMS, w,
              f"build.system 必须是 {sorted(BUILD_SYSTEMS)}")
        if build["system"] == "custom":
            _need(bool(build.get("commands")), w, "custom 构建必须给 build.commands")
        if "cache_inputs" in build:
            _need(isinstance(build["cache_inputs"], list) and all(
                isinstance(p, str) and p for p in build["cache_inputs"]), w,
                "build.cache_inputs 必须列出工具链、SDK 和外部构建依赖路径")
        _need(bool(target.get("gates")), w, "target 至少要有一个闸门")
        if raw["family"] in ("open-engine", "source-port", "recomp"):
            _need(bool(build.get("artifact")), w, "需要 build.artifact（产物相对路径）")

    return PortSpec(raw=raw, path=Path(where) if where != "<memory>" else None)


def load_spec(path: str | Path) -> PortSpec:
    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    spec = validate(raw, str(p))
    _check_relatives(spec, p)
    return spec


def _check_relatives(spec: PortSpec, path: Path) -> None:
    """补丁/许可/启动脚本这类随 spec 走的文件必须真的存在，缺失就当场报错。"""
    base = path.parent
    problems = []
    for rel in spec.source.get("patches", []):
        if not (base / rel).is_file():
            problems.append(f"source.patches: {rel}")
    for name, target in spec.targets.items():
        for rel in (target.get("build") or {}).get("patches", []):
            if not (base / rel).is_file():
                problems.append(f"{name}.build.patches: {rel}")
        for entry in (target.get("build") or {}).get("assets", []):
            src = str(entry.get("src", ""))
            if "${data}" in src:
                continue
            if not (base / src).exists():
                problems.append(f"{name}.build.assets: {src}")
        lic = target.get("package", {}).get("license_files", [])
        for rel in lic:
            if not (base / rel).is_file():
                problems.append(f"{name}.package.license_files: {rel}")
    if problems:
        raise SpecError(f"{path}: 随 spec 的文件不存在：{', '.join(problems)}")

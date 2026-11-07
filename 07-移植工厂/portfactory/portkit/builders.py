from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .profiles import Profile

# 宿主机上的 make：先看环境变量，再看 PATH，最后看本项目常用的便携版
MAKE_CANDIDATES = [
    "F:/_scratch/tools/make/bin/make.exe",
    "F:/工具链/make/bin/make.exe",
]


def make_program() -> str:
    value = os.environ.get("PORTFACTORY_MAKE")
    if value and Path(value).is_file():
        return value
    from shutil import which
    found = which("make")
    if found:
        return found
    for candidate in MAKE_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return "make"


@dataclass
class Command:
    cmd: str
    cwd: Path
    env: dict[str, str] = field(default_factory=dict)
    label: str = ""


def _jobs(target: dict) -> int:
    return int(target.get("build", {}).get("jobs") or min(20, os.cpu_count() or 4))


def _paths(target: dict, src: Path, build: Path) -> dict[str, str]:
    return {
        "src": src.as_posix(),
        "build": build.as_posix(),
        "artifact": (build / target["build"]["artifact"]).as_posix()
        if target.get("build", {}).get("artifact") else "",
    }


def common_env(target: dict, profile: Profile, src: Path, build: Path) -> dict[str, str]:
    """所有构建系统共享的加固项。

    这几条是十个端口里反复手工补的，统一放这里：
      * __FILE__ 里不许留构建机路径（-ffile-prefix-map）；
      * 去符号用链接器参数，不依赖 zig 那个空 strip；
      * 交叉编译时不把宿主机库目录混进来。
    """
    env: dict[str, str] = {}
    hardening = target.get("build", {}).get("hardening", True)
    flags = ["-O2"]
    ldflags: list[str] = []
    if hardening:
        flags += [f"-ffile-prefix-map={src.as_posix()}=.",
                  f"-ffile-prefix-map={build.as_posix()}=."]
        ldflags.append("-Wl,--strip-debug")
    env["CFLAGS"] = " ".join(flags)
    env["CXXFLAGS"] = env["CFLAGS"]
    env["LDFLAGS"] = " ".join(ldflags)
    for key, value in (target.get("build", {}).get("env") or {}).items():
        env[key] = str(value)
    if profile.vars.get("sdl2_root"):
        env.setdefault("SDL2_ROOT", profile.vars["sdl2_root"])
    return env


def plan(target: dict, profile: Profile, src: Path, build: Path) -> list[Command]:
    build = build if build.is_absolute() else build
    cfg = target["build"]
    system = cfg["system"]
    jobs = _jobs(target)
    env = common_env(target, profile, src, build)
    vars_ = {**_paths(target, src, build), **cfg.get("vars", {}), **profile.vars}
    vars_ = {k: str(v) for k, v in vars_.items()}
    expand = lambda text: _expand(str(text), vars_)  # noqa: E731

    if system == "cmake":
        build.mkdir(parents=True, exist_ok=True)
        args = [f"-DSDL2_DIR={Path(profile.vars['sdl2_root']) / 'lib' / 'cmake' / 'SDL2'}"
                if profile.vars.get("sdl2_root") and cfg.get("sdl2_dir", True) else "",
                f"-DCMAKE_PREFIX_PATH={profile.vars['sdl2_root']}"
                if profile.vars.get("sdl2_root") else ""]
        args += [expand(a) for a in cfg.get("configure", [])]
        configure = [f'"{profile.cmake}"', "-S", f'"{src.as_posix()}"',
                     "-B", f'"{build.as_posix()}"', "-G", "Ninja",
                     f'-DCMAKE_MAKE_PROGRAM="{profile.ninja}"',
                     "-DCMAKE_SKIP_RPATH=ON", "-DCMAKE_BUILD_TYPE=Release"]
        if profile.toolchain_file:
            configure.append(f'-DCMAKE_TOOLCHAIN_FILE="{profile.toolchain_file.as_posix()}"')
        configure += [a for a in args if a]
        return [
            Command(" ".join(configure), src, env, "cmake configure"),
            Command(f'"{profile.cmake}" --build "{build.as_posix()}" -j {jobs}', src, env,
                    "cmake build"),
        ]

    if system in ("gnumake", "autotools"):
        make = profile.vars.get("make") or make_program()
        make_var = cfg.get("makefile")
        parts = [f'"{make}"', f"-C", f'"{src.as_posix()}"', f"-j {jobs}"]
        if make_var:
            parts.append(f'-f "{make_var}"')
        for key, value in (cfg.get("make_vars") or {}).items():
            parts.append(f'{key}="{_check_var(key, expand(value))}"')
        if cfg.get("target"):
            parts.append(str(cfg["target"]))
        commands = []
        if system == "autotools":
            configure = [f'./configure --host={cfg.get("host", "aarch64-linux-gnu")}']
            configure += [expand(a) for a in cfg.get("configure", [])]
            commands.append(Command(" ".join(configure), src, env, "configure"))
        commands.append(Command(" ".join(parts), src, env, "make"))
        return commands

    if system == "meson":
        return [
            Command(f'meson setup "{build.as_posix()}" "{src.as_posix()}" '
                    + " ".join(expand(a) for a in cfg.get("configure", [])), src, env, "meson"),
            Command(f'ninja -C "{build.as_posix()}" -j {jobs}', src, env, "ninja"),
        ]

    if system == "custom":
        cwd = Path(expand(cfg.get("cwd", src.as_posix())))
        return [Command(expand(c), cwd, env, f"custom {i}")
                for i, c in enumerate(cfg["commands"])]

    raise ValueError(f"未知构建系统：{system}")


def _check_var(name: str, value: str) -> str:
    """本机 mingw make 把 recipe 里的双引号拼坏（实测：-DFOO='"bar"' 会变成一个畸形参数，
    后面整行都被吞进去）。所以 make 变量值里不许带引号，要带引号的宏请走 custom 构建。"""
    if '"' in value:
        raise ValueError(f"build.make_vars.{name} 含双引号：本机 make 的 recipe 撑不住引号，"
                         f"改用 custom 构建（命令直接交给 bash）")
    return value


def _expand(text: str, vars_: dict[str, str]) -> str:
    for key, value in vars_.items():
        text = text.replace("${" + key + "}", value)
    if "${" in text:
        raise ValueError(f"未展开的变量：{text}")
    return text


def artifact_path(target: dict, build: Path, src: Path) -> Path:
    rel = target["build"].get("artifact")
    if not rel:
        raise ValueError("spec 没有声明 build.artifact")
    rel = _expand(rel, {"src": src.as_posix(), "build": build.as_posix()})
    path = Path(rel)
    if path.is_absolute():
        return path
    candidate = build / path
    return candidate if candidate.exists() else src / path

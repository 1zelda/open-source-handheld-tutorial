from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

BUILD_MARKERS = [
    ("cmake", ["CMakeLists.txt"]),
    ("meson", ["meson.build"]),
    ("autotools", ["configure.ac", "configure.in"]),
    ("gnumake", ["GNUmakefile", "Makefile"]),
]

DEP_PATTERNS = [
    ("sdl2", re.compile(rb"#include\s*[<\"]SDL2?/SDL\.h|find_package\s*\(\s*SDL2")),
    ("sdl2-mixer", re.compile(rb"SDL_mixer\.h|SDL2_mixer")),
    ("sdl2-image", re.compile(rb"SDL_image\.h|SDL2_image")),
    ("sdl2-net", re.compile(rb"SDL_net\.h|SDL2_net")),
    ("opengl", re.compile(rb"#include\s*[<\"]GL/gl\.h|find_package\s*\(\s*OpenGL")),
    ("zlib", re.compile(rb"#include\s*<zlib\.h>")),
    ("openal", re.compile(rb"#include\s*<AL/al\.h>")),
]

LICENSE_HINTS = [
    ("GPL-2.0", re.compile(rb"GNU General Public License.*version 2", re.S)),
    ("GPL-3.0", re.compile(rb"GNU General Public License.*version 3", re.S)),
    ("LGPL", re.compile(rb"GNU Lesser General Public", re.S)),
    ("MIT", re.compile(rb"Permission is hereby granted, free of charge", re.S)),
    ("BSD", re.compile(rb"Redistribution and use in source and binary forms", re.S)),
    ("zlib", re.compile(rb"This software is provided 'as-is'", re.S)),
]

TEXT_SUFFIXES = {".c", ".h", ".cpp", ".hpp", ".cc", ".mm", ".mak", ".txt", ".md", ".mk"}
IGNORE_DIRS = {".git", "build", "obj", "_cache", "node_modules"}


def _git(cwd: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                              text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def detect_build_system(root: Path) -> tuple[str | None, Path | None]:
    for system, markers in BUILD_MARKERS:
        for marker in markers:
            if (root / marker).is_file():
                return system, root / marker
    return None, None


def _sample_text(root: Path, limit_files: int = 4000, limit_bytes: int = 40_000_000):
    seen = 0
    total = 0
    for path in root.rglob("*"):
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > 2_000_000:
            continue
        total += size
        seen += 1
        if seen > limit_files or total > limit_bytes:
            return
        yield path


def detect_deps(root: Path) -> list[dict]:
    found: dict[str, list[str]] = {}
    for path in _sample_text(root):
        try:
            blob = path.read_bytes()
        except OSError:
            continue
        for dep, pattern in DEP_PATTERNS:
            if pattern.search(blob):
                found.setdefault(dep, []).append(path.relative_to(root).as_posix())
    return [{"id": dep, "evidence": files[:3]} for dep, files in sorted(found.items())]


def detect_license(root: Path) -> dict:
    for name in ("LICENSE", "LICENSE.txt", "LICENSE.md", "COPYING", "COPYING.txt"):
        path = root / name
        if path.is_file():
            blob = path.read_bytes()[:200_000]
            for label, pattern in LICENSE_HINTS:
                if pattern.search(blob):
                    return {"engine": label, "file": name}
            return {"engine": "unknown", "file": name}
    return {"engine": "unknown", "file": None}


def draft(root: str | Path, spec_id: str, title: str | None = None,
          family: str = "source-port") -> dict:
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(root)
    system, marker = detect_build_system(root)
    repo = _git(root, "remote", "get-url", "origin")
    commit = _git(root, "rev-parse", "HEAD")
    deps = detect_deps(root)
    license_info = detect_license(root)

    build: dict = {"system": system or "custom", "artifact": "TODO/填产物相对路径",
                   "hardening": True}
    if system == "gnumake":
        build["makefile"] = marker.name if marker else "Makefile"
        build["target"] = "TODO"
        build["make_vars"] = {}
    elif system == "cmake":
        build["configure"] = []
    elif system == "custom":
        build["commands"] = ["TODO"]

    warnings = []
    if not repo or not commit:
        warnings.append("源码不是 git 仓库：source 只能写 local，版本不可复现")
    if system is None:
        warnings.append("没识别出构建系统：需要手写 build.commands")
    if license_info["engine"] == "unknown":
        warnings.append("没识别出许可：必须先确认引擎许可，再决定能不能随包分发")
    warnings.append("数据政策默认 user-supplied：确认是否真有自由素材可随包")

    draft_spec = {
        "schema": 1,
        "id": spec_id,
        "title": title or spec_id,
        "family": family,
        "source": {
            "repo": repo or "TODO",
            "commit": commit or "TODO",
            "patches": [],
        },
        "license": license_info,
        "data": {"policy": "user-supplied", "required": ["TODO"], "bundled": []},
        "targets": {
            "handheld": {
                "profile": "zig-aarch64",
                "arch": "aarch64",
                "min_glibc": "2.29",
                "deps": deps,
                "build": build,
                "gates": ["elf", "no_build_paths", "portmaster_layout",
                          "data_policy", "licenses", "deterministic_zip", "screenshot"],
                "package": {
                    "platform": "portmaster",
                    "port_dir": spec_id,
                    "launcher_file": f"{spec_id}.sh",
                    "zip_name": f"{spec_id}.zip",
                    "attr": {
                        "title": title or spec_id,
                        "desc": "TODO",
                        "inst": "TODO：说明玩家要把哪些数据放在哪里",
                        "genres": ["TODO"],
                        "porter": ["教程示例"],
                        "image": {},
                        "rtr": False,
                        "exp": False,
                        "runtime": [],
                        "min_glibc": "2.29",
                        "reqs": [],
                        "arch": ["aarch64"],
                    },
                    "license_files": [],
                },
            }
        },
        "_draft": {
            "detected_build": system,
            "marker": str(marker) if marker else None,
            "deps": deps,
            "warnings": warnings,
        },
    }
    return draft_spec


def write(draft_spec: dict, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(draft_spec, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    return out

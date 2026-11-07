from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

from ..intake import sha256_file


class CacheError(ValueError):
    pass


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def files(root: Path) -> list[Path]:
    if root.is_symlink() or root.is_junction():
        raise CacheError(f"快照不接受链接：{root}")
    root = root.resolve()
    if not root.is_dir():
        raise CacheError(f"目录不存在：{root}")
    result = []
    for base, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d != ".git")
        for name in dirs + names:
            path = Path(base) / name
            if name == ".git":
                continue
            if path.is_symlink() or path.is_junction():
                raise CacheError(f"快照不接受链接，请声明真实文件目录：{path}")
        result.extend(Path(base) / name for name in sorted(names) if name != ".git")
    return sorted(result)


def stamp(path: Path) -> dict:
    path = Path(path).absolute()
    if path.is_symlink() or path.is_junction():
        raise CacheError(f"快照不接受链接：{path}")
    path = path.resolve()
    if path.is_file():
        return {"path": str(path), "size": path.stat().st_size, "sha256": sha256_file(path)}
    if path.is_dir():
        entries = [{"path": p.relative_to(path).as_posix(), "size": p.stat().st_size,
                    "sha256": sha256_file(p)} for p in files(path)]
        return {"path": str(path), "sha256": digest(entries), "files": len(entries)}
    raise CacheError(f"依赖或产物不存在：{path}")


def unchanged(records: list[dict]) -> bool:
    try:
        return bool(records) and all(stamp(Path(r["path"])) == r for r in records)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def copy_source(source: Path, dest: Path) -> None:
    for path in files(source):
        out = dest / path.relative_to(source.resolve())
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, out)


def resolve_tool(program: str, shell: str, env: dict[str, str]) -> Path | None:
    candidate = Path(program)
    if candidate.is_file():
        return candidate.resolve()
    script = f"p=$(command -v {shlex.quote(program)}) || exit 1; " \
             'if command -v cygpath >/dev/null 2>&1; then cygpath -w "$p"; else printf "%s\\n" "$p"; fi'
    result = subprocess.run([shell, "-lc", script], env=env, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=30)
    if result.returncode:
        return None
    candidate = Path(result.stdout.strip())
    return candidate.resolve() if candidate.is_file() else None


def tool_identity(profile, target: dict, shell: str) -> dict:
    env = profile.child_env(os.environ)
    cfg = target["build"]
    programs = {"shell": shell}
    if cfg["system"] != "custom":
        programs.update(cc=profile.vars.get("cc") or env.get("CC") or "cc",
                        cxx=profile.vars.get("cxx") or env.get("CXX") or "c++")
    if profile.vars.get("zig"):
        programs["zig"] = profile.vars["zig"]
    if cfg["system"] == "cmake":
        programs.update(cmake=profile.cmake, ninja=profile.ninja)
    elif cfg["system"] in ("gnumake", "autotools"):
        from .builders import make_program
        programs["make"] = profile.vars.get("make") or make_program()
    elif cfg["system"] == "meson":
        programs.update(meson="meson", ninja="ninja")
    records = {}
    for label, program in programs.items():
        path = resolve_tool(program, shell, env)
        records[label] = stamp(path) if path else {"missing": program}
    if profile.toolchain_file:
        records["toolchain"] = stamp(profile.toolchain_file)
    if profile.bin_dir:
        for path in profile.bin_dir.iterdir():
            if path.is_file() and not path.suffix:
                records[path.name] = stamp(path)
    return {"profile": profile.id, "tools": records,
            "environment": digest(env), "vars": digest(profile.vars),
            "complete": all("missing" not in item for item in records.values())}

from __future__ import annotations

import os
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# 本机既有布局，找不到时再看环境变量
ZIG_CANDIDATES = [
    "F:/工具链/zig-x86_64-windows-0.17.0/zig.exe",
    "F:/工具链/zig-0.17.0/zig.exe",
]
MINGW_CANDIDATES = ["F:/_scratch/tools/mingw/mingw64"]
# cmake/ninja 不装进系统 PATH 也能用：pip 装的 venv、便携版都认
CMAKE_CANDIDATES = [
    "F:/_scratch/portfactory_env/Scripts/cmake.exe",
    "F:/工具链/cmake/bin/cmake.exe",
]
NINJA_CANDIDATES = [
    "F:/_scratch/portfactory_env/Scripts/ninja.exe",
    "F:/工具链/ninja/ninja.exe",
]


class ProfileError(RuntimeError):
    """工具链缺件 —— 属于阻塞，不是构建失败。"""


@dataclass
class Profile:
    id: str
    env: dict[str, str] = field(default_factory=dict)
    bin_dir: Path | None = None
    toolchain_file: Path | None = None
    cmake: str = "cmake"
    ninja: str = "ninja"
    vars: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    shell: str | None = None

    def child_env(self, base: dict[str, str] | None = None) -> dict[str, str]:
        env = dict(base or os.environ)
        if self.bin_dir is not None:
            env["PATH"] = str(self.bin_dir) + os.pathsep + env.get("PATH", "")
        env.update(self.env)
        return env


def _which(name: str, extra: list[str] | None = None) -> str | None:
    for candidate in extra or []:
        if Path(candidate).is_file():
            return candidate
    from shutil import which
    return which(name)


def _write_exe(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.replace("\r\n", "\n").encode("utf-8")
    if path.is_file() and path.read_bytes() == data:
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return
    path.write_bytes(data)
    try:
        path.chmod(0o755)
    except OSError:
        pass


def _zig() -> str:
    zig = os.environ.get("PORTFACTORY_ZIG") or _which("zig", ZIG_CANDIDATES)
    if not zig:
        raise ProfileError("找不到 zig：设 PORTFACTORY_ZIG 或在 F:/工具链 下装 zig 0.17.0")
    return zig.replace("\\", "/")


def _mingw_root() -> Path:
    root = os.environ.get("PORTFACTORY_MINGW") or next(
        (p for p in MINGW_CANDIDATES if Path(p, "bin", "gcc.exe").is_file()), None)
    if not root or not Path(root, "bin", "gcc.exe").is_file():
        raise ProfileError("找不到 mingw-w64：设 PORTFACTORY_MINGW 指向含 bin/gcc.exe 的目录")
    return Path(root)


def _hooks_dir(cache: Path, profile_id: str) -> Path:
    return cache / "profiles" / profile_id


def _shim_zig(profile_id: str, cache: Path, target_triple: str) -> Profile:
    """zig 交叉编译垫片。

    踩过的坑（十个端口里反复出现）都固化在这里：
      * Windows 宿主上 `-L F:/x -lSDL2` 会被拼成 `-l:F:\\x`，所以 sdl2-config 只输出 .so 全路径；
      * C++ 头文件只有 `zig c++` 驱动才会挂上（`zig cc -x c++` 找不到 <limits>）；
      * zig 自带 mingw libc 缺 POSIX 符号，Windows 验证构建优先用真正的 mingw64 档案。
    """
    zig = _zig()
    bin_dir = _hooks_dir(cache, profile_id) / "bin"
    for name in ("gcc", "cc", "clang"):
        _write_exe(bin_dir / name, f'#!/bin/sh\nexec "{zig}" cc -target {target_triple} "$@"\n')
    for name in ("g++", "c++", "clang++"):
        _write_exe(bin_dir / name, f'#!/bin/sh\nexec "{zig}" c++ -target {target_triple} "$@"\n')
    _write_exe(bin_dir / "ar", f'#!/bin/sh\nexec "{zig}" ar "$@"\n')
    _write_exe(bin_dir / "ranlib", f'#!/bin/sh\nexec "{zig}" ranlib "$@"\n')
    _write_exe(bin_dir / "strip", "#!/bin/sh\nexit 0\n")

    notes = [
        "zig 的 strip 桩是空操作：去符号统一用链接参数 -Wl,--strip-debug",
        "cmake 工程必须 -DCMAKE_SKIP_RPATH=ON，否则 -DXXX_LIBRARY=绝对路径会写进 RPATH",
    ]
    profile = Profile(id=profile_id, bin_dir=bin_dir, notes=notes)
    profile.vars["zig"] = zig
    profile.vars["cc"] = str(bin_dir / "gcc")
    profile.vars["cxx"] = str(bin_dir / "g++")
    return profile


def _sdl2_root(env_var: str = "PORTFACTORY_SDL2") -> Path | None:
    value = os.environ.get(env_var)
    if value and Path(value).is_dir():
        return Path(value)
    for guess in ("F:/_scratch/sdl2_aarch64", "F:/_scratch/cnc_build/sdl2"):
        if Path(guess, "include", "SDL2", "SDL.h").is_file():
            return Path(guess)
    return None


def _cmake_program() -> str:
    value = os.environ.get("PORTFACTORY_CMAKE")
    if value and Path(value).is_file():
        return value
    for candidate in CMAKE_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return _which("cmake") or "cmake"


def _ninja_program() -> str:
    value = os.environ.get("PORTFACTORY_NINJA")
    if value and Path(value).is_file():
        return value
    for candidate in NINJA_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return _which("ninja") or "ninja"


def _tools(profile: Profile) -> Profile:
    profile.cmake = _cmake_program()
    profile.ninja = _ninja_program()
    return profile


def materialize(profile_id: str, cache: Path, needs_sdl2: bool = True) -> Profile:
    cache = Path(cache)
    if profile_id == "host":
        return _tools(Profile(id="host"))

    if profile_id == "zig-aarch64":
        profile = _shim_zig(profile_id, cache, "aarch64-linux-gnu")
        toolchain = _hooks_dir(cache, profile_id) / "aarch64.cmake"
        toolchain.write_text(AARCH64_CMAKE.replace("@CC@", profile.vars["cc"])
                             .replace("@CXX@", profile.vars["cxx"]), encoding="utf-8")
        profile.toolchain_file = toolchain
        sdl2 = _sdl2_root()
        if needs_sdl2:
            if sdl2 is None:
                raise ProfileError("找不到 aarch64 版 SDL2 头/库：设 PORTFACTORY_SDL2 指向前缀目录")
            lib = next((p for p in (sdl2 / "lib" / "aarch64-linux-gnu", sdl2 / "lib")
                        if (p / "libSDL2.so").is_file()), None)
            if lib is None:
                raise ProfileError(f"{sdl2} 下没有 libSDL2.so")
            # Debian 的 SDL_config.h 打开了 X11 视频后端，编译期就会要 X11 头；有就带上
            inc = f"-I{(sdl2 / 'include' / 'SDL2').as_posix()} -D_REENTRANT"
            if (sdl2 / "x11" / "include" / "X11" / "Xlib.h").is_file():
                inc += f" -I{(sdl2 / 'x11' / 'include').as_posix()}"
            so_path = (lib / "libSDL2.so").as_posix()
            # 坑：Windows 宿主 zig 会把 -L + -lSDL2 拼坏，只能给 .so 全路径
            _write_exe(_hooks_dir(cache, profile_id) / "bin" / "sdl2-config",
                       "#!/bin/sh\n"
                       'case "$1" in\n'
                       f'  --cflags) echo "{inc}" ;;\n'
                       f'  --libs|--static-libs) echo "{so_path}" ;;\n'
                       "  --version) echo 2.26.5 ;;\n"
                       f'  --prefix) echo "{sdl2.as_posix()}" ;;\n'
                       "  *) exit 1 ;;\n"
                       "esac\n")
            # pkg-config 垫片：上游工程常直接问 pkg-config 要 SDL2。
            # 只能承认 sdl2；说"别的也有"会让配置脚本去编 ALSA/PNG 那些宿主机才有的后端。
            _write_exe(_hooks_dir(cache, profile_id) / "bin" / "pkg-config",
                       "#!/bin/sh\n"
                       'other=0\n'
                       'for a in "$@"; do\n'
                       '  case "$a" in\n'
                       '    -*) ;;\n'
                       '    [Ss][Dd][Ll]2|[Ss][Dd][Ll]2[_-]2.0) ;;\n'
                       '    *) other=1 ;;\n'
                       '  esac\n'
                       'done\n'
                       '[ "$other" = 1 ] && exit 1\n'
                       'for a in "$@"; do\n'
                       '  case "$a" in\n'
                       f'    --cflags) echo "{inc}" ;;\n'
                       f'    --libs) echo "{so_path}" ;;\n'
                       # 有些工程的链接行只取 --libs-only-l，拼成 -lSDL2 就找不到交叉编译版，
                       # 这里直接吐 .so 全路径（gcc/clang 都接受全路径输入）
                       f'    --libs-only-l) echo "{so_path}" ;;\n'
                       '    --libs-only-L|--libs-only-other) echo "" ;;\n'
                       '    --modversion) echo 2.26.5 ;;\n'
                       '    --exists|--atleast-version=*) exit 0 ;;\n'
                       '  esac\n'
                       'done\n'
                       'case "$*" in *--version*) echo 2.26.5 ;; esac\n'
                       "exit 0\n")
            profile.vars["sdl2_root"] = str(sdl2)
        profile.notes.append("-ffile-prefix-map 去掉 __FILE__ 里的构建机路径；自检会查残留")
        return _tools(profile)

    if profile_id == "zig-mingw":
        profile = _shim_zig(profile_id, cache, "x86_64-windows-gnu")
        # .rc 资源：zig 没有 windres，用空 COFF 顶替（图标/版本信息与运行无关）
        _write_exe(profile.bin_dir / "windres", WINDRES_STUB.format(zig=profile.vars["zig"]))
        profile.notes.append("zig 自带 mingw libc 缺 strndup/mempcpy/pthread_spin_* 等符号，"
                             "只在没有 mingw64 时兜底")
        return _tools(profile)

    if profile_id == "mingw64":
        root = _mingw_root()
        profile = Profile(id="mingw64", bin_dir=root / "bin")
        profile.vars["cc"] = str(root / "bin" / "gcc.exe")
        profile.vars["cxx"] = str(root / "bin" / "g++.exe")
        return _tools(profile)

    if profile_id == "devkitpro":
        root = os.environ.get("DEVKITPRO") or next(
            (p for p in ("F:/devkitPro", "C:/devkitPro") if Path(p, "devkitA64").is_dir()), None)
        if not root or not Path(root, "devkitA64", "bin").is_dir():
            raise ProfileError("Switch 目标需要 devkitPro：设 DEVKITPRO 指到含 devkitA64 的目录")
        root = Path(root).as_posix()
        msys_bash = f"{root}/msys2/usr/bin/bash.exe"
        if not Path(msys_bash).is_file():
            raise ProfileError(f"devkitPro 缺 msys2 shell：{msys_bash}")
        # 关键：msys2 的程序从 Git Bash 启动时收不到环境变量（实测连 FOO 都丢），
        # 构建必须跑在 devkitPro 自己的 msys2 bash 里，路径也换成 msys 视角的 /opt/devkitpro。
        prefix = "/opt/devkitpro" if Path(root).resolve() == Path("F:/devkitPro").resolve() else root
        posix_path = (f"{prefix}/devkitA64/bin:{prefix}/tools/bin:"
                      f"{prefix}/portlibs/switch/bin:/usr/bin:/bin")
        profile = Profile(id="devkitpro", shell=msys_bash,
                          env={"DEVKITPRO": prefix, "DEVKITARM": f"{prefix}/devkitA64",
                               "DEVKITA64": f"{prefix}/devkitA64",
                               "PORTLIBS": f"{prefix}/portlibs/switch",
                               "LIBNX": f"{prefix}/libnx",
                               "PATH": posix_path})
        profile.vars["make"] = "make"
        profile.vars["cc"] = f"{root}/devkitA64/bin/aarch64-none-elf-gcc.exe"
        profile.vars["cxx"] = f"{root}/devkitA64/bin/aarch64-none-elf-g++.exe"
        profile.notes.append("构建跑在 devkitPro 的 msys2 bash 里（Git Bash 启动的 msys 程序收不到环境变量）")
        profile.notes.append("devkitPro 在中文路径下会乱码，构建目录必须是纯英文")
        return _tools(profile)

    raise ProfileError(f"未知工具链档案：{profile_id}")


AARCH64_CMAKE = """\
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)
set(CMAKE_C_COMPILER "@CC@")
set(CMAKE_CXX_COMPILER "@CXX@")
set(CMAKE_LIBRARY_ARCHITECTURE aarch64-linux-gnu)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
"""

WINDRES_STUB = """\
#!/bin/sh
out=""
prev=""
for a in "$@"; do
  if [ "$prev" = "-o" ]; then out="$a"; fi
  prev="$a"
done
[ -n "$out" ] || exit 1
tmp="${TMPDIR:-/tmp}/rcstub_$$.c"
printf 'int rcstub;\\n' > "$tmp"
exec "{zig}" cc -target x86_64-windows-gnu -c "$tmp" -o "$out"
"""


def describe(profile: Profile) -> str:
    parts = [f"档案 {profile.id}"]
    if profile.bin_dir:
        parts.append(f"垫片目录 {profile.bin_dir}")
    if profile.toolchain_file:
        parts.append(f"cmake 工具链 {profile.toolchain_file}")
    return " / ".join(parts)


def probe(bin_dir: Path | None, program: str, shell: str | None = None,
          env: dict[str, str] | None = None) -> str | None:
    exe = program
    if bin_dir is not None:
        candidate = Path(bin_dir) / program
        if candidate.is_file():
            exe = str(candidate)
    argv = ([shell, "-lc", f"{exe} --version"] if shell else [exe, "--version"])
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=60, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    line = (proc.stdout or proc.stderr).splitlines()
    return line[0].strip() if line else None

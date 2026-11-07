#!/bin/bash
# Diablo（DevilutionX 1.6.0-dev, aa3dc7b1）-> aarch64 端口包的完整可复现构建
# 用法: 在 Git Bash 里 bash build.sh            # 交叉编译 + 组装 + 打包 + 自检
#       VERIFY_WIN=1 bash build.sh .. 需要 SDL2WIN=<mingw SDL2 前缀>  # 额外编 Windows 版做实跑验证
# 依赖: zig 0.17.0、cmake 3.31、ninja、git、curl、python（只用标准库）
#
# 两条硬教训（踩过）：
#   1) 构建根目录必须是纯 ASCII。CMake 生成的 .bat 会把"cmake 自己的安装路径"写成 UTF-8，
#      cmd 用 cp936 读，中文路径直接"系统找不到指定的路径"。所以 cmake 也复制一份到 ASCII 路径再调。
#   2) libpng 的生成脚本直接调 ${CMAKE_C_COMPILER} -E，而 zig 需要先给 cc/c++ 子命令，
#      所以 C/CXX 编译器都换成 .cmd 包装器。
set -e
set -o pipefail

Z="${ZIG:-/f/_scratch/zigwin/zig.exe}"
NJ="${NINJA:-/f/_scratch/tools/ninja/ninja.exe}"
HERE="$(cd "$(dirname "$0")" && pwd)"
B="/f/_scratch/devx_build"          # 纯 ASCII 构建根
S="$B/devilutionx_src"
P="$B/sdl2"                          # aarch64 SDL2 前缀（只借头文件 + 链接用 so，运行时用 CFW 自带）
CM_SRC="/f/工具链/cmake-3.31.6/cmake-3.31.6-windows-x86_64/bin/cmake.exe"
CM_ASCII="/f/_scratch/tools/cmake-dist/bin/cmake.exe"

mkdir -p "$B" "$B/bin"
# 整份 cmake 挪到 ASCII 路径（只复制第一次）
if [ ! -x "$CM_ASCII" ]; then
  mkdir -p "$(dirname "$CM_ASCII")"
  cp -r "$(dirname "$(dirname "$CM_SRC")")" /f/_scratch/tools/cmake-dist
fi
CM="${CMAKE:-$CM_ASCII}"

# 上游固定版本（2026-10 快照）
DEVX_COMMIT=aa3dc7b10e35abaad57548f0fca6ed94e8f4d611
SDL2_VER=2.26.5+dfsg-1

# ---- 源码 ----
if [ ! -d "$S/.git" ]; then
  mkdir -p "$S"; cd "$S"
  git init -q
  git remote add origin https://github.com/diasurgical/devilutionX.git
  git fetch -q --depth 1 origin "$DEVX_COMMIT"
  git checkout -q FETCH_HEAD
fi
[ "$(git -C "$S" rev-parse HEAD)" = "$DEVX_COMMIT" ] || { echo "源码不是钉住的 commit"; exit 1; }
cd "$B"

# ---- SDL2：Debian arm64 的 runtime + dev 两个包，只当"头文件 + 链接垫片" ----
# 设备上用的是 CFW 自带的 libSDL2-2.0.so.0，包里不带本体；这里钉 2.26.5 保证编出来的 API 面不比它新
for d in libsdl2-2.0-0 libsdl2-dev; do
  f="${d}_${SDL2_VER}_arm64.deb"
  [ -f "$f" ] || curl -sSL -o "$f" "http://ftp.debian.org/debian/pool/main/libs/libsdl2/$f"
done
mkdir -p "$P/include/SDL2" "$P/lib/aarch64-linux-gnu" "$P/bin"
python -X utf8 - "libsdl2-2.0-0_${SDL2_VER}_arm64.deb" "libsdl2-dev_${SDL2_VER}_arm64.deb" "$P" <<'PY'
import io, os, sys, tarfile
rt, dv, out = sys.argv[1], sys.argv[2], sys.argv[3]

def members(deb):
    b = open(deb, 'rb').read(); p = 8
    while p + 60 <= len(b):
        h = b[p:p+60]; name = h[:16].decode().strip(); size = int(h[48:58])
        if name.startswith('data.tar'):
            return tarfile.open(fileobj=io.BytesIO(b[p+60:p+60+size]))
        p += 60 + size + (size % 2)
    raise SystemExit('no data.tar in ' + deb)

def put(tf, m, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, 'wb') as f:
        f.write(tf.extractfile(m).read())

libdir = os.path.join(out, 'lib', 'aarch64-linux-gnu')
incdir = os.path.join(out, 'include', 'SDL2')
for tf in (members(rt), members(dv)):
    for m in tf.getmembers():
        if not m.isfile():
            continue
        n = m.name
        # 运行库：so.0 带完整版本号的那份，改名成 soname
        if '/libSDL2-2.0.so.0.' in n:
            put(tf, m, os.path.join(libdir, 'libSDL2-2.0.so.0'))
        # 头文件（dev 包把真正的 config 放在 /usr/include/aarch64-linux-gnu/SDL2/）
        elif '/usr/include/SDL2/' in n or '/usr/include/aarch64-linux-gnu/SDL2/' in n:
            put(tf, m, os.path.join(incdir, os.path.basename(n)))
        # 链接垫片 libSDL2main.a（winmain 那层在 Linux 上没用，但 CMake 会去找）
        elif n.startswith('./usr/lib/aarch64-linux-gnu/libSDL2') and n.endswith('.a'):
            put(tf, m, os.path.join(libdir, os.path.basename(n)))
        elif '/lib/aarch64-linux-gnu/cmake/SDL2/' in n:
            put(tf, m, os.path.join(libdir, 'cmake', 'SDL2', os.path.basename(n)))
PY
# dev 包的 SDL_config.h 只是 #include "_real_SDL_config.h" 的中转，交叉场景下展平
if [ -f "$P/include/SDL2/_real_SDL_config.h" ]; then
  cp -f "$P/include/SDL2/_real_SDL_config.h" "$P/include/SDL2/SDL_config.h"
fi
# sdl2-config.cmake 用 set_and_check 校验前缀里的 bin/，给个空目录就够
[ -f "$P/lib/aarch64-linux-gnu/libSDL2.so" ] || cp -f "$P/lib/aarch64-linux-gnu/libSDL2-2.0.so.0" "$P/lib/aarch64-linux-gnu/libSDL2.so"
mkdir -p "$P/bin"

# ---- 编译器包装 + 工具链文件 ----
printf '@echo off\r\n"%s" cc %%*\r\n' "$(cygpath -w "$Z")" > "$B/bin/zigcc.cmd"
printf '@echo off\r\n"%s" c++ %%*\r\n' "$(cygpath -w "$Z")" > "$B/bin/zigcxx.cmd"

cat > "$B/aarch64.cmake" <<EOF
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)

set(ZIG "$(cygpath -m "$Z")")
# 用 .cmd 包装: libpng 的生成脚本会直接调 \${CMAKE_C_COMPILER} -E，拿不到 ARG1
set(CMAKE_C_COMPILER "$(cygpath -m "$B")/bin/zigcc.cmd")
set(CMAKE_CXX_COMPILER "$(cygpath -m "$B")/bin/zigcxx.cmd")

# Ninja 不认 CMAKE_AR_ARG1：把 ar/ranlib 子命令直接写进归档规则
set(CMAKE_AR "\${ZIG}")
set(CMAKE_RANLIB "\${ZIG}")
foreach(_l C CXX)
  set(CMAKE_\${_l}_ARCHIVE_CREATE "<CMAKE_AR> ar qc <TARGET> <LINK_FLAGS> <OBJECTS>")
  set(CMAKE_\${_l}_ARCHIVE_APPEND "<CMAKE_AR> ar q <TARGET> <LINK_FLAGS> <OBJECTS>")
  set(CMAKE_\${_l}_ARCHIVE_FINISH "<CMAKE_RANLIB> ranlib <TARGET>")
endforeach()

set(ZIG_TARGET "-target aarch64-linux-gnu")
set(CMAKE_C_FLAGS_INIT "\${ZIG_TARGET}")
set(CMAKE_CXX_FLAGS_INIT "\${ZIG_TARGET}")
set(CMAKE_EXE_LINKER_FLAGS_INIT "\${ZIG_TARGET} -Wl,-s")
set(CMAKE_SHARED_LINKER_FLAGS_INIT "\${ZIG_TARGET} -Wl,-s")

set(SDL2_ROOT "$(cygpath -m "$P")")
set(CMAKE_PREFIX_PATH "\${SDL2_ROOT}")
set(SDL2_DIR "\${SDL2_ROOT}/lib/aarch64-linux-gnu/cmake/SDL2" CACHE PATH "")

set(CMAKE_FIND_ROOT_PATH "$(cygpath -m "$P")")
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
EOF

# ---- 配置 + 编译 ----
# 关键开关：
#   NONET=ON                    不链 libsodium（单人游戏用不上，省掉一整个加密栈）
#   DEVILUTIONX_SYSTEM_ZLIB/BZIP2=OFF  用 FetchContent 拉源码自己编（设备上没这两个 dev 包）
#   BUILD_ASSETS_MPQ=OFF        直接把 assets/ 目录发出去，不用 devilutionx.mpq
#   BUILD_MOD_MPQS=OFF          不带 Hellfire 资料片的 mod 包（那是另一份商业数据）
#   PALETTE_TRANSPARENCY_BLACK_16_LUT=ON  上游默认值；关掉会在 primitive_render.cpp 撞到编不过的分支
mkdir -p "$B/cross"
# 构建目录里残留的是别的源码树的 cache 时，CMake 会拒绝配置（"does not match the source"）
if [ -f "$B/cross/CMakeCache.txt" ] && ! grep -q "DevilutionX_SOURCE_DIR:STATIC=$(cygpath -m "$S")\$" "$B/cross/CMakeCache.txt"; then
  rm -rf "$B/cross"
  mkdir -p "$B/cross"
fi
"$CM" -S "$S" -B "$B/cross" -G Ninja \
  -DCMAKE_MAKE_PROGRAM="$NJ" \
  -DCMAKE_TOOLCHAIN_FILE="$(cygpath -m "$B")/aarch64.cmake" \
  -DCMAKE_BUILD_TYPE=Release \
  -DNONET=ON -DBUILD_TESTING=OFF -DDISABLE_LTO=ON \
  -DBUILD_ASSETS_MPQ=OFF -DBUILD_MOD_MPQS=OFF \
  -DDEVILUTIONX_PALETTE_TRANSPARENCY_BLACK_16_LUT=ON \
  -DLIBM=m -DDEVILUTIONX_SYSTEM_ZLIB=OFF -DDEVILUTIONX_SYSTEM_BZIP2=OFF \
  2>&1 | tail -20
"$NJ" -C "$B/cross" 2>&1 | tail -5

# ---- 组装端口包 ----
PKG="$HERE/package/diablo"
cp -f "$B/cross/devilutionx" "$PKG/devilutionx.aarch64"
rm -rf "$PKG/assets"
mkdir -p "$PKG/assets"
cp -r "$B/cross/assets/." "$PKG/assets/"
[ -f "$PKG/assets/ASSETS_VERSION" ] || { echo "assets 不完整"; exit 1; }
echo "== 二进制 $(stat -c%s "$PKG/devilutionx.aarch64") B / assets $(find "$PKG/assets" -type f | wc -l) 个文件"
# licenses/、port.json、gameinfo.xml、LICENSES.txt、screenshot.png 是随包文本，直接沿用仓库里的

# ---- 确定性打包 ----
cd "$HERE"
python -X utf8 - "$HERE" <<'PY'
import hashlib, os, sys, zipfile
here = sys.argv[1]
root = os.path.join(here, 'package')
out = os.path.join(root, 'Diablo.zip')
files = [('Diablo.sh', os.path.join(root, 'Diablo.sh'))]
for dp, dn, fn in os.walk(os.path.join(root, 'diablo')):
    dn.sort(); fn.sort()
    for f in fn:
        full = os.path.join(dp, f)
        files.append((os.path.relpath(full, root).replace(os.sep, '/'), full))
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for arc, full in files:
        zi = zipfile.ZipInfo(arc, (2026, 10, 28, 0, 0, 0))
        zi.create_system = 3
        zi.external_attr = (0o100755 if arc.endswith('.sh') else 0o100644) << 16
        zi.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(zi, open(full, 'rb').read(), compresslevel=9)
b = open(out, 'rb').read()
print('Diablo.zip', len(b), 'B', hashlib.sha256(b).hexdigest())
PY
python -X utf8 check_port.py "package/Diablo.zip"

# ---- 可选：Windows 版实跑验证（只验"引擎能不能吃分享版数据"，不进包） ----
# 需要一个 mingw x86_64 的 SDL2 前缀: SDL2WIN=/f/_scratch/q3win/sdl2/SDL2-2.30.9/x86_64-w64-mingw32
if [ "${VERIFY_WIN:-0}" = "1" ]; then
  : "${SDL2WIN:?VERIFY_WIN=1 时要给 SDL2WIN=<mingw SDL2 前缀>}"
  WIN="$B/win"
  printf '@echo off\r\n"%s" cc -target x86_64-windows-gnu %%*\r\n' "$(cygpath -w "$Z")" > "$B/bin/zigccw.cmd"
  printf '@echo off\r\n"%s" c++ -target x86_64-windows-gnu %%*\r\n' "$(cygpath -w "$Z")" > "$B/bin/zigcxxw.cmd"
  printf '@echo off\r\n"%s" ar %%*\r\n' "$(cygpath -w "$Z")" > "$B/bin/zig-ar.cmd"
  printf '@echo off\r\n"%s" ranlib %%*\r\n' "$(cygpath -w "$Z")" > "$B/bin/zig-ranlib.cmd"
  # 资源文件只影响图标/版本号，用空对象顶替（zig 的 ld 不认 mingw 那套 --undefined）
  echo 'int _empty_rc;' > "$B/bin/empty_rc.c"
  "$Z" cc -target x86_64-windows-gnu -c "$B/bin/empty_rc.c" -o "$B/bin/empty_rc.obj"
  cat > "$B/bin/windres.cmd" <<EOF
@echo off
set LAST=
:loop
if "%1"=="" goto done
set LAST=%1
shift
goto loop
:done
copy /y "$(cygpath -w "$B/bin/empty_rc.obj")" "%LAST%" >nul
EOF
  # SDL2main 里塞了 -Wl,--undefined=WinMain，zig 的链接器只接受 --undefined 之外的写法，
  # 直接在验证副本里把这半句删掉（只影响 Windows 验证版，不影响 aarch64 包）
  rm -rf "$B/sdl2win"; cp -r "$SDL2WIN" "$B/sdl2win"
  python -X utf8 - "$B/sdl2win/lib/cmake/SDL2/SDL2mainTargets.cmake" <<'PY'
import sys
p = sys.argv[1]
lines = open(p, encoding='utf-8').read().splitlines(True)
hit = [i for i, l in enumerate(lines) if 'undefined=WinMain' in l]
assert hit, '没找到 WinMain 那半句'
for i in hit:
    lines[i] = '  INTERFACE_LINK_LIBRARIES "\\$<LINK_ONLY:shell32>"\n'
open(p, 'w', encoding='utf-8', newline='').write(''.join(lines))
PY
  cat > "$B/windows.cmake" <<EOF
set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR x86_64)
set(CMAKE_C_COMPILER "$(cygpath -m "$B")/bin/zigccw.cmd")
set(CMAKE_CXX_COMPILER "$(cygpath -m "$B")/bin/zigcxxw.cmd")
set(CMAKE_AR "$(cygpath -m "$B")/bin/zig-ar.cmd")
set(CMAKE_RANLIB "$(cygpath -m "$B")/bin/zig-ranlib.cmd")
foreach(_l C CXX)
  set(CMAKE_\${_l}_ARCHIVE_CREATE "<CMAKE_AR> ar qc <TARGET> <LINK_FLAGS> <OBJECTS>")
  set(CMAKE_\${_l}_ARCHIVE_APPEND "<CMAKE_AR> ar q <TARGET> <LINK_FLAGS> <OBJECTS>")
  set(CMAKE_\${_l}_ARCHIVE_FINISH "<CMAKE_RANLIB> ranlib <TARGET>")
endforeach()
set(_T "-target x86_64-windows-gnu")
set(CMAKE_C_FLAGS_INIT "\${_T}")
set(CMAKE_CXX_FLAGS_INIT "\${_T}")
set(CMAKE_EXE_LINKER_FLAGS_INIT "\${_T} -lws2_32 -lwinmm -limm32 -lversion -lsetupapi -liphlpapi")
set(CMAKE_SHARED_LINKER_FLAGS_INIT "\${_T}")
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE NEVER)
set(CMAKE_RC_COMPILER "$(cygpath -m "$B")/bin/windres.cmd")
set(CMAKE_RC_COMPILE_OBJECT "<CMAKE_RC_COMPILER> -O coff -o <OBJECT> <SOURCE>")
set(SDL2_DIR "$(cygpath -m "$B")/sdl2win/lib/cmake/SDL2" CACHE PATH "")
EOF
  mkdir -p "$WIN"
  "$CM" -S "$S" -B "$WIN" -G Ninja \
    -DCMAKE_MAKE_PROGRAM="$NJ" \
    -DCMAKE_TOOLCHAIN_FILE="$(cygpath -m "$B")/windows.cmake" \
    -DCMAKE_BUILD_TYPE=Release \
    -DNONET=ON -DBUILD_TESTING=OFF -DDISABLE_LTO=ON \
    -DBUILD_ASSETS_MPQ=OFF -DBUILD_MOD_MPQS=OFF \
    -DDEVILUTIONX_SYSTEM_ZLIB=OFF -DDEVILUTIONX_SYSTEM_BZIP2=OFF 2>&1 | tail -5
  "$NJ" -C "$WIN" 2>&1 | tail -3
  echo "== Windows 版在 $WIN/devilutionx.exe；把分享版 spawn.mpq 放进 assets 同级目录再双击，可验到标题画面/进游戏"
fi

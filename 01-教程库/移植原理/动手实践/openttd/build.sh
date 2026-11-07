#!/bin/bash
# OpenTTD（运输大亨豪华版）-> aarch64 端口包的完整可复现构建
# 用法: 在 Git Bash 里 bash build.sh
#       只编不打包: SKIP_ZIP=1 bash build.sh
#       顺带编一个 Windows 同源版做实跑验证: WIN_VERIFY=1 bash build.sh
# 依赖: zig 0.17.0、cmake 3.31、ninja、git、curl、python（只用标准库）
#
# 产出的包结构:
#   OpenTTD.zip
#   ├── OpenTTD.sh              启动脚本（HOME 指进包目录，便携存档）
#   └── openttd/
#       ├── port.json / gameinfo.xml / LICENSES.txt / screenshot.png
#       ├── licenses/           引擎与素材的许可原文
#       ├── openttd.aarch64     主程序（SDL2 后端，libc++ 静态链入）
#       ├── openttd.gptk        左摇杆当鼠标（配 PortMaster 自带的 gptokeyb）
#       ├── lang/               语言表（没它就报 "No available language packs" 直接退出）
#       └── baseset/            OpenGFX / OpenSFX / OpenMSX 三套自由素材
#
# 四个坑（踩过）：
#   1) 交叉编译需要宿主 strgen。语言表是 strgen 生成的，宿主工具不能用 aarch64 编译器编，
#      得先用 zig 编一个 Windows 版 strgen，再把 -DHOST_BINARY_DIR 指过去。
#   2) zig 的 clang 默认 -Werror=date-time，而 OpenTTD 的 rev.cpp 故意嵌 __DATE__，
#      要显式 -Wno-error=date-time。
#   3) zig + libc++ 编 fmt 时缺 <cstdlib>（malloc/free 未声明），全局 -include cstdlib。
#   4) zig 前面挂 CMake 的 PCH，lld 会报 "unknown file type"，要关预编译头。
set -e
set -o pipefail

Z="${ZIG:-/f/_scratch/zigwin/zig.exe}"
NJ="${NINJA:-/f/_scratch/tools/ninja/ninja.exe}"
HERE="$(cd "$(dirname "$0")" && pwd)"
B="${BUILD_ROOT:-/f/_scratch/ottd_build}"
S="$B/ottd_src"
SDL="$B/sdl2"
CM_SRC="/f/工具链/cmake-3.31.6/cmake-3.31.6-windows-x86_64/bin/cmake.exe"
CM_ASCII="/f/_scratch/tools/cmake-dist/bin/cmake.exe"

# 上游固定版本
OTTD_TAG=15.3
OTTD_COMMIT=14ec60f248547d4d062a1160f0fc26d742319888
SDL2_VER=2.26.5+dfsg-1

# 自由素材（可再分发），版本 + sha256 都钉死
GFX_URL=https://cdn.openttd.org/opengfx-releases/7.1/opengfx-7.1-all.zip
GFX_SHA=928fcf34efd0719a3560cbab6821d71ce686b6315e8825360fba87a7a94d7846
SFX_URL=https://cdn.openttd.org/opensfx-releases/1.0.3/opensfx-1.0.3-all.zip
SFX_SHA=e0a218b7dd9438e701503b0f84c25a97c1c11b7c2f025323fb19d6db16ef3759
MSX_URL=https://cdn.openttd.org/openmsx-releases/0.4.2/openmsx-0.4.2-all.zip
MSX_SHA=5a4277a2e62d87f2952ea5020dc20fb2f6ffafdccf9913fbf35ad45ee30ec762

mkdir -p "$B" "$B/bin"
if [ ! -x "$CM_ASCII" ]; then
  mkdir -p "$(dirname "$CM_ASCII")"
  cp -r "$(dirname "$(dirname "$CM_SRC")")" /f/_scratch/tools/cmake-dist
fi
CM="${CMAKE:-$CM_ASCII}"

# ---- 编译器包装 + 工具链文件（Linux/aarch64 与 Windows 各一份）----
printf '@echo off\r\n"%s" cc %%*\r\n' "$(cygpath -w "$Z")" > "$B/bin/zigcc.cmd"
printf '@echo off\r\n"%s" c++ %%*\r\n' "$(cygpath -w "$Z")" > "$B/bin/zigcxx.cmd"
printf '@echo off\r\n"%s" cc -target x86_64-windows-gnu %%*\r\n' "$(cygpath -w "$Z")" > "$B/bin/zigcc_win.cmd"
printf '@echo off\r\n"%s" c++ -target x86_64-windows-gnu %%*\r\n' "$(cygpath -w "$Z")" > "$B/bin/zigcxx_win.cmd"

toolchain() {  # $1 = 目标名(aarch64|win64) $2 = ZIG_TARGET $3 = 额外 CXX 参数
  cat > "$B/$1.cmake" <<EOF
set(CMAKE_SYSTEM_NAME $([ "$1" = aarch64 ] && echo Linux || echo Windows))
set(CMAKE_SYSTEM_PROCESSOR $([ "$1" = aarch64 ] && echo aarch64 || echo x86_64))

set(ZIG "$(cygpath -m "$Z")")
set(CMAKE_C_COMPILER "$(cygpath -m "$B")/bin/zigcc$([ "$1" = aarch64 ] || echo _win).cmd")
set(CMAKE_CXX_COMPILER "$(cygpath -m "$B")/bin/zigcxx$([ "$1" = aarch64 ] || echo _win).cmd")

set(CMAKE_AR "\${ZIG}")
set(CMAKE_RANLIB "\${ZIG}")
foreach(_l C CXX)
  set(CMAKE_\${_l}_ARCHIVE_CREATE "<CMAKE_AR> ar qc <TARGET> <LINK_FLAGS> <OBJECTS>")
  set(CMAKE_\${_l}_ARCHIVE_APPEND "<CMAKE_AR> ar q <TARGET> <LINK_FLAGS> <OBJECTS>")
  set(CMAKE_\${_l}_ARCHIVE_FINISH "<CMAKE_RANLIB> ranlib <TARGET>")
endforeach()

set(ZIG_TARGET "$2")
set(CMAKE_C_FLAGS_INIT "\${ZIG_TARGET} -ffile-prefix-map=$(cygpath -m "$S")=. -ffile-prefix-map=$(cygpath -m "$B")=.")
set(CMAKE_CXX_FLAGS_INIT "\${ZIG_TARGET}$3 -ffile-prefix-map=$(cygpath -m "$S")=. -ffile-prefix-map=$(cygpath -m "$B")=.")
set(CMAKE_EXE_LINKER_FLAGS_INIT "\${ZIG_TARGET}$([ "$1" = aarch64 ] && echo ' -Wl,-s')")
EOF
}
# 说明：-Wno-error=date-time 是因为 rev.cpp 故意嵌 __DATE__；-include cstdlib 是 zig/libc++ 的 fmt 坑
toolchain aarch64 "-target aarch64-linux-gnu" " -Wno-error=date-time -include cstdlib"
toolchain win64 "-target x86_64-windows-gnu" " -Wno-error=date-time -include cstdlib"

SHARED_FLAGS=(-DCMAKE_BUILD_TYPE=Release -DCMAKE_DISABLE_PRECOMPILE_HEADERS=ON -DOPTION_INSTALL_FHS=OFF)

# ---- SDL2：Debian arm64 的 runtime + dev 包，只当"头文件 + 链接垫片" ----
# 设备上用 CFW 自带的 libSDL2-2.0.so.0，包里不带本体
SDL2_DEB_DIR="${SDL2_DEB_DIR:-$B/debs}"
SDL2_SHA256="7d875b119108a240015e7739c7a0de402616975281bcd8169cb434326fa93a66
b69722e33bdce9102c8608a648a9969c7e9e03bdb9c894f1ba441f9229d3e273"
mkdir -p "$SDL2_DEB_DIR"
i=0
for d in libsdl2-2.0-0 libsdl2-dev; do
  f="$SDL2_DEB_DIR/${d}_${SDL2_VER}_arm64.deb"
  want=$(echo "$SDL2_SHA256" | sed -n "$((i+1))p"); i=$((i+1))
  if [ ! -s "$f" ]; then
    curl -fsSL -o "$f" "http://ftp.debian.org/debian/pool/main/libs/libsdl2/${d}_${SDL2_VER}_arm64.deb" || rm -f "$f"
  fi
  [ -s "$f" ] || { echo "拿不到 $f。联网下不了的话，手动把 Debian arm64 的 $d ${SDL2_VER} 包放进去再跑"; exit 1; }
  echo "$want  $f" | sha256sum -c - >/dev/null || { echo "$f 的 sha256 不对"; exit 1; }
done
mkdir -p "$SDL/include/SDL2" "$SDL/lib/aarch64-linux-gnu"
python -X utf8 - "$(cygpath -m "$SDL2_DEB_DIR")/libsdl2-2.0-0_${SDL2_VER}_arm64.deb" \
  "$(cygpath -m "$SDL2_DEB_DIR")/libsdl2-dev_${SDL2_VER}_arm64.deb" "$(cygpath -m "$SDL")" <<'PY'
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
        if '/libSDL2-2.0.so.0.' in n:
            put(tf, m, os.path.join(libdir, 'libSDL2-2.0.so.0'))
        elif '/usr/include/SDL2/' in n or '/usr/include/aarch64-linux-gnu/SDL2/' in n:
            put(tf, m, os.path.join(incdir, os.path.basename(n)))
        elif n.startswith('./usr/lib/aarch64-linux-gnu/libSDL2') and n.endswith('.a'):
            put(tf, m, os.path.join(libdir, os.path.basename(n)))
        elif '/lib/aarch64-linux-gnu/cmake/SDL2/' in n:
            put(tf, m, os.path.join(libdir, 'cmake', 'SDL2', os.path.basename(n)))
PY
if [ -f "$SDL/include/SDL2/_real_SDL_config.h" ]; then
  cp -f "$SDL/include/SDL2/_real_SDL_config.h" "$SDL/include/SDL2/SDL_config.h"
fi
[ -f "$SDL/lib/aarch64-linux-gnu/libSDL2.so" ] || cp -f "$SDL/lib/aarch64-linux-gnu/libSDL2-2.0.so.0" "$SDL/lib/aarch64-linux-gnu/libSDL2.so"
SDL2_DIR="$(cygpath -m "$SDL")/lib/aarch64-linux-gnu/cmake/SDL2"

# ---- 源码 ----
if [ ! -d "$S/.git" ]; then
  if [ -n "${OTTD_MIRROR:-}" ]; then
    git clone -q --shared "$OTTD_MIRROR" "$S"
    git -C "$S" checkout -q "$OTTD_COMMIT"
  else
    mkdir -p "$S"; cd "$S"
    git init -q
    git remote add origin https://github.com/OpenTTD/OpenTTD.git
    git fetch -q --depth 1 origin "refs/tags/$OTTD_TAG:refs/tags/$OTTD_TAG"
    git checkout -q "$OTTD_TAG"
  fi
fi
[ "$(git -C "$S" rev-parse HEAD)" = "$OTTD_COMMIT" ] || { echo "源码不是钉住的 commit"; exit 1; }

# ---- 宿主 strgen（语言表生成器）----
if [ ! -f "$B/host/strgen.cmake" ]; then
  "$CM" -S "$S" -B "$B/host" -G Ninja \
    -DCMAKE_MAKE_PROGRAM="$NJ" \
    -DCMAKE_TOOLCHAIN_FILE="$(cygpath -m "$B")/win64.cmake" \
    "${SHARED_FLAGS[@]}" -DOPTION_TOOLS_ONLY=ON 2>&1 | tail -3
  "$NJ" -C "$B/host" 2>&1 | tail -2
fi
[ -f "$B/host/src/strgen/strgen.exe" ] || { echo "宿主 strgen 没编出来"; exit 1; }

# ---- 交叉编译主程序 ----
if [ "${PACKAGE_ONLY:-0}" = "1" ]; then
  # 只重新组装/打包，用现成的 $B/build/openttd（改 port.json、换素材时才用得上）
  [ -s "$B/build/openttd" ] || { echo "PACKAGE_ONLY=1 但 $B/build/openttd 不存在，去掉这个变量重跑"; exit 1; }
  echo "== PACKAGE_ONLY=1，跳过交叉编译"
else
rm -rf "$B/build"
"$CM" -S "$S" -B "$B/build" -G Ninja \
  -DCMAKE_MAKE_PROGRAM="$NJ" \
  -DCMAKE_TOOLCHAIN_FILE="$(cygpath -m "$B")/aarch64.cmake" \
  "${SHARED_FLAGS[@]}" -DCMAKE_SKIP_RPATH=ON \
  -DGLOBAL_DIR=/usr/share/games/openttd \
  -DSDL2_DIR="$SDL2_DIR" \
  -DHOST_BINARY_DIR="$(cygpath -m "$B")/host" 2>&1 | tail -6
"$NJ" -C "$B/build" 2>&1 | tail -3
[ -s "$B/build/openttd" ] || { echo "openttd 没编出来"; exit 1; }
fi

# ---- 自由素材（缓存在 $B/sets，带 sha256）----
SETS="$B/sets"
mkdir -p "$SETS"
fetch() {  # $1=url $2=sha $3=输出名
  f="$SETS/$3"
  if [ ! -s "$f" ]; then curl -fsSL -o "$f" "$1" || rm -f "$f"; fi
  [ -s "$f" ] || { echo "拿不到 $1（联网下不了就手动放进 $SETS/）"; exit 1; }
  echo "$2  $f" | sha256sum -c - >/dev/null || { echo "$f 的 sha256 不对"; exit 1; }
}
fetch "$GFX_URL" "$GFX_SHA" opengfx-7.1-all.zip
fetch "$SFX_URL" "$SFX_SHA" opensfx-1.0.3-all.zip
fetch "$MSX_URL" "$MSX_SHA" openmsx-0.4.2-all.zip

# ---- 组装端口包 ----
PKG="$HERE/package/openttd"
mkdir -p "$PKG/baseset" "$PKG/lang"
cp -f "$B/build/openttd" "$PKG/openttd.aarch64"
# 语言表是 strgen 从 src/lang/*.txt 生成的，编完在 build/lang；只带中英日韩，全带要多 13 MB
for f in english english_US simplified_chinese traditional_chinese japanese korean; do
  cp -f "$B/build/lang/$f.lng" "$PKG/lang/"
done
python -X utf8 - "$(cygpath -m "$SETS")" "$(cygpath -m "$PKG/baseset")" <<'PY'
import io, os, sys, tarfile, zipfile
sets, dst = sys.argv[1], sys.argv[2]
for z in ('opengfx-7.1-all.zip', 'opensfx-1.0.3-all.zip', 'openmsx-0.4.2-all.zip'):
    zf = zipfile.ZipFile(os.path.join(sets, z))
    tar = tarfile.open(fileobj=io.BytesIO(zf.read(zf.namelist()[0])))
    tar.extractall(dst, filter='data')
    print('== 解出', zf.namelist()[0])
PY
echo "== openttd $(stat -c%s "$PKG/openttd.aarch64") B / baseset $(du -sh "$PKG/baseset" | cut -f1)"

[ "${SKIP_ZIP:-0}" = "1" ] && { echo "== SKIP_ZIP=1，不打包"; exit 0; }

# ---- 确定性打包 ----
cd "$HERE"
python -X utf8 - "$HERE" <<'PY'
import hashlib, os, sys, zipfile
here = sys.argv[1]
root = os.path.join(here, 'package')
out = os.path.join(root, 'OpenTTD.zip')
files = [('OpenTTD.sh', os.path.join(root, 'OpenTTD.sh'))]
for dp, dn, fn in os.walk(os.path.join(root, 'openttd')):
    dn.sort(); fn.sort()
    for f in fn:
        full = os.path.join(dp, f)
        files.append((os.path.relpath(full, root).replace(os.sep, '/'), full))
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for arc, full in files:
        zi = zipfile.ZipInfo(arc, (2026, 10, 29, 0, 0, 0))
        zi.create_system = 3
        zi.external_attr = (0o100755 if arc.endswith('.sh') else 0o100644) << 16
        zi.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(zi, open(full, 'rb').read(), compresslevel=9)
b = open(out, 'rb').read()
print('OpenTTD.zip', len(b), 'B', hashlib.sha256(b).hexdigest())
PY
python -X utf8 check_port.py "package/OpenTTD.zip"

# ---- 可选的 Windows 同源验证构建 ----
if [ "${WIN_VERIFY:-0}" = "1" ]; then
  printf 'int otddres_stub;\n' > "$B/empty.c"
  "$Z" cc -target x86_64-windows-gnu -c "$B/empty.c" -o "$B/empty_rc.obj"
  # 只给本机验证构建用：.rc 里只有图标/版本信息，换成空 COFF 对象；必须 CRLF + 纯 ASCII，否则 cmd 解析崩
  python -X utf8 - "$(cygpath -w "$B/empty_rc.obj")" "$(cygpath -w "$B/bin/rcstub.cmd")" <<'PY'
import sys
src, dst = sys.argv[1], sys.argv[2]
lines = ['@echo off', 'set OUT=', ':loop', 'if "%~1"=="" goto done',
         'if /I "%~1"=="-o" (set OUT=%~2 & shift & shift & goto loop)',
         'if /I "%~1"=="/fo" (set OUT=%~2 & shift & shift & goto loop)',
         'if /I "%~1"=="-fo" (set OUT=%~2 & shift & shift & goto loop)',
         'shift', 'goto loop', ':done',
         'copy /y "%s" "%%OUT%%" >nul' % src, '']
open(dst, 'wb').write('\r\n'.join(lines).encode('ascii'))
PY
  rm -rf "$B/win"
  "$CM" -S "$S" -B "$B/win" -G Ninja \
    -DCMAKE_MAKE_PROGRAM="$NJ" \
    -DCMAKE_TOOLCHAIN_FILE="$(cygpath -m "$B")/win64.cmake" \
    -DCMAKE_RC_COMPILER="$(cygpath -m "$B")/bin/rcstub.cmd" \
    "${SHARED_FLAGS[@]}" -DHOST_BINARY_DIR="$(cygpath -m "$B")/host" 2>&1 | tail -3
  "$NJ" -C "$B/win" 2>&1 | tail -2
  echo "== Windows 验证版: $B/win/openttd.exe"
fi

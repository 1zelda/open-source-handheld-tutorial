#!/bin/bash
# Vanilla Conquer（C&C 黄金版 + 红色警戒 1 引擎重制）-> aarch64 端口包的完整可复现构建
# 用法: 在 Git Bash 里 bash build.sh
#       只编不打包: SKIP_ZIP=1 bash build.sh
# 依赖: zig 0.17.0、cmake 3.31、ninja、git、curl、python（只用标准库）、make 不需要
#
# 产出的包结构:
#   Cnc.zip
#   ├── Tiberian Dawn.sh      启动 C&C
#   ├── Red Alert.sh          启动 RA
#   └── cnc/
#       ├── port.json / gameinfo.xml / LICENSES.txt / screenshot.png
#       ├── licenses/         引擎与库的许可原文
#       ├── libs.aarch64/     libopenal.so.1（CFW 不带 OpenAL，必须随包）
#       ├── td/               vanillatd.aarch64 + 玩家自备的 MIX
#       └── ra/               vanillara.aarch64 + 玩家自备的 MIX
#
# 三条硬教训（踩过）：
#   1) 构建根目录必须纯 ASCII。CMake 生成的脚本会把 cmake 自己的安装路径按 UTF-8 写进 .bat，
#      cmd 用 cp936 读，中文路径直接"系统找不到指定的路径"。
#   2) OpenAL Soft 只钉 1.24.2。master 已经切到 C++20 modules，zig 的 libc++ 编不过。
#   3) zig 用 libc++ 时 <cstdlib> 里的 operator new 声明要靠 -include cstdlib 提前拉进来，
#      否则 OpenAL 的 al::vector 会报 "no matching operator new"。
set -e
set -o pipefail

Z="${ZIG:-/f/_scratch/zigwin/zig.exe}"
NJ="${NINJA:-/f/_scratch/tools/ninja/ninja.exe}"
HERE="$(cd "$(dirname "$0")" && pwd)"
B="${BUILD_ROOT:-/f/_scratch/cnc_build}"     # 纯 ASCII 构建根
S="$B/vc_src"                                 # Vanilla Conquer 源码
OAL_SRC="$B/openal_src"
OAL_PREFIX="$B/oal"                           # aarch64 OpenAL 安装前缀
SDL="$B/sdl2"                                 # aarch64 SDL2 头文件 + 链接垫片
CM_SRC="/f/工具链/cmake-3.31.6/cmake-3.31.6-windows-x86_64/bin/cmake.exe"
CM_ASCII="/f/_scratch/tools/cmake-dist/bin/cmake.exe"

# 上游固定版本（2026-10 快照）
VC_COMMIT=ce83b59edd99cccac6cebaae054ca04962c744b7
OAL_TAG=1.24.2
OAL_COMMIT=b621b5fce739525418f36e0474a46f9e1cab5e64
SDL2_VER=2.26.5+dfsg-1

mkdir -p "$B" "$B/bin"
# 整份 cmake 挪到 ASCII 路径（只复制第一次）
if [ ! -x "$CM_ASCII" ]; then
  mkdir -p "$(dirname "$CM_ASCII")"
  cp -r "$(dirname "$(dirname "$CM_SRC")")" /f/_scratch/tools/cmake-dist
fi
CM="${CMAKE:-$CM_ASCII}"

# ---- 编译器包装 + 工具链文件 ----
printf '@echo off\r\n"%s" cc %%*\r\n' "$(cygpath -w "$Z")" > "$B/bin/zigcc.cmd"
printf '@echo off\r\n"%s" c++ %%*\r\n' "$(cygpath -w "$Z")" > "$B/bin/zigcxx.cmd"

cat > "$B/aarch64.cmake" <<EOF
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)

set(ZIG "$(cygpath -m "$Z")")
# 用 .cmd 包装: 有的生成脚本会直接调 \${CMAKE_C_COMPILER} -E，拿不到 ARG1
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

set(CMAKE_FIND_ROOT_PATH "$(cygpath -m "$SDL");$(cygpath -m "$OAL_PREFIX")")
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
EOF

# ---- SDL2：Debian arm64 的 runtime + dev 两个包，只当"头文件 + 链接垫片" ----
# 设备上用的是 CFW 自带的 libSDL2-2.0.so.0，包里不带本体；这里钉 2.26.5 保证编出来的 API 面不比它新
# 两个包按 sha256 钉死；下不动就把它们放进 $SDL2_DEB_DIR（默认 $B/debs）再跑
SDL2_DEB_DIR="${SDL2_DEB_DIR:-$B/debs}"
SDL2_SHA256="7d875b119108a240015e7739c7a0de402616975281bcd8169cb434326fa93a66
b69722e33bdce9102c8608a648a9969c7e9e03bdb9c894f1ba441f9229d3e273"
mkdir -p "$SDL2_DEB_DIR"
cd "$B"
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
SDL2_DEB_DIR_W="$(cygpath -m "$SDL2_DEB_DIR")"
mkdir -p "$SDL/include/SDL2" "$SDL/lib/aarch64-linux-gnu" "$SDL/bin"
python -X utf8 - "$SDL2_DEB_DIR_W/libsdl2-2.0-0_${SDL2_VER}_arm64.deb" "$SDL2_DEB_DIR_W/libsdl2-dev_${SDL2_VER}_arm64.deb" "$(cygpath -m "$SDL")" <<'PY'
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
# dev 包的 SDL_config.h 只是 #include "_real_SDL_config.h" 的中转，交叉场景下展平
if [ -f "$SDL/include/SDL2/_real_SDL_config.h" ]; then
  cp -f "$SDL/include/SDL2/_real_SDL_config.h" "$SDL/include/SDL2/SDL_config.h"
fi
[ -f "$SDL/lib/aarch64-linux-gnu/libSDL2.so" ] || cp -f "$SDL/lib/aarch64-linux-gnu/libSDL2-2.0.so.0" "$SDL/lib/aarch64-linux-gnu/libSDL2.so"

# ---- OpenAL Soft：CFW 里没有，必须随包；钉 1.24.2 ----
# 没网时用 OAL_MIRROR=<本地已有仓库（路径即可）> 顶替上游地址，后面照样校验 commit
if [ ! -d "$OAL_SRC/.git" ]; then
  if [ -n "${OAL_MIRROR:-}" ]; then
    git clone -q --shared "$OAL_MIRROR" "$OAL_SRC"
    git -C "$OAL_SRC" checkout -q "$OAL_COMMIT"
  else
    mkdir -p "$OAL_SRC"; cd "$OAL_SRC"
    git init -q
    git remote add origin https://github.com/kcat/openal-soft.git
    git fetch -q --depth 1 origin "refs/tags/$OAL_TAG:refs/tags/$OAL_TAG"
    git checkout -q "$OAL_TAG"
  fi
fi
[ "$(git -C "$OAL_SRC" rev-parse HEAD)" = "$OAL_COMMIT" ] || { echo "OpenAL 源码不是钉住的 commit"; exit 1; }

mkdir -p "$B/oal_build"
"$CM" -S "$OAL_SRC" -B "$B/oal_build" -G Ninja \
  -DCMAKE_MAKE_PROGRAM="$NJ" \
  -DCMAKE_TOOLCHAIN_FILE="$(cygpath -m "$B")/aarch64.cmake" \
  -DCMAKE_BUILD_TYPE=Release \
  -DLIBTYPE=SHARED -DALSOFT_UTILS=OFF -DALSOFT_EXAMPLES=OFF -DALSOFT_TESTS=OFF \
  -DCMAKE_SKIP_RPATH=ON \
  -DCMAKE_CXX_FLAGS="-target aarch64-linux-gnu -include cstdlib" \
  -DCMAKE_INSTALL_PREFIX="$(cygpath -m "$OAL_PREFIX")" \
  2>&1 | tail -5
"$NJ" -C "$B/oal_build" 2>&1 | tail -3
"$CM" --install "$B/oal_build" >/dev/null
[ -f "$OAL_PREFIX/lib/libopenal.so.1" ] || { echo "OpenAL 没装出来"; exit 1; }

# ---- Vanilla Conquer 源码 + 三个渲染补丁 ----
if [ ! -d "$S/.git" ]; then
  if [ -n "${VC_MIRROR:-}" ]; then
    git clone -q --shared "$VC_MIRROR" "$S"
    git -C "$S" checkout -q "$VC_COMMIT"
  else
    mkdir -p "$S"; cd "$S"
    git init -q
    git remote add origin https://github.com/TheAssemblyArmada/Vanilla-Conquer.git
    git fetch -q --depth 1 origin "$VC_COMMIT"
    git checkout -q FETCH_HEAD
  fi
fi
[ "$(git -C "$S" rev-parse HEAD)" = "$VC_COMMIT" ] || { echo "源码不是钉住的 commit"; exit 1; }
# fixes.patch: 交错插值调色板两个 bug + 淡出 RemapTables 越界，细节见 README
if git -C "$S" apply --reverse --check "$HERE/fixes.patch" 2>/dev/null; then
  echo "== 补丁已在源码树里"
else
  git -C "$S" apply "$HERE/fixes.patch"
  echo "== 已应用 fixes.patch"
fi

# ---- 配置 + 编译 ----
#   NETWORKING=OFF        局域网对战用不到，省掉一整套 Winsock/加密
#   DDRAW/DSOUND=OFF      只走 SDL2 + OpenAL 这条跨平台路径
#   MAP_EDITOR*=OFF       地图编辑器是 32 位 Win32 工具，跟掌机无关
mkdir -p "$B/vc_build"
if [ -f "$B/vc_build/CMakeCache.txt" ] && ! grep -q "CMAKE_HOME_DIRECTORY:INTERNAL=$(cygpath -m "$S")\$" "$B/vc_build/CMakeCache.txt"; then
  rm -rf "$B/vc_build"; mkdir -p "$B/vc_build"
fi
"$CM" -S "$S" -B "$B/vc_build" -G Ninja \
  -DCMAKE_MAKE_PROGRAM="$NJ" \
  -DCMAKE_TOOLCHAIN_FILE="$(cygpath -m "$B")/aarch64.cmake" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PREFIX_PATH="$(cygpath -m "$OAL_PREFIX")" \
  -DSDL2_INCLUDE_DIR="$(cygpath -m "$SDL")/include/SDL2" \
  -DSDL2_LIBRARY="$(cygpath -m "$SDL")/lib/aarch64-linux-gnu/libSDL2.so" \
  -DBUILD_VANILLATD=ON -DBUILD_VANILLARA=ON \
  -DBUILD_REMASTERTD=OFF -DBUILD_REMASTERRA=OFF \
  -DBUILD_TESTS=OFF -DBUILD_TOOLS=OFF \
  -DCMAKE_SKIP_RPATH=ON \
  -DMAP_EDITORTD=OFF -DMAP_EDITORRA=OFF \
  -DNETWORKING=OFF -DOPENAL=ON -DDDRAW=OFF -DDSOUND=OFF \
  2>&1 | tail -20
"$NJ" -C "$B/vc_build" 2>&1 | tail -5

# ---- 组装端口包 ----
PKG="$HERE/package/cnc"
mkdir -p "$PKG/td" "$PKG/ra" "$PKG/libs.aarch64"
cp -f "$B/vc_build/vanillatd" "$PKG/td/vanillatd.aarch64"
cp -f "$B/vc_build/vanillara" "$PKG/ra/vanillara.aarch64"
cp -f "$OAL_PREFIX/lib/libopenal.so.1.24.2" "$PKG/libs.aarch64/libopenal.so.1"
echo "== vanillatd $(stat -c%s "$PKG/td/vanillatd.aarch64") B / vanillara $(stat -c%s "$PKG/ra/vanillara.aarch64") B"
echo "== libopenal $(stat -c%s "$PKG/libs.aarch64/libopenal.so.1") B"
# port.json / gameinfo.xml / LICENSES.txt / licenses/ / screenshot.png / 数据说明 都是随包文本，沿用仓库里的

[ "${SKIP_ZIP:-0}" = "1" ] && { echo "== SKIP_ZIP=1，不打包"; exit 0; }

# ---- 确定性打包 ----
cd "$HERE"
python -X utf8 - "$HERE" <<'PY'
import hashlib, os, sys, zipfile
here = sys.argv[1]
root = os.path.join(here, 'package')
out = os.path.join(root, 'Cnc.zip')
files = []
for name in ('Tiberian Dawn.sh', 'Red Alert.sh'):
    files.append((name, os.path.join(root, name)))
for dp, dn, fn in os.walk(os.path.join(root, 'cnc')):
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
print('Cnc.zip', len(b), 'B', hashlib.sha256(b).hexdigest())
PY
python -X utf8 check_port.py "package/Cnc.zip"

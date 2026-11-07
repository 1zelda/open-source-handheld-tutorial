#!/bin/bash
# Wolfenstein 3D（ECWolf 1.4.2）-> aarch64 端口包的完整可复现构建
# 用法: 在 Git Bash 里 bash build.sh；工作目录随意（脚本自己在 /f/_scratch 下建 ASCII 构建目录）
# 依赖: zig 0.17.0、cmake 3.31、ninja、git、curl、python（只用标准库）、本机 MSVC（只用来编 zipdir）
set -e

Z="${ZIG:-/f/_scratch/zigwin/zig.exe}"
CM="${CMAKE:-/f/工具链/cmake-3.31.6/cmake-3.31.6-windows-x86_64/bin/cmake.exe}"
NJ="${NINJA:-/f/工具链/ninja-1.12.1/ninja.exe}"
HERE="$(cd "$(dirname "$0")" && pwd)"
B="/f/_scratch/ecwolf_build"      # 必须是纯 ASCII 路径: zig/cmake 处理中文路径会出乱子
S="$B/ecwolf_src"
P="$B/prefix"
mkdir -p "$B"; cd "$B"

# 上游固定到这些 commit（2026-10 的快照），避免"今天编得过、明天编不过"
ECWOLF_COMMIT=ca1143ef008869f05c9db112289f561a3c9aa1c3
SDLMIXER_COMMIT=dce5c43df28a381e06b4a89ed456930dc0de973c
SDLNET_COMMIT=0033081290a6c8cd1342554e383ecd9c39abfa71

if [ ! -d "$S/.git" ]; then
  mkdir -p "$S"; cd "$S"
  git init -q
  git remote add origin https://github.com/ECWolfEngine/ECWolf.git
  git fetch -q --depth 1 origin "$ECWOLF_COMMIT"
  git checkout -q FETCH_HEAD
  cd "$B"
fi
cd "$S"
git submodule update -q --init deps/SDL_mixer deps/SDL_net
# 子模块是 --depth 1 拉的，逐个核对是不是钉住的 commit（子模块 URL 是相对路径，按 origin 解析）
[ "$(git -C deps/SDL_mixer rev-parse HEAD)" = "$SDLMIXER_COMMIT" ] || {
  echo "SDL_mixer 子模块不是钉住的 commit"; exit 1; }
[ "$(git -C deps/SDL_net rev-parse HEAD)" = "$SDLNET_COMMIT" ] || {
  echo "SDL_net 子模块不是钉住的 commit"; exit 1; }
cd "$B"

# ---- SDL2：只借头文件与"用来链接的 aarch64 so"，运行时用 CFW 自带的 libSDL2 ----
[ -f SDL2.tar.gz ] || curl -sSL -o SDL2.tar.gz \
  https://github.com/libsdl-org/SDL/releases/download/release-2.30.9/SDL2-2.30.9.tar.gz
[ -d SDL2-2.30.9 ] || tar xzf SDL2.tar.gz
[ -f sdl2.deb ] || curl -sSL -o sdl2.deb \
  "http://ftp.debian.org/debian/pool/main/libs/libsdl2/libsdl2-2.0-0_2.26.5+dfsg-1_arm64.deb"
mkdir -p "$P/lib" "$P/include/SDL2"
if [ ! -f "$P/lib/libSDL2-2.0.so.0" ]; then
  python -X utf8 - sdl2.deb "$P/lib" <<'PY'
import io, sys, tarfile
b = open(sys.argv[1], 'rb').read(); p = 8; out = sys.argv[2]
while p + 60 <= len(b):
    h = b[p:p+60]; name = h[:16].decode().strip(); size = int(h[48:58])
    if name.startswith('data.tar'):
        tf = tarfile.open(fileobj=io.BytesIO(b[p+60:p+60+size]))
        for m in tf.getmembers():
            if m.isfile() and 'libSDL2-2.0.so.0.' in m.name:
                open(out + '/libSDL2-2.0.so.0', 'wb').write(tf.extractfile(m).read())
    p += 60 + size + (size % 2)
PY
  ln -sf libSDL2-2.0.so.0 "$P/lib/libSDL2.so"
fi
cp -f SDL2-2.30.9/include/*.h "$P/include/SDL2/"

# ---- 交叉编译工具链文件（zig 当 C/C++ 编译器，Ninja 不认 CMAKE_AR_ARG1，归档规则要手写） ----
cat > "$B/aarch64.cmake" <<'EOF'
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)
set(ZIG "F:/_scratch/zigwin/zig.exe")
set(CMAKE_C_COMPILER "${ZIG}")
set(CMAKE_C_COMPILER_ARG1 "cc")
set(CMAKE_CXX_COMPILER "${ZIG}")
set(CMAKE_CXX_COMPILER_ARG1 "c++")
set(CMAKE_AR "${ZIG}")
set(CMAKE_RANLIB "${ZIG}")
foreach(_l C CXX)
  set(CMAKE_${_l}_ARCHIVE_CREATE "<CMAKE_AR> ar qc <TARGET> <LINK_FLAGS> <OBJECTS>")
  set(CMAKE_${_l}_ARCHIVE_APPEND "<CMAKE_AR> ar q <TARGET> <LINK_FLAGS> <OBJECTS>")
  set(CMAKE_${_l}_ARCHIVE_FINISH "<CMAKE_RANLIB> ranlib <TARGET>")
endforeach()
set(ZIG_TARGET "-target aarch64-linux-gnu")
set(CMAKE_C_FLAGS_INIT "${ZIG_TARGET}")
set(CMAKE_CXX_FLAGS_INIT "${ZIG_TARGET}")
set(CMAKE_EXE_LINKER_FLAGS_INIT "${ZIG_TARGET} -Wl,-s")
set(CMAKE_SHARED_LINKER_FLAGS_INIT "${ZIG_TARGET} -Wl,-s")
set(CMAKE_FIND_ROOT_PATH "F:/_scratch/ecwolf_build/prefix")
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
EOF

# ---- SDL2_mixer / SDL2_net：ECWolf 的 CMake 会强制要 opus/mod，本机没有那些外部库，
#      所以按配置文件手工挑源文件编一个"最小可用"版本（WAV/AIFF/VOC/Ogg-stb） ----
MIXER_DEF="-DMUSIC_WAV -DMUSIC_OGG -DOGG_USE_STB"
MIXER_SRC="src/mixer.c src/music.c src/utils.c src/effect_position.c src/effect_stereoreverse.c
src/effects_internal.c src/codecs/load_aiff.c src/codecs/load_voc.c src/codecs/mp3utils.c
src/codecs/music_wav.c src/codecs/music_ogg_stb.c"

build_mixer() {
  local SRC="$S/deps/SDL_mixer" O="$B/mixer_obj"
  rm -rf "$O"; mkdir -p "$O"
  local objs=""
  for f in $MIXER_SRC; do
    local o="$O/$(echo "$f" | tr '/' '_' | sed 's/\.c$/.o/')"
    "$Z" cc -target aarch64-linux-gnu -O2 -fPIC -I"$SRC/include" -I"$SRC/src" \
      -I"$SRC/src/codecs" -I"$P/include/SDL2" $MIXER_DEF -c "$SRC/$f" -o "$o"
    objs="$objs $o"
  done
  "$Z" cc -target aarch64-linux-gnu -shared -Wl,-soname,libSDL2_mixer-2.0.so.0 \
    -o "$P/lib/libSDL2_mixer-2.0.so.0" $objs "$P/lib/libSDL2-2.0.so.0" -lm
  ln -sf libSDL2_mixer-2.0.so.0 "$P/lib/libSDL2_mixer.so"
  cp -f "$SRC/include/SDL_mixer.h" "$P/include/SDL2/"
}

build_net() {
  local SRC="$S/deps/SDL_net" O="$B/net_obj"
  rm -rf "$O"; mkdir -p "$O"
  local objs=""
  for f in SDLnet.c SDLnetTCP.c SDLnetUDP.c SDLnetselect.c; do
    "$Z" cc -target aarch64-linux-gnu -O2 -fPIC -I"$P/include/SDL2" -I"$SRC" \
      -c "$SRC/$f" -o "$O/${f%.c}.o"
    objs="$objs $O/${f%.c}.o"
  done
  "$Z" cc -target aarch64-linux-gnu -shared -Wl,-soname,libSDL2_net-2.0.so.0 \
    -o "$P/lib/libSDL2_net-2.0.so.0" $objs "$P/lib/libSDL2-2.0.so.0"
  ln -sf libSDL2_net-2.0.so.0 "$P/lib/libSDL2_net.so"
  cp -f "$SRC/SDL_net.h" "$P/include/SDL2/"
}

echo "== 编 SDL2_mixer / SDL2_net"; build_mixer; build_net

# ---- gdtoa 要 arith.h / gd_qnan.h：交叉编译时它的 CMake 不会生成，
#      用同一份源码在本机（x86_64 小端 IEEE）跑一遍 arithchk/qnan 得到，值对 aarch64 同样成立 ----
mkdir -p "$B/gdtoa_gen"
"$Z" cc -target x86_64-windows-gnu -O1 -o "$B/gdtoa_gen/arithchk.exe" "$S/deps/gdtoa/arithchk.c"
"$B/gdtoa_gen/arithchk.exe" > "$B/gdtoa_gen/arith.h"
"$Z" cc -target x86_64-windows-gnu -O1 -I"$B/gdtoa_gen" -o "$B/gdtoa_gen/qnan.exe" "$S/deps/gdtoa/qnan.c"
"$B/gdtoa_gen/qnan.exe" > "$B/gdtoa_gen/gd_qnan.h"

# ---- 第一阶段：本机编 zipdir，导出 ImportExecutables.cmake（ECWolf 的 pk3 要用它打包） ----
# 本机是 MSVC；如果你在 Linux 上跑这一步，换成 -G Ninja 即可
echo "== 本机编工具"; rm -rf "$B/host"
"$CM" -S "$S" -B "$B/host" -G "Visual Studio 17 2022" -A x64 -DTOOLS_ONLY=ON -DCMAKE_BUILD_TYPE=Release
"$CM" --build "$B/host" --config Release --target zipdir

# ---- 第二阶段：交叉编译 aarch64 的 ecwolf ----
echo "== 交叉编译 ecwolf"; rm -rf "$B/xa"
"$CM" -S "$S" -B "$B/xa" -G Ninja \
  -DCMAKE_MAKE_PROGRAM="$NJ" \
  -DCMAKE_TOOLCHAIN_FILE="F:/_scratch/ecwolf_build/aarch64.cmake" \
  -DCMAKE_BUILD_TYPE=Release \
  -DIMPORT_EXECUTABLES="F:/_scratch/ecwolf_build/host/ImportExecutables.cmake"
cp "$B/gdtoa_gen/arith.h" "$B/gdtoa_gen/gd_qnan.h" "$B/xa/deps/gdtoa/"
"$NJ" -C "$B/xa"

# ---- 组装端口包 ----
PKG="$HERE/package/wolf3d"
rm -rf "$PKG/libs.aarch64"
mkdir -p "$PKG/libs.aarch64"
cp "$B/xa/ecwolf" "$PKG/ecwolf.aarch64"
cp "$B/xa/ecwolf.pk3" "$PKG/ecwolf.pk3"
cp "$P/lib/libSDL2_mixer-2.0.so.0" "$P/lib/libSDL2_net-2.0.so.0" "$PKG/libs.aarch64/"

cd "$HERE"
python -X utf8 - "$HERE" <<'PY'
import hashlib, os, sys, zipfile
here = sys.argv[1]
root = os.path.join(here, 'package')
out = os.path.join(root, 'Wolfenstein 3D.zip')
files = [('Wolfenstein 3D.sh', os.path.join(root, 'Wolfenstein 3D.sh'))]
for dp, dn, fn in os.walk(os.path.join(root, 'wolf3d')):
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
print('Wolfenstein 3D.zip', len(b), 'B', hashlib.sha256(b).hexdigest())
PY
python -X utf8 check_port.py "package/Wolfenstein 3D.zip"

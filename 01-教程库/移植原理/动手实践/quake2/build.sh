#!/bin/bash
# Quake II（Yamagi Quake II）-> aarch64 端口包的完整可复现构建
# 用法: 在 Git Bash 里 bash build.sh；工作目录随意（脚本自己在 /f/_scratch 下建 ASCII 构建目录）
# 依赖: zig 0.17.0、git、curl、unzip、python（只用标准库）
set -e

Z="/f/工具链/zig-x86_64-windows-0.17.0/zig.exe"
HERE="$(cd "$(dirname "$0")" && pwd)"
B="/f/_scratch/quake2_build"       # 必须是纯 ASCII 路径: zig 处理中文路径会乱码
S="$B/yamagi"
mkdir -p "$B"; cd "$B"

# 上游固定到这个 commit（2026-10-15, v8.71pre），避免"今天编得过、明天编不过"
Q2_COMMIT=9dbf699273e2546f3ad14cff3dee6a51a518cd2a

# 1. 引擎源码（GPL-2.0；LICENSE 里是逐组件许可清单）
if [ ! -d "$S" ]; then
  mkdir -p "$S"; cd "$S"
  git init -q
  git remote add origin https://github.com/yquake2/yquake2.git
  git fetch -q --depth 1 origin "$Q2_COMMIT"
  git checkout -q FETCH_HEAD
  cd "$B"
fi

# 2. SDL2 头文件（只借头，运行时用设备自带的 libSDL2）
[ -f SDL2.tar.gz ] || curl -sSL -o SDL2.tar.gz \
  https://github.com/libsdl-org/SDL/releases/download/release-2.30.9/SDL2-2.30.9.tar.gz
[ -d SDL2-2.30.9 ] || tar xzf SDL2.tar.gz
# Yamagi 有的文件写 <SDL.h>、有的写 <SDL2/SDL.h>，两套都要能解析
[ -d sdlinc/SDL2 ] || { mkdir -p sdlinc && cp -r SDL2-2.30.9/include sdlinc/SDL2; }

# 3. 链接与编译用的 aarch64 系统库/头（Debian arm64 包，只用于链接）
fetch_deb() {  # $1=输出文件名 $2=url
  [ -f "$1" ] || curl -sSL -o "$1" "$2"
}

extract_deb() {  # $1=deb $2=解出目录 $3..=规则 "成员名片段=>目标相对路径"
  python -X utf8 - "$1" "$2" "${@:3}" <<'PY'
import io, os, sys, tarfile
deb, outdir = sys.argv[1], sys.argv[2]
rules = sys.argv[3:]
b = open(deb, 'rb').read(); p = 8
while p + 60 <= len(b):
    h = b[p:p+60]; name = h[:16].decode().strip(); size = int(h[48:58])
    data = b[p+60:p+60+size]
    if name.startswith('data.tar'):
        tf = tarfile.open(fileobj=io.BytesIO(data))
        for m in tf.getmembers():
            for rule in rules:
                want, dst = rule.split('=>')
                if want in m.name and m.isfile():
                    if dst.endswith('/'):
                        dst = os.path.join(dst, os.path.basename(m.name))
                    target = os.path.join(outdir, dst)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    open(target, 'wb').write(tf.extractfile(m).read())
    p += 60 + size + (size % 2)
PY
}

fetch_deb sdl2.deb "http://ftp.debian.org/debian/pool/main/libs/libsdl2/libsdl2-2.0-0_2.26.5+dfsg-1_arm64.deb"
fetch_deb libgldev.deb "http://ftp.debian.org/debian/pool/main/libg/libglvnd/libgl-dev_1.6.0-1_arm64.deb"

[ -f libSDL2-2.0.so.0 ] || extract_deb sdl2.deb . "libSDL2-2.0.so.0.=>libSDL2-2.0.so.0"
[ -f glinclude/GL/gl.h ] || extract_deb libgldev.deb glinclude "include/GL/=>GL/" "include/KHR/=>KHR/"

# 4. 编译
O="$B/obj"; mkdir -p "$O"
CFLAGS=(-O2 -pipe -fomit-frame-pointer -fno-strict-aliasing -fwrapv -fvisibility=hidden
  -DNOUNCRYPT -DYQ2OSTYPE='"Linux"' -DYQ2ARCH='"aarch64"' -DBUILD_DATE='"Oct 28 2026"'
  -I "$S/src" -I "$B/SDL2-2.30.9/include" -I "$B/sdlinc")

# 文件清单直接来自 Makefile 的 *_OBJS_（commit 已固定），下面三条是 Linux 条件追加项
CLIENT="src/backends/generic/misc src/client/cl_cin src/client/cl_image src/client/cl_console
src/client/cl_download src/client/cl_effects src/client/cl_entities src/client/cl_input
src/client/cl_inventory src/client/cl_keyboard src/client/cl_lights src/client/cl_main
src/client/cl_network src/client/cl_parse src/client/cl_particles src/client/cl_prediction
src/client/cl_screen src/client/cl_tempentities src/client/cl_view src/client/curl/download
src/client/curl/qcurl src/client/input/gyro src/client/menu/menu src/client/menu/qmenu
src/client/menu/videomenu src/client/sound/ogg src/client/sound/openal src/client/sound/qal
src/client/sound/sdl src/client/sound/sound src/client/sound/wave src/client/vid/vid
src/common/argproc src/common/clientserver src/common/collision src/common/crc
src/common/cmdparser src/common/cvar src/common/filesystem src/common/glob src/common/md4
src/common/movemsg src/common/frame src/common/netchan src/common/pmove src/common/szone
src/common/zone src/common/shared/flash src/common/shared/rand src/common/shared/shared
src/server/sv_cmd src/server/sv_conless src/server/sv_entities src/server/sv_game
src/server/sv_init src/server/sv_main src/server/sv_save src/server/sv_send src/server/sv_user
src/server/sv_world
src/common/unzip/ioapi src/common/unzip/unzip src/common/unzip/miniz/miniz
src/common/unzip/miniz/miniz_tdef src/common/unzip/miniz/miniz_tinfl
src/client/input/sdl2 src/client/vid/glimp_sdl2
src/backends/unix/main src/backends/unix/network src/backends/unix/signalhandler
src/backends/unix/system src/backends/unix/shared/hunk"

REFL1="src/client/refresh/gl1/qgl src/client/refresh/gl1/gl1_draw src/client/refresh/gl1/gl1_image
src/client/refresh/gl1/gl1_light src/client/refresh/gl1/gl1_lightmap src/client/refresh/gl1/gl1_main
src/client/refresh/gl1/gl1_mesh src/client/refresh/gl1/gl1_misc src/client/refresh/gl1/gl1_model
src/client/refresh/gl1/gl1_scrap src/client/refresh/gl1/gl1_surf src/client/refresh/gl1/gl1_warp
src/client/refresh/gl1/gl1_sdl src/client/refresh/gl1/gl1_buffer
src/client/refresh/files/common src/client/refresh/files/surf src/client/refresh/files/models
src/client/refresh/files/pcx src/client/refresh/files/stb src/client/refresh/files/wal
src/client/refresh/files/pvs src/common/shared/shared src/common/md4
src/backends/unix/shared/hunk"

SOFT="src/client/refresh/soft/sw_aclip src/client/refresh/soft/sw_alias src/client/refresh/soft/sw_bsp
src/client/refresh/soft/sw_draw src/client/refresh/soft/sw_edge src/client/refresh/soft/sw_image
src/client/refresh/soft/sw_light src/client/refresh/soft/sw_main src/client/refresh/soft/sw_misc
src/client/refresh/soft/sw_model src/client/refresh/soft/sw_part src/client/refresh/soft/sw_poly
src/client/refresh/soft/sw_polyset src/client/refresh/soft/sw_rast src/client/refresh/soft/sw_scan
src/client/refresh/soft/sw_sprite src/client/refresh/soft/sw_surf
src/client/refresh/files/surf src/client/refresh/files/common src/client/refresh/files/models
src/client/refresh/files/pcx src/client/refresh/files/stb src/client/refresh/files/wal
src/client/refresh/files/pvs src/common/shared/shared src/common/md4
src/backends/unix/shared/hunk"

GAME="src/common/shared/flash src/common/shared/rand src/common/shared/shared
src/game/g_ai src/game/g_chase src/game/g_cmds src/game/g_combat src/game/g_func src/game/g_items
src/game/g_main src/game/g_misc src/game/g_monster src/game/g_phys src/game/g_spawn
src/game/g_svcmds src/game/g_target src/game/g_trigger src/game/g_turret src/game/g_utils
src/game/g_weapon src/game/monster/berserker/berserker src/game/monster/boss2/boss2
src/game/monster/boss3/boss3 src/game/monster/boss3/boss31 src/game/monster/boss3/boss32
src/game/monster/brain/brain src/game/monster/chick/chick src/game/monster/flipper/flipper
src/game/monster/float/float src/game/monster/flyer/flyer src/game/monster/gladiator/gladiator
src/game/monster/gunner/gunner src/game/monster/hover/hover src/game/monster/infantry/infantry
src/game/monster/insane/insane src/game/monster/medic/medic src/game/monster/misc/move
src/game/monster/mutant/mutant src/game/monster/parasite/parasite
src/game/monster/soldier/soldier src/game/monster/supertank/supertank src/game/monster/tank/tank
src/game/player/client src/game/player/hud src/game/player/trail src/game/player/view
src/game/player/weapon src/game/savegame/savegame"

compile() {  # $1=标签 $2=额外参数 $3=文件列表
  # 注意：并行编译必须逐个 wait 并检查退出码。用裸 wait 时某个文件编失败会被
  # 静默吞掉，后面的链接可能"成功"产出一个 1.7 KB 的空 .so（踩过）。
  local tag="$1" extra="$2" list="$3" pids=()
  for f in $list; do
    local out="$O/${tag}/$(echo "$f" | tr '/' '_').o"
    mkdir -p "$(dirname "$out")"
    # shellcheck disable=SC2086
    "$Z" cc -target aarch64-linux-gnu -c "${CFLAGS[@]}" $extra -o "$out" "$S/$f.c" &
    pids+=($!)
    if [ ${#pids[@]} -ge 8 ]; then
      for p in "${pids[@]}"; do wait "$p" || { echo "编译失败: $tag"; return 1; }; done
      pids=()
    fi
  done
  for p in "${pids[@]}"; do wait "$p" || { echo "编译失败: $tag"; return 1; }; done
}

echo "== 编译 client"; compile cl "" "$CLIENT"
echo "== 编译 ref_gles1"; compile g1 "-fPIC -DYQ2_GL1_GLES -I$S/src/client/refresh/gl1/glad-gles1/include" "$REFL1"
echo "== 编译 ref_gl1"; compile g1d "-fPIC -I $B/glinclude" "$REFL1"
echo "== 编译 ref_soft"; compile gs "-fPIC" "$SOFT"
echo "== 编译 baseq2/game"; compile game "-fPIC" "$GAME"

# gles1 需要额外编 glad 加载器（桌面 gl1 用不到）
if [ ! -f "$O/g1/src_client_refresh_gl1_glad-gles1_src_glad.o" ]; then
  "$Z" cc -target aarch64-linux-gnu -c "${CFLAGS[@]}" -fPIC -DYQ2_GL1_GLES \
    -I "$S/src/client/refresh/gl1/glad-gles1/include" \
    -o "$O/g1/src_client_refresh_gl1_glad-gles1_src_glad.o" \
    "$S/src/client/refresh/gl1/glad-gles1/src/glad.c"
fi

echo "== 链接"
"$Z" cc -target aarch64-linux-gnu -O2 -Wl,-s -o "$B/quake2.aarch64" \
  "$O"/cl/*.o "$B/libSDL2-2.0.so.0" -lm -ldl
"$Z" cc -target aarch64-linux-gnu -O2 -Wl,-s -shared -o "$B/ref_gles1.so" \
  "$O"/g1/*.o "$B/libSDL2-2.0.so.0" -lm -ldl
"$Z" cc -target aarch64-linux-gnu -O2 -Wl,-s -shared -o "$B/ref_gl1.so" \
  "$O"/g1d/*.o "$B/libSDL2-2.0.so.0" -lm -ldl
"$Z" cc -target aarch64-linux-gnu -O2 -Wl,-s -shared -o "$B/ref_soft.so" \
  "$O"/gs/*.o "$B/libSDL2-2.0.so.0" -lm -ldl
"$Z" cc -target aarch64-linux-gnu -O2 -Wl,-s -shared -o "$B/game.so" "$O"/game/*.o -lm

# 5. 放进端口包并重打 zip（固定时间戳，保证字节级可复现）
PKG="$HERE/package/quake2"
mkdir -p "$PKG/baseq2"
cp "$B/quake2.aarch64" "$B/ref_gles1.so" "$B/ref_gl1.so" "$B/ref_soft.so" "$PKG/"
cp "$B/game.so" "$PKG/baseq2/"

cd "$HERE"
python -X utf8 - "$HERE" <<'PY'
import hashlib, os, sys, zipfile
here = sys.argv[1]
root = os.path.join(here, 'package')
out = os.path.join(root, 'Quake2.zip')
files = [('Quake2.sh', os.path.join(root, 'Quake2.sh'))]
for dp, dn, fn in os.walk(os.path.join(root, 'quake2')):
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
print('Quake2.zip', len(b), 'B', hashlib.sha256(b).hexdigest())
PY
python -X utf8 check_port.py package/Quake2.zip

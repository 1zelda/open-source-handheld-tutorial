#!/bin/bash
# Quake III Arena（ioquake3）-> aarch64 端口包的完整可复现构建
# 用法: 在 Git Bash 里 bash build.sh；工作目录随意（脚本自己在 /f/_scratch 下建 ASCII 构建目录）
# 依赖: zig 0.17.0、git、curl、python（只用标准库）
set -e

Z="/f/工具链/zig-x86_64-windows-0.17.0/zig.exe"
HERE="$(cd "$(dirname "$0")" && pwd)"
B="/f/_scratch/quake3_build"       # 必须是纯 ASCII 路径: zig 处理中文路径会乱码
S="$B/ioq3"
mkdir -p "$B"; cd "$B"

# 上游固定到这个 commit（2026-10-12, main），避免"今天编得过、明天编不过"
Q3_COMMIT=87a99d18206e878a20289f05ac3c16005dcae5c3

if [ ! -d "$S" ]; then
  mkdir -p "$S"; cd "$S"
  git init -q
  git remote add origin https://github.com/ioquake/ioq3.git
  git fetch -q --depth 1 origin "$Q3_COMMIT"
  git checkout -q FETCH_HEAD
  cd "$B"
fi

# SDL2 头文件（只借头，运行时用设备自带的 libSDL2）
[ -f SDL2.tar.gz ] || curl -sSL -o SDL2.tar.gz \
  https://github.com/libsdl-org/SDL/releases/download/release-2.30.9/SDL2-2.30.9.tar.gz
[ -d SDL2-2.30.9 ] || tar xzf SDL2.tar.gz

# 链接用的 aarch64 SDL2（Debian arm64 包，只用于链接，不进包）
[ -f sdl2.deb ] || curl -sSL -o sdl2.deb \
  "http://ftp.debian.org/debian/pool/main/libs/libsdl2/libsdl2-2.0-0_2.26.5+dfsg-1_arm64.deb"
if [ ! -f libSDL2-2.0.so.0 ]; then
  python -X utf8 - sdl2.deb <<'PY'
import io, sys, tarfile
b = open(sys.argv[1], 'rb').read(); p = 8
while p + 60 <= len(b):
    h = b[p:p+60]; name = h[:16].decode().strip(); size = int(h[48:58])
    if name.startswith('data.tar'):
        tf = tarfile.open(fileobj=io.BytesIO(b[p+60:p+60+size]))
        for m in tf.getmembers():
            if m.isfile() and 'libSDL2-2.0.so.0.' in m.name:
                open('libSDL2-2.0.so.0', 'wb').write(tf.extractfile(m).read())
    p += 60 + size + (size % 2)
PY
fi

# 音频走 ioquake3 自带的 SDL 后端（sdl_snd.c），不编 USE_OPENAL：
# Debian 的 libopenal1 是 C++ 写的，要额外带 libstdc++/libgcc_s，而且那版要 GLIBC_2.38，
# 在 R36S/XF45V 上直接起不来。SDL2 设备上本来就有，省一层依赖。

# ---- 编译 ----
O="$B/obj"; mkdir -p "$O"
CFLAGS=(-O2 -pipe -fomit-frame-pointer -fno-strict-aliasing -fwrapv -fvisibility=hidden
  -DPRODUCT_VERSION='"1.36"' -DPRODUCT_DATE='"Oct 28 2026"'
  -I "$S/code" -I "$B/SDL2-2.30.9/include")

CLIENT="client/cl_cgame client/cl_cin client/cl_console client/cl_input client/cl_keys
client/cl_main client/cl_net_chan client/cl_parse client/cl_scrn client/cl_ui client/cl_avi
client/libmumblelink client/snd_altivec client/snd_adpcm client/snd_dma client/snd_mem
client/snd_mix client/snd_wavelet client/snd_main client/snd_codec client/snd_codec_wav
client/snd_codec_ogg client/snd_codec_opus client/qal client/snd_openal
sdl/sdl_input sdl/sdl_snd
server/sv_bot server/sv_client server/sv_ccmds server/sv_game server/sv_init server/sv_main
server/sv_net_chan server/sv_snapshot server/sv_world
qcommon/cm_load qcommon/cm_patch qcommon/cm_polylib qcommon/cm_test qcommon/cm_trace
qcommon/cmd qcommon/common qcommon/cvar qcommon/files qcommon/md4 qcommon/md5 qcommon/msg
qcommon/net_chan qcommon/net_ip qcommon/huffman qcommon/q_math qcommon/q_shared
qcommon/unzip qcommon/ioapi qcommon/vm qcommon/vm_armv7l qcommon/vm_interpreted
qcommon/vm_powerpc qcommon/vm_sparc qcommon/vm_x86
sys/con_log sys/sys_autoupdater sys/sys_main sys/sys_unix sys/con_tty
botlib/be_aas_bspq3 botlib/be_aas_cluster botlib/be_aas_debug botlib/be_aas_entity
botlib/be_aas_file botlib/be_aas_main botlib/be_aas_move botlib/be_aas_optimize
botlib/be_aas_reach botlib/be_aas_route botlib/be_aas_routealt botlib/be_aas_sample
botlib/be_ai_char botlib/be_ai_chat botlib/be_ai_gen botlib/be_ai_goal botlib/be_ai_move
botlib/be_ai_weap botlib/be_ai_weight botlib/be_ea botlib/be_interface botlib/l_crc
botlib/l_libvar botlib/l_log botlib/l_memory botlib/l_precomp botlib/l_script botlib/l_struct
asm/ftola asm/snapvector
thirdparty/zlib-1.3.1/adler32 thirdparty/zlib-1.3.1/crc32 thirdparty/zlib-1.3.1/inffast
thirdparty/zlib-1.3.1/inflate thirdparty/zlib-1.3.1/inftrees thirdparty/zlib-1.3.1/zutil
thirdparty/libogg-1.3.6/src/bitwise thirdparty/libogg-1.3.6/src/framing
thirdparty/libvorbis-1.3.7/lib/analysis thirdparty/libvorbis-1.3.7/lib/bitrate
thirdparty/libvorbis-1.3.7/lib/block thirdparty/libvorbis-1.3.7/lib/codebook
thirdparty/libvorbis-1.3.7/lib/envelope thirdparty/libvorbis-1.3.7/lib/floor0
thirdparty/libvorbis-1.3.7/lib/floor1 thirdparty/libvorbis-1.3.7/lib/info
thirdparty/libvorbis-1.3.7/lib/lookup thirdparty/libvorbis-1.3.7/lib/lpc
thirdparty/libvorbis-1.3.7/lib/lsp thirdparty/libvorbis-1.3.7/lib/mapping0
thirdparty/libvorbis-1.3.7/lib/mdct thirdparty/libvorbis-1.3.7/lib/psy
thirdparty/libvorbis-1.3.7/lib/registry thirdparty/libvorbis-1.3.7/lib/res0
thirdparty/libvorbis-1.3.7/lib/sharedbook thirdparty/libvorbis-1.3.7/lib/smallft
thirdparty/libvorbis-1.3.7/lib/synthesis thirdparty/libvorbis-1.3.7/lib/vorbisfile
thirdparty/libvorbis-1.3.7/lib/window"

CLIENT_INC=(-I "$S/code/thirdparty/zlib-1.3.1"
 -I "$S/code/thirdparty/libogg-1.3.6/include"
 -I "$S/code/thirdparty/libvorbis-1.3.7/include" -I "$S/code/thirdparty/libvorbis-1.3.7/lib")
CLIENT_DEF=(-DBOTLIB -DUSE_RENDERER_DLOPEN -DUSE_ICON -DNO_GZIP -DUSE_CODEC_VORBIS)
RENDERER_DEF=(-DUSE_RENDERER_DLOPEN -DUSE_ICON -DUSE_INTERNAL_JPEG
 -I "$S/code/thirdparty/jpeg-9f")

GL1="renderercommon/tr_font renderercommon/tr_image_bmp renderercommon/tr_image_jpg
renderercommon/tr_image_pcx renderercommon/tr_image_png renderercommon/tr_image_pvr
renderercommon/tr_image_tga renderercommon/tr_noise renderercommon/puff
renderercommon/tr_subs sdl/sdl_gamma sdl/sdl_glimp qcommon/q_shared qcommon/q_math
renderergl1/tr_altivec renderergl1/tr_animation renderergl1/tr_backend renderergl1/tr_bsp
renderergl1/tr_cmds renderergl1/tr_curve renderergl1/tr_flares renderergl1/tr_image
renderergl1/tr_init renderergl1/tr_light renderergl1/tr_main renderergl1/tr_marks
renderergl1/tr_mesh renderergl1/tr_model renderergl1/tr_model_iqm renderergl1/tr_scene
renderergl1/tr_shade renderergl1/tr_shade_calc renderergl1/tr_shader renderergl1/tr_shadows
renderergl1/tr_sky renderergl1/tr_surface renderergl1/tr_world"

JPEG=$(cd "$S/code/thirdparty/jpeg-9f" && ls j*.c | sed 's|\.c$||; s|^|thirdparty/jpeg-9f/|' | tr '\n' ' ')

compile() {  # $1=标签 $2=文件列表；额外参数来自全局 EXTRA 数组
  # 并行编译必须逐个 wait 并检查退出码：裸 wait 会吞掉失败，最后链出个空壳 .so（踩过）
  local tag="$1" list="$2" pids=()
  for f in $list; do
    local out="$O/${tag}/$(echo "$f" | tr '/' '_').o"
    mkdir -p "$(dirname "$out")"
    "$Z" cc -target aarch64-linux-gnu -c "${CFLAGS[@]}" "${EXTRA[@]}" -o "$out" "$S/code/$f.c" &
    pids+=($!)
    if [ ${#pids[@]} -ge 8 ]; then
      for p in "${pids[@]}"; do wait "$p" || { echo "编译失败: $tag ($f)"; return 1; }; done
      pids=()
    fi
  done
  for p in "${pids[@]}"; do wait "$p" || { echo "编译失败: $tag"; return 1; }; done
}

EXTRA=("${CLIENT_INC[@]}" "${CLIENT_DEF[@]}")
echo "== 编译 client"; compile cl "$CLIENT"
EXTRA=("${RENDERER_DEF[@]}")
echo "== 编译 renderer_opengl1"; compile r1 "$GL1 $JPEG"

echo "== 链接"
"$Z" cc -target aarch64-linux-gnu -O2 -Wl,-s -o "$B/quake3.aarch64" \
  "$O"/cl/*.o "$B/libSDL2-2.0.so.0" -lm -ldl
"$Z" cc -target aarch64-linux-gnu -O2 -Wl,-s -shared -o "$B/renderer_opengl1.so" \
  "$O"/r1/*.o "$B/libSDL2-2.0.so.0" -lm -ldl


# ---- gl4es（把桌面 GL1 翻成 GLES2：RK3326 的 Mali 只认 GLES，ioquake3 的 GL1 渲染器要它）----
G="$B/gl4es"
if [ ! -d "$G" ]; then
  mkdir -p "$G"; cd "$G"
  git init -q
  git remote add origin https://github.com/ptitSeb/gl4es.git
  git fetch -q --depth 1 origin 1891af323d4547487296e50ba5932bde65c7b345
  git checkout -q FETCH_HEAD
  cd "$B"
fi

# EGL/GLES 头文件（libgles-dev / libegl-dev，arm64 包但头文件与架构无关）
[ -f libgles-dev.deb ] || curl -sSL -o libgles-dev.deb   "http://ftp.debian.org/debian/pool/main/libg/libglvnd/libgles-dev_1.7.0-3+b1_arm64.deb"
[ -f libegl-dev.deb ] || curl -sSL -o libegl-dev.deb   "http://ftp.debian.org/debian/pool/main/libg/libglvnd/libegl-dev_1.7.0-3+b1_arm64.deb"
if [ ! -f glinc/GLES2/gl2.h ]; then
  python -X utf8 - libgles-dev.deb libegl-dev.deb <<'PY'
import io, os, sys, tarfile
for deb in sys.argv[1:]:
    b = open(deb, 'rb').read(); p = 8
    while p + 60 <= len(b):
        h = b[p:p+60]; name = h[:16].decode().strip(); size = int(h[48:58])
        if name.startswith('data.tar'):
            tf = tarfile.open(fileobj=io.BytesIO(b[p+60:p+60+size]))
            for m in tf.getmembers():
                if m.isfile() and '/include/' in m.name:
                    dst = os.path.join('glinc', m.name.split('/include/')[1])
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    open(dst, 'wb').write(tf.extractfile(m).read())
        p += 60 + size + (size % 2)
PY
fi

GL4ES="gl/arbconverter gl/arbgenerator gl/arbhelper gl/arbparser gl/array gl/blit gl/blend
gl/buffers gl/build_info gl/debug gl/decompress gl/depth gl/directstate gl/drawing gl/enable
gl/envvars gl/eval gl/face gl/fog gl/fpe gl/fpe_cache gl/fpe_shader gl/framebuffers
gl/gl_lookup gl/getter gl/gl4es gl/glstate gl/hint gl/init gl/light gl/line gl/list
gl/listdraw gl/listrl gl/loader gl/logs gl/matrix gl/matvec gl/oldprogram gl/pixel
gl/planes gl/pointsprite gl/preproc gl/program gl/queries gl/raster gl/render gl/samplers
gl/shader gl/shaderconv gl/shader_hacks gl/stack gl/stencil gl/string_utils gl/stubs
gl/texenv gl/texgen gl/texture gl/texture_compressed gl/texture_params gl/texture_read
gl/texture_3d gl/uniform gl/vertexattrib gl/wrap/gl4eswraps gl/wrap/gles gl/wrap/glstub
gl/math/matheval
glx/hardext glx/gbm glx/glx glx/glx_stubs glx/lookup glx/rpi glx/streaming glx/utils
egl/egl egl/lookup"

GFLAGS=(-O2 -pipe -fPIC -fvisibility=hidden -std=gnu11
  -Wno-date-time -Wno-return-mismatch -Wno-int-conversion -Wno-incompatible-pointer-types
  -Wno-deprecated-non-prototype
  -DNOX11 -DEGL_NO_X11 -DNO_GBM -DGLX_STUBS -DDEFAULT_ES=2 -DUSE_CLOCK
  -I "$G/include" -I "$G/src" -I "$G/src/glx" -I "$B/glinc")

compile_gl4es() {
  local list="$1" pids=()
  for f in $list; do
    local out="$O/gl4es/$(echo "$f" | tr '/' '_').o"
    mkdir -p "$(dirname "$out")"
    "$Z" cc -target aarch64-linux-gnu -c "${GFLAGS[@]}" -o "$out" "$G/src/$f.c" &
    pids+=($!)
    if [ ${#pids[@]} -ge 8 ]; then
      for p in "${pids[@]}"; do wait "$p" || { echo "gl4es 编译失败 ($f)"; return 1; }; done
      pids=()
    fi
  done
  for p in "${pids[@]}"; do wait "$p" || { echo "gl4es 编译失败"; return 1; }; done
}

echo "== 编译 gl4es"; compile_gl4es "$GL4ES"
# -rpath $ORIGIN：libEGL.so.1 依赖同目录的 libGL.so.1，不靠 LD_LIBRARY_PATH 也能找到
"$Z" cc -target aarch64-linux-gnu -O2 -Wl,-s -shared -Wl,-soname,libGL.so.1 -Wl,-rpath,'$ORIGIN' -o "$B/libGL.so.1" "$O"/gl4es/*.o -lm -ldl
"$Z" cc -target aarch64-linux-gnu -O2 -Wl,-s -shared -Wl,-soname,libEGL.so.1 -Wl,-rpath,'$ORIGIN' -o "$B/libEGL.so.1" "$O/gl4es/egl_egl.o" "$O/gl4es/egl_lookup.o" "$B/libGL.so.1" -ldl

# ---- 组装端口包 ----
PKG="$HERE/package/quake3"
rm -rf "$PKG/libs.aarch64"
mkdir -p "$PKG/baseq3" "$PKG/gl4es.aarch64"
cp "$B/quake3.aarch64" "$B/renderer_opengl1.so" "$PKG/"
cp "$B/libGL.so.1" "$B/libEGL.so.1" "$PKG/gl4es.aarch64/"

cd "$HERE"
python -X utf8 - "$HERE" <<'PY'
import hashlib, os, sys, zipfile
here = sys.argv[1]
root = os.path.join(here, 'package')
out = os.path.join(root, 'Quake3.zip')
files = [('Quake3.sh', os.path.join(root, 'Quake3.sh'))]
for dp, dn, fn in os.walk(os.path.join(root, 'quake3')):
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
print('Quake3.zip', len(b), 'B', hashlib.sha256(b).hexdigest())
PY
python -X utf8 check_port.py package/Quake3.zip

#!/bin/bash
# 用同一份 ioquake3 源码编一个 Windows x64 版，只为了在本机真跑一遍、截 port 的封面图。
# 设备上的包仍由 build.sh 交叉编出；这里产出的 exe/dll 不进包。
# 用法: bash build_windows.sh   （先跑过 build.sh，源码已拉在 /f/_scratch/quake3_build）
set -e

Z="/f/工具链/zig-x86_64-windows-0.17.0/zig.exe"
S="/f/_scratch/quake3_build/ioq3"
W="/f/_scratch/q3win"
B="$W/build"
SDL="$W/sdl2/SDL2-2.30.9/x86_64-w64-mingw32"
mkdir -p "$B/obj/cl" "$B/obj/r1" "$B/baseq3"

[ -d "$SDL" ] || { mkdir -p "$W/sdl2"; tar xzf "$W/SDL2-devel-2.30.9-mingw.tar.gz" -C "$W/sdl2"; }

# 头文件用 SDL2 源码里的扁平 include（ioquake3 写的是 <SDL_version.h>）；
# MinGW 开发包的头文件在 include/SDL2/ 子目录里，只拿它的 .dll.a 和 SDL2.dll
# SDL 在 Windows 上默认把 main 改名成 SDL_main（要配 SDL2main 提供 WinMain）；
# 定义 SDL_MAIN_HANDLED 保留 ioquake3 自己的 main，按控制台程序链接
CFLAGS=(-O2 -pipe -fno-strict-aliasing -fwrapv
  -DPRODUCT_VERSION='"1.36"' -DPRODUCT_DATE='"Oct 28 2026"' -DSDL_MAIN_HANDLED
  -I "$S/code" -I "/f/_scratch/quake3_build/SDL2-2.30.9/include")

# Windows 平台源文件替换：sys_win32 + con_passive（CMake 的 windows.cmake 与 client 段）
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
sys/con_log sys/sys_autoupdater sys/sys_main sys/sys_win32 sys/con_passive
asm/ftola asm/snapvector
botlib/be_aas_bspq3 botlib/be_aas_cluster botlib/be_aas_debug botlib/be_aas_entity
botlib/be_aas_file botlib/be_aas_main botlib/be_aas_move botlib/be_aas_optimize
botlib/be_aas_reach botlib/be_aas_route botlib/be_aas_routealt botlib/be_aas_sample
botlib/be_ai_char botlib/be_ai_chat botlib/be_ai_gen botlib/be_ai_goal botlib/be_ai_move
botlib/be_ai_weap botlib/be_ai_weight botlib/be_ea botlib/be_interface botlib/l_crc
botlib/l_libvar botlib/l_log botlib/l_memory botlib/l_precomp botlib/l_script botlib/l_struct
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
CLIENT_DEF=(-DBOTLIB -DUSE_RENDERER_DLOPEN -DNO_GZIP -DUSE_CODEC_VORBIS)

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

compile() {
  local tag="$1" list="$2" pids=()
  for f in $list; do
    local out="$B/obj/${tag}/$(echo "$f" | tr '/' '_').o"
    "$Z" cc -target x86_64-windows-gnu -c "${CFLAGS[@]}" "${EXTRA[@]}" -o "$out" "$S/code/$f.c" &
    pids+=($!)
    if [ ${#pids[@]} -ge 8 ]; then
      for p in "${pids[@]}"; do wait "$p" || { echo "编译失败: $tag ($f)"; return 1; }; done
      pids=()
    fi
  done
  for p in "${pids[@]}"; do wait "$p" || { echo "编译失败: $tag"; return 1; }; done
}

EXTRA=("${CLIENT_INC[@]}" "${CLIENT_DEF[@]}")
echo "== 编译 client (win64)"; compile cl "$CLIENT"
EXTRA=(-DUSE_RENDERER_DLOPEN -DUSE_INTERNAL_JPEG -I "$S/code/thirdparty/jpeg-9f")
echo "== 编译 renderer_opengl1 (win64)"; compile r1 "$GL1 $JPEG"

echo "== 链接"
"$Z" cc -target x86_64-windows-gnu -O2 -mconsole -o "$B/quake3.exe" \
  "$B"/obj/cl/*.o "$SDL/lib/libSDL2.dll.a" -lws2_32 -lwinmm -lpsapi
"$Z" cc -target x86_64-windows-gnu -O2 -shared -o "$B/renderer_opengl1.dll" \
  "$B"/obj/r1/*.o "$SDL/lib/libSDL2.dll.a"
cp "$SDL/bin/SDL2.dll" "$B/"

# 用官方 demo 数据（q3demo，免费可再分发）真跑一遍：pak0.pk3 由 linuxq3ademo 自解包脚本解出
if [ ! -f "$W/demo_payload/demoq3/pak0.pk3" ]; then
  echo "缺 demo 数据: 先解包 $W/linuxq3ademo.gz.sh" >&2; exit 1
fi
cp "$W/demo_payload/demoq3/pak0.pk3" "$B/baseq3/"
ls -la "$B"

#!/bin/bash
# Quake on QuakeSpasm -> aarch64 的完整可复现构建（本机 Windows + zig 0.17.0 实跑）
# 用法: 在 Git Bash 里 bash build.sh；工作目录随意（脚本自己在 F:/_scratch 下建 ASCII 构建目录）
set -e

Z=${ZIG:-/f/工具链/zig-x86_64-windows-0.17.0/zig.exe}
HERE="$(cd "$(dirname "$0")" && pwd)"
B=${QB:-/f/_scratch/quake_build}          # 必须是纯 ASCII 路径:zig/msys 处理中文路径会乱码
mkdir -p "$B"; cd "$B"

# 1. 引擎源码（GPL-2.0）。0.97.0 没有 tag，锁到这版 master 的 commit
QS_COMMIT=c9c8ee9895961669c4674e8f8ca8c64cc43e38b5
if [ ! -d quakespasm/.git ]; then
  git init -q quakespasm
  git -C quakespasm remote add origin https://github.com/sezero/quakespasm.git
  git -C quakespasm fetch -q --depth 1 origin "$QS_COMMIT"
  git -C quakespasm checkout -q FETCH_HEAD
fi

# 2. SDL2 头文件（只借头；运行时用掌机自带的 SDL2）
[ -f SDL2.tar.gz ] || curl -sSL -o SDL2.tar.gz \
  https://github.com/libsdl-org/SDL/releases/download/release-2.30.9/SDL2-2.30.9.tar.gz
[ -d SDL2-2.30.9 ] || tar xzf SDL2.tar.gz

# 3. 链接用的 aarch64 libSDL2-2.0.so.0 与 libGL.so.1（Debian arm64 包，只用于解析符号，不进包）
fetch_deb_so() {
  local deb=$1 url=$2 lib=$3
  if [ ! -f "$lib" ]; then
    [ -f "$deb" ] || curl -sSL -o "$deb" "$url"
    DEB="$deb" LIB="$lib" python - <<'PY'
import io, os, tarfile
b = open(os.environ['DEB'], 'rb').read(); p = 8
want = os.environ['LIB']
while p + 60 <= len(b):
    h = b[p:p+60]; name = h[:16].decode().strip(); size = int(h[48:58])
    data = b[p+60:p+60+size]
    if name.startswith('data.tar'):
        tf = tarfile.open(fileobj=io.BytesIO(data))
        cand = [m for m in tf.getmembers() if m.name.endswith('/' + want) or ('/' + want + '.') in m.name]
        open(want, 'wb').write(tf.extractfile(cand[0]).read())
    p += 60 + size + (size % 2)
PY
  fi
}
fetch_deb_so sdl2-arm64.deb \
  "http://ftp.debian.org/debian/pool/main/libs/libsdl2/libsdl2-2.0-0_2.26.5+dfsg-1_arm64.deb" \
  libSDL2-2.0.so.0
fetch_deb_so libgl1.deb \
  "http://ftp.debian.org/debian/pool/main/libg/libglvnd/libgl1_1.6.0-1_arm64.deb" \
  libGL.so.1

# 4. 数据：LibreQuake v0.09-beta lite（美术 BSD-3 / QuakeC GPL-2.0，可再分发）
[ -f lq-lite.zip ] || curl -sSL -o lq-lite.zip \
  https://github.com/lavenderdotpet/LibreQuake/releases/download/v0.09-beta/lite.zip
[ -d lq/lite/id1 ] || python -c "import zipfile; zipfile.ZipFile('lq-lite.zip').extractall('lq')"

# 5. 交叉编译：关掉 CD 音频/Win 专用网络/音乐解码器/lodepng（image.c 已内联）
CODEC_FREE="snd_flac snd_vorbis snd_opus snd_mp3 snd_mpg123 snd_mp3tag snd_mikmod snd_modplug snd_xmp snd_umx"
SKIP="cd_null net_win net_wins net_wipx pl_win sys_sdl_win lodepng $CODEC_FREE"
SRC=""
for f in quakespasm/Quake/*.c; do
  b=$(basename "$f" .c); skip=0
  for s in $SKIP; do [ "$b" = "$s" ] && skip=1; done
  [ $skip -eq 0 ] && SRC="$SRC $f"
done
"$Z" cc -target aarch64-linux-gnu -O2 -DNDEBUG -DUSE_SDL2 -DDO_USERDIRS=0 \
  -Wno-trigraphs -Wno-date-time -Wno-builtin-macro-redefined \
  -D__DATE__="\"2026-10-28\"" -D__TIME__="\"00:00:00\"" \
  -I "$B/SDL2-2.30.9/include" \
  $SRC "$B/libSDL2-2.0.so.0" "$B/libGL.so.1" -lm -ldl -lpthread -Wl,-s \
  -o "$B/quakespasm.aarch64"
ls -l "$B/quakespasm.aarch64"

# 6. 组装 PortMaster 包并重打 zip（缺什么补什么，已有数据不动）
PKG="$HERE/package/quake"
mkdir -p "$PKG/data/id1"
cp "$B/quakespasm.aarch64" "$PKG/"
[ -f "$PKG/quakespasm.pak" ] || cp quakespasm/Quake/quakespasm.pak "$PKG/"
[ -f "$PKG/data/id1/pak0.pak" ] || cp lq/lite/id1/pak0.pak lq/lite/id1/pak1.pak "$PKG/data/id1/"
[ -f "$PKG/COPYING.LibreQuake-BSD3" ] || cp lq/lite/id1/docs/COPYING "$PKG/COPYING.LibreQuake-BSD3"
[ -f "$PKG/COPYING.LibreQuake-GPL2" ] || cp lq/lite/id1/docs/misc-docs/COPYING "$PKG/COPYING.LibreQuake-GPL2"
[ -f "$PKG/README-IMPORTANT-LICENCE-INFO" ] || cp lq/lite/id1/docs/README-IMPORTANT-LICENCE-INFO "$PKG/"

cd "$HERE"
python - "$HERE" <<'PY'
import os, sys, zipfile, hashlib
here = sys.argv[1]; root = os.path.join(here, 'package'); out = os.path.join(root, 'Quake.zip')
files = [('Quake.sh', os.path.join(root, 'Quake.sh'))]
for dp, dn, fn in os.walk(os.path.join(root, 'quake')):
    dn.sort(); fn.sort()
    for f in fn:
        full = os.path.join(dp, f)
        files.append((os.path.relpath(full, root).replace(os.sep, '/'), full))
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for arc, full in files:
        zi = zipfile.ZipInfo(arc, (2026, 10, 28, 0, 0, 0))
        zi.create_system = 3; zi.external_attr = 0o100644 << 16
        zi.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(zi, open(full, 'rb').read(), compresslevel=9)
b = open(out, 'rb').read()
print('Quake.zip', len(b), 'B', hashlib.sha256(b).hexdigest())
PY
python -X utf8 check_port.py package/Quake.zip

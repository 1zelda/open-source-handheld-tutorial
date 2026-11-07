#!/bin/bash
# Freedoom on doomgeneric -> aarch64 的完整可复现构建（本机 Windows + zig 0.17.0 实跑）
# 用法: 在 Git Bash 里 bash build.sh；工作目录随意（脚本自己在 F:/_scratch 下建 ASCII 构建目录）
set -e

Z="/f/工具链/zig-x86_64-windows-0.17.0/zig.exe"
HERE="$(cd "$(dirname "$0")" && pwd)"
B="/f/_scratch/doom_build"          # 必须是纯 ASCII 路径:zig/msys 处理中文路径会乱码
mkdir -p "$B"; cd "$B"

# 1. 引擎源码（GPL-2.0）
[ -d doomgeneric ] || git clone --depth 1 https://github.com/ozkl/doomgeneric.git

# 2. SDL2 头文件（只借头；运行时用掌机自带的 SDL2）
[ -f SDL2.tar.gz ] || curl -sSL -o SDL2.tar.gz \
  https://github.com/libsdl-org/SDL/releases/download/release-2.30.9/SDL2-2.30.9.tar.gz
[ -d SDL2-2.30.9 ] || tar xzf SDL2.tar.gz

# 3. 链接用的 aarch64 libSDL2-2.0.so.0（Debian arm64 包，只用于链接）
if [ ! -f libSDL2-2.0.so.0 ]; then
  curl -sSL -o sdl2-arm64.deb \
    "http://ftp.debian.org/debian/pool/main/libs/libsdl2/libsdl2-2.0-0_2.26.5+dfsg-1_arm64.deb"
  python - <<'PY'
import io, tarfile
b = open('sdl2-arm64.deb','rb').read(); p = 8
while p + 60 <= len(b):
    h = b[p:p+60]; name = h[:16].decode().strip(); size = int(h[48:58])
    data = b[p+60:p+60+size]
    if name.startswith('data.tar'):
        tf = tarfile.open(fileobj=io.BytesIO(data))
        cand = [m for m in tf.getmembers() if '/libSDL2-2.0.so.0.' in m.name]
        open('libSDL2-2.0.so.0','wb').write(tf.extractfile(cand[0]).read())
    p += 60 + size + (size % 2)
PY
fi

# 4. Freedoom 0.13.0 免费数据（BSD 许可，可再分发）
[ -f freedoom.zip ] || curl -sSL -o freedoom.zip \
  https://github.com/freedoom/freedoom/releases/download/v0.13.0/freedoom-0.13.0.zip
[ -d freedoom-0.13.0 ] || unzip -o -q freedoom.zip

# 5. 三处补丁（上游源码本身编不过/不适合掌机，见 README 的踩坑表）
cd doomgeneric/doomgeneric
python - <<'PY'
p='doomgeneric_sdl.c'; s=open(p,encoding='utf-8').read()
if '#include <ctype.h>' not in s:
    s=s.replace('#include <stdio.h>\n#include <unistd.h>\n',
                '#include <stdio.h>\n#include <ctype.h>\n#ifndef _WIN32\n#include <unistd.h>\n#endif\n',1)
if 'SDL_WINDOW_FULLSCREEN_DESKTOP' not in s:
    s=s.replace('SDL_WINDOW_SHOWN','SDL_WINDOW_FULLSCREEN_DESKTOP',1)
open(p,'w',encoding='utf-8').write(s)
PY

# 6. 交叉编译：排除其它平台后端与 SDL2_mixer 的两个源文件（本包不做音效）
SRC=$(ls *.c | grep -vE "doomgeneric_(allegro|emscripten|linuxvt|soso|sosox|win|xlib)\.c|i_sdl(sound|music)\.c|i_allegro.*\.c")
"$Z" cc -target aarch64-linux-gnu -O2 -std=gnu99 -D_DEFAULT_SOURCE \
  -I "$B/SDL2-2.30.9/include" $SRC "$B/libSDL2-2.0.so.0" -lm -Wl,-s \
  -o "$B/doomgeneric.aarch64"
ls -l "$B/doomgeneric.aarch64"

# 7. 组装 PortMaster 包并重打 zip
PKG="$HERE/package/doom"
mkdir -p "$PKG/data"
cp "$B/doomgeneric.aarch64" "$PKG/"
[ -f "$PKG/data/freedoom1.wad" ] || cp "$B/freedoom-0.13.0/freedoom1.wad" "$PKG/data/"
[ -f "$PKG/COPYING.freedoom" ] || cp "$B/freedoom-0.13.0/COPYING.txt" "$PKG/COPYING.freedoom"

cd "$HERE"
python - "$HERE" <<'PY'
import os, sys, zipfile, hashlib
here = sys.argv[1]; root = os.path.join(here, 'package'); out = os.path.join(root, 'Doom.zip')
files = [('Doom.sh', os.path.join(root, 'Doom.sh'))]
for dp, dn, fn in os.walk(os.path.join(root, 'doom')):
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
print('Doom.zip', len(b), 'B', hashlib.sha256(b).hexdigest())
PY
python -X utf8 check_port.py package/Doom.zip

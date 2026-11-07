#!/bin/bash
# 从上游源码到 aarch64 二进制的完整构建记录（本机 Windows + zig 0.17.0 实跑）
# 用法: 在 Git Bash 里 bash build.sh，工作目录随意（脚本自己建 build/）
set -e

Z="/f/工具链/zig-x86_64-windows-0.17.0/zig.exe"
HERE="$(cd "$(dirname "$0")" && pwd)"
B="$HERE/build"
mkdir -p "$B"

cd "$B"

# 1. 源码（310,377 B）
[ -f opentyrian.tar.gz ] || curl -L -o opentyrian.tar.gz \
  https://codeload.github.com/opentyrian/opentyrian/tar.gz/refs/heads/master
[ -d opentyrian-master ] || tar xzf opentyrian.tar.gz

# 2. SDL2 头文件（7,681,555 B）
[ -f SDL2.tar.gz ] || curl -L -o SDL2.tar.gz \
  https://github.com/libsdl-org/SDL/releases/download/release-2.30.9/SDL2-2.30.9.tar.gz
[ -d SDL2-2.30.9 ] || tar xzf SDL2.tar.gz

# 3. 链接用的 aarch64 libSDL2-2.0.so.0（Debian arm64 包，1,862,400 B）
#    只用于链接；运行时用掌机系统自带的 SDL2
if [ ! -f libSDL2-2.0.so.0 ]; then
  curl -L -o sdl2-arm64.deb \
    "http://ftp.debian.org/debian/pool/main/libs/libsdl2/libsdl2-2.0-0_2.26.5+dfsg-1_arm64.deb"
  python - <<'PY'
import io, tarfile
b = open('sdl2-arm64.deb','rb').read(); p = 8
while p + 60 <= len(b):
    h = b[p:p+60]; name = h[:16].decode().strip(); size = int(h[48:58])
    data = b[p+60:p+60+size]
    if name.startswith('data.tar'):
        tf = tarfile.open(fileobj=io.BytesIO(data))
        real = [m for m in tf.getmembers() if m.name.endswith('libSDL2-2.0.so.0')]
        # 真正的内容在 libSDL2-2.0.so.0.2xxx 里，.so.0 只是符号链接
        cand = [m for m in tf.getmembers() if '/libSDL2-2.0.so.0.' in m.name]
        m = (cand or real)[0]
        open('libSDL2-2.0.so.0','wb').write(tf.extractfile(m).read())
    p += 60 + size + (size % 2)
PY
fi

# 4. 游戏数据（Tyrian 2.1 免费发布）直接进成品目录
PKG="$HERE/package/tyrian"
mkdir -p "$PKG/data"
[ -f "$PKG/data/tyrian1.lvl" ] || (cd opentyrian-master && bash get_data.sh "$PKG/data")

# 5. 交叉编译（源码/库的顺序不能反）
cd opentyrian-master
"$Z" cc -target aarch64-linux-gnu -O2 -std=iso9899:1999 -DNDEBUG \
  -DTARGET_UNIX -DTYRIAN_DIR='"/roms/ports/tyrian/data"' \
  -include stdlib.h -include string.h \
  -I ../SDL2-2.30.9/include \
  src/*.c ../libSDL2-2.0.so.0 -lm -Wl,-s \
  -o "$PKG/opentyrian.aarch64"

cd "$HERE"
ls -l "$PKG/opentyrian.aarch64"

# 6. 重新打 zip（带 Unix 权限位），再跑自检
python - "$HERE" <<'PY'
import os, sys, zipfile, hashlib
here = sys.argv[1]; root = os.path.join(here, 'package'); out = os.path.join(root, 'Tyrian.zip')
files = [('Tyrian.sh', os.path.join(root, 'Tyrian.sh'))]
for dp, dn, fn in os.walk(os.path.join(root, 'tyrian')):
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
print('Tyrian.zip', len(b), 'B', hashlib.sha256(b).hexdigest())
PY
python -X utf8 check_port.py package/Tyrian.zip

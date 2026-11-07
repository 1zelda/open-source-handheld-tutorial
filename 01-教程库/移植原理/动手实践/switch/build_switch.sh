#!/bin/bash
# 从上游源码到 opentyrian.nro（本机 Windows + devkitPro 实跑，2026-10-28）
# 前置：devkitPro 在 F:\devkitPro，见 README.md「装 devkitPro 的坑」
# 注意：msys2 拿到中文路径会乱码，所以构建放在纯英文目录，最后把 .nro 拷回来。
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="/f/_scratch/opentyrian_switch"
mkdir -p "$WORK/romfs/data"

# 1. 源码（310,377 B）
cd "$WORK"
[ -f src.tar.gz ] || curl -L -o src.tar.gz \
  https://codeload.github.com/opentyrian/opentyrian/tar.gz/refs/heads/master
[ -d opentyrian-master ] || tar xzf src.tar.gz
mkdir -p "$WORK/source"
cp opentyrian-master/src/*.c opentyrian-master/src/*.h "$WORK/source/"

# 2. 数据：复用 PortMaster 端口里的 106 个文件
if [ ! -f "$WORK/romfs/data/tyrian1.lvl" ]; then
  cp "$HERE/../tyrian/package/tyrian/data/"* "$WORK/romfs/data/"
fi
cp "$HERE/Makefile" "$WORK/Makefile"
cp "$HERE/icon.jpg" "$WORK/icon.jpg"

# 3. romfsInit()：不挂 romfs 读不到 romfs:/data
python - "$WORK/source/opentyr.c" <<'PY'
import sys
p = sys.argv[1]
s = open(p, encoding='utf-8', errors='surrogateescape').read()
if 'romfsInit' not in s:
    s = '#ifdef __SWITCH__\n#include <switch.h>\n#endif\n' + s
    s = s.replace('int main(int argc, char *argv[])\n{',
                  'int main(int argc, char *argv[])\n{\n#ifdef __SWITCH__\n\tromfsInit();\n#endif', 1)
    open(p, 'w', encoding='utf-8', errors='surrogateescape', newline='\n').write(s)
    print('patched romfsInit')
PY

# 4. 编译（在 msys2 的 bash 里跑，PATH 要带 devkitA64/tools/portlibs）
/f/devkitPro/msys2/usr/bin/bash.exe -c "export DEVKITPRO=/opt/devkitpro DEVKITA64=/opt/devkitpro/devkitA64 \
  HOME=/f/devkitPro/home \
  PATH=/usr/bin:/opt/devkitpro/devkitA64/bin:/opt/devkitpro/tools/bin:/opt/devkitpro/portlibs/switch/bin; \
  cd $WORK && make -j8"

cp "$WORK/opentyrian.nro" "$HERE/opentyrian.nro"
python - "$HERE/opentyrian.nro" <<'PY'
import sys, hashlib
b = open(sys.argv[1], 'rb').read()
print(len(b), 'B', hashlib.sha256(b).hexdigest())
print('header:', b[16:20], '| romfs data found:', b.find(b'tyrian1.lvl') > 0)
PY

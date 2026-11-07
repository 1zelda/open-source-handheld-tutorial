# tyrian/ —— 本页所有命令与产物的原始记录

2026-10-28 本机实跑（Windows 10 19045 / Git Bash / zig 0.17.0 / Python 3.13）。

## 产物

| 文件 | 字节 | 说明 |
|---|---|---|
| `package/Tyrian.zip` | 5,039,180 | sha256 `944c62e1c6355c8c296fc79269cee3b41d3f8f811472f0b1192f85d7e8234f46` |
| `package/Tyrian.sh` | 1,093 | 启动脚本 |
| `package/tyrian/opentyrian.aarch64` | 518,624 | sha256 `288f4ed470f4175b211d43cc328360f6891644d15a535005a25105d9a53e8e35` |
| `package/tyrian/data/` | 11,483,700 / 106 文件 | Tyrian 2.1 免费数据 |
| `package/tyrian/screenshot.png` | 53,804 | 640×400 实跑截图 |
| `package/tyrian/port.json` | 718 | 5 顶层键 + 12 attr 键 |
| `package/tyrian/gameinfo.xml` | 527 | ES 条目 |
| `package/tyrian/tyrian.gptk` | 586 | 抄官方包 |
| `package/tyrian/conf/opentyrian/opentyrian.cfg` | 33 | `section video / item fullscreen 0` |

## 输入

- OpenTyrian 源码 tar.gz：310,377 B（GitHub opentyrian/opentyrian master）
- SDL2-2.30.9.tar.gz：7,681,555 B
- libsdl2-2.0-0_2.26.5+dfsg-1_arm64.deb：565,580 B → libSDL2-2.0.so.0 1,862,400 B
- Tyrian 2.1 数据 zip：4,754,048 B（`camanis.net/tyrian/tyrian21.zip`）

## 原样命令

```bash
Z="/f/工具链/zig-x86_64-windows-0.17.0/zig.exe"

# aarch64
cd opentyrian-master
"$Z" cc -target aarch64-linux-gnu -O2 -std=iso9899:1999 -DNDEBUG \
  -DTARGET_UNIX -DTYRIAN_DIR='"/roms/ports/tyrian/data"' \
  -include stdlib.h -include string.h -I ../SDL2-2.30.9/include \
  src/*.c ../libSDL2-2.0.so.0 -lm -Wl,-s -o ../out/opentyrian.aarch64

# Windows（本地验证用）
"$Z" cc -target x86_64-windows-gnu -O2 -std=iso9899:1999 -DNDEBUG -DTARGET_WIN32 \
  -DTYRIAN_DIR='"C:\\TYRIAN"' -include stdlib.h -include string.h \
  -I ../SDL2-2.30.9/x86_64-w64-mingw32/include/SDL2 src/*.c \
  ../SDL2-2.30.9/x86_64-w64-mingw32/lib/libSDL2main.a \
  ../SDL2-2.30.9/x86_64-w64-mingw32/lib/libSDL2.dll.a \
  -lwinmm -limm32 -lversion -lole32 -loleaut32 -luuid -lsetupapi -lcfgmgr32 \
  -ldinput8 -ldxguid -lshell32 -luser32 -lgdi32 -ladvapi32 -lhid -lm \
  -o ../out/opentyrian.exe
```

## 真实报错（原文）

1. `error: call to undeclared library function 'malloc'`（`src/animlib.c:188`、`src/editship.c:48`）
   → 加 `-include stdlib.h -include string.h`。
2. `ld.lld: error: unable to find library -l:F:\开源掌机教程\_scratch\port_demo\libSDL2.so`
   → 不用 `-L.. -lSDL2`，把 `.so` 当输入文件直接传给编译器。
3. Windows 下弹 `The Tyrian data files were not found`：exe 在中文路径，`fopen` 读不了 UTF-8 路径；
   移到 `F:\portdemo_test`（纯 ASCII）后正常。
4. 用 `[video]` INI 语法写配置无效；引擎语法是 `section video` / `item fullscreen 0`
   （`src/config_file.c:604-640`、`:989`）。改对后 Windows 实测全屏 1920×1080。

## 实测输出

```
$ python -X utf8 check_port.py package/Tyrian.zip
...
22/22 通过
```

ELF：`machine 183`、`NEEDED ['libSDL2-2.0.so.0','libm.so.6','libc.so.6']`、
`GLIBC max GLIBC_2.29`、`interp /lib/ld-linux-aarch64.so.1`。

## 未实测

- 真机（R36S / XF45V）插卡启动：本机未接掌机。
- Switch `.nro`：本机未装 devkitPro。

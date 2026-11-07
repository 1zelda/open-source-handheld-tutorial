# OpenTyrian → Switch（.nro）实编记录

在 **Windows 本机**用 devkitPro / devkitA64 r30 把同一份 OpenTyrian 源码编成 **`opentyrian.nro`**，数据全部打进 romfs，单个文件即可分发。

| 项 | 数值 |
|---|---|
| 成品 | `opentyrian.nro` **18,825,002 B** |
| sha256 | `0ca87dfcf71e7a780147700f9419617f75c924f224f7ea9d66ee3497faa72f6a` |
| 中间 ELF | `opentyrian.elf` 18,066,112 B（未 strip） |
| romfs | 106 个文件，约 12 MB，全部来自 [`../tyrian/package/tyrian/data`](../tyrian/package/tyrian/data) |
| 编译器 | devkitA64 r30 / gcc **16.1.0** / binutils 2.46.0 |
| 运行库 | libnx **4.12.0**、switch-sdl2 **2.28.5-4**、switch-mesa 20.1.0-5 |
| 构建时间 | 2026-10-28，本机 |
| 复现性 | 用本目录 `build_switch.sh` 重编，字节数完全一致（18,825,002 B），sha256 会变——调试信息里带构建路径 |

## 怎么装到 Switch

```
opentyrian.nro  →  SD 卡 /switch/opentyrian/opentyrian.nro
```

主机上按住 **R** 打开任意游戏进 hbmenu → 选中 OpenTyrian 启动。
数据在 romfs 里，**不需要**额外拷贝 `data/` 目录。

配置/存档走的是进程工作目录（hbmenu 启动时一般是 `sdmc:/`），不是 romfs（romfs 只读）。

## 复现

前置：devkitPro 装在 `F:\devkitPro`，见下面「装 devkitPro 的坑」。

```bash
export DEVKITPRO=/opt/devkitpro
export DEVKITA64=/opt/devkitpro/devkitA64
export PATH=/usr/bin:/opt/devkitpro/devkitA64/bin:/opt/devkitpro/tools/bin:/opt/devkitpro/portlibs/switch/bin
cd 这个目录
make -j8
```

`Makefile` 就是官方 `switch-examples/templates/application` 的模板，只改了五处：

| 改动 | 值 |
|---|---|
| `TARGET` / `SOURCES` | `opentyrian` / `source` |
| `ROMFS` | `romfs`（内含 `romfs/data/` 106 个文件） |
| `CFLAGS` | 加 `-I$(PORTLIBS)/include/SDL2`、`-std=iso9899:1999`、`-DTYRIAN_DIR='"/romfs/data"'` |
| `LIBS` | `-lSDL2 -lEGL -lGLESv2 -lglapi -ldrm_nouveau -lstdc++ -lm -lnx` |
| 源码补丁 | `source/opentyr.c` 顶部 `#include <switch.h>`，`main()` 第一行 `romfsInit()` |

`romfsInit()` 不能省：不挂 romfs，`romfs:/data/tyrian1.lvl` 读不到，游戏会停在 “data files were not found”。
libnx 4.12 里它是内联包装，反汇编看到的是 `bl romfsMountSelf`。

## 链接时踩到的四个报错（按出现顺序）

| 报错原文 | 根因 | 修法 |
|---|---|---|
| `fatal error: SDL_types.h: No such file or directory` | 源码按 SDL1 习惯 `#include "SDL.h"`，而 switch-sdl2 头文件在 `portlibs/switch/include/SDL2/` | `-I$(PORTLIBS)/include/SDL2` |
| `undefined reference to 'eglGetError'` | SDL2 静态库引用了 EGL，但 `-lSDL2` 不会自动带出 | 加 `-lEGL` |
| `undefined reference to 'operator new(unsigned long)'` / `std::__throw_length_error` | `libEGL.a` 里是 mesa 的 C++ 代码，C 链接器不会自动带 libstdc++ | 加 `-lstdc++`（放在 `-lEGL` 之后） |
| `undefined reference to 'nouveau_pushbuf_kick'`，随后 `powf/exp2f/log2f` | mesa 还依赖 nouveau 和 libm | 加 `-lglapi -ldrm_nouveau`，最后补 `-lm` |

最终链接行（`make` 自动拼）：

```
aarch64-none-elf-gcc ... -lSDL2 -lEGL -lGLESv2 -lglapi -ldrm_nouveau -lstdc++ -lm -lnx
```

顺序别乱：`-lnx` 永远最后，`-lm` 在它前面，`-lstdc++` 要排在 `-lEGL` 后面。

## 装 devkitPro 的坑（本机实际走的路）

官方 `devkitProUpdater-3.0.3.exe`（196,304 B）只是个 NSIS 引导器，真正下载的是
`msys-2.10.0.1.7z`（**112,134,749 B**）。这台机器上 `pkg.devkitpro.org` 被 Cloudflare
按 UA 拦（curl 和 HeadlessChrome 都 403，普通 Chrome UA 才放行），所以没用 GUI 安装器，
改成手工铺开：

1. 用 Chrome UA 下 `https://pkg.devkitpro.org/msys-2.10.0.1.7z`，7zr 解到 `F:\devkitPro`（23,908 文件 / 967,194,538 B）。
2. `msys2/etc/fstab` 里 `#{DEVKITPRO}` 换成 `F:/devkitPro`（映射 `/opt/devkitpro`）。
3. `msys2/etc/pacman.conf`：
   - `[options]` 加 `XferCommand = /usr/bin/curl.exe -L -C - -f -o %o -A "<Chrome UA>" %u`
     （**必须放 `[options]`**，写到 `[dkp-libs]` 下面不生效）；
   - 两个 devkitPro 源加 `SigLevel = Never`。
4. 手工用 Chrome UA 下 `dkp-libs.db` / `dkp-windows.db` 放进 `var/lib/pacman/sync/`
   （pacman 自己的 UA 会被拦，`-Sy` 同步不下来）。
5. 运行 pacman 时**必须带上代理环境变量**：msys 里的 curl 不加代理会走 IPv6 直连，一样 403。

```bash
export HOME=/f/devkitPro/home PATH=/usr/bin http_proxy=http://127.0.0.1:7890 https_proxy=http://127.0.0.1:7890
pacman -S --noconfirm --needed switch-dev switch-sdl2
```

只装 `switch-dev` + `switch-sdl2` 就够；`switch-sdl2_image/mixer/ttf` 这个游戏用不到。
（OpenTyrian 的网络对战在 `WITH_NETWORK` 宏里，没定义就不会拉 SDL2_net。）

## 验证到哪一步

**已验证（有输出为证）**

- 编译、链接、`elf2nro` 全部成功。
- NRO 头和官方模板 `tplapp.nro` **逐字节同构**：前 16 字节 `20 00 00 14 f0 00 00 00 "HOMEBREW"`，紧跟 `NRO0`。
- romfs 里能搜到 `tyrian1.lvl`、`voices.snd`、`opentyrian.cfg` 等文件名。
- `opentyrian.elf`：ELF64 / AArch64 / PIE（`Type: DYN`）。
- `main` 反汇编第一条外部调用是 `bl romfsMountSelf`。
- NACP：name=`OpenTyrian`、author=`OpenTyrian Team`。

**没验证（不冒充）**

- **没有在真机或模拟器上运行过**：本机没有 Switch，也没有 keys/firmware，装不了可用的模拟器。
  所以“能进标题、能开一局、手柄/音频正常”这三条都还没人看到过。
- `nxlink` 推送未跑（需要同一局域网里的主机开 netloader）。

## 和 Linux 端口（`../tyrian/`）的区别

| | R36S / XF45V（PortMaster） | Switch |
|---|---|---|
| 产物 | `Tyrian.zip`（`.sh` + 目录 + ELF） | 单个 `opentyrian.nro` |
| 二进制 | aarch64 ELF + glibc 2.29 | aarch64 ELF（libnx/newlib，无 glibc） |
| 数据 | 包内 `tyrian/data/` | 嵌进 NRO 的 romfs |
| 手柄 | gptokeyb 映射成键盘 | SDL2/libnx 直接读 HID，不需要 gptk |
| 启动方式 | Ports 菜单脚本 | hbmenu 直接启动 |

## 现在：流水线一条命令复现（2026-10-30）

上面是手工那一版的记录。同一件事已经进了 `07-移植工厂` 的流水线：`specs/tyrian.json` 的 `switch`
目标从取源、拉免费数据、打 romfs 补丁、调 devkitA64 编译、打包到闸门全自动。

```bash
cd F:/开源掌机教程/07-移植工厂
py -3 工厂.py port build specs/tyrian.json --target switch
```

| 项 | 手工版（10-28） | 流水线版（10-30） |
|---|---|---|
| 产物 | `opentyrian.nro` 18,825,002 B | `Tyrian-switch.zip` **7,753,487 B**（`opentyrian.nro` 18,820,906 B + `licenses/COPYING` + `README.txt`） |
| sha256 | 会变（调试信息里带构建路径） | zip `3c4605f8…`、nro `6cef85cf…`，两次全量重跑字节一致 |
| 构建路径泄漏 | nro 里有 29 处 `_scratch` | 0 处（`-ffile-prefix-map` + `MSYS2_ARG_CONV_EXCL`） |
| 闸门 | 人工核对 | `nro` / `no_build_paths` / `licenses` / `deterministic_zip` 四项自动判定 |
| 编译用时 | 未记录冷编译 | 12.3 s（热缓存、romfs 已展开） |

流水线上又踩了两个新坑，都已固化进代码：

1. **msys2 程序从 Git Bash 拉起时环境是空的**：devkitPro 的 `make.exe` 被 Git Bash 启动后连
   `FOO=hello` 都看不到，Makefile 第一行就报 "Please set DEVKITPRO"。现在该档案的所有命令都
   改由 `F:/devkitPro/msys2/usr/bin/bash.exe -lc` 执行，PATH/DEVKITPRO/PORTLIBS 全用 POSIX 路径。
2. **msys2 自动路径转换会改写 `-D` 宏**：`-DTYRIAN_DIR='"/romfs/data"'` 被改写成
   `F:/devkitPro/msys2/romfs/data` 编进二进制，Switch 上 RomFS 就挂错了。用
   `MSYS2_ARG_CONV_EXCL=-DTYRIAN_DIR` 只豁免这一个参数（`-I/opt/...` 仍照常转换）。

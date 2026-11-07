# duke3d/ —— 流水线（portkit）产出的第一个商业游戏引擎端口

2026-10-30 本机实跑（Windows 10 19045 / Git Bash / zig 0.17.0 / winlibs gcc 16.2.0 / Python 3.13）。

这个目录里**没有一个手写打包脚本**：引擎编译、补丁、包结构、校验全部由
`07-移植工厂/portkit` 按 `specs/duke3d.json` 跑出来，两行命令就是全部流程：

```bash
cd F:/开源掌机教程/07-移植工厂
py -3 工厂.py port build specs/duke3d.json --target handheld   # 掌机 aarch64 包
py -3 工厂.py port build specs/duke3d.json --target windows    # 同源 Windows 构建（验证用）
```

## 产物

| 文件 | 字节 | 说明 |
|---|---:|---|
| `package/Duke3D.zip` | 1,631,625 | sha256 `7f0699acf6723b8cccf78041fefc1bb0f41f283b45dfc96f1ac1be576a1ec3e9`，7 个条目 |
| `package/Duke3D.sh` | 1,082 | 启动脚本（0755，含 DUKE3D.GRP 缺失检查） |
| `package/duke3d/eduke32` | 2,954,184 | aarch64 ELF，sha256 `ef0cd212a1564fe6153f18156961ade2f1d6df5be99647891fb8358af04d1a25` |
| `package/duke3d/screenshot.png` | 127,388 | 640×480，同源 Windows 构建实跑 E1L1 截图 |
| `package/duke3d/port.json` | 815 | 5 顶层键 + 12 attr 键 |
| `package/duke3d/gameinfo.xml` | 187 | ES 条目 |
| `package/duke3d/licenses/gpl-2.0.txt` | 18,431 | EDuke32 引擎许可原文 |
| `package/duke3d/licenses/build.txt` | 282,131 | BUILD 引擎许可原文（源码树 `source/build/doc/build.txt`） |

阶段耗时（取自 `F:/_scratch/portkit/duke3d/state.json` 与 `logs/` 时间戳）：fetch 5.2s / build 5.9s（20 并行，`obj/` 有缓存）/ package 0.1s / verify 0.0s。
冷编译没单独计时，删掉 `obj/` 后重跑才会是完整时长。

## 输入

- 源码：`https://voidpoint.io/terminx/eduke32.git`，commit `ec5824db81817866f70da326d3811bb0f52b3517`（本地镜像 `F:/_scratch/duke_src`）
- 补丁：`specs/patches/duke3d-no-alsa.patch` —— 掌机没有 ALSA 头文件，把 `driver_alsa.cpp` 的入口换成空实现并加 `#if` 守卫
- SDL2 aarch64 前缀：`F:/_scratch/sdl2_aarch64`（Debian 2.26.5 的 `libSDL2.so` + 头文件 + X11 头）
- 许可：`specs/licenses/gpl-2.0.txt`、`specs/licenses/build.txt`
- 截图：`specs/duke3d/screenshot.png`（= `F:/_scratch/duke_run/shot_640.png`）

## 数据政策：包里不放任何商业数据

引擎是 GPL-2.0 源码编出来的，游戏数据 `DUKE3D.GRP` 完全由玩家自备（正版光盘、GOG 版或 3D Realms 的免费分享版都行）：

- spec 里 `data.policy = user-supplied`，`required = ["DUKE3D.GRP"]`
- 启动脚本检测不到 `DUKE3D.GRP` 就打印中英提示、`sleep 6` 后退出
- `data_policy` 闸门会扫包内所有文件名，命中 `*.grp` 等 19 类商业数据后缀直接判失败

截图右上角的 `UNREGISTERED SHAREWARE` 水印来自当时实跑用的免费分享版数据，不是引擎水印。

## 真正的编译命令

流水线展开出来的就是这一行（`port plan` 可以随时打印）：

```
make -C <work>/handheld/src -j 20 \
  PLATFORM=LINUX ARCH=aarch64 BITS=64 USE_OPENGL=0 POLYMER=0 \
  HAVE_GTK2=0 HAVE_FLAC=0 HAVE_VORBIS=0 USE_LIBVPX=0 USE_MIMALLOC=0 \
  CUSTOMOPT="-Wno-error=date-time -DEDUKE32_NO_ALSA -g0 \
             -ffile-prefix-map=<work>/handheld/src=. -Wl,--strip-debug" \
  SUBPLATFORM=HANDHELD eduke32
```

`SUBPLATFORM=HANDHELD` 是关键：设成 `LINUX` 会让 EDuke32 的 makefile 去链 `-lFLAC -lasound`
并给二进制加 `-Wl,-rpath,'$ORIGIN'`（RPATH 会被 ELF 闸门判失败）；设成空值也没用，
`ifndef` 会把空当未定义再回落到 `LINUX`。

## ELF 事实（闸门原样输出）

- `DT_NEEDED`：`libSDL2-2.0.so.0`、`libm.so.6`、`libc.so.6`、`libpthread.so.0`、`libdl.so.2` —— 5 个全在白名单
- 无 `libstdc++` 动态依赖、无 RUNPATH/RPATH
- glibc 符号最高 `GLIBC_2.29`，与 port.json 的 `min_glibc: 2.29` 一致
- `no_build_paths`：`_scratch` / `F:/` / `/f/` 三个探针 0 命中（`-ffile-prefix-map` 生效）

## 这一轮踩到的坑（按发生顺序）

1. **`X11/Xlib.h` 找不到**：Debian 的 `SDL_config.h` 打开了 X11 视频后端，编译期就要 X11 头。
   → 建了一个带 `x11/include` 的规范前缀 `F:/_scratch/sdl2_aarch64`，sdl2-config 垫片里补 `-I`。
2. **`alsa/asoundlib.h` 找不到**：两个原因叠在一起——(a) `pkg-config` 垫片对任何包都回 `exists`，
   让 configure 以为有 ALSA；(b) spec 把 `SUBPLATFORM` 写成了 `SUBLATFORM`，`GNUmakefile` 的
   `ifneq ($(SUBPLATFORM),LINUX)` 没排除 `driver_alsa.cpp`，`Common.mak` 的 `ifndef` 又把空值当 `LINUX`。
   → 垫片只认 sdl2；spec 改成 `SUBPLATFORM=HANDHELD`；删掉旧 `obj/`（残留的 .o 会让 make 认为已编过）。
3. **ELF 闸门把 64 位读成 16 位**：`parse_elf` 把 EI_CLASS 字节乘了 8。→ 改成 1→32 位、2→64 位。
4. **`deterministic_zip` 报“条目未按名字排序”**：打包时拿 `Path` 排序，Windows 下路径比较不分大小写。
   → 改成按归档内相对路径字符串排序。
5. **干跑时 `port.json` 目录不存在**：`--dry-run` 没有复制任何文件，暂存目录没建。→ 打包前先建 `licenses/`。

## Windows 同源构建（只作验证，不上掌机）

```
port build --target windows  →  build 84.5s，5/5 闸门 pass
dist/Duke3D-win-proof.zip    2,573,198 B  sha256 c545fb6177b17c6ab5f8003bb2f7f34fa77a144e89026834d70d8e22f4e96592
```

这一半的意义是证明**同一份 spec 换工具链档案就能出第二个平台的产物**（拼错一个 make 变量，
两边会一起错或一起对），而不是要发布 Windows 版。

## Switch 路线现状（老实说）

`nro` 闸门（0x10 处 `NRO0` + 首指令 ARM64 分支）和 `devkitpro` 工具链档案已经在流水线里，
但本机没装 devkitPro ⇒ `prepare` 阶段直接 **blocked（不是 fail）**，不会伪造一个“通过”。
要出 `.nro` 需要 `DEVKITPRO` 指向 devkitPro 安装目录并补 SDL2 switch 库，这一条是目前唯一缺的硬件侧条件。

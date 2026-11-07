# 第五个端口：Quake III Arena（ioquake3）

这个包的定位和其它几个不同：**它是“引擎”移植，不含任何游戏数据**。

- 引擎：[ioquake3](https://github.com/ioquake/ioq3)，GPL-2.0，固定到 commit `87a99d18206e878a20289f05ac3c16005dcae5c3`（2026-10-12, main）。
- 数据：**你自备**原版 `_baseq3/pak0.pk3` … `pak8.pk3`。包里一个 pak 都没有，也没有 `q3key` 序列号文件。
- 渲染：`renderer_opengl1.so` 是运行时 dlopen 的独立渲染器；RK3326 这类只有 GLES 的机器，靠随包的 **gl4es** 把桌面 GL1 翻成 GLES2。
- 音频：用 ioquake3 自带的 **SDL2 后端**，不用 OpenAL（原因见下）。

## 产物

| 文件 | 字节 | 说明 | sha256 |
|---|---:|---|---|
| `package/quake3/quake3.aarch64` | 1,014,856 | 引擎主程序，ELF 64-bit AArch64 | `6e6b335d3558419084ab3815f17e2d52c0cfa33c0a3f0ae594bd4e5c9799dd7e` |
| `package/quake3/renderer_opengl1.so` | 515,424 | GL1 渲染器，导出 `GetRefAPI` | `5ddcfc71cb4fcc9556b970669d0b0846aa0a0629523f7ea6309f752307a21998` |
| `package/quake3/gl4es.aarch64/libGL.so.1` | 1,273,640 | gl4es，导出 `glXGetProcAddressARB/glXChooseVisual` | `a0829cbf1d5eecdce3eb662ab4382e0f8152fa2e67b18573c69f8e3811008925` |
| `package/quake3/gl4es.aarch64/libEGL.so.1` | 23,800 | EGL 包装层，导出 `eglGetDisplay/eglCreateContext` | `9d04b9dda057b93109842affb38d72066efd57ce38eb544718e111baea928c6a` |
| `package/Quake3.zip` | 1,689,475 | 整个端口包（12 个条目） | `d1183665ac9778b791d47594e824fa2be010e5711cff537afad0f903402f3a00` |

包内结构：

```
Quake3.sh                        启动脚本（PortMaster 样板 + gl4es 接线）
quake3/port.json                 rtr=false，items=[Quake3.sh, quake3]
quake3/gameinfo.xml
quake3/quake3.aarch64
quake3/renderer_opengl1.so
quake3/gl4es.aarch64/libGL.so.1
quake3/gl4es.aarch64/libEGL.so.1
quake3/quake3.gptk               手柄映射（左摇杆=移动，右摇杆=转身，L1/R1=开火）
quake3/screenshot.png            640×480，Windows 版实跑截的
quake3/COPYING.GPL-2.0           ioquake3 的 GPL-2.0 全文副本
quake3/baseq3/PUT YOUR PK3 FILES HERE.txt
```

引擎/渲染器/gl4es 三个二进制的依赖都只有 `libSDL2-2.0.so.0 / libm / libc / libdl`（`libEGL.so.1` 额外依赖同目录的 `libGL.so.1`，链接时已写 `$ORIGIN` rpath）。最高符号版本 `GLIBC_2.29`，`port.json` 里 `min_glibc` 就写 2.29。

## 为什么这样搭

**1. 渲染器是独立 `.so`，而且默认不是 opengl1。**
ioquake3 把渲染器编译成 `renderer_opengl1.so` / `renderer_opengl2.so`，由 `CL_InitRef` 按 cvar `cl_renderer` 拼文件名后 `Sys_LoadDll`（先找二进制所在目录，再找 `fs_basepath`）。这个 cvar 的默认值是 **`opengl2`**，而 `opengl2` 渲染器需要 GL2 着色器，在 Mali 上根本没路。所以启动脚本里必须有 `+set cl_renderer opengl1`——删了它，日志里会直接出现 `Trying to load "renderer_opengl2.so" ... Failed to load renderer`。

**2. gl4es 只在需要的时候接上。**
GL1 渲染器用的是桌面 GL 1.x 固定管线，RK3326 的 Mali 驱动只给 GLES2。启动脚本照 PortMaster 惯例 source `libgl_${CFW_NAME}.txt`，当 `LIBGL_FB` 非空（说明该 CFW 只能走 gl4es）时才：

```bash
export LD_LIBRARY_PATH="$GAMEDIR/gl4es.${DEVICE_ARCH}:$LD_LIBRARY_PATH"
export SDL_VIDEO_GL_DRIVER="$GAMEDIR/gl4es.${DEVICE_ARCH}/libGL.so.1"
export SDL_VIDEO_EGL_DRIVER="$GAMEDIR/gl4es.${DEVICE_ARCH}/libEGL.so.1"
```

这与 PortMaster 官方 Quake 3 端口的做法一致（我们只是把引擎换成上游 ioquake3）。`LD_LIBRARY_PATH` 只在需要 gl4es 时加，避免把系统自带的 libGL 顶掉。

**3. 不用 OpenAL。**
最初版本编了 `-DUSE_OPENAL`，并从 Debian arm64 包里取 `libopenal.so.1` 随包发。自检当场抓到两个问题：那版 OpenAL 是 C++ 写的，要额外带 `libstdc++.so.6` + `libgcc_s.so.1`；而且它要求 **GLIBC_2.38**，R36S / XF45V 上直接起不来。改成 ioquake3 自带的 SDL2 音频后端（不定义 `USE_OPENAL`），依赖回到 SDL2/libc/libm，最高只剩 GLIBC_2.29。代价是没有 OpenAL 的 3D 定位音效，SDL 混音够用。

**4. 序列号不进包。**
官方 PortMaster Quake 3 端口（quake3e）包里带一个 `q3key`。我们没有、也不该带：那是用户的商业凭据。ioquake3 在找不到 `q3key` 时会自己生成一份随机内容（日志里的 `QKEY building random string`），单机和局域网完全不需要它；只有连 pure 在线服务器时才会用到用户自己的 key。

**5. 游戏逻辑不编进引擎。**
Q3 的 game/cgame/ui 是数据包里的 `vm/*.qvm`，由引擎的 VM 解释器加载，所以包里没有 `game.so`，也不需要。`com_basegame` 默认 `baseq3`，用户把 `pak0..pak8` 放进去即可。

## 怎么重建

```bash
# 需要: zig 0.17.0、git、curl、tar、python（只用标准库）
bash "01-教程库/移植原理/动手实践/quake3/build.sh"
```

脚本自己会在 `/f/_scratch/quake3_build` 建纯 ASCII 构建目录（zig 处理中文路径会乱码），做这些事：

1. 拉 ioquake3 固定 commit 到 `ioq3/`；
2. 下 SDL2-2.30.9 源码（**只借头文件**，运行时用设备自带的 libSDL2），再从 Debian 包取 arm64 `libSDL2-2.0.so.0` **只用于链接**，不进包；
3. 编 client（125 个源文件：client/server/qcommon/botlib/sys_unix + 内置 zlib/libogg/libvorbis）；
4. 编 `renderer_opengl1.so`（37 个源文件 + jpeg-9f 的 46 个 `.c`）；
5. 拉 gl4es 固定 commit `1891af323d4547487296e50ba5932bde65c7b345`，用 `NOX11 + EGL_NO_X11 + NO_GBM + GLX_STUBS + DEFAULT_ES=2 + USE_CLOCK` 编出 `libGL.so.1` 和 `libEGL.so.1`；
6. 拷进 `package/quake3/`，按固定时间戳（2026-10-28 00:00:00，`.sh` 755、其它 644）重打 `Quake3.zip`，最后跑 `check_port.py`。

Windows 验证版由同目录的 `build_windows.sh` 编：

```bash
bash "01-教程库/移植原理/动手实践/quake3/build_windows.sh"
```

它用同一份源码 + zig 的 `x86_64-windows-gnu` 目标，把平台源文件换成 `sys_win32.c` + `con_passive.c`，链接 SDL2 的 MinGW 导入库，产出 `quake3.exe`（1,338,368 B）、`renderer_opengl1.dll`（785,920 B）和 `SDL2.dll`。注意 `-DSDL_MAIN_HANDLED`：SDL 在 Windows 上默认把 `main` 改名成 `SDL_main` 并要求 `SDL2main` 提供 `WinMain`，定义它以后保持自己的 `main`，按控制台程序链接。

## 本机实测（Windows 版真跑）

数据用两套**免费可下载**的东西拼出来，只为在这台机器上看到画面：

- Quake III 官方 Demo 的 `pak0.pk3`（从 `linuxq3ademo.gz.sh` 自解包，48.9 MB 脚本 → `demo_payload/demoq3/pak0.pk3`，46,853,694 B，含 q3dm1/q3dm7/q3dm17/q3tourney2 四张图）；
- Q3 1.32b 点发布版的 `pak1..pak8`（官方免费发布的补丁包，`linuxq3apoint-1.32b-3.x86.run`，30.9 MB）。

Demo 的 `ui.qvm` 是 version 3，ioquake3 要 version 6，直接跑会停在 `User Interface is version 3, expected 6`；把点发布版的 pak1..pak8 一起放进去，`pak8.pk3` 里的 `vm/ui.qvm`（version 6）覆盖掉它，整条链路才通。ioquake3 认 demo 的 `pak0`（会打印一条 "using pak0.pk3 from the demo" 的警告），所以 9 个 pak 放齐后能进图。

实际启动命令与截图方式：

```bash
cd /f/_scratch/q3win/build
./quake3.exe +set cl_renderer opengl1 \
  +set r_mode -1 +set r_customwidth 640 +set r_customheight 480 +set r_fullscreen 0 \
  +set in_joystick 0 +set com_introPlayed 1 +set com_maxfps 60 \
  +map q3dm1 +wait 240 +screenshotJPEG +wait 20 +quit
```

输出（节选）：

```
ioq3 1.36 win_mingw64-x86_64 Oct 28 2026
MODE: 3, 640 x 480 windowed hz:N/A
GL_VENDOR: NVIDIA Corporation
GL_RENDERER: NVIDIA GeForce RTX 5060 Ti/PCIe/SSE2
Loading vm file vm/ui.qvm...
File "vm/ui.qvm" found in "...\baseq3\pak8.pk3"
...
Server: q3dm1
Loading vm file vm/qagame.qvm...
Loading vm file vm/cgame.qvm...
Wrote screenshots/shot0001.jpg
```

`shot0001.jpg`（83,386 B）就是包里的 `screenshot.png`（转 PNG 后 382,262 B，640×480）：q3dm1 里玩家视角、HUD 100 血、124 甲、20 发。**这张图只能证明“同一份源码 + GL1 渲染器 + 这套数据”能跑通**，不是 aarch64 真机截图。

两点注意：

- `map` 命令由服务器端注册，写在 `autoexec.cfg` 里会太早执行（日志里是 `Unknown command "map"`）；放在命令行 `+map` 才有效。
- 截图落在 `fs_homepath/baseq3/screenshots/`，Windows 下默认是 `%APPDATA%\Quake3\baseq3\screenshots\`。

## 装到机器上

```bash
# 1. 解包到 ports/（PortMaster 正常安装即可，也可以手工）
unzip Quake3.zip -d /roms/ports/

# 2. 放你自己的原版数据（不提供、不能提供）
cp /path/to/your/baseq3/pak0.pk3 ... pak8.pk3 /roms/ports/quake3/quake3/baseq3/

# 3. 启动：PortMaster 菜单里选 Quake III，或
cd /roms/ports/quake3 && ./Quake3.sh
```

启动脚本会先把 `baseq3/pak0.pk3` 是否存在检查一遍，缺了就用中英文提示并 `sleep 6` 退出。日志在 `ports/quake3/log.txt`。

想改分辨率/全屏：第一次启动后 `quake3/baseq3/q3config.cfg` 会生成，改 `r_mode`、`r_customwidth/r_customheight`，或者直接在启动脚本的 `+set` 里改。

## 自检

```bash
python -X utf8 "01-教程库/移植原理/动手实践/quake3/check_port.py" \
  "01-教程库/移植原理/动手实践/quake3/package/Quake3.zip"
```

38 项，当前 **38/38 通过**。除了通用项（结构、port.json 5+12 键、items 一致、ELF 64 位、e_machine=183、依赖白名单、glibc 上限、gptk/gameinfo/许可证/启动参数）之外，这个包特有：

- `rtr=false`，`inst` 指明放 `baseq3/`，**包内没有任何 `baseq3/pak*.pk3`**；
- **包内没有任何名为 `q3key` 的文件**；
- `renderer_opengl1.so` 导出 `GetRefAPI`；
- `gl4es/libGL.so.1` 导出 `glXGetProcAddressARB`、`glXChooseVisual`；`libEGL.so.1` 导出 `eglGetDisplay`、`eglCreateContext`；
- **包里没有 libopenal**（音频走 SDL2）；
- 启动脚本里同时出现 `cl_renderer opengl1`、`fs_homepath`、`SDL_VIDEO_GL_DRIVER/EGL_DRIVER`。

导出符号检查是真的看 `.dynsym` 且要求 `st_shndx != 0`——不是看名字在不在字符串表里。

## 许可证与边界

- 引擎源码 ioquake3：GPL-2.0（`quake3/COPYING.GPL-2.0` 是仓库里 `COPYING.txt` 的原样副本，15,429 B）。我们发布的是自己从这份源码编出来的二进制，符合 GPL。
- gl4es：MIT（`ptitSeb/gl4es`），随包的是自己编的 `libGL.so.1` / `libEGL.so.1`。
- 游戏数据：Quake III Arena 的 `pak0.pk3` 是商业内容，**用户自备**；`pak1..pak8` 是 id 免费发布的点发布补丁，但本包同样不带，由用户自己从正版安装目录里拿。
- 序列号：不随包、不内置；ioquake3 会自己生成一份随机占位文件，不影响单机/局域网。
- 本机验证用的 demo 数据和点发布数据都**没有**进入发布包（`check_port.py` 会拦）。

## 已经测了什么、没测什么

**本机实测（有产物为证）**

- aarch64 交叉编译成功：主程序 1,014,856 B、渲染器 515,424 B、gl4es 两个 so；`e_machine=183`、依赖白名单、最高 `GLIBC_2.29`。
- 渲染器导出 `GetRefAPI`，gl4es 两个库的 EGL/GLX 入口都在。
- 同一份源码的 Windows 版真实启动，GL1 渲染器加载、`q3dm1` 进图、HUD 正常，截图落盘。
- `build.sh` 连跑两次，`Quake3.zip` 的 sha256 一致（`d1183665…`，1,689,475 B）；自检 38/38。

**没测（不冒充）**

- 真机 R36S / XF45V 插卡启动：本机没接掌机。上机后失败先看 `ports/quake3/log.txt`，重点看是不是走到 `Trying to load "renderer_opengl1.so"`、以及有没有 `Using gl4es for OpenGL` 这行。
- gl4es 在 Mali 上的实际帧率/兼容性：只验证了二进制结构与导出符号，没有在 GLES 设备上跑过。
- 联机（需要用户自己的 `q3key`）与 Team Arena 数据（`missionpack/`）：都没测。

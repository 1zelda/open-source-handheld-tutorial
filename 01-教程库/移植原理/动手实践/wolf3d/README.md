# Wolfenstein 3D (ECWolf) on R36S / ARM Linux

第六个从源码交叉编译出来的 PortMaster 端口，补上前五个都没覆盖的一类：
**引擎开源可分发、游戏数据必须用户自备**（`rtr: false`）。
数据那条线用 id/Apogee 免费发布的分享版 WL1 在本机实跑验证，正式版 WL6/SOD 不随包。

| 东西 | 值 |
|---|---|
| 引擎 | `ECWolfEngine/ECWolf` 1.4.2 @ `ca1143e`（GPL-2.0+，Wolf3D 的源码级移植） |
| 随包引擎资源 | `ecwolf.pk3`（由源码 `wadsrc/` 生成，99 个条目，XLAT/DECORATE/SNDINFO 等文本定义） |
| 二进制 | `ecwolf.aarch64` **1,646,840 B**，aarch64 ELF、最高 `GLIBC_2.29` |
| 依赖 | `libSDL2-2.0.so.0`（CFW 自带）+ 自编 `libSDL2_mixer-2.0.so.0`(565,120 B) / `libSDL2_net-2.0.so.0`(53,448 B) |
| 成品包 | `package/Wolfenstein 3D.zip` **1,229,931 B**，sha256 `3f6c5c93bd1ae2027ed083992ac1643a06efcfe44ec7f7d76be1f18d63962a2b` |
| 自检 | `check_port.py` **42/42 通过** |

## 目录

```
wolf3d/
├─ build.sh              # 从零重建：拉 ECWolf(+子模块) → 编 mixer/net → 编 aarch64 → 打包 → 自检
├─ check_port.py         # 包校验器（42 项，含“包里不许有商业数据”这条正则）
├─ README.md             # 本页
└─ package/
   ├─ Wolfenstein 3D.sh  # 启动器（数据检查 + gptokeyb + --config/--savedir/640x480）
   ├─ Wolfenstein 3D.zip # 成品
   └─ wolf3d/
      ├─ ecwolf.aarch64
      ├─ ecwolf.pk3
      ├─ port.json       # items / rtr=false / min_glibc 2.29 / arch aarch64
      ├─ gameinfo.xml    # Wolfenstein 3D + Spear of Destiny 两条
      ├─ ecwolf.gptk
      ├─ screenshot.png  # 640×480，Windows 实跑 E1L1 游戏内
      ├─ libs.aarch64/
      ├─ LICENSES.txt / COPYING.GPL-2.0 / LICENSE.SDL2_*.txt
      └─ PUT YOUR WOLF3D DATA HERE.txt   # 空目录占位说明
```

## 为什么是 `rtr: false`

ECWolf 本身是 GPL 源码，随便发；但**它没有游戏内容**——地图、贴图、音效都在
`*.WL1/WL6/SOD` 那几组商业文件里（id Software 的资产，不是 ECWolf 的）。
所以按 PortMaster 的规矩：包只带引擎，`rtr` 填 `false`，`inst` 明说
“把你自己买的 WL6 或免费的 WL1 放进 `ports/wolf3d/`”。

`ecwolf.pk3` 容易被误会成“自带游戏”，其实它是**引擎定义文件**：用仓库里的
`wadsrc/` 目录经 `zipdir` 打出来的 DECORATE/XLAT/SNDINFO 文本，**不含任何 id 美术/地图**。
`check_port.py` 对包内所有条目和 pk3 内所有条目跑同一条数据文件正则
（`*.wl1|*.wl6|*.sod|*.wad|vswap.*|gamemaps.*|maphead.*|audiot.*|...`），命中即失败。

## 构建流水线

```bash
bash "01-教程库/移植原理/动手实践/wolf3d/build.sh"
```

全在 `F:/_scratch/ecwolf_build`（**必须纯 ASCII**）里做：

1. 拉 ECWolf 到固定 commit，`git submodule update` 固定 SDL_mixer / SDL_net 版本。
2. 从 Debian arm64 的 `libsdl2-dev` deb 里取 SDL2 头文件与 `libSDL2-2.0.so.0`（只当链接目标，不进包）。
3. 用 zig 手编**最小 SDL2_mixer**（只留 WAV/AIFF/VOC/Ogg-stb 解码）和 SDL2_net（4 个文件）。
4. 生成 gdtoa 的 `arith.h` / `gd_qnan.h`（交叉编译下这俩是构建期跑出来的，不能直接编）。
5. 宿主 MSVC 编一次 `zipdir`（`-DTOOLS_ONLY=ON`），拿到 `ImportExecutables.cmake`。
6. zig 交叉编 ECWolf，`-Wl,-s` 直接剥符号。
7. 拷产物 → 确定性 zip（固定时间戳/权限）→ 跑 `check_port.py`。

### 这一路上真正卡住的地方

| 现象 | 根因 | 处理 |
|---|---|---|
| cmake 退出码 127、**零输出** | `-DCMAKE_C_COMPILER` 指向含中文的路径（`F:/工具链/.../zig.exe`），CMake 静默失败 | 建 ASCII junction `F:\_scratch\zigwin` |
| `ninja: zig.exe qc ...` → `unknown command: qc` | Ninja 不认 `CMAKE_AR_ARG1`，把 `ar` 子命令丢了 | 覆写 `CMAKE_<LANG>_ARCHIVE_CREATE/APPEND/FINISH`，把 `ar qc`/`ranlib` 写死在规则里 |
| Windows 目标下同样的错又出现 | `Windows-GNU.cmake` 会把上面覆写的规则**再盖回去** | 改用 `.cmd` 包装脚本 `zig-ar.cmd` / `zig-ranlib.cmd` |
| `include could not find IMPORTFILE-NOTFOUND` | 交叉构建需要宿主构建导出的 `ImportExecutables.cmake` | `-DIMPORT_EXECUTABLES=.../host/ImportExecutables.cmake` |
| `windres` 不存在 | zig 不带资源编译器 | 桩脚本只把空 COFF 拷成 `<OBJECT>`（认**最后一个**位置参数，不是只认 `-o`） |
| `undefined reference: GetAdaptersInfo` 等 | Windows 版要显式链 socket/适配器库 | `-lws2_32 -lwinmm -limm32 -lversion -lsetupapi -liphlpapi` |
| `arith.h not found` | gdtoa 的表是构建期算出来的 | 用 x86_64-windows-gnu 编 `arithchk`/`qnan` 跑一遍，把结果拷进 `xa/deps/gdtoa/` |
| `undefined reference: read_id3v2_from_mem` | 少一个文件 | 补 `src/codecs/mp3utils.c`（它自己定义 `ENABLE_ID3V2_TAG`） |
| `zig objcopy --strip-all` 卡死 | zig 0.17 的 objcopy 有坑 | 不用 objcopy，链接时加 `-Wl,-s` |
| CMake 编 SDL2_mixer 报 `Could NOT find OpusFile` | 这个 fork 强制 `OPUS/MOD ON`，而 `external/` 子模块是空的 | 放弃它的 CMake，按文件清单手编最小版 |

## 验证到哪一步

**本机实测**

- aarch64 交叉编译成功；ELF `e_machine=183`；`DT_NEEDED` 只有
  `libSDL2_mixer-2.0.so.0`、`libSDL2_net-2.0.so.0`、`libSDL2-2.0.so.0`、`libm/libc/libpthread/libdl`；
  符号最高 `GLIBC_2.29`，`port.json` 的 `min_glibc` 就写 2.29。
- 同一份源码编成 Windows 版，**带分享版 WL1 真跑**：标题画面 → 菜单 → E1L1 游戏内，
  截图存 `screenshot.png`（640×480，HEALTH 100% / AMMO 8 / 手枪）。
  日志里能看到 `MAP01 - Wolf1 Map1` 和 `S_Init: Opened audio: 44100Hz (2 channels)`，
  说明地图加载与 OPL2 音乐通路都是通的。
- 42 项校验全过：目录结构、`port.json` 键与 `rtr=false`、`inst` 措辞、
  **包内与 pk3 内均无商业数据文件**、ELF 机器号/依赖/glibc、mixer 与 net 的导出符号、
  不夹带 `libSDL2`、启动器里 `libs.${DEVICE_ARCH}` / `--config` / `--savedir` /
  `--fullscreen --res 640 480` / `--joystick -1` / WL6 判断加 `exit 1`。
- 打包是字节级确定的：固定 zip 时间戳、`create_system=3`、`.sh` 记 `0755` 其余 `0644`、
  deflate 9 级，重复跑两次 sha256 相同。

**未实测（不冒充）**

- 真机 R36S / XF45V 插卡启动：本机没接掌机。
- 掌机上的实际帧率与手柄手感；`ecwolf.gptk` 的映射只按 PC 键盘逻辑推的。
- 正式版 WL6 / SOD：本机没有这两份商业数据，只用免费的 WL1 验证过。

## 已知取舍

- **只支持 aarch64**（R36S/XF45V 那条线）。要 armhf 得换 `-target arm-linux-gnueabihf` 重来一遍。
- 音乐走 ECWolf 内置的 OPL2 模拟（`src/dosbox/dbopl.cpp`、`src/mame/fmopl.cpp`），
  不依赖 SDL_mixer 的 MOD/MIDI 解码器——所以 mixer 才能裁到只剩 WAV/Ogg。
- 不附 `libSDL2`，交给 CFW；包里那两个 `.so` 只放 `libs.aarch64/`，靠启动器
  `LD_LIBRARY_PATH` 挂进去。
- 存档写在 `$GAMEDIR/saves`（启动器 `mkdir -p` 并传 `--savedir`），不在 SD 卡根目录乱丢。

## 法律

- 引擎 ECWolf 1.4.2：GPL-2+，随包附 `COPYING.GPL-2.0`；其中 ZDoom 派生部分为
  BSD-3-Clause，版权声明抄在 `LICENSES.txt`。
- SDL2_mixer / SDL2_net：zlib 许可，两份许可原文随包。
- **不含任何 id Software 商业数据**：无 `*.WL6`、无 `*.SOD`、无 `WOLF3D.EXE`、
  `ecwolf.pk3` 也不含 id 美术。分享版 WL1 是 id/Apogee 免费发布的，本包同样不附带。

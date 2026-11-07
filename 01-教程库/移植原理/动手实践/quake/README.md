# Quake on QuakeSpasm → R36S / ARM Linux

第三个从源码交叉编译出来的 PortMaster 端口。第一份 Doom 用的是“GPL 引擎 + BSD 数据”，
这份把“大作”往前推了一格：**Quake 的商业战役换成了 LibreQuake 的免费同名战役**，
引擎和地图、模型、声音全都允许再分发，包里不含任何 id Software 的商业数据。

| 东西 | 值 |
|---|---|
| 引擎 | QuakeSpasm 0.97.0（GPL-2.0，`sezero/quakespasm`） |
| 数据 | LibreQuake v0.09-beta `lite`（美术 BSD-3 / QuakeC GPL-2.0），`pak0.pak` 43,948,916 B + `pak1.pak` 5,856,792 B |
| 引擎资源 | `quakespasm.pak` 558,464 B（项目随源码发布，控制台字体/菜单图） |
| 二进制 | `quakespasm.aarch64` **707,088 B**，aarch64 ELF，依赖 `libSDL2-2.0.so.0` + `libGL.so.1`，最高 `GLIBC_2.27` |
| 成品包 | `package/Quake.zip` **25,905,909 B**，sha256 `41c069462fc4ec02ea2cb9b51c8a54dfa7a0cd85e533c9d2abf4bc9be08a9b99` |
| 自检 | `check_port.py` **22/22 通过**（比 Doom 多了 libGL、引擎 pak、三份数据文件三项断言） |

## 目录

```
quake/
├─ build.sh              # 从源码建 aarch64 二进制（一条命令，字节级可复现）
├─ check_port.py         # 包校验器（由 doom/ 那份复制，改了二进制前缀/必需数据/引擎 pak）
├─ README.md             # 本页
└─ package/
   ├─ Quake.sh           # 启动器（gptokeyb 把按键翻成键鼠）
   ├─ Quake.zip          # 成品
   └─ quake/
      ├─ quakespasm.aarch64
      ├─ quakespasm.pak  # 引擎自带 UI 资源，缺了没有控制台字体
      ├─ port.json       # items / rtr=true / min_glibc 2.27 / arch aarch64
      ├─ gameinfo.xml
      ├─ quake.gptk
      ├─ screenshot.png  # 640×480，Windows 实跑 LibreQuake 开局关
      ├─ data/id1/pak0.pak
      ├─ data/id1/pak1.pak
      ├─ data/id1/autoexec.cfg   # 掌机键位
      ├─ COPYING.GPL-2.0
      ├─ COPYING.LibreQuake-BSD3
      ├─ COPYING.LibreQuake-GPL2
      └─ README-IMPORTANT-LICENCE-INFO
```

## 为什么不是“Quake 共享版数据”

原来打算走 id 官方 shareware 包（`quake106.zip`），实测两条都不通：
quaddicted 的链接返回的是 HTML 页面，真正的镜像给的是 **16 位 DOS 自解压程序**（`deice.exe`），
本机 64 位 Windows 和 Wine 都跑不了它。共享版路线放弃，改用 LibreQuake——
它本来就是为“不买 Quake 也能玩”而做的完整免费战役（4 章 + 死斗地图），不是试玩关。

## 编译时做的取舍（源码零改动）

| 取舍 | 原因 |
|---|---|
| 排除 `snd_flac/vorbis/opus/mp3/mpg123/mp3tag/mikmod/modplug/xmp/umx` | 这些都要额外第三方解码库；先不要音乐，省掉依赖链 |
| 保留 `snd_wave.c` + `snd_codec.c` | 音效是 WAV，走 SDL2 音频，实测能初始化（44100 Hz 立体声） |
| 排除 `lodepng.c` | `image.c` 里已经 `#include "lodepng.c"`，再单独编译会重复定义 |
| 排除 `cd_null.c`，保留 `cd_sdl.c` | SDL2 版 `cd_sdl.c` 自己就把 CD 音频禁掉了，不需要 null 后端 |
| `-Wno-trigraphs -Wno-date-time` | zig/clang 把 `??` 三字符组和 `__DATE__` 当错误 |
| `-DDO_USERDIRS=0` | 存档/config 直接写 basedir，掌机上路径可预期 |
| 排除 `net_win/net_wins/net_wipx/pl_win/sys_sdl_win` | Linux 目标用 `net_bsd/net_udp/pl_linux/sys_sdl_unix` |

## 构建与复现

```bash
bash "01-教程库/移植原理/动手实践/quake/build.sh"
```

脚本自己下源码（锁到 commit `c9c8ee9`）、SDL2 头、两块 arm64 `.so`（只用于链接）和 LibreQuake，
在 `F:/_scratch/quake_build`（纯 ASCII 路径）里编，然后重打 zip 并跑自检。
换一个构建目录（`QB=/f/_scratch/quake_build3`）再跑一次，二进制与 zip 的 sha256 完全一致：

```
二进制 6b60d6fc500482d12111ed601d4dca088cf8011e73e3bbe3f55de20a2555d5b1  (707,088 B)
Quake.zip 41c069462fc4ec02ea2cb9b51c8a54dfa7a0cd85e533c9d2abf4bc9be08a9b99  (25,905,909 B)
```

能字节级复现是因为把 `__DATE__/__TIME__` 钉死了（引擎会把编译时刻印在版本串里，
不钉的话每次构建都差几分钟）。

Windows 验证版（同一份源码，只把 `pl_linux/sys_sdl_unix/net_bsd/net_udp`
换成 `pl_win/sys_sdl_win/net_win/net_wins/net_wipx`）：

```bash
zig cc -target x86_64-windows-gnu -O2 -DNDEBUG -DUSE_SDL2 -D_USE_WINSOCK2 -DDO_USERDIRS=0 \
  -Wno-trigraphs -Wno-date-time -I <SDL2>/include/SDL2 <上面的 69 个 .c> \
  <SDL2>/lib/libSDL2main.a <SDL2>/lib/libSDL2.dll.a -lopengl32 -lwinmm -lws2_32 -Wl,-s -o qs_win.exe
```

## 验证到哪一步

**本机实测（Windows x86_64，同一份引擎源码 + 同一份 LibreQuake 数据）**

- 启动到 LibreQuake 开局关（`data/id1` 原样拷入），640×480 跑通，截图见 `screenshot.png`。
- 控制台日志确认：`Video mode 640x480x24`、`Sound Initialization / SDL audio spec 44100 Hz`、
  `CDAudio disabled at compile time`、`execing autoexec.cfg` 无报错。
- 换 `+map start` 可反复进关；演示循环（demo1-3）自动播放。
- aarch64 二进制：`e_machine=183`、`NEEDED` 只有 `libSDL2-2.0.so.0 / libGL.so.1 / libm / libc`、
  符号版本最高 `GLIBC_2.27`（只有一个 `powf@GLIBC_2.27`，其余全是 2.17），所以 `min_glibc` 填 **2.27** 而不是 2.17。
- 包校验 22 项全过。

**未实测（不冒充）**

- 真机 R36S 插卡启动：本机没接掌机。R36S 的 ArkOS/JELOS 一般带 glibc 2.36 + SDL2 2.26+，满足 2.27 门槛。
- 右摇杆鼠标转身的手感：`quake.gptk` 里 `mouse_scale = 8192`（gptokeyb 对 RK3326 的推荐起步值），
  `autoexec.cfg` 里 `sensitivity 4`；真机嫌快就把 `mouse_scale` 调大，嫌慢就调小。
- OGG 音乐：LibreQuake 的 28 MB 配乐没打进包（需要 Vorbis 解码库），只保留音效。

## 掌机键位

| 手柄 | 键 | 作用 |
|---|---|---|
| 左摇杆 | w/a/s/d | 前后左右 |
| 右摇杆 | 鼠标移动 | 转身 / 抬头低头 |
| R2 | 鼠标左键 | 开火（`+attack`） |
| A / L2 | 空格 / 鼠标右键 | 跳 |
| X / 十字键上 | q | 下一把武器 |
| L1 / 十字键下 | r | 上一把武器 |
| Y | v | 近战（斧头） |
| R1 | z | 视角回正 |
| B | ctrl | 水里下潜 |
| Select | Tab | 计分板 |
| Start | Esc | 菜单（退出也在这里） |

## 法律

- 引擎 QuakeSpasm：`LICENSE.txt` 前两行 `GNU GENERAL PUBLIC LICENSE / Version 2, June 1991` → GPL-2.0，随包附 `COPYING.GPL-2.0`。
- `quakespasm.pak`：QuakeSpasm 发布包自带资源，与源码同许可（项目根就是 GPL-2.0 的 `LICENSE.txt`）。
- LibreQuake：`docs/README-IMPORTANT-LICENCE-INFO` 原文——“bsd3 is permissive and is what all the
  models textures and sounds are under；gpl2 … applies to the quakec, progs.dat and pop.lmp”。
  两份副本（`COPYING.LibreQuake-BSD3`、`COPYING.LibreQuake-GPL2`）都随包。
- 包里**不含** id Software 的 `pak0/pak1` 商业数据、不含 `id1` 原版音乐。
  想玩原版战役：把自己的正版 `pak0.pak`/`pak1.pak` 覆盖到 `data/id1/` 即可，引擎不用改。

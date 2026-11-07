# 移植原理

讲"移植到底是怎么发生的"、以及在这台机器上怎么把一个合法移植跑起来。这一层以前整个库是空的。

| 文件 | 解决什么问题 |
|---|---|
| `00-移植是怎么回事_小白完全教程.md` | 六条移植路线的区别与判据；为什么凡是合法移植都要你自备正版；GTA III/VC/SA/**V**、**Max Payne 1/2/3**、**合金装备**的逐个核实结论与出处；在 XF45V 上装 `gta3` / `maxpayne` 的完整六步命令；术语词典；硬边界 |
| `01-代码级解剖_一个真实移植仓库里改了哪几处.md` | 代码级。以 `orktes/max_arm64`（109 个文件，zip 22,944,719 B）为样本，逐行讲"运行时加载官方 `.so` + 打钩子"这条路：`hook_arm64` 的 3 条指令、`mprotect` 三态、ELF 自验、EGL/OpenAL/手柄/路径大小写/数据来源共**七处必改点**，每处给文件:行号；附授权与素材的文件级核对 |
| `02-交叉编译与打包_从一行C到一个能插卡玩的端口.md` | 动手级。本机零编译器 → zig 0.17.0（zip 100,268,137 B，解压 19,505 个文件）交叉编出真产物：`fbcheck.c` 3,984 B → aarch64 musl 静态 **1,588,784 B**；四条能用的命令 + 五条翻车报错原文；怎么读 ELF 头验货；glibc 双闸门；`port.json` 5+12 个键；成品 `动手实践/package/fbcheck.zip` **864,160 B** |
| `03-自己做一个能玩的端口_OpenTyrian实战.md` | 完整端口实战。OpenTyrian 52 个 `.c` → aarch64 **518,624 B**（GLIBC_2.29、依赖系统 SDL2）→ `Tyrian.zip` **5,039,180 B**；真实报错（隐式声明、`-l:` 路径、中文路径、配置语法）；Windows 同源码实跑截图；`check_port.py` 22/22；上卡/SSH 测试；**Switch 的 devkitPro 路线已实际编出 `.nro`（18,825,002 B）**，含链接四连错与 Cloudflare/中文路径两个环境坑 |
| `动手实践/` | 上面两篇的可执行副本：`fbcheck.*`（探针示例）与 `tyrian/`（完整可玩端口：`package/Tyrian.zip` / `build.sh` / `check_port.py` / `README.md`）与 `switch/`（`opentyrian.nro` / `Makefile` / `build_switch.sh` / `README.md`）与 `doom/`（第二个 aarch64 端口：GPL-2.0 的 doomgeneric + BSD 许可的 Freedoom 数据，`package/Doom.zip` 10,711,009 B、19/19 自检、无音效）与 `quake/`（第三个 aarch64 端口：GPL-2.0 的 QuakeSpasm 0.97.0 + LibreQuake v0.09-beta 免费战役，`package/Quake.zip` 25,905,909 B、22/22 自检、右摇杆鼠标转身）与 `quake2/`（第四个 aarch64 端口、第一个“大作本体”：GPL-2.0 的 Yamagi Quake II 引擎 + 三个渲染器 + `baseq2/game.so`，`package/Quake2.zip` 1,509,627 B、39/39 自检、**商业 pak 用户自备**、默认 GLES1 硬加速）与 `quake3/`（第五个 aarch64 端口：GPL-2.0 的 ioquake3 + 运行时 dlopen 的 `renderer_opengl1.so` + 随包 **gl4es** 把桌面 GL1 翻成 GLES2，`package/Quake3.zip` 1,689,475 B、38/38 自检、**不带 pak/不带 q3key**）与 `wolf3d/`（第六个 aarch64 端口、`rtr:false` 的引擎包：GPL-2.0 的 ECWolf 1.4.2 + 自编 SDL2_mixer/net + 源码生成的 `ecwolf.pk3`，`package/Wolfenstein 3D.zip` 1,229,931 B、42/42 自检、**WL6/SOD 用户自备，本机用免费 WL1 实跑**、zig 交叉构建的 ar/windres/gdtoa 三处坑）与 `diablo/`（第七个 aarch64 端口、`rtr:false` 的大型商业游戏引擎：Sustainable Use 许可的 DevilutionX 1.6.0-dev @ `aa3dc7b1` + 随包 184 个引擎界面资源，`package/Diablo.zip` 4,915,310 B、33/33 自检、**DIABDAT.MPQ/spawn.mpq 用户自备**、自带 SDL2 手柄支持不叠 gptk、12 个 FetchContent 子依赖里踩穿 cmake/zig 九个坑）与 `cnc/`（第八个 aarch64 端口、**一个包两个游戏**：GPL-3.0+EA 附加条款的 Vanilla Conquer @ `ce83b59` 同时编出泰伯利亚黎明与红警 1，`package/Cnc.zip` 2,121,783 B、61/61 自检、**MIX 数据用户自备**且 `td/`、`ra/` 分目录放、CFW 没有 OpenAL 所以随包 `libopenal.so.1`、引擎自带手柄、三处“插值表”缺陷导致整屏黑白棋盘格已定位并修掉）与 `openttd/`（第九个 aarch64 端口、第一个**连素材都自由**的 `rtr:true` 包：GPL-2.0 的 OpenTTD 15.3 @ `14ec60f2` + 随包 OpenGFX 7.1 / OpenSFX 1.0.3 / OpenMSX 0.4.2 与 6 份 `lang/*.lng`，`package/OpenTTD.zip` 20,259,152 B、45/45 自检、**不需要原版 TTD 数据**、宿主 strgen 交叉/date-time/PCH/cstdlib/构建路径五处坑） |

配套阅读：
- 机型侧的 PortMaster 行为（能力标签、`.CUSTOM_DEVICE`、双卡坑）→ `../机型固件/XiFan_XF45V/00-XF45V完全指南.md` §七
- 端口包的逐包判定 → `../../04-游戏资源库/公版与开源游戏/PortMaster移植游戏指南.md` 与 `portmaster_自备数据审计.tsv`
- 已入库的移植成品 → `../../04-游戏资源库/爆款收录/README.md`
- 自己想写引擎 → `../00-C++学习路线.md`

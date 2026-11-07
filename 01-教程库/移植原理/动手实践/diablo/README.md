# Diablo (DevilutionX) on R36S / ARM Linux

第七个从源码交叉编译出来的 PortMaster 端口，和 Wolfenstein 3D 同属
**引擎开源可分发、游戏数据必须用户自备**（`rtr: false`）那一类，
但难度不在引擎小、而在依赖树大：一个 CMake 项目里挂了 12 个 FetchContent 子依赖。

分享版数据（`spawn.mpq`，暴雪/GoG 免费发布）只在本机 Windows 版上做“引擎能不能吃数据”的验证，
不进包；正式版 `DIABDAT.MPQ` 由玩家自备。

| 东西 | 值 |
|---|---|
| 引擎 | `diasurgical/devilutionX` 1.6.0-dev @ `aa3dc7b1`（Sustainable Use License 1.0） |
| 二进制 | `devilutionx.aarch64` **4,092,016 B**，sha256 `c53752eec58fbef29919db92ba98f4bea7d6607a599d94c293a774489ee5445e` |
| 架构/依赖 | aarch64 ELF；只要 `libSDL2-2.0.so.0` + libc/libm/libpthread/libdl，**不带 libstdc++**（libc++ 静态链入） |
| 随包资源 | `assets/` **184 个文件 / 5,248,228 B**（字体、UI 图、城镇地牢模板、tsv 数据、lua） |
| min_glibc | **2.29**（实测最高符号就是 `GLIBC_2.29`） |
| 成品包 | `package/Diablo.zip` **4,915,310 B**，sha256 `42fc59d88f2a0251cf7f5c077a6844d8f06d6cf90ebc557e2c2e6a6bea8e7612` |
| 自检 | `check_port.py` **33/33 通过**（目录模式和 zip 模式都跑过） |

## 目录

```
diablo/
├─ build.sh              # 从零重建：拉源码 → 备 SDL2 垫片 → zig 交叉编 → 组装 → 确定性打包 → 自检
├─ check_port.py         # 包校验器（33 项，含“包里不许有 .mpq/存档”这条正则）
├─ README.md             # 本页
└─ package/
   ├─ Diablo.sh          # 启动器（数据检查 + --data-dir/--save-dir/--config-dir，手柄交给引擎）
   ├─ Diablo.zip         # 成品
   └─ diablo/
      ├─ devilutionx.aarch64
      ├─ assets/         # 引擎自带资源（见下）
      ├─ port.json       # items / rtr=false / min_glibc 2.29 / arch aarch64
      ├─ gameinfo.xml
      ├─ screenshot.png  # 640×480，Windows 实跑：战士在崔斯特瑞姆，背包里一把短剑
      ├─ licenses/       # 13 份（DevilutionX 本体 + 每个静态链入的第三方）
      ├─ LICENSES.txt    # 人话版许可说明
      └─ PUT YOUR DIABLO DATA HERE.txt
```

和其他六个端口不一样的地方：**没有 `libs.aarch64/`**（不捆绑任何 .so），
**没有 `.gptk`**（DevilutionX 自带 SDL2 GameController 支持，直接用 PortMaster 的
`$sdl_controllerconfig`，再叠一层键盘映射反而会和它抢手柄）。

## 为什么是 `rtr: false`

DevilutionX 是 Diablo 1 的**源码级重写**，代码可发；但**美术/音效/地图全在原版数据里**。
包里的 `assets/` 是引擎资源——字体位图、按钮图、城镇/地牢模板、怪物行为表、lua 脚本，
相当于 ECWolf 的 `ecwolf.pk3`；真正的游戏内容（贴图、怪物、物品、语音）都在 MPQ 里。

- 想玩正式版：自备 `DIABDAT.MPQ`（GoG 版里有）放进 `ports/diablo/`
- 想先试玩：暴雪的免费分享版 `spawn.mpq` 也行（只有前两层地牢，角色固定战士）
- `check_port.py` 对包内所有条目跑 `\.(mpq|sv|hsv)$`，命中即失败

## 构建流水线

```bash
bash "01-教程库/移植原理/动手实践/diablo/build.sh"
```

全在 `F:/_scratch/devx_build`（**必须纯 ASCII**）里做：

1. 拉 DevilutionX 到钉住的 commit（`--depth 1` 只取这一个）。
2. 从 Debian arm64 的 `libsdl2-2.0-0` + `libsdl2-dev` 两个 deb 里取 SDL2 头文件、
   `libSDL2-2.0.so.0` 和 cmake 配置——**只当链接垫片，不进包**，设备上用 CFW 自带的。
3. 写工具链文件（zig cc/c++ 的 `.cmd` 包装 + ar/ranlib 规则覆写）并配置。
4. 一次 ninja 编完 245 个目标：DevilutionX 本体 + FetchContent 拉下来的
   zlib/bzip2/lua/sol2/SDL2_image+libpng/SDL_audiolib/libsmackerdec/mpqfs/tl/
   SheenBidi/unordered_dense/magic_enum。
5. 拷二进制与 `assets/` → 确定性 zip（固定时间戳/权限）→ 跑 `check_port.py`。

关键开关：`NONET=ON`（不链 libsodium，单人游戏用不上）、`BUILD_ASSETS_MPQ=OFF`
（直接发 `assets/` 目录，不用 `devilutionx.mpq` 打包）、`BUILD_MOD_MPQS=OFF`
（Hellfire 资料片是另一份商业数据，不做）、`DEVILUTIONX_SYSTEM_ZLIB/BZIP2=OFF`
（设备上没有这两个 dev 包，让 CMake 自己拉源码编）。

### 这一路上真正卡住的地方

| 现象 | 根因 | 处理 |
|---|---|---|
| `Could not find a package configuration file provided by "SDL2"` | Debian 的 `sdl2-config.cmake` 在 `lib/aarch64-linux-gnu/cmake/SDL2/`，配置里用 `../../../..` 反推前缀 | `-DSDL2_DIR=<前缀>/lib/aarch64-linux-gnu/cmake/SDL2`，并把前缀设成 `CMAKE_FIND_ROOT_PATH` |
| `set_and_check() ... does not exist: .../bin` | 该配置文件会检查前缀下的 `bin/` 目录 | 建一个空 `bin/` |
| `SDL_config.h` 里只有一句 `#include "_real_SDL_config.h"` | multiarch 把真配置放在 `include/aarch64-linux-gnu/SDL2/` | 把 `_real_SDL_config.h` 展平覆盖 `SDL_config.h` |
| libpng: `Could NOT find ZLIB` | 设备上没有 zlib dev 包，FindZLIB 也找不到交叉目标 | `-DDEVILUTIONX_SYSTEM_ZLIB=OFF -DDEVILUTIONX_SYSTEM_BZIP2=OFF`（走 FetchContent 源码） |
| Lua: `libm not found` | 它的 CMake 在 configure 期就要求 `LIBM` 有值 | 预置 cache `-DLIBM=m`（真链接由 zig 的 glibc sysroot 完成） |
| `error: unknown command: -E` | libpng 的生成脚本直接调 `${CMAKE_C_COMPILER} -E`，zig 需要 `cc` 子命令 | 编译器换成 `.cmd` 包装器（`zig cc` / `zig c++`） |
| `ninja: zig.exe qc ...` | Ninja 不认 `CMAKE_AR_ARG1`，`ar` 子命令被吞 | 覆写 `CMAKE_<LANG>_ARCHIVE_CREATE/APPEND/FINISH`，把 `ar qc`/`ranlib` 写死 |
| `Trimming assets` 那步报“系统找不到指定的路径” | CMake 生成的 `.bat` 写入了 **cmake 自己的安装路径**（中文 `F:/工具链/...`），cmd 按 cp936 读 UTF-8 就崩 | 把 cmake 整份复制到 ASCII 路径再调用（junction 没用，CMake 会解析真实路径） |
| `no matching function for call to 'DrawHalfTransparentUnalignedBlendedRectTo'` @ `primitive_render.cpp:184` | 关掉 16-LUT 才会走到这个未更新的重载，是上游 bug | 用上游默认值 `DEVILUTIONX_PALETTE_TRANSPARENCY_BLACK_16_LUT=ON` |
| （Windows 验证版）`error: unsupported linker arg: --undefined` | SDL2main 的 cmake 配置塞了 `-Wl,--undefined=WinMain` | 在验证副本里删掉这半句（只影响 Windows 验证版） |

## 本机实跑验证（Windows 版，分享版数据）

`VERIFY_WIN=1 SDL2WIN=<mingw SDL2 前缀> bash build.sh` 会额外编一个
`devilutionx.exe`；把分享版 `spawn.mpq`（25,448,219 B，sha256
`64427cd7c1ba904eaa2e0031c16a6b136d0ecef9abc888c5ff8344b459356e38`）放在 exe 同级目录，
日志里能看完整条启动链：

```
VERBOSE: Found user preferred locales: zh_CN, zh_CN, zh, en
VERBOSE: Best match locale: en
INFO: Created renderer: direct3d
VERBOSE: Missing: DIABDAT
VERBOSE:   Found: spawn in .\
VERBOSE: Aulib sampleRate=22050 channels=2 frameSize=221 format=0x8120
VERBOSE: Control: device None -> KeyboardAndMouse, mode None -> KeyboardAndMouse
VERBOSE: Loading palette from ui_art\diablo.pal
VERBOSE: Re-encoding dungeon CELs: 3,547 frames, 2,176,004 bytes
VERBOSE: Load thread finished in 70ms
```

也就是：MPQ 找到了、音频设备开了、调色板/地牢 CEL 解码成功、进游戏存档建了
（`saves\spawn_0.sv`）。截图链走完了标题 → 选职业 → 分享版提示 → 新游戏 → 崔斯特瑞姆游戏内
（HUD 血蓝球、背包、物品名“短剑”全在）。

`assets/` 这套“目录当资源”的模式是有效的：日志里 `assets: ...\assets\`，
不需要 `devilutionx.mpq`。

### 中文界面（本包没带，原因写在代码里）

日志第一行就暴露了：系统 locale 是 `zh_CN`，引擎会去找 `zh_CN.mo/.gmo`，找不到就回落到英文。
中文没随包，卡在两件事上：

1. 上游的 `zh_CN.po` 要 `msgfmt` 编成 `zh_CN.gmo` 才生效（本机没有 gettext）；
2. `Source/utils/language.cpp` 里，非英文 locale 在“高字号”下**强制要求 `fonts.mpq`**
   （`github.com/diasurgical/devilutionx-assets` 的 v5 发布，58.6 MB，CC BY-NC-SA 4.0），
   没有就弹 “Missing fonts.mpq” 并强制回落英文。

一个 4.9 MB 的包塞 58.6 MB 字体只为中文 UI，不划算，所以默认英文。
真要中文：下载 `fonts.mpq` 放 `ports/diablo/`，再把上游 `Translations/zh_CN.po`
用 Poedit/`msgfmt` 编成 `zh_CN.gmo` 放进 `assets/`，然后在 Options → Language 里选中文。

## 许可

| 组件 | 许可 | 随包原文 |
|---|---|---|
| DevilutionX 本体 + `assets/` | Sustainable Use License 1.0（免费分发、非商业；必须随附条款） | `licenses/DevilutionX.txt` |
| SDL_audiolib（静态链入） | LGPL-3.0 | `licenses/SDL_audiolib-LGPL-3.0.txt` |
| libsmackerdec（静态链入） | LGPL-2.1 | `licenses/libsmackerdec-LGPL-2.1.txt` |
| zlib / bzip2 / libpng / SDL2_image / sol2 / Lua / mpqfs / tl / magic_enum / unordered_dense | zlib/MIT/Apache-2.0 等 | `licenses/*.txt` |
| SheenBidi | Apache-2.0 | `licenses/SheenBidi-Apache-2.0.txt` |
| libSDL2 本体 | 设备 CFW 提供，不随包 | — |
| 游戏数据（DIABDAT.MPQ / spawn.mpq） | 暴雪资产，用户自备 | 不随包 |

两个 LGPL 库是**静态**链进二进制的。按 LGPL 3.0 §4(d)/2.1 §6 的要求，
`LICENSES.txt` 里写清了上游来源 + 钉住的 commit + 重新链接的做法（改 `build.sh` 的
`4. 一次 ninja` 那步，把对应库换成 `.so` 或替换目标文件后重编）。

## 装到机器上

1. 把 `Diablo.zip` 解到 `ports/`（PortMaster 会摆成 `ports/diablo/` + `Diablo.sh`）。
2. 把你的 `DIABDAT.MPQ`（或免费的 `spawn.mpq`）放进 `ports/diablo/`。
3. 启动即可；存档在 `ports/diablo/saves/`，配置写 `ports/diablo/diablo.ini`。
4. 手柄：引擎自带映射，不用配 gptk。默认 **B 主行动**（攻击/交谈）、**Y 副行动**（开箱/开门/拾取）、
   **X 放法术**、**A 取消/关菜单**、方向键走位、**LB/RB 喝血/喝蓝**、
   按 Back 进菜单导航（菜单里再按十字上下/左右切页、A 确认、B 返回）、摇杆按下是地图。
   全都能在 Options → Controller 里改。

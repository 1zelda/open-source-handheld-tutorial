# Freedoom on doomgeneric → R36S / ARM Linux

第二个从源码交叉编译出来的 PortMaster 端口，用来补上 Tyrian 没覆盖的一类：
**引擎与数据都允许再分发**（GPL-2.0 引擎 + BSD 数据），不需要用户自备任何东西。

| 东西 | 值 |
|---|---|
| 引擎 | `ozkl/doomgeneric`（GPL-2.0，ID Software Doom 源码的可移植封装） |
| 数据 | Freedoom 0.13.0 `freedoom1.wad`（BSD 三条款，28,795,076 B） |
| 二进制 | `doomgeneric.aarch64` **475,784 B**，aarch64 ELF、依赖 `libSDL2-2.0.so.0`、最高 `GLIBC_2.17` |
| 成品包 | `package/Doom.zip` **10,711,009 B**，sha256 `587f045d06c3e6d8b8f1ba0d69b5a9ccb3fae8c93ffbc88b68e75bd86f387200` |
| 自检 | `check_port.py` **19/19 通过** |

## 目录

```
doom/
├─ build.sh              # 从零重建：拉源码/头文件/WAD → 编 aarch64 → 打包 → 自检
├─ check_port.py         # 包校验器（由 tyrian/ 那份复制，只改 3 处常量）
├─ README.md             # 本页
└─ package/
   ├─ Doom.sh            # 启动器（gptokeyb 把按键翻成键盘）
   ├─ Doom.zip           # 成品
   └─ doom/
      ├─ doomgeneric.aarch64
      ├─ port.json       # items / rtr=true / min_glibc 2.17 / arch aarch64
      ├─ gameinfo.xml
      ├─ doom.gptk
      ├─ screenshot.png  # 640×400，Windows 实跑标题菜单
      ├─ data/freedoom1.wad
      ├─ COPYING.GPL-2.0
      └─ COPYING.freedoom
```

## 为什么选这一组

- **引擎 GPL-2.0**：doomgeneric 根目录 `LICENSE` 首行 `GNU GENERAL PUBLIC LICENSE Version 2`。
- **数据 BSD**：Freedoom `COPYING.txt` 是 BSD 式三条款，明确允许再分发二进制；
  它是**独立创作的美术/关卡**，不是 id 商业 WAD，所以整包可以随附数据。
- 对比 Tyrian：那份是“引擎开源 + 数据免费但需注明出处”，这份连数据都允许再分发。

## 三处补丁（上游源码直接编不过 / 不适合掌机）

| 现象 | 根因 | 补丁 |
|---|---|---|
| `allegro/base.h: No such file` | 目录里有 4 个 Allegro 后端源文件，Makefile.sdl 本来就不编它们 | 编译列表排除 `i_allegro*.c`、`doomgeneric_allegro.c` 等其它平台后端 |
| `call to undeclared library function 'tolower'` | clang/zig 把隐式声明当错误，源文件漏 `<ctype.h>` | 在 `doomgeneric_sdl.c` 顶部补 `#include <ctype.h>` |
| Windows 下 `unistd.h` 不存在 | SDL 后端无条件包含它，但代码并没用到 | 用 `#ifndef _WIN32` 包住 |
| 640×400 小窗，掌机上不满屏 | 上游固定 `SDL_WINDOW_SHOWN` | 改成 `SDL_WINDOW_FULLSCREEN_DESKTOP` |

## 构建

```bash
bash "01-教程库/移植原理/动手实践/doom/build.sh"
```

脚本会在 `F:/_scratch/doom_build`（纯 ASCII 路径）里重新下载并编译。
校验单包：

```bash
python -X utf8 "01-教程库/移植原理/动手实践/doom/check_port.py" \
  "01-教程库/移植原理/动手实践/doom/package/Doom.zip"
```

## 验证到哪一步

**本机实测**

- aarch64 交叉编译成功；ELF 头 machine=183、NEEDED=`libSDL2-2.0.so.0`、最高 `GLIBC_2.17`。
- 同一份源码编成 Windows 版，带 `freedoom1.wad` 实跑到标题菜单并截图（`screenshot.png`）。
- `port.json` 5+12 键、items、`data/freedoom1.wad`、两份许可证副本等 19 项校验全过。

**未实测（不冒充）**

- 真机 R36S / XF45V 插卡启动：本机没接掌机。
- 音效：本包**不带音效**。要加得链接 `SDL2_mixer` 并定义 `FEATURE_SOUND`，
  多一个运行时依赖，先用无音版跑通画面与输入。

## 已知取舍

- 无音效（见上）。
- doomgeneric 只处理键盘事件，所以走 PortMaster 标准做法：`gptokeyb` 把 ABXY/十字键翻成
  `ctrl/space/shift/方向键`，映射表在 `doom.gptk`。
- 存档由 doomgeneric 写当前目录（`$GAMEDIR`）；掌机上该目录可写。

## 法律

- 引擎 GPL-2.0：随包附 `COPYING.GPL-2.0`，源码地址写在 `port.json` 与这里。
- 数据 Freedoom：随包附 `COPYING.freedoom`，允许再分发。
- 不含任何 id Software 商业 WAD，也不含任何商业游戏数据。

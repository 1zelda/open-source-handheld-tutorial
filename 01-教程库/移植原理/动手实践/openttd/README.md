# OpenTTD（运输大亨豪华版）→ R36S / XF45V 端口

1994 年 Chris Sawyer 的《Transport Tycoon Deluxe》被开源重写成 **OpenTTD**，跑在 aarch64
掌机上。和前面几个端口不一样：**素材也是自由的**（OpenGFX / OpenSFX / OpenMSX 三套
社区重制素材，许可允许再分发），所以这个包 `rtr: true`，拷进去就能玩，不需要原版光盘。

- 上游：<https://github.com/OpenTTD/OpenTTD>
- 钉住版本：标签 `15.3`，commit `14ec60f248547d4d062a1160f0fc26d742319888`
- 引擎许可：GPL v2.0（`licenses/OpenTTD-GPL-2.0.txt`），**源码未打任何补丁**
- 素材许可：OpenGFX GPL-2.0 / OpenMSX GPL-2.0 / OpenSFX CC BY-SA 3.0

## 包里有什么

```
OpenTTD.zip
├── OpenTTD.sh                启动脚本（HOME 指进包目录，存档跟着包走）
└── openttd/
    ├── port.json  gameinfo.xml  LICENSES.txt  screenshot.png
    ├── licenses/             引擎与三套素材、SDL2 的许可原文
    ├── openttd.aarch64       主程序 12,347,832 B（SDL2 后端，libc++ 静态链入）
    ├── openttd.gptk          左摇杆当鼠标（配 PortMaster 自带的 gptokeyb）
    ├── lang/                 语言表（英/英式/简中/繁中/日/韩）
    └── baseset/              OpenGFX 7.1 + OpenSFX 1.0.3 + OpenMSX 0.4.2，约 19 MB
```

SDL2 用 CFW 自带的，包里不带本体；gptokeyb 由 PortMaster 提供。配置文件写在
`openttd/.openttd/openttd.cfg`（因为启动脚本把 `HOME` 指进了包目录），第一次启动写
`fullscreen = true` + `resolution = 640,480`。

`lang/*.lng` 不是可选的：引擎找不到语言表会直接报 `No available language packs
(invalid versions?)` 然后退出，**连主菜单都进不去**。这些 `.lng` 是构建时用宿主
`strgen` 从 `src/lang/*.txt` 生成的，不是仓库里现成的文件。

## 怎么玩

| 键 | 作用 |
| --- | --- |
| 左摇杆 | 鼠标移动（`deadzone_scale = 6`，越小越快） |
| A | 左键（确认、铺路、选工具） |
| B | 右键（取消、查地块信息） |
| X | 中键 |
| Y | 空格（游戏中暂停 / 地图滚动键） |
| L1 | 慢速鼠标（铺铁路、拖窗口时用） |
| R1 | Shift（修路时按住是强制/拆除） |
| Back | Esc |
| Start | Enter |

OpenTTD 本身只有鼠标键盘操作，这里靠 gptokeyb 把左摇杆映射成相对鼠标移动。640x480 上
工具条图标比较小，L1 慢速是必须的。

## 构建

```bash
bash build.sh                     # 全量：宿主工具 + 交叉编译 + 组装 + 打包 + 自检
PACKAGE_ONLY=1 bash build.sh      # 只重新组装/打包（改 port.json、换素材时用）
SKIP_ZIP=1 bash build.sh          # 只编不打包
WIN_VERIFY=1 bash build.sh        # 顺带编一个 Windows 同源版做实跑验证
```

依赖：zig 0.17.0、cmake 3.31、ninja、git、curl、python（只用标准库）。构建根默认
`/f/_scratch/ottd_build`（`BUILD_ROOT=` 可改，**必须纯 ASCII**）。

四段流程：取 SDL2 arm64 头文件包 → **编一个 Windows 版宿主 strgen** → 交叉编译 OpenTTD
→ 校验并解出三套素材、组装、确定性打包、跑 `check_port.py`。

自检 45 条（`python check_port.py package/OpenTTD.zip`）：一个启动脚本与一个二进制、
AArch64/依赖白名单/glibc 上限、无构建期 RPATH、二进制里不许留构建机路径、
三套 baseset 是否齐全（`opengfx.obg` / `opensfx.obs` / 31 首 `*.mid`）、`lang/` 至少有
英文和简体中文、截图是真 PNG、包内不许出现原版 TTD 的素材、五份许可原文、`.gptk` 的
鼠标键位、启动脚本的 `HOME`/SDL 驱动/gptokeyb/清理。

成品：`OpenTTD.zip` 20,259,152 B（68 个文件），
sha256 `d5d7af4b02d4d3af6af8dbaa856b3bc0849448e8c32211712bdf5c32a17e3efb`。
打包是确定性的（固定时间戳、固定权限），同一份输入重跑两次字节相同。

## 踩过的坑

- **交叉编译要宿主 `strgen`**。语言表是 `strgen` 生成的，而 `strgen` 得在本机跑，
  不能用 aarch64 编译器编。做法：先用 zig 编 `x86_64-windows-gnu` 的
  `-DOPTION_TOOLS_ONLY=ON` 构建（只出 strgen），再把 `-DHOST_BINARY_DIR=` 指给主构建。
  这一步漏了的话，构建会拿 aarch64 的 strgen 在本机执行，Windows 上根本跑不起来，
  整个编译当场中断。
- **`rev.cpp` 故意嵌 `__DATE__`**，zig 的 clang 默认 `-Werror=date-time`，直接编译失败。
  加 `-Wno-error=date-time`。注意 `CMAKE_CXX_FLAGS_INIT` 只在第一次配置时生效，
  改完得删掉构建目录重来，否则看起来像"改了没反应"。
- **zig 的 libc++ 编 fmt 缺 `<cstdlib>`**：`malloc`/`free` 未声明。全局 `-include cstdlib`，
  和 OpenAL 那个坑同源。
- **CMake 预编译头 + lld**：`cmake_pch.hxx.o: unknown file type`。
  `-DCMAKE_DISABLE_PRECOMPILE_HEADERS=ON` 关掉。代价是全量编译慢一点，不影响产物。
- **Windows 验证构建缺 `windres`**（zig 没有 RC 编译器，CMake 找 `windres` 失败）。
  `.rc` 里只有图标和版本信息，写了个 12 行的 `rcstub.cmd` 把空 COFF 对象拷到输出路径上。
  这个 stub 必须 CRLF + 纯 ASCII——用 bash heredoc 写出来的 LF + 中文字符串会让 cmd
  解析崩（报 `文件名、目录名或卷标语法不正确`），最后是用 Python 生成才稳定。
- **二进制里漏了构建机路径**：`__FILE__` 会展开成 `F:/_scratch/ottd_src/...`（201 处），
  而且默认的 `GLOBAL_DATA_DIR` 是 Windows 路径。加
  `-ffile-prefix-map=<源码>=. -ffile-prefix-map=<构建根>=.` 和
  `-DGLOBAL_DIR=/usr/share/games/openttd`，自检里查 `_scratch`/`F:/` 字样。
- **`-DSDL2_DIR=` 的绝对路径会进 RPATH**，加 `-DCMAKE_SKIP_RPATH=ON`，和 cnc 那次一样。
- **`lang/` 必须随包**，见上文；搜索路径里既有可执行文件所在目录（`SP_BINARY_DIR`），
  也有当前工作目录（`SP_WORKING_DIR`，受 `_do_scan_working_directory` 控制，见
  `src/fileio.cpp`），所以启动脚本先 `cd "$GAMESUB"` 再 `"./$GAMEBIN"` 最稳。

## 验证到哪一步

- Windows 同源构建（同一 commit、同一套编译选项）实跑通过：主菜单自动识别中文界面，
  新游戏 → 地图生成器（256x256、平整、1950 年）→ 生成成功，进游戏后城镇 `Fort Beningley`
  人口 849、日期 `1950年1月5日`、资金 `£100,000`，OpenGFX 的铁路/建筑/地形都正常渲染。
  `screenshot.png` 就是这次实跑的截图。
- aarch64 二进制做了静态核对（架构、依赖、glibc 上限、RPATH、构建路径、许可），
  **没有真机跑过**。这和 Quake / Diablo / C&C 是同一套口径：能静态证明的静态证明，
  实跑用同源 Windows 构建代替，真机表现等上机再补。
- 手柄映射没有在真机上试过力度，`deadzone_scale = 6` 是按 640x480 的工具条图标密度估的，
  上机后可能要调。

## 许可

引擎 GPL v2.0（源码 = 钉住的 commit，无补丁）；OpenGFX / OpenMSX GPL v2.0；
OpenSFX CC BY-SA 3.0；SDL2 zlib（运行时由 CFW 提供，不随包分发）；gptokeyb GPL v3
（由 PortMaster 提供）；C++ 标准库是 zig 静态链入的 libc++。
原版 TTD 的商业素材（`sample.cat`、`trg*.grf`、`gm/*.gm`）不在包内，本包也不需要它们。

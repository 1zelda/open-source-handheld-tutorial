# 命令与征服（Vanilla Conquer）→ R36S / XF45V 端口

1995 年的《命令与征服：泰伯利亚黎明》和 1996 年的《红色警戒》初代，用 EA 公开源码重编成的
**Vanilla Conquer** 引擎跑在 aarch64 掌机上。一个端口包带两个游戏，共用一个引擎。

- 上游：<https://github.com/TheAssemblyArmada/Vanilla-Conquer>
- 钉住版本：`ce83b59edd99cccac6cebaae054ca04962c744b7`（`vanilla` 分支，2026-10 快照）
- 引擎许可：GPL v3 + EA 附加条款（`licenses/Vanilla-Conquer-GPL-3.0.txt`）
- **游戏数据不在包内**：商业 MIX 由玩家自备，见下

## 包里有什么

```
Cnc.zip
├── Tiberian Dawn.sh          启动 C&C（读 cnc/td/）
├── Red Alert.sh              启动红警（读 cnc/ra/）
└── cnc/
    ├── port.json  gameinfo.xml  LICENSES.txt  screenshot.png
    ├── licenses/             引擎与库的许可原文
    ├── libs.aarch64/         libopenal.so.1（OpenAL Soft 1.24.2）
    ├── td/  vanillatd.aarch64 + 玩家自备数据
    └── ra/  vanillara.aarch64 + 玩家自备数据
```

两个游戏的数据放在**两个独立目录**里：泰伯利亚黎明和红警的大量 MIX 同名（`CONQUER.MIX`
和 `REDALERT.MIX` 之外还有 `GENERAL.MIX`、`SOUNDS.MIX`…），混在一个目录里会互相覆盖，
表现出来就是诡异的图像/音效错乱。启动脚本各跑各的子目录，天然隔开。

SDL2 用 CFW 自带的（PortMaster 都有）；**OpenAL 掌机上基本都没有，所以随包带**，
`LD_LIBRARY_PATH` 里把 `libs.aarch64` 排在最前，想换版本直接覆盖那个 `.so` 就行。

## 数据怎么放

泰伯利亚黎明（放进 `ports/cnc/cnc/td/`）：

| 来源 | 需要的文件 |
| --- | --- |
| 正版 C&C Gold（GOG / Steam《C&C 终极合集》） | 安装目录里的 `*.MIX` 全部 |
| 2007 年 EA 免费放出的 GDI95 版 | `CONQUER.MIX GENERAL.MIX MOVIES.MIX SCORES.MIX SOUNDS.MIX AUD.MIX TEMPERAT.MIX WINTER.MIX DESERT.MIX` |

红色警戒 1（放进 `ports/cnc/cnc/ra/`）：正版光盘/GOG 版或 2008 年 EA 免费放出的红警，
`REDALERT.MIX`、`MAIN.MIX`、`MIXES/*.MIX` 等全部拷进去。红警的 `*.MIX` 有的在子目录
`MIXES\`，把里面的文件**平铺**到 `ra/` 下即可。

本仓库不附带、也不提供这些数据的下载。

## 构建

```bash
bash build.sh            # 交叉编译 + 组装 + 打包 + 自检
SKIP_ZIP=1 bash build.sh  # 只编不打包
```

依赖：zig 0.17.0、cmake 3.31、ninja、git、curl、python（只用标准库）。构建根默认
`/f/_scratch/cnc_build`，可用 `BUILD_ROOT=` 改，但**必须是纯 ASCII 路径**。

流程是四段：取 SDL2 的 arm64 头文件包 → 编 OpenAL Soft → 编 Vanilla Conquer（打完补丁）
→ 确定性打包并跑 `check_port.py`。

自检 61 条（`python check_port.py package/Cnc.zip`），覆盖：两个启动脚本与两个二进制、
AArch64/依赖白名单/glibc 上限、二进制里不许留构建期 RPATH、包内不许出现任何游戏数据文件、
许可原文、启动脚本该有的 `LD_LIBRARY_PATH`/手柄映射/缺数据退出/不抢手柄。

成品：`Cnc.zip` 2,121,783 B，
sha256 `c767216bcc1601fd7c762d2802c6ecdbda91eab49f377347235f66a6dbf9732f`；
`vanillatd.aarch64` 1,301,192 B、`vanillara.aarch64` 1,681,696 B、
`libopenal.so.1` 1,543,184 B。

## 打了哪些补丁（`fixes.patch`，5 个文件 39 行）

上游在 640x400 高分模式下有一套「交错插值」：320x200 的画面放大时，隔行像素按
`PaletteInterpolationTable[256][256]` 查表混色。这个表是运行时按当前调色板现算的，
出问题的时候整屏会变成**黑白棋盘格**（原始像素保留、所有插值像素变黑）。三处：

1. **`common/interpal.cpp` — 读短文件就当读到了。**
   `Read_Interpolation_Palette()` 不看 `Read()` 的返回值，读 64 KB 表的时候如果只读进来
   768 字节（某些版本同名的 `.PAL` 就是一份普通调色板），剩余部分全零，但它还是把
   `InterpolationPaletteChanged` 清成 false，于是引擎相信「表已经有了」再也不重建。
   改成只有完整读到 65536 字节才算数。

2. **`tiberiandawn/conquer.cpp` — 放完电影把表清空了不补。**
   `Play_Movie()` 进片头前把插值表 memset 成 0，指望 `VQA_SetPalette()` 按电影调色板
   重新填。但 `VQA_SetPalette()` 只有在**同时加载了 `.VQP` 调色板缓存**（`PalettesRead`）
   时才填表——免费数据/正版数据里都没有那批 `.VQP`，结果电影和之后的主菜单全黑。
   改成只有真的会重填时才清零。

3. **`common/vqapalette.cpp` — 没有 `.VQP` 就不填表。**
   配合上一条，在没有 `.VQP` 缓存时用电影自己的调色板现算一张表，播完电影不残留黑屏。

附带一处：**`tiberiandawn/display.cpp` 的 `RemapTables` 越界写**。淡出/淡入时算出来的
色带下标可能超过 256，往上写 16 字节会踩到相邻表。加了边界判断，越界就不搬。

补丁以 `git apply` 打进钉住的 commit，改后的完整源码 = 上述 commit + 这个 patch，
GPL v3 要求的东西都在包里。

## 踩过的坑

- **OpenAL Soft 只能钉 1.24.2**。master 已经切到 C++20 modules，zig 的 libc++ 编不过；
  1.24.2 之后的开发版也陆续加了新语法。钉 tag + 校验 commit 哈希。
- **zig + libc++ 要 `-include cstdlib`**。OpenAL 的 `al::vector` 用到 `operator new`，
  不提前把 `<cstdlib>` 拉进来会报 "no matching operator new"。
- **`CMAKE_CXX_FLAGS` 会覆盖工具链里的 `-target`**。给 OpenAL 单独传
  `-DCMAKE_CXX_FLAGS="-target aarch64-linux-gnu -include cstdlib"`，别只写 `-include`。
- **SDL2 的 dev 包是 multiarch 布局**（`/usr/include/aarch64-linux-gnu/SDL2`），
  而且 `SDL_config.h` 是个只 `#include "_real_SDL_config.h"` 的中转，交叉场景下要展平。
- **手柄是引擎自带的**，别套 gptokeyb。`common/wwkeyboard_sdl2.cpp` 左摇杆移光标、
  右摇杆边缘滚屏、A/B 左右键、X=G、Y=F、Back=ESC、Start=Enter、RT 加速，
  默认关，由 `[Mouse] ControllerEnabled=yes` 打开（INI 从二进制旁边读 → 便携模式）。
- **画面比例**：引擎渲染 640x400，`Video.Boxing=true` 时按 `BoxingAspectRatio`（默认
  16:10）留上下黑边。掌机是 640x480，启动脚本写 `Boxing=false` 让它铺满，
  跟原版 CRT 上的 4:3 拉伸一致。
- **cmake 会把构建根写进 RPATH**。SDL2/OpenAL 是用 `-DSDL2_LIBRARY=` 指的绝对路径，
  不加 `-DCMAKE_SKIP_RPATH=ON` 的话二进制里会留下
  `F:/_scratch/.../sdl2/lib:.../oal/lib` 这么一串构建机路径（差 96 字节），
  在掌机上毫无意义还可能干扰库搜索。两个工程都加了，自检里也逐条查。

## 验证到哪一步

- Windows 同源构建（同一 commit + 同一补丁）实跑：片头电影、标题画面、淡入淡出都正常，
  全彩、无棋盘格。修之前是整屏黑白格子，日志里插值表首字节全 0；修之后非 0 且画面正常。
- aarch64 二进制做了静态核对（架构、依赖、glibc 上限、许可），**没有真机跑过**。
  这跟前面几个端口（Quake 系列、Diablo）是同一套口径：能静态证明的静态证明，
  实跑用同源的 Windows 构建代替，真机表现等上机再补。
- 免费数据（2007 GDI95）缺 `choose.wsa` 等几个过场文件，`PlayIntro` 那步会卡住。
  这是数据缺口不是端口问题：正版 C&C Gold 数据齐全则不受影响。
- 打包这天的实际路径要说清楚：最后一次全量构建时 GitHub 直连不通，用了本机已有的
  两个仓库镜像（`OAL_MIRROR=` / `VC_MIRROR=`，`git clone --shared` 后 checkout 到同一个
  钉住的 commit）；默认的 `git fetch` 网上下载路径当天早些时候跑通过。两条路取到的
  源码 commit 相同，补丁和配置完全一样。

## 许可

引擎 GPL v3 + EA 附加条款；OpenAL Soft LGPL-2.0（动态库随包，可替换）；
SDL2 zlib（运行时由 CFW 提供，不随包分发）；C++ 标准库是 zig 静态链入的 libc++。
游戏数据版权归 EA，本包不含。

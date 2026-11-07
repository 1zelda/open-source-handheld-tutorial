# 各平台 BIOS 需求总表

> 这份表回答一个问题:**这台模拟器到底要不要 BIOS,要的话要哪一个、放哪、叫什么名字。**
> "必须"= 没它开不了机或大量游戏黑屏;"可选"= 没有也能玩,但部分功能/游戏会出问题;"无需"= 完全不用。

## 速查表

| 平台 | 是否必须 | 需要的文件 | 放哪里 | 不装会怎样 |
|---|---|---|---|---|
| GB / GBC | 无需 | — | — | — |
| GBA | 可选 | `bios_gba.bin`(GBA 开机固件,约 16K) | 模拟器目录/`scummvm` 同级 | 部分游戏(如《黄金太阳》续作、一些带 BIOS 调用的)启动异常、缺少开机动画;Mednafen/No$gba 要求严格 |
| NES / FC | 无需 | — | — | 只玩非mapper hack 时完全不需要 |
| SNES / SFC | 无需(极少例外) | 个别 BS-X / Satellaview 游戏要 `bs-x.bin` | 同上 | 只影响卫星广播类冷门游戏 |
| MD / SMD (Genesis) | 无需 | — | — | — |
| GG / SMS | 无需 | — | — | — |
| **PS1** | **强烈建议** | `PSX/PSX.EXE` + `scph5500/5501/5502.bin`(美/日/欧任选其一或全放) | DuckStation:`PSX/` 目录;RetroArch PCSX-ReARMed 可容忍无 BIOS | 无 BIOS:很多游戏卡在三点Logo或黑屏、区域判断错乱、部分游戏(如《合金装备》过场)直接崩 |
| **PS2** | **必须** | `PS2/SCPH*.bin`(如 `SCPH10000.R3303.bin` 等,按机型) | PCSX2 的 `bios/` 目录 | 没有 BIOS 无法启动任何游戏 |
| **PSP** | 可选(强烈建议) | `PSP/flash0/` 整个目录(`font0.dat`、`imagemod_*.bin`、`lh5-4.stg` 等) | PPSSPP 的 `flash0/` | 无官方固件时 PPSSPP 用 ProFX 替代,多数游戏能跑,但字体/部分 UI 错乱、少数游戏黑屏 |
| NDS | 必须(部分前端可替代) | `nds_biios.bin`(7Fh 类型,常见为 **76KB** 正式版) + `dsi_biios.bin`(256KB,仅 DSi 模式需要) | DeSmuME/melonds 设置里指定路径 | 无 BIOS:melonds 系列很多游戏无法引导;DeSmuME 有 HLE 替代但兼容性和精度明显下降 |
| 3DS | 必须 | `cia` 方式安装的固件 + `sysmodel` 相关文件;或从 SD 卡 dump 的 `27 个 fatless/encrypted` 系统文件 | Citra 的 `sysdata/` | 无固件无法进任何游戏(系统菜单也起不来) |
| **世嘉土星** | 建议 | `segast/saturn_bios.bin`(北美/日/欧 3 版,约 512K) | Mednafen/Yabause 目录 | 无 BIOS 基本不能启动 |
| **Dreamcast** | 建议 | `dc/dc_boot.bin`(按区域 HKT-xxxx)+ `dc_font.bmp`/`128_00_00.bin` 等 OS 件 | Flycast / Redream 的 `data/dc/` | 无 boot 文件不能引导;缺字体文件部分游戏文字丢失 |
| N64 | 无需 | — | — | 高延迟/部分游戏需要 `HLE` 或真实 CIC,但不是传统 BIOS |
| Wii / GameCube | 无需(推荐装) | Dolphin 会提示安装 `IOS`/`common key`;GC 不需 | Dolphin 自动导入 | 不装不影响游戏,但影响读碟与部分功能 |
| PS3 | 必须 | `PS3UPDAT.PUP` 固件(官方免费,从 PlayStation 官网下载) | RPCS3 里 File → Install Firmware | 不装完全无法运行 |
| WiiU | 必须 | 从本机 dump 的 `title` 系统文件 | Cemu 的 `title/` | 不装无法运行系统级功能 |
| Switch | 必须 | 从自有 Switch dump 的 `prod.keys` + `title keys` + 固件 `package3` | yuzu 系延续项目的 `keys/` | 不装无法解密运行任何游戏 |
| Atari/Intellivision/Coleco 等 | 视核心 | 部分核心要求各自 BIOS | RetroArch 启动时会给缺文件提示 | — |

## 怎么知道自己缺什么

1. **RetroArch**:启动游戏时若弹出 "Missing BIOS / firmware" 提示,它会明确写出**期望的文件名和 MD5**。按它说的名字放就是最快的路径。
2. **DuckStation / PPSSPP / RPCS3 / melonds**:各自 Settings → BIOS / Firmware 页面直接列出当前已识别与缺失文件及其校验和。
3. 用 `_工具脚本` 里的校验脚本把你手头的 BIOS 与官方期望 MD5 对比(见 `校验方法.md`),因为**文件名对但内容错**是最常见的坑。

## 关于文件名的大小写和扩展名

掌机固件对大小写敏感(Linux 系)。常见要求:
- DuckStation 要求目录名 `PSX`、文件名 `PSX.EXE`(全大写)、`scph5500.bin` 等(**小写**)。
- PPSSPP 要求 `flash0` 目录及内部文件名严格一致。
- RetroArch 各核心要求的文件名在其文档里写死,别自行改名。

## 合法获取途径(唯一推荐路径)

BIOS 是你机器里的固件代码,提取自己的机器是合规做法:
- PS1/PS2/PSP:用自有主机 + 记忆卡导出法或 homebrew(如 FreeBoot 类工具链)提取;也可用你已购买的主机 UMD/官方升级包(PS3 固件是索尼**官方免费下载**)。
- NDS/3DS:用自有掌机 + homebrew launcher dump 到 SD 卡。
- Switch:`lockpick`/`hacmount` 之类工具从自有机器导出 keys(需自有机器)。
- 各平台 ROM:从你**自己购买的卡带/光盘**用 GCNMini、DSdumper、Switch dump cart 等工具导出。

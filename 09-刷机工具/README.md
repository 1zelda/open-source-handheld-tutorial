# 刷机工具台账（2026-11-05 建立）

> 这一目录里的每个文件都是**本轮亲自从官方站点 / GitHub Release / GitHub Actions 产物直链下载并逐字节校验**的。
> 校验值来源分三种，表里写清是哪一种：
> - **对上上游 digest** = GitHub Release 资产元数据里官方公布的 sha256，本机 `certutil` 重算后一致；
> - **仅本机算得** = 上游不公布校验值（7-Zip 安装包、SD 协会压缩包、Actions 产物），只能记录本机哈希，作为"以后有没有被换过"的对照基线；
> - （镜像台账那边还有第三种：作者随包发布的 `.sha256`，见 `../02-模拟器库/已clone仓库/系统镜像/README.md` §〇）
>
> 重算命令（PowerShell 或 Git Bash 都行）：
> ```
> certutil -hashfile rufus-4.15p.exe SHA256
> ```

## 一、总表

| 文件 | 版本 | 字节数 | sha256 | 官方来源 | 什么时候用 |
|---|---|---|---|---|---|
| `7z2605-x64.exe` | 7-Zip 26.05 | 1,663,506 | `fd99e86f57d8f429ef5ed045bf98315af962e2309b0f1ba87a147a44c71647d0`（仅本机算得） | https://7-zip.org/a/7z2605-x64.exe | **第一步必用**。固件镜像是 `.img.xz` / `.7z.00x` 分卷，右键"7-Zip → 解压到当前文件夹"。别用 WinRAR（会把分卷解坏） |
| `rufus-4.15p.exe` | Rufus 4.15（`p`=便携版，免安装） | 1,989,992 | `84c8a437f8af89257524478489e5c85f1edf25f761d299e2bcde46ac0afbe106`（对上上游 digest） | https://github.com/pbatard/rufus/releases/download/v4.15/rufus-4.15p.exe （从 https://rufus.ie/en/ 取到的直链） | 写卡。选镜像后点"开始"→ 弹提示时选**以 DD 模式写入**。dArkOSen 官方 README 点名支持的工具 |
| `usbit.zip` | USB Image Tool 1.91 | 848,041 | `c7cc951a3ddb832f78232fe8619981deca1c379d8a4286c21d9cf553c626e8a5`（仅官方站点，无 digest 公布） | https://www.alexpage.de/download/usbit/usbit.zip （页面 https://www.alexpage.de/usb-image-tool/download/ ） | 写卡**备选**。dArkOSRE(southoz) 在上游文档里首选它。解压即用，需要 .NET Framework 4.7 |
| `imager-v2.0.12.exe` | Raspberry Pi Imager 2.0.12 | 22,315,568 | `98bff90afe23339d0768915f6f68d35ac254740ec1eac2082ebeaa9ba41bc8e3`（对上上游 digest） | https://github.com/raspberrypi/rpi-imager/releases/download/v2.0.12/imager-v2.0.12.exe | 写卡**备选**，优点是能吃 `.img.xz` 不用先解压（但先解压再校验哈希更稳） |
| `balenaEtcher-win32-x64-2.1.9.zip` | balenaEtcher 2.1.9（便携 zip） | 284,199,765 | `b87cf10ea10efe03346a057d4a549cc0e57874618fd4ebc030b4de8d97c4b94b`（对上上游 digest） | https://github.com/balena-io/etcher/releases/download/v2.1.9/balenaEtcher-win32-x64-2.1.9.zip | ⚠️ **放着别优先用**。ArkOS/dArkOS 系上游文档明确写"大量用户用 Etcher 写坏"（`../01-教程库/机型固件/R36S/00-R36S完全指南.md` 第四节）。只有在别的工具都失败时才试它 |
| `SDCardFormatterv5_WinEN_504.zip` | SD Memory Card Formatter 5.0.4 | 6,506,579 | `aaabf4f98077236a4ee2dd94224cf491ed23f1e059b3d506347ab3d40eb564ab`（仅本机算得） | https://www.sdcard.org/downloads/formatter/eula_windows/SDCardFormatterv5_WinEN_504.zip | **卡2（资料卡）格式化用它**，以及"卡反复失败先归零重来"。Windows 自带格式化对 SD 卡的分配单元/对齐不如它规范 |
| `rkdevtool_0.16.0_x64-setup.exe` | RKDevTool（开源重制版）0.16.0 | 4,298,682 | `71867a67ef02006248f16ee20da0214512281d37284dd6f6eefe1c75a6030b82`（对上上游 digest） | https://github.com/hiifong/rkdevtool/releases/download/v0.16.0/rkdevtool_0.16.0_x64-setup.exe | **救砖/线刷 eMMC 备用**。状态栏会显示 Maskrom / Loader，能下 Loader、按分区写、读芯片与 Flash 信息 |
| `Flash-Guide.tool.rar` | 稀范官方"中文教程&刷机工具"包 20260424 | 13,878,956 | `99e6913d2288d993af90f257d877ebd300c85641482e83cb28abe1a738c5b6db`（对上上游 digest） | https://github.com/handheld520/XiFan-v1.0-FullPack/releases/download/20260424/Flash-Guide.tool.rar | ★**稀范机型（XF45V/R36MAX2/RF45H 等）刷 eMMC 就用它**。里面是 FactoryTool_v1.81 + RK-USB-DriverAssitant_v5.1.1 + `EMMC升级刷机教程.doc` |
| `Flashing.software.rar` | 同上的英文版（Upgrade tutorial.doc） | 14,036,840 | `930ed905c0de8a16c3a51f9246158bb06ae273471428b8ae6802131b9a153081`（对上上游 digest） | https://github.com/handheld520/XiFan-v1.0-FullPack/releases/download/20260424/Flashing.software.rar | 同上，文档是英文版 |
| `dtbselect/dtbselect-rk3326-windows.zip` | AURKNIX CI 产物 20261021（artifact 12317831848 同族） | 8,531,575 | `22d870a430911493cbbffe11eb2b87addc13d44b0a1cb603daf538453ae78349`（Actions 产物无公开 digest，仅本机算得） | `gh api repos/AveyondFly/distribution_rocknix/actions/artifacts` → `/zip` | **ROCKNIX/AURKNIX 系（R36S / R36MAX2）选设备树用**。内含 `dtbselect-rk3326-windows-x64.zip` → `DtbselectWin64.exe` 8,748,308 B `37ee77299e638d93dc31c486ce84e2c5c0cf6e7c5ec9af15f412be870b4b3c38` |
| `dtbselect/dtbselect-rk356x-windows.zip` | 同仓库 CI 产物 20261021（artifact `dtbselect-rk356x-windows` 12310908389） | 8,520,661 | `371dad0c19f14ecfb66fa0c3736ed59bf2b724998af802a467b5d0ce61ac52fa`（仅本机算得） | 同上 | **NGP45HT（RK3562）选设备树用**。内层 zip 8,518,019 B `a026cbdca83019b725fcbf15d6628c4c8aee12ad54ae59a3135eae0c09c7c636` → `DtbselectWin64.exe` 8,737,340 B `506047965de618538631f251987cc981aeb2cf6ffb10a27efbf37b864e80ca71` |

## 二、稀范官方工具包拆开是什么（已实测解包）

`.rar` 用 Windows 自带的 `C:\Windows\System32\tar.exe`（libarchive）就能列/解，中文文件名是 GBK 编码，解出来会显示乱码但内容完好。实测结构：

```
Flash-Guide.tool.rar
└── 中文教程&刷机工具/
    ├── Design software tools(1).zip      ← 12,319,164 B，198 个条目
    │   └── Design software tools/
    │       ├── FactoryTool_v1.81/         ← 瑞芯微量产/烧录工具（含 Chinese.ini / English.ini 语言包）
    │       └── RK-USB-DriverAssitant_v5.1.1/  ← 瑞芯微 USB 驱动（Maskrom/Loader 识别必需）
    └── EMMC升级刷机教程.doc               ← 1,673,728 B，官方图文步骤
```

`EMMC升级刷机教程.doc` 正文（antiword 抽取，原话照抄）：

> 先安装驱动 …… 然后打开 FactonryTool（原文如此，即 FactoryTool）……
> 机器链接 OTG 插口，USB 连接电脑，
> **关机状态下**：同时按住 10 秒开机键和音量+，进入刷机状态，刷机成功拔出，按一下重启键，然后按开机键开机。
> **开机状态下**：先按一下重启键，然后按住音量+，十秒进入刷机状态，刷机成功拔出，按一下重启键，然后按开机键开机。

英文版 `Upgrade tutorial.doc` 与之一致（"The machine is linked to the OTG port and USB to the computer…"）。

**这两句话是稀范机型进 MASKROM 的唯一官方口径**，比任何"拆机短接"都安全：`音量+ 与 开机键同时按住 10 秒`（关机态），或 `按一下重启键 → 按住音量+ 10 秒`（开机态）。

## 二·五、`dtbselect/` 目录：ROCKNIX/AURKNIX 的"选机型"工具

实测目录结构（外层是 Actions 产物 zip，里面还套了一层 zip）：

```
dtbselect/
├── dtbselect-rk3326-windows.zip      8,531,575 B
│   └── dtbselect-rk3326-windows-x64.zip  8,528,838 B  74589ee6…2012
│       ├── DtbselectWin64.exe        8,748,308 B  37ee77299e…3c38
│       └── config/extlinux.conf            253 B   ← 模板，会被写进卡的 extlinux/
└── dtbselect-rk356x-windows.zip      8,520,661 B
    └── dtbselect-rk356x-windows-x64.zip  8,518,019 B  a026cbdc…c636
        └── DtbselectWin64.exe        8,737,340 B  506047965d…ca71
```

**同名 `DtbselectWin64.exe` 一共有三个版本，别混着用**：

| 版本 | 字节数 | 来自 | 用在哪 |
|---|---|---|---|
| RK3326 CI 版 | 8,748,308 | 本目录 `dtbselect-rk3326-windows.zip` | 刷 RK3326 档的 AURKNIX/ROCKNIX 卡 |
| RK356X CI 版 | 8,737,340 | 本目录 `dtbselect-rk356x-windows.zip` | NGP45HT（RK3562） |
| **卡里自带的那份** | **8,415,037** | 直接躺在刷好的 BOOT 根目录 | ★**优先用这个**——它和镜像同一次构建，机型表必然匹配 |

用法：卡写完后在 Windows 下打开 BOOT 分区 → 双击 `DtbselectWin64.exe` → 选机型（NGP45HT 在表里的机型名是 `Xifan NGP45H`，没有尾字母 T）→ 它会改 `extlinux/extlinux.conf` 里的 `FDT`/`FDTDIR`/`FDTOVERLAYS` 与 `uboot.hwid_adc`。
细节见 `../01-教程库/机型固件/00-刷机通用流程与工具.md` §4.3 与 `../01-教程库/机型固件/NGP45HT/00-NGP45HT完全指南.md` §四。

⚠️ 这两个外层 zip **`7zr` 打不开**（报 `Cannot open the file as archive`，是 Actions 用 zip64 流式写 EOCD 导致的），**不代表包坏了**。用 Python 解：
```bash
py -3 -c "import zipfile; zipfile.ZipFile('dtbselect-rk356x-windows.zip').extractall('.')"
```

## 三、按"你要干什么"选工具

| 场景 | 用什么 | 备注 |
|---|---|---|
| 把固件写进 TF 卡（绝大多数开源掌机的正规刷法） | 7-Zip 解压 → Rufus（DD 模式）/ USB Image Tool | 写之前先 `certutil` 校一次镜像哈希 |
| 卡反复黑屏/校验失败，怀疑卡本身 | SD Card Formatter 5.0.4 重格一次再重写 | 别用"快速格式化"了事 |
| 刷进机器内置 eMMC（稀范 R36MAX2/XF45V 这类有 eMMC 的机器） | 稀范官方 `Flash-Guide.tool.rar` 里的 FactoryTool v1.81 + DriverAssitant v5.1.1 | 进刷机态的按键组合见上文官方正文 |
| 官方包丢了/想自己看分区、救砖 | RKDevTool 开源重制版 0.16.0 | 状态栏要先看到 `Found One MASKROM Device` 才算连上 |
| ROCKNIX/AURKNIX 刷完黑屏，要**改机型（设备树）** | 优先用**卡里自带的** `DtbselectWin64.exe`；卡里没有才用本目录 `dtbselect/` 对应芯片那一档 | ArkOS4Clone 系用的是另一个工具 `dtb_selector_win32.exe`（也在卡里），**两者不通用** |
| 只是想装游戏/移植包，不刷系统 | **一个都不用**，直接往卡 2 的 `roms/`、`ports/` 放文件 | 见 `../04-游戏资源库/` |

## 四、安全声明（重要，别跳过）

1. 上面 11 个条目**只从官方域名与 GitHub Release/Actions 取**：`7-zip.org`、`rufus.ie`→`github.com/pbatard/rufus`、`alexpage.de`、`github.com/raspberrypi`、`github.com/balena-io`、`sdcard.org`、`github.com/hiifong`、`github.com/handheld520`、`github.com/AveyondFly`（AURKNIX CI 产物）。
   **绝对不要**从"XX下载站/高速专线/绿色版"下同名文件——这类站会二次打包。
1b. `dtbselect/` 那两个 zip 是 **GitHub Actions 产物**，平台不给公开 digest，所以只能记本机哈希；它们的可信度取决于 `AveyondFly/distribution_rocknix` 这个仓库本身。相比之下 Release 资产有 digest 可对，证据更强。
2. 装之前先跑一次 Windows Defender 全文件扫描（右键 → 使用病毒防护程序扫描）。哈希对得上不代表"没毒"，只代表"和官方发布的是同一份"。
3. FactoryTool / DriverAssitant 是瑞芯微闭源二进制，随稀范官方包分发；我无法核对它的签名链，**它的可信度等于稀范这个上游厂商**。只在你确实要刷自己机器的 eMMC 时用它。
4. 驱动类安装（DriverAssitant）会往系统装内核驱动，**建议装完记着它存在**；不再需要线刷时可以在"设备和管理器/程序和功能"里卸掉。
5. 这些工具**只在 Windows 10/11 64 位**实测可行（本机 10.0.19045）。32 位系统请改用 `rufus-4.15_x86.exe`（上游有发，digest `20e1345715aff4aebf016839f721390882201a2b5d00655424c4ca38cb919576`，本目录未下载）。

## 五、复现下载

```bash
bash F:/开源掌机教程/_scratch/dl_tools.sh     # 本目录前 7 个
bash F:/开源掌机教程/_scratch/dl_xifan.sh     # 稀范官方两个 rar（+ 原厂镜像）
bash F:/开源掌机教程/_scratch/dl_dtbselect.sh # dtbselect 两个 CI 产物（按 artifact id 取）
```
脚本里每条 URL/artifact 与期望 sha256（dtbselect 还要比对字节数）写死，**哈希不符就删掉重下**，不会静默放过。
本轮 2026-11-05 实跑 `dl_dtbselect.sh` 输出两行 `SKIP`（文件在位且哈希一致），不是"理论上能跑"。
上游另有 `dtbselect-rk3326s-windows` / `dtbselect-rk3566-windows` / `dtbselect-rk356x-rk3566-windows` 三个变体**没下**——它们是给别的硬件档的，该选哪个由你刷的镜像文件名与设备页决定，别按名字猜。

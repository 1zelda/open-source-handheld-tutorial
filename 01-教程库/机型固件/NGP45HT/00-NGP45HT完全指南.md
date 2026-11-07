# XiFan NGP45HT 完全指南(2026-11-05)

> 这是稀范 2026 年 10 月的新机器,**芯片不是 RK3326,而是 RK3562**。
> 所以本库里 R36S / XF45V / R36MAX2 那三篇的 dtb 表、主题档、PortMaster 设备名**一概不能照抄**。
> 通用流程(校验/写卡/线刷/双卡)看 [`../00-刷机通用流程与工具.md`](../00-刷机通用流程与工具.md);本篇只讲 NGP45HT 特有的部分。

---

## 一、结论卡

| 问题 | 答案 |
|---|---|
| 机型 | **深圳市稀范科技 XiFan NGP45HT**,4.5 寸**横版**;固件里的正式机型名是 **`Xifan NGP45H`**(dtb 名 `rk3562-ngp45h.dtb`,**没有尾字母 T**) |
| 芯片 | **Rockchip RK3562**:四核 Cortex-A53,最高 2.0GHz,Mali-G52 GPU,1 TOPS NPU(官方规格页:https://www.rock-chips.com/a/en/products/RK35_Series/2024/0626/1983.html) |
| 屏幕 | **1024×768 横屏**,MIPI-DSI,像素时钟 **52 MHz**,PHY **480 Mbps/lane**,bpc 8(数值取自机型设备树原文,见第三节) |
| 存储 | **板载 eMMC + 两个 TF 槽**(设备树注释原话:"Both DW-MMC ports are wired as removable SD-card slots on the vendor DT") |
| 网络 | **AIC8800DC USB WiFi**(不是 SDIO 模块,原因写在设备树注释里:SDIO 的控制 GPIO 与摇杆/耳机检测重叠) |
| 视频输出 | **有 HDMI 输出**,走 **RK628**(RGB-in → HDMI-out 桥片,i2c3 地址 0x50),并带 HDMI 音频(`rk628_sound`) |
| 其他 | RK817 PMIC(电池+充电+codec,`hp-volume=<15>`/`spk-volume=<11>`)、四键电阻梯 ADC、**震动马达**(`rumble-ngp45h`)、摇杆 LED(quirks 里有 `analog_sticks_ledcontrol_single`) |
| 该刷什么 | **AURKNIX(distribution_rocknix)的 RK356X-RK3562 镜像**。本轮可取到的最新是 CI 产物 `AURKNIX-RK356X.aarch64-20261021-RK3562.img.gz`;公开 Release 频道里最新是 `nightly-20260918` 的 `...-20260918-RK3562.img.gz` |
| 明确不能用 | ❌ ArkOS4Clone / dArkOS4Clone(本轮把仓库 `boot/dArkOS/consoles` 全量列出共 **95** 个机型目录,**含 `ngp` 的 0 个**;带 "45h" 字样的是 `r45h`/`rf45h`,跟 NGP45H 无关);❌ dArkOSRE-R36、dArkOSen-R36S(纯 RK3326);❌ 主线 ROCKNIX(NGP45H 是**本改版相对主线额外适配**的机型,手册 §3 原话:"以下为本改版相对 **ROCKNIX 主线** **额外适配**的设备清单") |
| 官方包在哪 | 稀范的 GitHub 镜像组织 `handheld520` 下 16 个机型仓**没有 NGP45 系列**(本轮 `gh api users/handheld520/repos` 全量列过)⇒ 官方 EmuELEC/OTA 走厂家网盘/B 站渠道,**不在本库收录范围** |
| 最需要注意的坑 | ① 必须用 **`-RK3562`** 那个后缀的镜像,RK3326/RK3566 包刷不进去;② 写卡后要在启动分区跑 **`DtbselectWin64.exe`** 选 "Xifan NGP45H",不选就黑屏;③ 镜像里自带 `resize_storage_10G`,首次开机会把 storage 缩成 10GiB、其余空间建成 exFAT `GAMES` 分区——想改布局要在开机**之前**动这个文件(见第四节) |

**性能预期(和 R36S 系的关系)**:RK3562 的 A53@2.0GHz + Mali-G52 明显强于 RK3326 的 A35+Mali-G31 MP2,
社区实测口径是"RK3562 能碰到 PS2/GC 的门口"——自媒体把 NGP45HT 和"能跑 PS2"放在一起讲(见第七节引用),
但那类结论要按游戏逐条看;310 元档的实测视频里"战神 2 带不动"也是同一批人说的。**别按"RK3562 = 随便玩 PS2"来规划。**

---

## 二、怎么把"NGP45HT"这个商品名对上固件里的 `NGP45H`

商品名带 T、固件机型名不带 T,这属于常见现象(稀范的命名线:XF/RF/DC/R36/NGP + 尺寸 + V/H/T 后缀)。我用的对应证据:

1. `AveyondFly/distribution_rocknix` 仓库里有 `projects/ROCKNIX/devices/RK356X/linux/dts/rockchip/rk3562-ngp45h.dts`,
   头部注释原话:`Xifan NGP45H — RK3562 gaming handheld with landscape 1024x768 DSI panel`,
   `model = "Xifan NGP45H"; compatible = "xifan,ngp45h", "rockchip,rk3562-evb1-lp4x-v10", "rockchip,rk3562";`
   (本地存档:`_scratch/ngp45h.dts`)
2. 同一仓库有独立 quirks 目录 `projects/ROCKNIX/packages/hardware/quirks/devices/Xifan NGP45H/`
   (内含 `001-device_config`、`002-adc-key`、`011-led_control`、`500-enable-led`、`bin/ledcontrol`、`bin/analog_sticks_ledcontrol_single`、`sleep.d/pre/500-disable-led`)。
3. 我**下载的镜像本体里**能直接搜到这块 dtb 与它的选择项(证据见第三节),不是抄文档表格。
4. 商品侧:B 站有专条视频《NGP45HT稀范科技新机NGP45HT开源掌机》(BV1cfpv6FEjF,2026-10-09),
   什么值得买 2026-10 的实测文《「能跑PS2」?310元稀范新机到货》写"10月10日起,深圳市稀范科技接连放出两台新机:NGP45HT和RF45H"。
   ⇒ **NGP45HT 就是 RK3562 那台 4.5 寸横版机**;`RF45H` 是另一台(RK3326/1024×768,本库 `panel_specs.tsv` 有 `rf45h` 行)。

⚠️ **我不能替你确认的**:NGP45HT 与早期可能的 "NGP45H" 批次在**面板/PMIC 版本**上是否完全一致。
设备树只有一份,选 "Xifan NGP45H" 是当前唯一有维护的选项;若刷后进系统一切正常(有画面、四键、震动、WiFi),就不必纠结尾字母。

---

## 三、镜像里到底有没有 NGP45H?——我直接查了下载下来的字节

用 `nightly-20260918` 的 `AURKNIX-RK356X.aarch64-20260918-RK3562.img.gz`(1,850,009,484 B,sha256 对上 GitHub asset digest `bd744ad6…fac85`)解流,读它的启动分区(FAT32):

```
分区表: p1 type=0xc FAT32 起始 LBA 32768 / 2.00 GB     p2 type=0x83 / 0.03 GB
根目录: kernel 39,186,944 B   system 2,005,729,280 B   kernel.md5 48 B   system.md5 48 B
        DtbselectWin64.exe 8,415,037 B   dtbselect 259 B   dtb_selector.py 7,040 B
        device_trees/  overlays/  extlinux/  aurknix/  resize_storage_10G 0 B  ms_unsupported 0 B
```

在镜像前 400 MB 里搜字符串 `ngp45h` 命中 40 处,其中两处是关键:

1. `dtb_selector.py` 里那份 `ALL_DEVICES` 列表(**这就是你在 Windows 上会看到的选项,共 8 条,RK3562 全部支持机型**):
```python
ALL_DEVICES: List[Tuple[str, str]] = [
    ("AISLPC RG52 Mini", "device_trees/rk3562-rg52mini.dtb"),
    ("AISLPC RG52 Mini v1 (RK915 WiFi)", "device_trees/rk3562-rg52mini-v1.dtb"),
    ("AISLPC RG43H Pro", "device_trees/rk3562-rg43h.dtb"),
    ("AISLPC RG43H Pro v1 (RK915 WiFi)", "device_trees/rk3562-rg43h-v1.dtb"),
    ("Xifan NGP45H", "device_trees/rk3562-ngp45h.dtb"),
    ("Xifan XF55H", "device_trees/rk3562-xf55h.dtb"),
    ("AISLPC RG43V Pro", "device_trees/rk3562-rg43v.dtb"),
    ("AISLPC RG43V Pro v1 (RK915 WiFi)", "device_trees/rk3562-rg43v-v1.dtb"),
]
```
2. 展平后的 dtb 二进制里能读到 `xifan,ngp45h`、`Xifan NGP45H`、`hp-det-ngp45h`、`rumble-ngp45h`、`rk628-ngp45h` 等节点名
   ⇒ **dtb 真的打进了这个镜像**,不是"表格上有、镜像里没有"。

### 3.1 两份 RK3562 镜像**不同版**,选设备树的界面条目数不一样(本轮实测)

上面那份列表是 **nightly-20260918** 的。我把 **CI 20261021** 也解析了,同一位置多出第 9 条:

| 实测项 | CI `…-20261021-RK3562.img.gz` | nightly `…-20260918-RK3562.img.gz` |
|---|---|---|
| BOOT 里 `DtbselectWin64.exe` | **8,737,340 B**(与本目录 `09-刷机工具/dtbselect/dtbselect-rk356x-windows.zip` 内层那个 exe **同字节数**,即同一次构建产出) | 8,415,037 B |
| `dtb_selector.py` | 7,098 B,`ALL_DEVICES` **9 条** | 7,040 B,`ALL_DEVICES` **8 条** |
| 多出来的机型条目 | `("Pocket AIS", "device_trees/rk3562-pocket-ais.dtb")` | ——(没有这一条) |
| `system` 分区文件大小 | 1,993,261,056 B | 2,005,729,280 B |

⇒ 结论:**别把两份混着描述**。你在 Windows 上看到的选项数量取决于你刷的是哪一份;`NGP45H` 这一条两份都有,所以本指南第四节的做法对两份都成立。
`dtb_selector.py` 里 `patch_fdt_line()` 的作用也读到了原文:它就是把 `extlinux.conf` 里**第一条未注释的 `FDT …` 行**替换成所选 dtb 的路径——所以"工具改的到底是什么"不是猜的,它改的就是 §通用文档 4.3 那行。

关于 `ms_unsupported`(0 字节空文件):我在仓库里搜不到读取它的代码(`gh api search/code` 命中 0),**作用未查明**。
不要把它理解成"我的机器不受支持"——同一份根目录里 `resize_storage_10G` 也是 0 字节空文件,而后者明显是"预置的开箱布局开关"。

---

## 四、NGP45HT 刷机步骤(AURKNIX RK3562)

### 4.1 取哪个包(2026-11-05 的三条频道)

| 频道 | 文件 | 大小 | 校验 | 备注 |
|---|---|---|---|---|
| **CI 产物(最新)** | `AURKNIX-RK356X-20261021.zip` 里的 `AURKNIX-RK356X.aarch64-20261021-RK3562.img.gz` | zip 5,498,679,337 B;内层 img.gz **1,839,363,132 B** | 作者**在包里附了 `.img.gz.sha256`**,已逐字节对上(见台账) | 下载需登录 GitHub(`gh` 带 token);**Actions 产物会过期**,本轮查 API 时 `expired=false`,但别指望它长期在 |
| **Nightly Release** | `nightly-20260918` → `AURKNIX-RK356X.aarch64-20260918-RK3562.img.gz` | 1,850,009,484 B | ✅ 对上 GitHub asset digest `bd744ad6da01a4fff0690e7541696ea48cca5d6a1b40434b09e0ce2fe49fac85` | 长期可下载,直链不用登录。**这就是"公开频道里最新含 NGP45H 的镜像"** |
| 正式发布 | `AveyondFly/distribution_rocknix` releases | — | — | 手册 §3.4 把 RK3562 列为已支持机型;但按镜像文件名挑,**没有 `-RK3562` 后缀就等于没有这块板**(20260622 那批只有一个笼统的 `AURKNIX-RK356X…img.gz`,RK3562/RK3566 三套后缀是 20260918 才分出来的——本轮 release 资产表可复核) |

> 三条频道的**机型与架构必须完全一致**。AURKNIX 手册 §3.4 原话:
> "RK356X 发布包包含 **RK3562**、**RK3566-Generic** 和 **RK3566-Specific** 三套安装镜像,共用同一更新包。它与使用主线 6.x 内核的独立 **RK3566** 发布包不兼容,请按镜像文件名中的后缀选择。"
> §3.2 另一句同样适用于本机:"**RK3326 与 RK3566 镜像相互独立:不要使用 RK3326 包刷 RK3566 机器**。"

### 4.2 写卡

1. `.img.gz` 可以直接喂给 Rufus(DD 模式)/ rpi-imager;要更稳就先 `gunzip` 出 `.img`,**算一次 sha256 再写**。
2. **卡建议 32–128GB 三星/闪迪**。镜像里预置了 `resize_storage_10G`,而 `fs-resize` 的判据是(原文逻辑):
   - 触发条件同主线 ROCKNIX:存在 `/storage/.please_resize_me`;
   - 在能被挂成 `/flash` 的 FAT 分区**根目录**放空文件 `resize_storage_<整数>G`;
   - **磁盘总容量必须严格大于**该整数 GiB,否则记日志 "disk too small … falling back to full storage resize" 并**删掉标记文件**,退回"storage 占满整盘";
   - 成功路径:`resizepart` 到 10GiB → `e2fsck`/`resize2fs` → 剩余空间 `mkpart` + `mkfs.exfat -n GAMES` → 删除标记 → 重启。
   ⇒ **默认开箱结果 = 10GiB 的 /storage + 剩下全部是 exFAT 的 GAMES 分区**(Windows 直接拷 ROM 很方便)。
   想要别的比例:开机前进 BOOT 分区把 `resize_storage_10G` 改名成 `resize_storage_32G` 之类(**只能有一个**匹配 `resize_storage_*G` 的文件,脚本用 `find … -name 'resize_storage_*G'` 取第一个)。
3. 首次开机不要拔电源、不要插第二张卡;扩容+重启期间**别断电**。

### 4.3 选设备树(这一步决定黑不黑屏)

手册 §3.4 的操作口径:"写卡后,在启动分区运行 `/flash/dtbselect`(Linux)或 `DtbselectWin64.exe`(Windows),选择与机器完全一致的设备树"。
本机选 **"Xifan NGP45H"**。

- 我本地存了两份 `DtbselectWin64.exe`(不同构建,字节数与哈希不同,**别混着当同一个工具**):
  - 来自 CI dtbselect 产物(RK356X):8,737,340 B,sha256 `506047965de618538631f251987cc981aeb2cf6ffb10a27efbf37b864e80ca71`
  - 来自 CI dtbselect 产物(RK3326):8,748,308 B,sha256 `37ee77299e638d93dc31c486ce84e2c5c0cf6e7c5ec9af15f412be870b4b3c38`
  - **注意**:镜像 BOOT 分区自带的那份是 8,415,037 B(20260918 构建)。⇒ **优先用卡里自带的那份**,版本要和镜像匹配。
- 它做的事就是把 `extlinux/extlinux.conf` 里的 `FDT` 指向 `device_trees/rk3562-ngp45h.dtb`(对比:RK3566-Generic 走 `FDTDIR` 多 dtb 自动挑,RK3562 是单 FDT 显式选)。

### 4.4 进系统后先做两件事

1. **跑 `Test Gamepad`**(AURKNIX 手册 §3.6):**Portable/Modules 类工具菜单里的 `Test Gamepad`**,启动 `gamepad-tester`(`/usr/bin/gamepad-tester`),基于 SDL2 GameController 逐键/摇杆/扳机/震动查看识别结果。
   NGP45H 有独立 `rocknix-joypad` 节点、四键 ADC 电阻梯和 `rumble-ngp45h` 震动脚,**先确认键位与震动正常再进游戏**,否则会把硬件映射问题误判成 ROM 问题。
2. **确认纯电池能冷启动**:RK3326 那一系有过 AIC8800 USB WiFi 驱动卡住电池冷启动的先例
   (arkos4clone issue #448,社区定位到 `aic8800_fdrv_usb.ko`,见 [`../R36MAX2/00-R36MAX2完全指南.md`](../R36MAX2/00-R36MAX2完全指南.md) 第六节)。
   NGP45H 用的正是同一族 WiFi(AIC8800DC,USB 总线)⇒ **风险同类,但是否复现未验证**。第一次开机后请专门做一次"拔线冷启动"测试。

---

## 五、内置存储与 eMMC

- 设备树里 eMMC 挂在 `sdhci`,厂商树**没开 HS400**(`mmc-hs400-1_8v`/`mmc-hs400-enhanced-strobe` 被删),`max-frequency = <52000000>`
  ⇒ 内置存储跑的是 lower-speed MMC 模式;这既解释了"eMMC 不快",也说明**别拿"eMMC 读写慢"当卡坏的判据**。
- 想把系统装进 eMMC:AURKNIX 在 **MOD_TOOLS** 里带 `Install AURKNIX to EMMC.sh`(手册 §8.1)。
  手册自己写明:脚本假定 **TF 卡 = `/dev/mmcblk1`、eMMC = `/dev/mmcblk0`,**"必须先确认机器上 mmcblk0/mmcblk1 与你的实际 TF、eMMC 对应关系,错误选盘会破坏数据;操作时需接入电源,过程中不要断电"**。
  所以顺序永远是:① 先用 TF 卡把系统跑通 → ② 开机进终端 `lsblk` 核对盘符 → ③ 再跑这个脚本。
- 反过来说,如果 eMMC 已经刷坏:Rockchip 平台走 MASKROM/Loader + FactoryTool 线刷救(通用文档第六节 + `09-刷机工具/README.md`)。
  **稀范没给过 NGP45HT 的官方线刷包**,所以这条路线风险自担 —— 这点必须先说清楚再动手。

---

## 六、ROM / BIOS / Ports 的路径差异(和 ArkOS 系不一样)

AURKNIX 是 ROCKNIX 架构,路径与 ArkOS/dArkOS 完全不同:

| 内容 | 位置 |
|---|---|
| ROM | `/storage/roms/<系统>/`(手册 §2.1 明确 BIOS 在 `/storage/roms/bios/` 下对应文件夹) |
| 游戏分区(默认布局) | 首启生成的 exFAT **`GAMES`** 分区,Windows/Mac 可直接读写;设备内按镜像 automount 规则挂载(手册 §4) |
| 电子书/音乐 | `/storage/roms/ebook`、`/storage/roms/music`(手册 §7,`kebook` 支持 EPUB/PDF/TXT,可背景音乐+自动翻页;`kplayer` 支持在线歌词) |
| 额外模拟器 | 手册 §2:本改版比主线多带 `drastic_adv-sa`(增强版 NDS 独立)、`free-j2me`、`OpenBOR-ff`、`fbneoplus-lr`、`gam4980-lr`(BBK 4980 电子辞典)、`hbmame-lr`、`onscripter-lr`、PyMO/cpymo。
  **NDS 想调双屏布局**看 §5:`/storage/.config/drastic/resources/bg/<分辨率>/layout.json`(1024×768 就填 `1024x768` 那档) |
| OTA | 手册 §10:在线 `rocknix-update update`;离线把 `AURKNIX-RK356X.aarch64-<日期>.tar`(+`.sha256`)放进 `/storage/roms/.update/`,跑 `MOD_TOOLS/Offline Upgrade.sh`,**重启**由 init 读 `redirect_part` 刷 SYSTEM/KERNEL。
  ⚠️ 更新包必须与机型+架构一致;§3.4 特别写明 **RK356X(Rockchip 5.10 BSP)与主线 6.x 内核的独立 RK3566 包互不兼容** |
| PortMaster | AURKNIX/ROCKNIX 有自己的 ports 机制,和 ArkOS 的 `Install.PortMaster` 不是一回事;合法可下载池统计见 `04-游戏资源库/公版与开源游戏/PortMaster移植游戏指南.md` |

---

## 七、外部信息(仅作市场背景,不作为刷机依据)

- B 站:《NGP45HT稀范科技新机NGP45HT开源掌机》BV1cfpv6FEjF(2026-10-09)、《rg52mini,XF55H,NGP45H新一代开源掌机推荐》BV1xsTv6bE48、《4.5寸横版来了!稀范RF45H开箱评测》BV19spk6vEwT。
- 什么值得买《「能跑PS2」?310元稀范新机到货,战神2带不动,联机对战…》:时间线"10月10日起,深圳市稀范科技接连放出两台新机:NGP45HT和RF45H",并给出"战神2 带不动"的实测。
- Rockchip 官方 RK3562 规格页:Quad-core Cortex-A53 up to 2.0GHz、Mali-G52 GPU、1TOPS NPU。

Sources:
- [Rockchip RK3562 官方产品页](https://www.rock-chips.com/a/en/products/RK35_Series/2024/0626/1983.html)
- [NGP45HT稀范科技新机NGP45HT开源掌机(B站)](https://www.bilibili.com/video/BV1cfpv6FEjF)
- [rg52mini，XF55H，NGP45H新一代开源掌机推荐(B站)](https://www.bilibili.com/video/BV1xsTv6bE48/)
- [「能跑PS2」？310元稀范新机到货(什么值得买)](https://post.smzdm.com/p/al38lr5e/)
- [AURKNIX(distribution_rocknix) 中文用户手册](https://github.com/AveyondFly/distribution_rocknix/blob/main/USER_MANUAL_cn.md)
- [AURKNIX nightly 镜像发布页](https://github.com/AveyondFly/distribution-nightly/releases)

---

## 八、下一步读哪篇

| 你要做的事 | 去这里 |
|---|---|
| 校验/写卡/进 MASKROM/双卡/OTA 通用规矩 | `../00-刷机通用流程与工具.md` |
| 另一台 XiFan RK3326 机器(R36MAX2) | `../R36MAX2/00-R36MAX2完全指南.md` |
| RK3326 生态全景(dtb、ROM/BIOS 表、性能天花板) | `../R36S/00-R36S完全指南.md` |
| 已下载镜像与工具的字节数/sha256/来源 | `../../../02-模拟器库/已clone仓库/系统镜像/README.md`、`../../../09-刷机工具/README.md` |

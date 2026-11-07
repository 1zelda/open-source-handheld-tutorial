# 机型固件

汇总对照表在 `00-机型固件对照表.md`(机型→芯片→可用固件→本地资料→刷机风险分级)。
通用步骤(校验下载、写卡、进 MASKROM、双卡布局、选设备树)只写在 `00-刷机通用流程与工具.md` 一处,机型篇不重复。

## 本轮(2026-11-05)写成的四篇机型完全指南

| 篇 | 机型 | 芯片 | 屏幕 | 能刷什么(本地已下并已校验的镜像) |
|---|---|---|---|---|
| `NGP45HT/00-NGP45HT完全指南.md` | XiFan NGP45HT(商品名;固件机型名 `Xifan NGP45H`) | **RK3562** | 1024×768 | AURKNIX RK3562(CI 20261021 / nightly 20260918)——**只有这一条路** |
| `R36S/00-R36S完全指南.md` | Anbernic/原厂 R36S 及克隆板 | RK3326 | 640×480 | ArkOS4Clone 20261008 / dArkOSen 10312026 / dArkOSRE / ROCKNIX 20261101 / AURKNIX RK3326 |
| `R36MAX2/00-R36MAX2完全指南.md` | XiFan R36MAX2 | RK3326 | **1024×768** | ArkOS4Clone 20261008(首选)+ AURKNIX RK3326 + 厂家 EmuELEC |
| `XiFan_XF45V/00-XF45V完全指南.md` | XiFan XF45V | RK3326 | **1024×768** | ArkOS4Clone 20261008(首选)+ AURKNIX RK3326 + 厂家中文 EmuELEC 包 |

镜像的下载来源、SHA256、校验来源分档(【API-digest】/【作者.sha256】/【官方 .sha256】/【仅本机】)和"哪个文件对哪台机器"在
[`../../02-模拟器库/已clone仓库/系统镜像/README.md`](../../02-模拟器库/已clone仓库/系统镜像/README.md);
刷机工具(FactoryTool、dtbselect、Rufus 等)的哈希台账在 [`../../09-刷机工具/README.md`](../../09-刷机工具/README.md)。
全 RK3326 机型的屏幕真值(逐 dtb 解析)在 [`../../05-硬件与机型资料/屏幕真值表.md`](../../05-硬件与机型资料/屏幕真值表.md)。

子目录用途:
- `NGP45HT/ R36S/ R36MAX2/ XiFan_XF45V/` — 上面这四台机器的完整刷机记录
- `Anbernic/` — RG35XX 系列、RG405M/RG Cube/RG556 的刷机记录与按键配置
- `Miyoo-Trimui/` — Miyoo Mini(Plus)、Trimui Smart Pro / Brick
- `安卓掌机/` — Retroid、奥丁、AYANEO Pocket 的前端与映射方案(不涉及刷机)
- `Win掌机/` — GPD / OneXPlayer / AYANEO x86 机型的 RetroBat、ES-DE 部署
- `SteamDeck/` — RetroDECK 与 Steam 层配置

每个子目录里请写"具体到某机型某固件某步骤"的记录,通用结论一律回到对照表改,避免两处不一致。

# Switch / PS Vita / 开源掌机：破解与移植的发布源指北

> **这份文档不是搬运。** 你上一条要求"把教程复制放到根目录"，但 `switch.hacks.guide` 页脚写的是
> `Copyright © 2026 Nintendo Homebrew`，**没有 CC 授权**，整篇复制就是侵权。所以流程部分是我自己复述、
> 逐步解释"这一步在你的机器上到底做了什么"，并把出处链接挂全。
>
> **本文所有数字都是 2026-10-10 现场拉的**，不是抄旧笔记：GitHub 字段用认证过的 `gh api`（走 7890 代理），
> 网站状态用 `curl` 实测。复核命令在第 7 节，你自己跑一遍就能重算全部结论。
> 凡是本机测不出来的，我标 **UNVERIFIED**，不编数。
>
> **本文只回答"在哪里发布"这一件事**：往下还有几份配套件 ——
> `06-资讯监控/README.md`（**156 个启用源的登记表 + 每日日报生成**，把"哪里发布"变成可自动抓的东西）、
> `04-游戏资源库/爆款收录/README.md`（**已经落地的 42 组 / 65 个文件 / 815.7 MB(十进制)**，逐个和上游 sha256 双向对账，
> 以及每一条**拒收 / 只监控**的理由）、
> `06-资讯监控/大作登陆平台.md`（**"某大作/经典作品登陆到某平台"专线的累计清单**，判定列来自人工维护的 `06-资讯监控/大作判定.tsv`）、
> 以及 `06-资讯监控/README.md` §六（**每天 08:30 的 Windows 计划任务 + 每天 09:30 的 Qoder 定时任务**，含撤销命令）。
> 本文下面所有数字都是**建线当天**的实测快照，会随定时任务每天漂移。各篇之间的接口见 §8。

---

## 0. 一句话回答"到底在哪里发布"

这个生态是**分层**的，混不得：

| 层 | 发什么 | 首发在哪 | 可信度 |
|---|---|---|---|
| 代码/二进制 | 自制固件、引导器、自制软件、开源移植的**引擎** | **GitHub release**（唯一有哈希、有提交历史、有许可的一层） | 高 |
| 教程 | 流程图、避坑 | 专用指南站 + Wiki | 中高（要看最后更新日期） |
| 资讯/事件 | "XX 能玩 YY 了" | 论坛(GBAtemp/wololo) → Reddit → IGN/Kotaku 这类媒体 → YouTube/B站 | 逐层衰减，到 B站基本只剩标题 |
| **游戏本体/整合包** | NSP、XCI、VPK、大气层整合包 | **网盘(夸克)、私有 Discord/QQ 群、文件站(buzzheavier)** | **零。无哈希、无来源、随时失效，且全是别人的版权内容 —— 本库不收录** |

你的判断是对的：**最大的那些平台确实是国外的**，而且"破解文件"和"资讯"常常不在同一个地方发。
上一轮我只翻了 GitHub 和英文媒体，漏了中文渠道那一层（B站 + we1zard 这类工具箱站），这次补上了 ——
见 §1.4。

> **2026-10-13 自查补一句**：上面这张表第一行"GitHub release"，我当初只挂了**固件与工具链**
> （Atmosphere / Hekate / MissionControl / libnx…），**单个移植作者的 release 流基本没挂**，
> 所以"某个引擎发了新版"这件事我当时是看不见的 —— 只能等 GBAtemp 有人发帖转载。这一层现在补齐，见 **§1.1.5**。

---

## 1. Nintendo Switch：首发源清单

### 1.1 上游仓库（二进制真正出炉的地方）

全部 `gh api` 实测。**许可列很重要**：GPL 意味着"这是别人重写的代码"，不等于里面有游戏。

| 项目 | 仓库 | stars | 最后推送 | 最新 release | 许可 | 它发什么 |
|---|---|---|---|---|---|---|
| **Atmosphère** | `Atmosphere-NX/Atmosphere` | 20058 | **2026-10-09** | 1.12.0 (2026-09-27) | GPL-2.0 | 自制固件本体 |
| **Hekate** | `CTCaer/hekate` | 8867 | 2026-09-28 | v6.5.4 (2026-09-28) | GPL-2.0 | 图形引导器/备份工具 |
| **MissionControl** | `ndeadly/MissionControl` | 3570 | **2026-10-02** | v0.16.0 (2026-10-02) | MIT | 自制软件/移植的统一安装器 —— **移植资讯的实际首发点** |
| libnx | `switchbrew/libnx` | 1471 | 2026-10-01 | v4.12.0 (2026-09-28) | MIT | 自制软件开发库 |
| nx-hbmenu | `switchbrew/nx-hbmenu` | 1404 | 2025-11-16 | v3.6.1 | MIT | 自制软件菜单 |
| Sphaira | `NaGaa95/sphaira` | 852 | **2026-10-06** | 1.0.8 (2026-10-06) | — | 文件浏览器/启动器 |
| **Ultrahand-Overlay** | `ppkantorski/Ultrahand-Overlay` | 686 | 2026-09-28 | v2.5.3 (2026-07-17) | MIT | **现役**叠加菜单 |
| ns-usbloader | `developersu/ns-usbloader` | 2343 | 2026-09-19 | v7.3 | — | 安装工具（也用于装 dump，本库只当安装工具记） |
| GTA:SA on Switch | `NaGaa95/gtasa_nx` | 49 | 2026-08-15 | 1.0.4 | — | **合法移植**：引擎，仍需自备手游版数据 |
| **Sega Rally on Switch（本轮新爆款）** | `jacquesdupontd/port0r` | **51** | **2026-10-10** | **Switch 版在 tag `switch-v0.5.3`**（`latest` 是 Quest APK v0.2.4） | **null**（README：*"The app's own source code is not public for now"*） | 作者自建的 Model 2A 引擎成品包，**要自备 MAME 0.289 的 `srallyc.zip`/`segabill.zip`** |
| **Warnel Chawpiovs（本轮新爆款）** | `frwololo/warnel-chawpiovs` | **21** | **2026-10-10** | 1.7.1（5 个平台包，全有 digest） | **null** | Godot 写的 Marvel Champions 规则执行器；作者就是 wololo.net 本人；卡牌数据首次运行自行联网取 |

### 1.1.5 移植**作者**的发布层（2026-10-13 补 —— 这一层之前基本是盲区）

你问"Switch 新移植的信息发布地方你收录了吗"。我把 `合法收录登记表.tsv` 的 46 条按 `repo` 反查回 `源登记表.tsv`，
结果是**只有 13 条挂着对应的 release 流**。也就是说：已经下进池的风之杖（SwitchWaker / SwitchWakerHD）、
索尼克大冒险2（sa2-nx）、Model 2/Model 3 街机（model2-nx / supermodel-nx）、Sega Rally（port0r）、
GTA3（gta3-nx）、NXStation、ioQuake3 全家族 —— **作者发新版我根本看不见**，只能等 GBAtemp 有人发帖转载。
本轮补 22 行（20 启用 + 2 点名拒用），每条都先 curl 实测再登记，实测码与条数写在 `note` 列。

| 挂法 | 地址形态 | 为什么这么挂 | 实测（2026-10-13） |
|---|---|---|---|
| **作者级活动流** | `https://github.com/<user>.atom` | 一人多仓，一条流覆盖他全部仓库的 release **和新开仓**。挂的人：`NaGaa95`(71 仓，NetherSX2_nx ★286 / lswtcs_nx ★28)、`toniisound`(model2-nx、supermodel-nx、oracles-nx、daytona-recomp-nx)、`ChanseyIsTheBest`(68 仓，sa2-nx)、`Mayo1970`(ioQuake3 五平台)、`Rinnegatamante`(386 仓，Vita 主力)、`WE1ZARD`(nxStore/Magic-Suite)、`jiraiya78`(NXStation) | 29 / 28 / 30 / 28 / 30 / 30 / 8 条，全 `200` |
| **单仓库 release 流** | `.../releases.atom` | `centollOS.atom` 实测 **200 但 449 字节 0 条**（作者级流是空的），可他那两个仓库的 releases 各有 10 / 8 条 → **作者流不能当万能替代** | SwitchWaker 10 条、SwitchWakerHD 8 条、port0r 10 条、gta3-nx 3 条、halo-ce-vita 10 条、RSDKv3(Wii U) 8 条、RSDKv3-PSP 2 条、SRB2-PS4 1 条、dxx-3ds 8 条、warnel-chawpiovs 10 条 |
| **目录 / 清单流** | `.../commits.atom` | `robzilla10001/SwitchPorts`（★297，**Switch 移植总清单**）与 `CostelaCNX/PortNX`（★18，Switch 上的移植浏览器）。清单新增一行 = 有新移植出现，比论坛帖快；前者不发 release，所以挂 commits 流 | 20 / 5 条 |

**补完当天就出货的东西**（以前只能等转载），这批现在都进了台账，`flag_hot=HOT`：

- `ChanseyIsTheBest`：`sa2-nx` **1.0.0 → 1.0.1 → 1.0.2**（10-07/10-12）、
  **`UnleashedRecomp-NX 1.0.0`**（10-02，Xbox 360 版《索尼克释放/决绝》静态重编）、
  **`futari-nx 1.0.0`**（10-08，`Mushihimesama Futari Ver 1.5` Xbox 360 → Switch，ReXGlue 静态重编）、
  `sonicjumpfever_nx 1.0.0`（10-08）、`MarathonRecomp-NX 1.0.3`（10-01，仓库自述是《索尼克'06》X360 版的重编工程）
- `centollOS`：**SwitchWaker 10-07→10-12 连发 0.1.0…v0.4.0 十个版本**，SwitchWakerHD 同日 0.4.6
- `toniisound`：`model2-nx v1.0`（10-10）、`supermodel-nx 1.2.1 / 1.3.0 / 1.3.1`、`oracles-nx 1.0`（10-10，GBC《不可思议的帽子/四季的果实》原生 C 重实现）
- `NaGaa95`：`ProjectCane 0.4.0-beta.1 / beta.2`（10-10、10-12，`Sly Cooper and the Thievius Raccoonus` 反向工程）

**这几个的许可与数据口径我都读了 README 原文**，全部是"引擎重编 + 自备数据"，没有夹带游戏镜像：
model2-nx 原文 *"No ROMs are included: provide your own, and only use copies of games you own."*；
ProjectCane 原文 *"ProjectCane does not include the original game's copyrighted data."*；
UnleashedRecomp-NX 原文 *"You must provide the files from your own legally acquired copy of the game"*（并标注带 DLC 需 10 GiB）。
所以按本库既有口径：**作者公开发布的成品包可收（有上游 sha256 可对账），游戏镜像/ROM 一律不碰**。
上面这批是否要落进 `爆款收录/`，我按"四问判定"逐条走完再动，不在这一轮里偷偷加。

**这次补源同时暴露的一个闸门缺口已经写进代码**（细节见 `06-资讯监控/README.md` §二 坑五）：
作者级流里大量是 `pushed xxx-nx` / `created a branch` 的活动流水，而这些条目的 **URL 自带仓库 slug**，
`arrival_of()` 连 URL 一起扫就把"作品名 + 平台"从 slug 里凭空造了出来（大作专线一度 44→69）。
现在 `AUTHOR_NOISE` 在入库前丢掉这类事件，脚本输出多一列 `活动流丢弃=N`，专线回落到 **55 条**。

**已经被时间淘汰、但旧教程还在猛推的：**

| 名字 | 实测状态 | 该换成的现役方案 |
|---|---|---|
| `WerWolv/Tesla-Menu` | 1129★，**最后推送 2023-05-27**，release 也停在 2023-05-27 → 已冻结 | `ppkantorski/Ultrahand-Overlay` |
| `eliboa/TegraRcmGUI` | 2318★，**最后推送 2021-11-30**，最后 release 2.6 是 **2019-07-02** | 指南站现在推荐的注入方式（见 §2 第 3 步） |

### 1.2 指南站（教程首发）

| 站点 | curl 实测 | 定位 | 能不能抄 |
|---|---|---|---|
| `switch.hacks.guide` | **200** | 唯一的权威全流程指南，Nintendo Homebrew 出品 | **不能整篇搬运**（All rights reserved），可以复述+挂链接 |
| `wiki.switchroot.org` | **200** | Switchroot 各发行版文档 + 机型资料 | 看站点许可再定 |
| `switchbrew.org` | **200** | 开发者 Wiki（协议、标题ID、文件格式） | 技术资料，引用可以 |
| `wiki.switchbrew.org` | 000 | —— | **本机 TLS 失败，不代表站点死亡**，浏览器可达即算正常 |
| `switch-hacks.info` | 502 | —— | UNVERIFIED，网关报错 |
| `repo.missioncontrol.net`、`socalconsolemodding.com` | 000 | 疑为在线安装源/指南镜像 | UNVERIFIED（本机 TLS/代理层失败，同 gnu.wtf 那类） |

### 1.3 论坛 / 资讯

| 源 | 实测 | 说明 |
|---|---|---|
| **GBAtemp** `gbatemp.net` | curl **403 = Cloudflare 反爬，站点活着**（浏览器可达） | 最大的主机自制综合论坛；Switch 分区和新闻流都在这里 |
| **wololo.net** | **200**，`/feed/` RSS **200** | 复古/自制新闻博客，**有真 RSS**，最适合程序化盯新消息 |
| r/SwitchHomebrew、r/AtmosphereCustomFirmware | 站点 200 | 支持与技术讨论 |
| r/SwitchPirates | RSS `.rss` **200**（存在） | 它确实是最大的 Switch 折腾集散地之一，**但下载区是盗版内容，本库不收录其链接**；订阅数本机测不到（`about.json` 从数据中心 IP 返 403）→ **UNVERIFIED** |
| Discord | **UNVERIFIED** | 我没拿到可靠的 invite slug，**不编**。以指南站页面里列的官方服务器链接为准 |
| IGN / Kotaku / Notebookcheck | 可达 | 只在"事件"层面报道，永远慢一手且不带文件 |

### 1.3.5 论坛穷举层（2026-10-13 第二轮，你要求的"从最出名的到小众的全部穷举"）

七轮离线探测、约 **160 个候选站**（脚本与 log 在 `_scratch/probe_feeds2..7.py` / `probe2..7.log`），
**结论先说**：能程序化订阅的论坛比想象中少得多，而且**猜引擎路径是错的**——要嗅页面自己声明的
`<link rel="alternate" type="application/rss+xml">`。emutalk 和 wololo 论坛的可用地址就是这么找到的（此前四种引擎路径全 404/403）。

| 引擎 | 实测能用的口 | 代表源 |
|---|---|---|
| XenForo 2 | `app.php/feed`、`app.php/feed/topics` | wololo 论坛（探测 200/15、200/10；生产两轮 000，`note` 已记） |
| Discourse | `/latest.rss` | **`forums.libretro.com`**（200/30，RetroArch/libretro 官方论坛；**域名不是 libretro.dev**） |
| NodeBB | `/recent.rss`（**`/latest.rss` 404**） | RetroPie 论坛 200/20 |
| IPS 门户 | `ewr-porta/index.rss` | EmuTalk 200/20，连测三次稳定 |
| SMF | `index.php?action=.xml;type=rss2` | RomHacking.net 200/5 |
| Resetera 自建 | `/index.rss` | 200/39~40 |
| YouTube | `feeds/videos.xml?channel_id=UC…`，**channelId 要从 `@handle/videos` 的 HTML 里挖** `"channelId":"(UC[\w\-]{22})"` | MVG / ObsidianAnt / ETA PRIME / GBAtemp 官方频道，全 200 |
| itch.io | `games/newest.xml` | 200/36（**滚动"最新上架"，不幂等**，第二轮还多出 7 条轮换） |
| Discuz! | `forum.php?mod=rss&auth=0`（按 fid 的变体只回 HTML/0 条） | 吾爱破解 200/20；**A9VG、MYDIGIT 200 但 0 条 = 要登录态 auth key** |

**这一层当场抓到的真东西**（都是论坛帖，不是 GitHub release，以前只能等转载）：
`Sega Rally on Switch 1, coming soon`（SegaXtreme 10-01）、`Oddworld Abe's Oddysee 2D port using R.E.L.I.V.E.`（10-09）、
`Neon Genesis Evangelion v2.0 English translation patch`（10-08）、`PS5 Hypervisor Exploit Released up to 13.60 (Byepervisor Reborn)`（Resetera 10-13）、
`Xbox 360 softmod`（MVG 10-12）、`EmuDeck on Armada`（Retro Handhelds Weekly）。
大作专线**没有**被论坛层灌脏（新 27 源 `ARR=0`）——论坛帖是讨论体，凑不齐"作品+登陆动词+平台"三同现，
这点和坑五的假命中是两回事；反倒因此暴露了**综合源灌闲聊**的问题，已用 `HOT_CONTEXT` 按 `kind` 分档挡住（见监控 README §二 坑六）。

**够不着的部分我也按名字登记，不写成"不存在"**：国外论坛 **27** 条停用（console5/MiSTer/AtariAge/Odroid 403、
analogue/Batocera/switchroot/muos/3dsonne/TeamSn00py 等 000、purenx 500、orangespecs 406、**n4g 451（法律屏蔽）**、
trimui 429、consoledevnet 521、MAME 论坛/AssemblerGames/TGames 404、recalbox/cbps 200 但 HTML 0 条、retrostage 正文流只有 1 条），
中文层 **16** 条停用（**贴吧 403（桌面/移动/fdir 三种写法全挡）**、A9VG/MYDIGIT 要 auth key、chiphell 567、
3DM/游民 403、ali213/17173/快科技/NGA/购物猫 404、tgbus 000、知乎只回 JSON、Anbernic 官网无订阅口、卡饭可达但主题无关）。
**中文视频/网盘层的唯一真通路是自建 RSSHub，公共实例实测 403/503/000 全灭 —— 这是本项目当前唯一的真缺口**，明写在登记表 `cn_rsshub_public` 的 `note` 里。
场景/盗版层（preDB、SRRDB、SCENE.ORG、OSW、Files-Notes、myscene、TX 硬改论坛）与
**可达但拒不使用**的 r/Piracy `200/25`、r/SwitchPirates `200/25`、r/roms `429` 全部登记为 `enabled=0`；
**`BAN` 闸门（`.nsp/.xci/.iso/merged_keys/prod.keys/romset/warez/dump pack`）照旧拦死，这一轮一个字没放松**。

### 1.4 中文渠道层（上一轮我漏掉的，你补给我的）

你给的 B站视频我抓了，元数据如下（**这是"资讯衰减链"的最后一环，看它怎么变形**）：

- 视频：**「没错！Switch玩上GTA5了！！」**，UP 主 **玩機社**，发布 **2026-09-06**，
  简介原文两行：`GTA5移植作者：Paralympics Productions` / `WiZBOX工具箱：we1zard.com`。

`we1zard.com` 实测（不是"找不到"，是**中文整合包站**）：

| 项 | 实测内容 |
|---|---|
| 站点性质 | WE1ZARD 个人站；导航=首页/商店/教程/更新日志/反馈；口号 `Switch 折腾升级更省心!`；自称 `100% 免费使用`；页脚 `© 2026 WE1ZARD. All rights reserved` |
| 宣传的东西 | `稳定高效的整合包`，工具列表里出现 **DBI**（装 NSP/XCI 的安装器）和 **Edizon**（改存档/金手指） |
| 下载方式 | **夸克网盘** `pan.quark.cn/s/…`，不是 GitHub、**无哈希、无版本校验** |
| 社群 | B站 `space.bilibili.com/3595105`、QQ 群二维码链接、爱发电众筹页 |
| GitHub | `github.com/we1zard`（用户，2022-08-13 注册，17 个公开库） |
| ├ **Magic-Suite** | **79★，最后推送 2026-10-07**，简介：`为极限超频而生, 一个好看好用又稳定的大气层整合包`，README 把人导回 we1zard.com |
| └ **nxStore** | 4★，**最后推送 2026-10-10（就是今天）**，`自托管的社区 NX 应用商店` |

**结论**：中文层是真实且活跃的存在（两天前还在推），但它的**游戏本体走网盘、无哈希、捆绑改存档工具**，
这三条决定了它能进"渠道清单"，不能进"下载指引"。我要用的部分只有 `nxStore` 这类自制应用分发和教程结构，
以及"作者改名/换域名要去 GitHub 反查"这个技巧。

---

## 2. Switch 破解流程逐步解释（每步在机器上干了什么）

按 `switch.hacks.guide` 的实际页面顺序（我抓了导航项，11 节）。**关键前置**：
只有**初代未补丁机型（V1，2018 年前后批次）**能靠 bootROM 漏洞 `fusee-gelee` 软破；
判断方法就是指南第一步 —— 查序列号或读芯片熔丝，**不用先动手**。

| # | 指南步骤 | 这一步在硬件层面做了什么 | 为什么不能省 |
|---|---|---|---|
| 1 | Getting Started | 判定你的机器属于"可软破 / 必须焊芯片"哪一类 | 判错会白折腾甚至刷坏 |
| 2 | Entering RCM | 短接右 Joy-Con 滑轨的 **PIN10 与 GND**（或用 jig），让 Tegra SoC 在**开机前**进入 USB Recovery Mode。此时 CPU 跑的是 NVIDIA 固化在 bootROM 里的恢复程序，**还没碰闪存** | RCM 是唯一能在系统之前插话的入口 |
| 3 | Sending a Payload | 从 PC 往 RCM 的 USB 端点塞一段签名外代码（`fusee.bin` / hekate）。`fusee-gelee` 利用 bootROM 里 USB 恢复码的**整数溢出**绕过校验，把 payload 跳进内存执行。**纯内存操作，重启就没了，不写任何区** | 这就是"软破"的含义：可逆 |
| 4 | Introduction to Modchips | **补丁机型（V2/V2.1/Lite）修掉了 bootROM 漏洞**，唯一路径是焊一颗 PICOX/RCM2Pico 之类的小芯片在板上，由它在每次上电时**自动完成第 2+3 步** | 不可逆的硬件改动，这是风险分水岭 |
| 5 | Payload / Bootloader 目录摆放 | 在 SD 卡建 `/bootloader/`（hekate 的 `payload.bin` + `ini` 配置）、`/atmosphere/`、`/switch/` | 路径写错=引导器找不到层，表现为"点了没反应" |
| 6 | CFW on sysMMC **vs** emuMMC | sysMMC=直接在**机身内置存储**上跑自制；emuMMC=把内置系统**整份克隆到 SD** 再跑克隆那份。差别在封机风险与污染面：emuMMC 出问题或联网被封，伤的是 SD 那份 | 选 sysMMC 就把主机身份押上去 |
| 7 | 分区 SD + 创建 emuMMC | 把 SD 切成"系统分区(存游戏/自制) + HSM 隐藏分区(存克隆的内置系统)"。**需要 ≥128GB** 的卡才够装整份内置存储 | 克隆不完整会在游戏更新时炸 |
| 8 | 格式化/分区 SD（不克隆那条路） | 只走 sysMMC 时，SD 用 FAT32/exFAT 单分区即可 | 簇大小/文件系统选错会让某些平台 ROM 读不到 |
| 9 | microSD 卡准备 | 换掉杂牌卡（指南反复强调速度/兼容性是首要故障源） | 掌机 90% 的"刷坏了"其实是卡坏了 |
| 10 | Making Essential Backups | 从**你自己机器**里 dump：`PRODINFO.bin`（设备密钥与证书区，**出厂唯一、丢了无法重建**）、`rawnand`/`sysnand` 系统备份、以及**你自己机器的** `prod.keys`。耗时 10–30 分钟 | 这是唯一能在刷砖后把机器救回来的东西 |
| 11 | Launching CFW | hekate 的 ini 里选 Atmospheric 层 → 启动 → `hbmenu` | 到这里才算跑通 |

**一句话总则**：第 2–3 步不写闪存（可逆），第 4 步动烙铁（不可逆），第 6 步决定风险落在哪块存储上，
第 10 步决定出事后可不可挽回。**先做 10，再碰 6。**

---

## 3. PS Vita：现状、失效链接与"Halo 真能玩"的证据链

### 3.1 老教程的链接已经烂了（这是本轮实测最有用的一条）

| 旧教程里出现的 | 实测结果（2026-10-10） | 正确的名字 |
|---|---|---|
| `TheOfficialFloM/Relaax`（网页注入 Henkaku 的站） | **GitHub 404，两种拼写（FloM / FloW）都是 404 —— 仓库已没了**；作者主页 `theofficialflow.github.io/` 现在返 **200**，但 `…/Relaax/Relaax.html` 返 **404**，即**那个网页注入入口已经随仓库一起消失** | 现役路径见 **§3.4**（已核完）：`vita.hacks.guide`（**200**）+ `jailbreak.psp2.dev`（**200**） |
| `vitasdk/vitasdk` | **404 —— 这个仓库名从来不存在** | **`vitasdk/vita-toolchain`**（292★）；包管理 `vitasdk/vdpm`（271★，push 2026-09-25）；头文件 `vitasdk/vita-headers`（242★） |

`vitasdk` 组织**活着**，公开库里还有 `samples`(360★)、`buildscripts`(65★)、`autobuilds`(38★)、
`vitasdk.github.io`(10★，push 2026-09-26)。也就是说：**工具链首发在 GitHub 的 vitasdk 组织，但入口名要写对。**

### 3.2 你点名的 Halo：是真的，而且性质完全清白

一手证据（README 原文照录）：

- `isifire/halo-ce-vita` — **GPL-3.0**，7★，最后推送 **2026-10-02**。
- 项目自述：*"a **native port of the Halo: Combat Evolved decompilation**"*，基于一份 Xbox build 2342
  （`cachebeta.exe`，README 里直接给了 SHA-256 `4cc87b45…4d9520`）做**反编译重写**。
- 数据条款原文：*"The port does **not** include proprietary game data. You must provide your own
  **legally acquired** Halo: Combat Evolved files from an original Xbox disc image (`.iso`/`.xiso`) or retail `.map` files."*
- 装机要求（`port/vita/README.md` 原文）：**3.60–3.74 固件 + HENkaku/Ensō + VitaShell**；
  `ux0:` 约 **1.5 GB** 空间（游戏会把读到的 map 解压成缓存，最大约 765 MB）；
  把 Xbox 版整个 `maps` 目录（`ui.map`、`bloodgulch.map`、`a10.map`…）拷到 **`ux0:data/haloce-vita/maps/`**，
  并把碟里的 `default.xbe` 放到 `ux0:data/haloce-vita/`（读盘画面取它的图）。
  运行状态：**全战役 30 FPS**，直连 LibGxm 硬件渲染 + Cg shader，离线 shader 缓存存
  `ux0:data/haloce-vita/shaders/`；长按 **Select+Start** 一秒开性能浮层。
- **GitHub 上没有 Release**（`releases?per_page=3` → `n=0`）：作者不发预编译包 → 别人转发的 `.vpk` 来自第三方，
  **这正是网盘包无哈希的成因**。
- 作者在 **2026-10-02 同一天连推两条提交，把"清白"写成了仓库纪律**（提交信息原文，完整未截断）：
  - `chore: exclude local Vita SDK, legacy builds and extracted game data` —— 把**已提取的游戏数据**从仓库里剔出去。
  - `CI: no automatic releases (this repository's releases are the Vita builds)` —— 正文写得很清楚：
    原来的 workflow 会把 main 上每个通过的构建自动发成"latest release"并推 Discord，
    现在改成**手工发 release**，但 *"The builds still run and keep their artifacts"* →
    **构建产物留在 GitHub Actions 里**（要登录去 Actions 页翻），**"没有 release"不等于"没有构建"**。
  → 这两条是判别"这个移植能不能收"的**教科书级信号**：作者自己在管边界，而且管到了 CI 配置那一层。
  （顺带一条拍视频用得上的事实：**CI 那条提交**的 trailer 里带着
  `Co-Authored-By: Claude Opus 5.5` 与 `Claude-Session: https://claude.ai/code/session_…`
  （另一条 `chore:` 是单行提交，没有 trailer），
  即**这个 Vita 移植至少部分是 AI 结对写的** —— 这是仓库里的事实，不是我推测的。）
- ⚠ 文档内部不一致：主 README 写 `ux0:data/halo/maps/`，`port/vita/README.md` 写 `ux0:data/haloce-vita/maps/`。
  **以 `port/vita/README.md` 为准**（它是移植专属说明，还给了缺图时的游戏内提示行为）。

血缘链（**全部活着，且都在这两天还在推**）：

| 上游 | stars | 许可 | 最后推送 | 备注 |
|---|---|---|---|---|
| `bnunu/halo-1` | 307 | **CC0-1.0** | 2026-10-10 | 反编译基座 |
| `punpckhdq/halo` | 179 | CC0-1.0 | 2026-10-09 | 另一支反编译 |
| `cybersecurity/halo-ce-universal` | — | — | — | **已改名迁移**，现在叫 **`OpenCommunityEdition/OpenCE`**（1324★，push 2026-10-10）。**链接会烂，这就是活例** |
| `BirchWoodGod/halo-ce-vita` | 59 | GPL-3.0 | 2026-10-09 | Vita 原生 LibGxm 渲染层 |
| `Xita-Project/xita` | 4 | GPL-3.0 | 2026-10-02 | **已关闭**，库说明直接写"Halo 的工作继续于 `BirchWoodGod/halo-ce-vita`" |

**传播链**（这才是你问的"讯息在哪里发布"）：
GitHub 首发 → **r/VitaPiracy** 三帖（`Halo CE Recompiled for the PS Vita` → `Halo CE port Release` →
`Halo CE PS Vita v1.0.3`）→ Facebook 小组转发 → B站/短视频搬运。
也就是说：**同一件事，代码在 GitHub，热度在名字里带"Piracy"的版块**。
你要的是前者的信息，后者只是它的回声 —— 但你要知道回声在哪，否则永远觉得自己"没找对地方"。

### 3.3 Vita3K（PC 端那条路，5802★，push 2026-10-09）

和"破解机子"无关，但所有"PSV 能玩 XX"的讨论里有一半其实是 Vita3K 上的演示。
判定标题真假时先看它写的是**掌机原生**还是**模拟器**。

### 3.4 Vita 当前的正确安装路径（我把"待核"核完了）

上一版这里我写着"待核"。现在每条都是本机实测过的：

| 环节 | 当前正解 | 实测证据 |
|---|---|---|
| 全流程指南 | **`vita.hacks.guide`**（源码仓库 `hacks-guide/Guide_Vita`，206★，push 2026-04-15） | curl **200**，20995 B |
| 注入入口 | **设备浏览器打开 `jailbreak.psp2.dev`**（HENlo），先按指南升到 **3.74** | curl **200**（HTTP 与 HTTPS 都通） |
| 授权持久化 | **Ensō**（`henkaku/enso` 297★，**冻结于 2020-08-25**）；`henkaku/henkaku` 525★，**冻结于 2019-08-23** | `gh api orgs/henkaku/repos` |
| 作者主页 | `theofficialflow.github.io`（HENlo 239★、h-encore 1109★、VitaShell 1550★、Adrenaline 1712★、GePatch 387★） | curl **200** |
| 装完后的收尾 | VitaDeploy / `vitasdk/vdpm`（271★，最新 v0.1.6 2026-08-28） | `gh api` |
| 自制软件目录站 | `rinnegatamante.eu/vitadb/`（VitaDB-Downloader 304★）、`robin994/NeoVitaDB-Catalog`（push 2026-10-07）、`VegettoSan/PSVitaAlive`（push 2026-10-09） | 全部实测可达/在更 |

**已经死透、别再引用的**：`TheOfficialFloM/Relaax`（**两种拼法都 404**）、`theflow0.github.io`（404）、
`psvitabrain.com`（**DNS 都解析不了**）、`henkaku.website`（502）、GBAtemp wiki 的 `Henkaku_Latest` 页（**404，页面已没了**）、
`dev.wololo.net`（502）。

也就是说：**2019–2023 那批教程里"打开 Relaax 网页点一下"的第二步，今天整条都不存在了**，
入口换成了 `jailbreak.psp2.dev`。这就是为什么"抄旧教程"在这个领域是负资产。

`hacks.site` 本机 curl 仍是 **000**（TLS 层失败，和 `gnu.wtf`、`portmaster.io` 同一类本机网络问题，**不代表站点死亡**）→ 保持 **UNVERIFIED**。

### 3.5 Vita 这一侧"成品"从哪拿：本库已落地的五个，以及为什么另外两个没有

| 已落地（`04-游戏资源库/爆款收录/`） | 文件 | 大小 | 上游有没有给 sha256 | 要不要自备数据 |
|---|---|---|---|---|
| `vit_vitashell/VitaShell.vpk` | 官方 release 的 `.vpk` | 1.9 MB | **UPSTREAM_ABSENT**（作者不发 digest，只能自算） | 否 |
| `vit_adrenaline/Adrenaline.vpk` | PSP 运行时 | 0.4 MB | UPSTREAM_ABSENT | **要**：必须自备 PSP 官方固件文件 |
| `vit_toolchain/vitasdk-…-2026-05-24.tar.bz2` | 官方 autobuild（Windows） | 91.1 MB | **OK**（和上游 digest 逐字节对上） | 否 |
| `vit_henlo_src/HENlo-master.zip` | HENlo **源码**快照 | 19 KB | LOCAL_ONLY（zipball 无上游 digest） | 否 |
| `pp_trax/TRAX.1.0.0.zip` | **TRAX 1.0.0**（PSP + Vita 音乐播放器，r/PSVita 2026-10-09 那条） | 12.8 MB | **OK**（上游 digest 逐字节对上） | 否（但**仓库无 LICENSE**，属"免费分发"不是开源 → 只本地自用） |

**两个刻意的"没有"**：

1. **Vita 上的 `.vpk` 大多不在 GitHub Releases**。自制软件的真实集散地是 **VitaDB**
   （`rinnegatamante.eu/vitadb/`，curl **200**）和它在 GitHub 上的目录快照
   （`robin994/NeoVitaDB-Catalog` push **2026-10-07**、`VegettoSan/PSVitaAlive` push **2026-10-09**）。
   所以要"最新最全"就得走 VitaDB 那条线，GitHub 只能给你**作者自己发了 release 的那部分**。
2. **HENlo 的成品 `20.bin` / `374.bin` 我没有替你去第三方站抓**。
   `vita.hacks.guide` 的做法是**让你在设备浏览器里打开 `jailbreak.psp2.dev` 现场注入**——
   注入页本身由作者控制，我从别的域名搬一份 `.bin` 回来，等于把来源链换成不可信的。
   所以我只收了**源码快照**（上面那 19 KB），要跑请照 §3.4 的正版入口。

**⚠ 一条要防的"消息与仓库错位"（本轮实测，Adrenaline）**：日报 2026-10-09 收到 GBAtemp 帖
`Adrenaline now releases nightly builds`，另外还能搜到 `Adrenaline v8.0.0 Release`（r/vitahacks）这类标题。
但**官方仓库这一侧我逐项测过**：`TheOfficialFloW/Adrenaline` 1712★、最后推送 **2024-01-13**、
`releases?per_page=8` 里**最新仍是 v7（2020-09-22，1 个资产）**、分支只有 `master`、
`.github/workflows` 目录 **404**（也就是**这个仓库里没有 nightly 的 CI 可言**）。
→ **v8 / nightly 的发布位置我这轮没实测到，标 UNVERIFIED**（大概率在作者的 Discord 或别处），不编。
本库那份 `vit_adrenaline/Adrenaline.vpk` 就是官方 **v7** release 的那枚资产，而且
**包内 `sce_sys/param.sfo` 根本不带版本号**（`APP_VER` = `00.00`，Adrenaline 自己管更新）——
所以**别指望从文件名或包内元数据判断新旧**，"下到的到底是哪版"只能靠台账里记的 `repo + tag`。
这也是我给登记表加 `tag` 列的原因（port0r 的 Switch 版同样不在 `latest`，见 §5.5）。

---

## 4. 开源掌机这条线（你的 XF45V 就在这里）

**最有用的一条实测结论：上游 ArkOS 已经 14 个月没动，活跃的是 clone 分支。**

| 仓库 | stars | 最后推送 | 判定 |
|---|---|---|---|
| `christianhaitian/arkos`（上游 ArkOS） | 2151 | **2025-08-01** | **基本停更** —— 旧教程里"去上游提 issue/下最新包"已经不成立 |
| **`lcdyk0517/arkos4clone`** | 739 | **2026-10-08** | **活跃**，RK3326 克隆机主线；本机（XF45V）走这条。它的 `dtbTools` 页面是机型适配要点 |
| `christianhaitian/dArkOS` | — | 2026-09-23 | 活跃（本库已 clone，516MB） |
| `AeolusUX/ArkOS-R3XS` | 1597 | 2026-06-09 | R3XS 分支，有自建 Pages 站 |
| `southoz/dArkOSRE-R36` / `djparentx/dArkOSen-R36S` | — | 2026-05-01 / 2026-10-01 | 社区改版，后者还在动 |
| `christianhaitian/PortMaster`（初代） | 705 | **2024-02-03** | **已停** —— 现役是 **`PortsMaster` 组织**（`PortMaster-Info` = `ports.json` 清单、`PortMaster-GUI`、`PortMaster-Website`，本库三个都 clone 了） |
| `EmuELEC/EmuELEC` | 2920 | 2026-10-08 | **活跃，但只给 Amlogic 芯片**（`description` 明写 retro emulation for Amlogic devices）。**跟 RK3326 无关，别混** |
| `shauninman/MinUI` | 1465 | 2025-11-27 | 活跃；RG35XX 系首选 |
| `OnionUI/Onion` | 4290 | 2026-02-07 | 脚本层/工具集，Pages 站活着 |
| **`batocera-linux/batocera.linux`** | **3250** | **2026-10-10** | **活跃 —— 我上一轮写"Batocera 不在 GitHub"是错的**，原因纯粹是我把仓库名猜成了 `batocera.linux/batocera` 拿到 404。下载页 `batocera.org/download` curl **200**；旁边还有 `batocera-linux/batocera-emulationstation` 440★ / push 2026-10-10。GitLab 只是历史镜像，**首发源在 GitHub**。 |
| **`JustEnoughLinuxOS/distribution`（JELOS）** | 945 | 2024-05-08 | **已死，且是"整组织归档"级别的死**：`archived=true`，该 org 名下仓库**全部** `archived=true`。更要命的是 `jelos.org` 现在返回 **200**，但 `<title>` 是 **"Synthetic Autonomic Mind - AI Tools for macOS & Linux"** —— 域名已易主/被抢注，**跟掌机再无关系**。凡是给出 `jelos.org` 链接的教程一律作废。 |

**muOS 我上一轮说"没定位到 org 名"，这轮定位到了**：org 是 **`MustardOS`**（GitHub 上仓库名很朴素，所以按 "muOS" 搜关键词搜不到本体）：

| `MustardOS/*` 仓库 | stars | 最后推送 |
|---|---|---|
| `MustardOS/internal` | 114 | **2026-10-10** |
| `MustardOS/frontend` | 77 | **2026-10-10** |
| `MustardOS/theme` | 103 | 2026-08-21 |
| `MustardOS/extra` | 18 | **2026-10-10** |

镜像**不在 GitHub Releases**（该 org 不发 release），官方下载页 `https://muos.dev/release` curl **200**（36 KB），
页面里是 `/release/current/2601_1` + `/release/archive/2403_0 … 2410_3` 这类版本号目录 —— **要找新固件就盯 muos.dev，别盯 GitHub**。

**ArkOS 这条线的"下架"细节（本轮实测，值得记住）**：

- `christianhaitian/arkos` 最新 release 标签是 `v2.0.07.31.2025`，`assets` 数量 = **0**。**GitHub 上没有镜像可下**，
  上游只给 wiki + Google Drive 链接。所以"去 ArkOS 的 GitHub Releases 下载"这种教程话术**现在连点都点不到**。
- 对比：`christianhaitian/dArkOS` 最新 release `v08272026` 有 **29 个 assets**（**dArkOS 走的是 GitHub Releases，ArkOS 上游不走**）。
- `JustEnoughLinuxOS/distribution` 调 `releases/latest` 直接 **404**（一个 release 都没有）。

**掌机侧的"移植游戏"首发**：清单是 `ports.json`（`PortsMaster/PortMaster-Info`，push **2026-10-10**）
+ 官网 `https://portmaster.games`（curl **200**；`portmaster.io` 是 **000**，别再写它）。
现役组织 `PortsMaster` 里活跃的几个：`PortMaster-Info`（清单，2026-10-10）、`PortMaster-GUI`（**284★，2026-10-07**）、
`PortMaster-Themes`（2026-10-08）、`PortMaster-Website`（2026-10-05）；`PortMaster-Releases` 停在 2024-09-09。
本库已落地 **632 个包 / 21.32 GB**（548 个开箱能玩、84 个仍需自备数据），
详见 `04-游戏资源库/公版与开源游戏/ports全量合法池/README.md`。
其中 77 个 `availability=free` 的补件已经开做：**能免登录直连拿到的 5 项抓进了 `04-游戏资源库/公版与开源游戏/免费素材/`（201.8 MB，逐项 sha256）**，
剩下 72 个卡在 itch.io —— 它的免登录下载链（`?download` 页取 `csrf_token` + `upload_id` → `POST download_url` → 拿回 `/download/<token>`）**最后一步只返回 200 的 HTML 中转页，不回文件体**，
所以那 62 个必须由人在浏览器里点；逐端口清单和"该放哪个目录"写在 `免费素材/README.md`。

**`harbourmaster`（设备上的 ports 安装器）本轮实测结果有点尴尬，如实写**：
官方文档页 `portmaster.games/harbourmaster.html`（**200**）里的链接仍指向 `github.com/kloptops/harbourmaster`
（21★，`archived=false`），但该仓库 `pushed_at` = **2023-09-10**、`releases.atom` 最新一条是
**"PortMaster Public Beta v8.4.1"（2023-09-09）**；PyPI 上的 `harbourmaster` 包名 **404**；
文档里引的 `raw.githubusercontent.com/kloptops/Portmaster-misc/main/releases/050_kloptops.source.json` 现在 **404**。
→ 结论：**安装器的实际发布通道已经不在那个仓库了**，能确认的活跃代码在 `PortsMaster/PortMaster-GUI`
（里面带 `do_muos_release.sh` / `do_trimui_release.sh` / `do_x86_64_release.sh`，即按系统分别出包）。
**本库 `04-游戏资源库/爆款收录/hh_harbourmaster/PortMaster.zip` 里的就是这张 2023 网的产物**
（解压后 `PortMaster/version` = `8.4.1`，473 个条目）—— 所以**别把它当最新版**：
设备上真正在跑的 `hm` 由系统镜像自带并自己更新，版本只会比这份新。要用就 `hm` 命令走起，别拿这份 zip 去覆盖。

**论坛/社区**：GBAtemp 的掌机分区（403 是反爬，站点活着）、`r/ArkOS`/`r/Anbernic`/`r/RetroHandhelds`
（curl 到 subreddit 页面 **200**，订阅数**未实测**）、厂家论坛（ANBERNIC/Powkiddy 官方站）、
以及 B站机型 UP 主的实机视频。Discord 是这几条线的**真实首发地**（固件更新通知、nightly 链接常只发在群里），
但 invite slug 我**没一个能实测确认**（除 `EmuELEC/EmuELEC` 的 repo description 合法写着 `discord.gg/jQWCFwTn5T`），
其余一律标 UNVERIFIED，你自己从官方站点页面点进去。

---

## 4.5 怀旧机型这条线（PS1/PS2/3DS/Wii/Wii U/DC/FC/街机/PS3/FPGA）—— 2026-10-10~11 两轮补的

你原话是"开源掌机 怀旧机型 PS1 PS2 SWITCH 3DS PSV FC 等等"。**上一版这里确实是空的**：
47 个源几乎全压在 Switch/Vita/掌机固件三条线上，PS1/PS2/Wii/DC/FC/FPGA 一条都没有。
现在 **156 个启用源**（2026-10-14 实测：93 GitHub `.atom`（54 releases + 32 commits + 7 条作者级活动流）+ 17 Reddit + 11 GBAtemp 版块 + **7 个国外论坛** + 21 家媒体/站点（含 itch 与 RHWeekly） + **4 个 YouTube 频道流** + 3 个中文源；
登记表共 **220 行**，另 **64 行**是实测够不着或点名拒用的，每行 `note` 带 `http` 码与条数；
10-11 那轮补的是 `gh_skycraft`，10-13 两轮补的是 **Switch 移植作者的 release 层**（见 §1.1.5）与**国内外论坛穷举层**（见 §1.3.5），10-14 这轮补的是**移植层项目本体的发布流**（马克思佩恩 1 / openRW / mgs_reversing / gtasa_vita / Descent 3 rebirth / ScummVM / OpenRA，见 §5 末尾与 `01-教程库/移植原理/00-移植是怎么回事_小白完全教程.md`），按机型分好了（表在 `06-资讯监控/README.md` §二）。这一节只记**补源过程中实测出来的硬事实**，
因为每一条都推翻了一个"看起来很合理"的仓库名。

### 仓库名会搬走，旧名字直接 404

我按直觉写的第一批 URL **五个是 404**，全部靠 `gh api` 现搜才找对：

| 我以为的 | 实测 | 现役 |
|---|---|---|
| `Luma3DS/Luma3DS` | **404** | **`LumaTeam/Luma3DS`**（6765★，push 2026-09-04，最新 release 2026-04-02） |
| `ArtemZar/melonDS`、`melonDS/melonDS`、`melonDS-aurora/melonDS` | 全 **404** | **`melonDS-emu/melonDS`**（5097★，最新 release 2025-11-18） |
| `flycast-emyn/flycast` | **404** | **`flyinghead/flycast`**（2582★，push 2026-10-10） |
| `Snes9x-Project/snes9x-cat`、`mame/mame`、`Nearinfinity/Gambatte`、`ps2dev/ps2libretro` | **404** | Snes9x 正源是 **`snes9xgit/snes9x`**（3356★，但**最新 release 停在 2024-07-07**）；Gambatte 走 libretro 侧 `libretro/gambatte-libretro` |
| `hacks-guide/Guide_PSP-PSX-PS2` | **404** | 该 org 根本没有这条线。列一下它到底有什么（`gh api orgs/hacks-guide/repos` 实测）：`Guide_3DS` 1865★/2026-10-01、`Guide-WiiU` 184★/**2026-10-09**、`Guide_Wii` 125★/2026-10-01、`Guide_Vita` 206★/2026-04-15、`MSET9` 108★/2026-09-25、`Guide_Panda` 31★/2025-03-18（**这条我上一版写错了**：它不是"新机种"，`gh api` 实测描述原文是
"A complete guide to Panda 3DS custom firmware, from stock to boot9strap." —— 是 **Panda 3DS 仿制机**的 CFW 教程），**另外 `Guide_WiiU-OLD` 53★/2020-05-06、`Guide_Switch-OLD` 42★/2020-05-03 是冻结件**，名字带 `-OLD` 的一律别当现行 |

**结论**：这类"某个主机场景"的仓库，org 名一搬家，旧教程里链接就全成 404。
加源时**必须先 `gh api repos/<候选>` 拿一次 200**，别拿记忆写表。

### GBAtemp 的分版块 RSS 是现成的，但 PS1/PS2 没有版块

`https://gbatemp.net/forums/<slug>.<node>/index.rss` 实测**全部 200**（节点号从首页 HTML 里
`grep -oE '/forums/[a-z0-9-]+\.[0-9]+'` 取，不是我编的）。条目数**按版块大小分两档**，这点要说清楚，
不然你会以为每个源都给你 30 条：

- **30 条**：`nintendo-3ds.199`、`sony-psp.44`、`nintendo-wii.105`、`nintendo-wii-u.245`、
  `nintendo-switch.283`、**`nintendo-switch-2.776`**（新版块，移植消息多在这）、
  `sony-playstation-3.219`、`sony-playstation-4.251`、`sony-ps-vita.215`、`smartphones-tablets-handhelds.194`
- **只有 5~6 条**：`retro-portables-fan-club.423`（复古掌机版）—— 而且**同一版块两次测出 6 条和 5 条**，
  因为它给的是"最近更新的主题"，会随时间漂。**所以别把条目数当站点健康度看**。

**但导航里根本没有 PS1/PS2 独立版块**（只有 PS3/PS4/PS5/Vita/PSP）。这两条线的论坛层是 `psx-place.com`，
而它实测 **403**（Cloudflare，站点活着，纯 curl 拿不到条目）→ 已作为 `enabled=0` 行登记在表里，
所以：**PS1/PS2 的场景消息目前只能靠 GitHub 那一层覆盖**（`stenzek/duckstation` 10806★ push 2026-10-10 是 PS1 线最活跃的源，
但它的 `LICENSE` 实测是 **CC BY-NC-ND 4.0**（`gh api repos/stenzek/duckstation/license` 首行就是
Attribution-NonCommercial-NoDerivatives 4.0）—— **这不是开源**：可以自己用，不能二次分发、不能演绎，
所以将来真要收它的包，口径和 `TRAX` 一样按"作者公开发布的成品包，本地自用"记，别写成"开源"）；
PS2 线是 `ps2dev/ps2sdk`+`ps2toolchain`+`israpps/FreeMcBoot-Installer`+`israpps/BDMAssault`）。

### `old.reddit.com` 是个陷阱，别换过去

`www.reddit.com/r/<sub>/.rss` 经常 429/403，看着像死了。我试过换 `old.reddit.com`：它回 **200**，
但正文是 327 KB 的 **"Welcome to Reddit" HTML 反爬页**，条目数 **0** ——
**比 429 更危险，因为它长得像成功**。所以 Reddit 一律留 `www`，
脚本里新增了 `html_not_feed` 状态专门点名这类"200 但给的是 HTML"。

同理 `r/retrogaming` 这类大版首跑就 429，`r/3DS` 首跑 200 —— 都是瞬态 IP 限流，隔时段重跑能补回来。

### 复刻硬件（FPGA / Analogue Pocket）是独立的一条线，别混进"破解"

`MiSTer-devel/Main_MiSTer` 3298★ push 2026-10-09、`neil-morrison44/pocket-sync` 962★ **feed 最新 2026-10-10**、
`mattpannella/pupdate` 1378★。这条线的"新消息"是**核心更新**（今天 MiSTer 提交里就有 `Add X-Gunner lightgun support`），
跟破解/移植是两个生态位，但都是"怀旧机型资源"，你既然点名了就一起盯。

### 2026-10-11 又补了四条，并且核出一件影响整条 Vita 线的大事

补的源（每条都是先 `curl` 拿 200/条目数再登记）：

| id | 源 | 实测 |
|---|---|---|
| `gt_ps3` | GBAtemp PS3 版块 `sony-playstation-3.219` | `200 / 30 条`，回填 29 条进台账 |
| `gh_mame` | `mamedev/mame` 提交流 | `200 / 20 条`。**`mame/mame` 实测 404**，正源 org 是 `mamedev`；这条对口"街机/FC/世嘉"那一层 |
| `gh_psl1ght` | `ps3dev/PSL1GHT` 提交流 | `200 / 20 条`、326★、`archived=false`、push **2026-10-08**，`LICENSE` 首行 `Copyright (c) 2011 PSL1GHT Development Team` = **MIT**。论坛帖"PS3 开源 SDK 被复活并更新"核实为真 |
| `gh_xash3d` | `FWGS/xash3d-fwgs` 提交流 | `200 / 20 条`、2833★、push 2026-10-09。**`FWGS/xash3d` 仓库自己写着 DEPRECATED**，又是一次搬家。**但 `/license` 返回 404、根目录只有 README 且通篇不提许可** → 默认版权保留，**这条只当活动度监控，不进收录表** |

核出来的大事：**PS3 / PS Vita 的 PlayStation Store 要关了**。这条我按"转帖 → 一手"走完了一遍：
GBAtemp PS3 版块只是转帖，**一手来源是 PlayStation 官方博客 2026-07-01《An update on PlayStation Store for PS3 and PS Vita》**
（作者 Sid Shuman，Sony Interactive Entertainment Content Communications）。原文要点照抄：

- `PlayStation Store on PS3 will close in select markets starting this year, followed by global closures for PS3 and PS Vita next year.`
- 分地区时间表：`Mexico, Honduras, Nicaragua – … starting August 2026`；
  `Additional Latin American and Middle Eastern countries – … starting late 2026`；
  **`In all other countries, PlayStation Store on PS3 and PS Vita will close in July 2027`**
- 已购内容：**`players will still be able to download previously purchased content after the closing date for the foreseeable future`**
  —— 注意这句的措辞是 *for the foreseeable future*，**不是永久承诺**，所以别把它当"以后随时能重下"。
- 关闭理由（原文）：商店要转到新的商务/支付标准，PS3 与 PS Vita 已经撑不住这些更新。

**可达性也记一条（这次差点把我骗过去）**：同一篇博客、同一个 URL，
内置网页抓取工具**两次都 404**；`curl -L` 经 7890 代理第一次 200、第二次 **404**，随后**连试 5 次全 200 / 166 KB**。
那个 404 的响应体有 120 KB，是索尼自己的错误页，不是"页面不存在"的空响应。
→ **判可达性必须重试两三次再看，单次 404 什么都证明不了**；`ghacks.net` 这类二手媒体则是稳定 403（反爬）。
复核命令就是 §7 里那条 `curl -sS -L -A "Mozilla/5.0" <博客 URL>`。

对你的直接含义：**Vita 上"官方商店还能买"这条路有截止日期（中国大陆走"其余国家"那一档，2027-07）**，
买过的东西短期内还能重下、但没有永久保证 → `PSVitaAlive`、`VitaDB`、`NeoVitaDB-Catalog` 这几条源不是"锦上添花"，
是**在关门前把清单和可得性记录下来的备份窗口**。
自制侧链路（h-encore 装机、VitaShell 拷本地文件）**本来就不走商店**，所以不在这次关闭的影响范围里 —— 但别把它当成"商店关了我照样能拿到商业游戏"，那是两码事（见 §6）。
（这条超出 14 天窗口，所以按设计**只在台账里、不进爆款短名单** —— 这类"超窗但重要"的条目得手动捞，别指望筛选。）

### 今天这一天，新机型的源真的立刻出货了（不是我编的存量）

| 标题 | 出处 / 日期 | 判定（**已全部跑完四问，2026-10-11**） |
|---|---|---|
| `[RELEASE] Flycast Vita` by Rinnegatamante & Bythos | GBAtemp Vita 版 2026-09-29 | **已下载** `vit_flycast/Flycast.vpk`（4.9 MB，GPL-2.0，作者不发 digest → `UPSTREAM_ABSENT`）；DC 游戏备份与 flash ROM 自备 |
| `[Release] Mario Kart 64 3DS Port Complete` | GBAtemp 3DS 版 2026-10-10 | **只监控**：一手仓库 `Epic0522/MarioKart64-3DSPort-Complete`（20★，承接 EstebanPdN 的原移植，基座 SpaghettiKart）**未声明许可** —— `/license` 404 且根目录无 LICENSE/COPYING，`THIRD_PARTY_NOTICES.md` 自己写着尚缺全项目许可声明；README 要自备美版 `mk64.z64` |
| `[Release] The Legend of Zelda: Ocarina of Time N64 3DS Port` | GBAtemp 3DS 版 2026-10-10 | **拒收**：`Andresac90/OOT-64-3DS-Port` 未声明许可，**且把 zeldaret/oot 解包的原厂音频序列与对象模型 commit 进源码**（`assets/audio/sequences/seq_0.prg.seq` 655,296 B 等，与上游同名同大小）→ 连"只收源码"都不成立 |
| `[Release] Oddworld: Abe's Oddysse 3DS native port`（OP 自己把 Odyssey 拼错成 `Oddysse`，我照原样引） | GBAtemp 全站 2026-10-10 | **只监控**：帖内唯一外链是 `aliveteam.github.io`（上游 R.E.L.I.V.E.），**端口一手仓库查不到**（6 组 `gh` 搜索 + 作者名 `YaTupoyDebil` 用户页 404），页面内无附件无直链；上游 `AliveTeam/alive_reversing` 同样未声明许可 |
| `PCSX2-Wii Alpha` | GBAtemp Wii 版 2026-10-08 | **已下载（源码）** `wii_gekko2_src/Gekko2-main.zip`（5.6 MB，GPL-3.0）—— 实测该仓库 **releases=0、tags 空 → 成品根本没发布**，所以只能收源码自编；README:62 要自备 PS2 BIOS 放 `sd:/pcsx2/bios/` |
| `rpcs3 allegedly being ported to ps4` | GBAtemp PS4 版 2026-10-07 | **只监控**：只有二手新闻 `en.gamegpu.com`（Cloudflare 403，3 次 curl + WebFetch 都读不到正文），搜不到任何 rpcs3-on-PS4 仓库；措辞是 "allegedly"，当消息看 |
| `[RELEASE] PS4 RetroArch Port (Unofficial)` | GBAtemp PS4 版 2026-09-20 | **只监控**：GitHub 仓库 `releases=0`，东西挂 **mega.nz 网盘** → 给不出上游哈希，按网盘包红线不收；且已停更 |
| `Anbernic Is Cloning the Nintendo 3DS Next, Minus the 3D` | Time Extension 2026-10-09 | 硬件新闻，不进收录流程；和你 XF45V 的选购线有关，记在 §4 |

这八条，再加上 2026-10-11 那节补的 `Xash3D FWGS PS3`（**一手仓库实为 `Mayo1970/xash3d-fwgs`，README 首行 xashPS3、32★、非 fork；
FWGS/xash3d-fwgs 官方 28 个分支里没有 ps3**；tag 1.5 有 5 个带 sha256 的 `.pkg`，但 `/license` 404 且根目录无 LICENSE → **未声明许可，只监控**。
注意别和上游 **`FWGS/xash3d` 本体混了 —— 那个是 GPL-3.0**，"没有许可"只指 fwgs 那个分支仓库），
一共 **九条** —— 它们是 §5.5 那套四问（有一手仓库？许可？要不要自备数据？成品挂在哪个 tag？）的**待判队列**。
**这九条现在判完了；同一轮另加了 20 多条新线索一起判，判定表在 `06-资讯监控/大作判定.tsv`（2026-10-14 现 39 行，逐条带文件级证据），
落到本地的东西见 `04-游戏资源库/爆款收录/`（现 42 组 / 65 个文件 / 815.7 MB）。**
2026-10-11 下午又把这轮剩下的 **4 条"待判定"全部判完，表里现在待判定=0**，见下面 §4.6。

### 判定轮里新出现的三条"大作登陆 Switch/3DS/PS4"，以及一条被我自己纠正的话

同一天里 GBAtemp 又冒出几条更符合你需求的标题（作品+平台+动词同现），它们现在都进了专线清单：

| 标题 | 帖子号 | 判定与依据 |
|---|---|---|
| `[Release] Model2 NX 1.0 (experimental) – Sega Model 2 emulator for Nintendo Switch` | 685198 | **已下载** `sw_model2nx/model2nx.nro`（52,561,935 B，上游 digest 逐字节相符 → `OK`）；街机 ROM 自备 |
| `[Release] SuperModel NX - Sega Model 3 arcade emulator for Nintendo Switch` | 684935 | **已下载** `sw_supermodelnx/supermodel.nro`（10,729,888 B → `OK`）；`spdx` 回 `NOASSERTION` **不等于没许可** —— LICENSE 699 行正文写着 Supermodel is distributed as free software under the terms of the GNU General Public License |
| `[RELEASE] DXX-3DS - Descent 1. Stable mono and experimental Stereo3D build` | 683116 | **已下载** `n3ds_dxx3ds/d1x-3ds-2.1.1.cia` + `.3dsx`（两个都 `OK`）；许可是 **D1X-Rebirth License**（`COPYING.txt` 首行原文），它内含 Parallax 原始授权"grants a royalty-free, perpetual license … for non-commercial, royalty or revenue free purposes"——**许可本身就允许非商业自用**；我一度把它写成"GPL-2.0 系"，那是错的，已按正文改掉 |
| `ioQuake3-PS4` | 681529 | **已下载** `ps4_ioquake3/` 5 个 `.pkg`（68.2 MB，5/5 与上游 digest 相符），GPL-2.0 |
| `ioQuake3-PS3` / `-Wii` / `-PSP` | 681321 / 681264 / 683804 | **全部已下载**：同一个作者 `Mayo1970` 的 4 个 ioQuake3 移植都是 **GPL-2.0**，release 资产**逐个带上游 digest**。PS3 = tag 2.0 的 5 个 `.pkg`、Wii = tag 1.3.3 的 5 个 zip、PSP = tag 1.5 的 3 个 zip —— 13 个文件**全部 sha256 OK**；`pak0.pk3`（商业）自备，OpenArena/TeamArena 数据本身自由授权。**PS3 仓库 README 有张五行变体表**（原文 *"Five builds are produced from the same source tree"*）：主包 / OpenArena / Team Arena / Quake 3 Classic（协议 43，能和 DC 跨玩）/ **`ef` = Star Trek Voyager: Elite Force**；同页原话 *"You need to bring your own `.pk3` files — none are included in this repo"*。Wii 那 5 个 zip 每个里面就 `boot.dol`+`ICON.PNG`+`meta.xml`（丢 HBC 的 `apps/`），PSP 那 3 个是 `EBOOT.PBP`+一个 `PLACE_YOUR_PAK_FILES_HERE.txt` |
| `[Release] ScummVM for WiiU` | 684813 | **已下载** `wiiu_scummvm/` aroma + rpx 两包（29.3 MB，2/2 `OK`）；GPL-3.0（`COPYING` 实测 674 行完整 GNU GPL v3 正文），纯引擎不含游戏数据 |
| `Sonic Adventure 2 (XBOX 360 Ver.) - Switch Port` | 685092 | **源码已下载**（`sw_sa2nx_src/sa2-nx-main.zip`，`ChanseyIsTheBest/sa2-nx`，LICENSE 正文 GNU GPL v3）；**成品 `sa2.nro` 拒收** —— 那是把原厂机器码重编译进二进制的产物，不是作者有权分发的东西 |
| `Zelda The Wind Waker GC - Switch Port` | 685126 | **源码已下载**（`sw_wakerhd_src/SwitchWakerHD-main.zip`，`centollOS/SwitchWakerHD` 71★，MPL-2.0）；HD 版成品仍未收（v0.4.3 zip 是把游戏静态重编译进二进制的产物 → 只收源码）。**⚠ 这一条我上一版写错了**：当时断言"帖标题写 GC 版系误传、只有 HD 版"，2026-10-11 下午把 685126 原帖与同作者 dev update 帖 685220 的外链都抓下来对过，**两个帖都同时链 `SwitchWaker`（GC 反编译）与 `SwitchWakerHD`（Wii U 静态重编译）两个仓库，GC 版是真的** → 已订正并补收 GC 版源码（见 §4.6） |

### 4.6 2026-10-11 下午的补判：四条"待判定"清零（含一处我自己的错判要订正）

上午那轮判定表里剩 4 条 `待判定`（09:30 的判定任务没赶上当天 15:24 那轮新出的两条），现在逐条走完 §5.5 的四问：

| 线索 | 载体（实测） | 许可 | 要不要自备数据 | 判定 |
|---|---|---|---|---|
| `[Wii U] Sonic CD (2011) — Updated Port`（GBAtemp 帖 685222） | `vbarros22/RSDKv3-Decompilation`（RSDKModding 的 fork，1★，push 2026-10-10）tag **wiiu-1.3.3-beta1** 唯一资产 `SonicCD-WiiU-1.3.3-Beta1.zip` **2,967,039 B**，上游 digest `sha256:15384233e378` → 入账 **`OK`** | `LICENSE.md` 首行 **`# RSDKv3/v4 DECOMPILATION SOURCE CODE LICENSE v2`**（1,610 B；`spdx` 回 `NOASSERTION` 只因为它是自定义许可，**不是没许可**）：允许复制/修改/公开分发，条件=预编译包默认关 DLC、禁商用、双向署名、**不得分发游戏素材** | **要**：帖内原话 *"No commercial game assets are included. You must provide your own legally obtained `Data.rsdk`"*，放 `SD:/SonicCD/` | **已下载成品**（`wiiu_rsdkv3_soniccd/`）。拆包实测只有 3 个成员：`wiiu/apps/SonicCD/RSDKv3.wuhb` 2,973,024 B + `README-WiiU.md` 4,281 B + `LICENSE.md` 1,632 B，**零原厂素材**；仓库 tree 206 blob / 4,023,957 B，最大是 `wiiu/tv.png` 934,243 B（作者自绘的 Wii U 按键说明图） |
| `Zelda Wind Waker & Wind Waker HD Switch ports: 60fps, Touchscreen`（dev update 帖 685220） | **两个仓库**：`centollOS/SwitchWaker`（GC 反编译，34★，非 fork）+ `centollOS/SwitchWakerHD`（HD 静态重编译，71★，源码快照上午就在库内） | SwitchWaker = **MIT**（`LICENSE` 1,117 B，正文首行 `MIT License`，第二行 `Copyright (c) 2026 Pulpparty and depende3000 and the SwitchWaker contributors`） | **要**：`INSTALL.md` 原话 *"the download holds the program only"*，要自备 USA **`GZLE01` rev0 未压缩 ISO（1.4 GB）**；`THIRD_PARTY.md` 原话 *"the repository contains no asset, executable or data file of the game"* | **已下载源码**（`sw_switchwaker_src/SwitchWaker-main.zip` **10,176,443 B**，`LOCAL_ONLY`）；**release 成品不收**：tag v0.3.0 的 `SwitchWaker-v0.3.0-switch.zip` 9,489,582 B 与 `.zip` 10,189,883 B 虽然都带上游 sha256，但那是把风之杖反编译码静态编进二进制的游戏衍生体，与 `sw_wakerhd_src`/`sw_sa2nx_src` 同线；作者自己也写 *"Please don't share HD builds, as they contain code generated from your disc"* |
| `4rd Strike (Street Fighter III: 3rd Strike hack) running on MiSTer`（Reddit r/MiSTerFPGA `1x26um9`） | `Stegosaur982/4rd-strike-mister`（2★，非 fork，push 2026-10-10，仓库总大小 **6 KB**）：tree 只有 2 个文件 —— `Street Fighter III 4rd Strike.mra` **7,155 B** + `README.md` 870 B。**发的是 MRA 补丁描述文件，不是 ROM 转储** | **未声明许可**（`/license` 实测 `lic=null`） | **要**：Jotego 的 CPS-3 核心只吃你自己 dump 的原版街机 ROM | **只监控，不下载** —— 三条都独立成立：未声明许可（和 685070/683374 同一条规矩）、releases=0 且 tags 空（没有成品载体）、跑起来仍要自备 ROM。仓库本身干净，所以**不属于** §6 那种"夹带原厂素材"的拒收类。评论区一条实用事实（u/neoak）：**这个 MRA 已经进 Arcade Offset 发行包的 `update_all`**，想试不用手动抓文件 |
| `Remove port/linux/game/cache_file_formats.c.orig, a merge leftover`（`BirchWoodGod/halo-ce-vita` 提交 `14e681e2`） | 该仓库就是 §3.2 血缘表里那条 Vita 原生 LibGxm 基座，**已从 59★ 涨到 61★，push 2026-10-11** | **GPL-3.0**（`/license` spdx） | **要**：README 明写不含专有游戏数据，自备 Xbox 版 `maps` 目录 + `default.xbe` | **已下载（走的是上午那份源码快照 `halo_birch_src/halo-ce-vita-main.zip` 28,354,053 B，`LOCAL_ONLY`）**。这条 ARR 本身只是合并残留清理，没有新载体。**⚠ 一个会变的位置**：该仓库**现在已经有 release 了**（v1.0.3 → **v1.1.0-beta.3**：`halo.vpk` 4,678,468 B、`HaloCEVitaInstaller.exe` 50,550,607 B、两个 linux server tar、`SHA256SUMS`，全部带上游 digest），`.vpk` 属静态重编译成品，按上面同一条规则**不收**；另外 tree 今天已长到 7,364 blob / **115,412,395 B**（比我们的快照大一倍，主要是 `config/relocs.json` 12.3 MB 与 `research/` 那批反编译元数据）→ 要更新快照得先手动删掉本地那个 zip 再跑 `scene_dl.py`，否则幂等闸门会跳过 |

**这轮把一条本来就藏在既有判定里、但没写成文字的规则挑明了**（是我从 `sw_wakerhd_src`/`sw_sa2nx_src`（不收成品）与 `sw_port0r`/`ps_srb2ps4`/`hh_nxstation`（收成品）这两组既有结论反推出来的口径，不是你的要求）：
**成品收不收，看它是"通用引擎/播放器/模拟器/前端"还是"某一款游戏的重编译体"** ——
前者运行时读你自备的数据，二进制里没有那款游戏的程序码（Sonic CD 的 `RSDKv3.wuhb`、port0r、NXStation、ioQuake3 各包都属这一类）；
后者二进制本身就是原厂程序码翻译出来的产物（风之杖 GC/HD、SA2、Halo CE 的 `.vpk`、《索尼克 2006》的 `MarathonRecomp.nro`），按 §6 只收源码。
这条口径已经写进上面四条的 `note`，下次判同类帖子不用再猜。
**⚠ 2026-10-14 我自己违反过一次并当场退回**：判 Marathon（GBAtemp 帖 682907 → `ChanseyIsTheBest/MarathonRecomp-NX`）时只看见 `GPL-3.0` + 上游自述"不含素材"，
就把 tag `1.0.3` 那枚 61,419,106 B 的 `.nro` 当成品收了（上游确实给了 digest，verify 还能对上），复核才认出它和 27/28/29/38 是同一条静态重编译路线 ——
**已删文件、`收录台账.tsv` 从 66 行退回 65 行、登记表改写成 `sw_marathonrecomp_src`（`kind=source`，4,115,248 B，LOCAL_ONLY）、判定表 payload 跟着改指向、`--relabel` 重算**。
**判据补一句**：许可条款与"不含素材"两件事都不能替代"二进制里装的是谁的代码"这一问（另见 `交接稿-项目目标与现状.md` §六 口径 15）。

**★ 2026-11-03 口径变更（用户明确覆盖，本节 §540 那条归纳作废为"默认档"）**：上面"静态重编译体只收源码、成品不收"这句，
**出处是我（助手）2026-10-11 从既有条目反推的归纳，本文件当时就注明了"不是你的要求"**。2026-11-03 用户点名要求改掉这条"错误口径"并授权批量下载成品包，
所以现行为：**重编译体的 release 成品包可以下载并本地自用**（首批落地在 `06-资讯监控/PS5移植商店/成品包/`，逐件记 sha256 与解包复检）。
**仍然成立的两条硬边界是用户自己定的，不是我的归纳**：① 不批量抓取商业 ROM/BIOS 全集（2026-10-02）；② 不下载泄露源码（2026-10-12，GTA V 两轮 dump）。
**新增一条风险分界（用户已知悉）**：下回来自己用与把它发出去是两件事——成品包进视频、网盘、群或任何分发渠道，性质从"自用"变成"分发"，
那是 §4.6 里 Take-Two 对 GTA5 Switch 移植发律师函、以及 Nintendo 一贯的打击面。**要出节目就用屏幕录制与讲解，不外发二进制。**

---

### 4.7 晚上补的一条：你问"哪个开源项目能把 MC 放进各种游戏里"

答案是 **`chasmlol/SkyCraft`**（不是模拟器、不是重制，是**把两个正在运行的游戏对接起来**）：

| 实测项 | 结果 |
|---|---|
| 仓库 | `chasmlol/SkyCraft`，开仓 **2026-09-30 16:40Z**，最后一次 push 2026-10-01；**11 天 1172★ / 87 fork**，主语言 C++ |
| 许可 | **MIT**（`/license` 回 `MIT`，`LICENSE` 首行 `MIT License`、`Copyright (c) 2026 chasmlol`） |
| 机制 | **Skyrim 侧一个 SKSE 插件 + Minecraft 侧一个 Fabric mod，两边走共享内存**（`protocol/skycraft_protocol.h` 22,602 B）。MC 在后台隐藏跑自己的物理/方块/物品栏，**老滚负责渲染整个世界**（`skse/src/WorldRender.cpp` 146 KB）。两个游戏都没被重写 |
| 仓库干不干净 | tree 实测 **137 个 blob**，最大的非源码文件是 `docs/screenshot.jpg` 389,411 B 和 `gradle-wrapper.jar` 47,505 B —— **Bethesda/Mojang 的资源一个都没有** |
| 成品 | tag `v0.1.2`（2026-10-01）3 个资产：`SkyCraft-0.1.2.zip` 25,111,237 B、`skycraft-fabric-0.1.2.jar` 247,869 B、`-pdb.zip` 23,210,521 B。**前两个都带上游 `sha256` 且逐字节相符 → 已入账 `OK`**，pdb 那个用 `filter` 排掉了 |
| 包内实测 | 外层 5 个成员（`SkyCraft.dll` 4,036,608 B + 内层 `SkyCraft-Minecraft.zip` 23,953,382 B + `THIRD-PARTY-NOTICES.md` + `LICENSE.txt` + `SkyCraft.ini`）；内层 52 个成员 / 解压 51.3 MB，**全是 Prism Launcher 未修改便携构建(GPL-3.0) + Fabric API 0.161.0(Apache-2.0) + e4mc(MIT) + Qt6 运行库**，最大三个是 `Qt6Core.dll` / `prismlauncher.exe` / `Qt6Gui.dll`。**没有 MC 也没有老滚的文件**，游戏本体首次运行才由 Prism 从官方源下 |
| 你要准备什么 | 正版 Skyrim SE/**AE 1.6.x-1.7.x**（作者在 1.7.104 上测，1.5.97 与 VR 不行）+ SKSE64 + Address Library + **拥有 Java 版的 Microsoft 账号**；额外约 3 GB 内存、1.5 GB 磁盘。README 建议装 Alternate Start，因为开场海姆登是重脚本、容易卡死 |

**"放进各种游戏"这一波是怎么冒出来的**：SkyCraft 本体只管老滚，但它开源（MIT）之后一周内社区就 fork 出一堆换宿主的移植，
我逐个在 GitHub 上点过（星数都还很小，别当成熟方案）：`Boom64dude/MarioCraft`(超级马力欧64，**"Built on SkyCraft"**)、
`mrborghini/libertycraft`(GTA IV，**"SkyCraft port"**)、`IvanSobolev/GTASaCraft`(GTA SA)、`Rom4203/BotwCraft`(旷野之息/王国之泪)、
`Duocor3/minepunk`(赛博朋克2077)、`YllariSang/CrafterHunter`(怪物猎人 世界/Linux)、`justbustin/minecraft-crossover-bridge`(MHW+艾尔登法环，Apple Silicon 走 CrossOver)、
`aeironnsarmiento/PeakCraft`(PEAK)、`SawyerTheNerd/Minecraft-X-HalfLife`(半条命)、`Gmoney8129/Fallout-Craft`(辐射4)、
`cabcrab/Granny-Minecraft-Passthrough`、`aanananahwllans-cloud/CrashCraft`(古惑狼1)、`CS-LX/MCInBlender`(在 Blender 里玩)。

**发布链记一下（这条线原来不在我监控的源里，是这次现搜到的，现已挂成第 96 个源）**：作者发 GitHub release → 中文/短视频层由
TikTok 系列 *"Play Minecraft Inside Other Games"*（作者署名 Riphy）和 YouTube 教程（"I Put Minecraft Inside Skyrim (FULL GUIDE)"）带起来 →
TikTok 的搜索页会把这一系列聚合成合辑。**换句话说：这类"游戏 A 里能玩游戏 B"的东西，首发一定在 GitHub，火起来在短视频，论坛（GBAtemp）反而滞后**。
**已经挂进 `源登记表.tsv` 了（2026-10-11 22:26，用户点头后加的）**：`gh_skycraft` =
`https://github.com/chasmlol/SkyCraft/releases.atom`，`enabled=1`。当场跑了一遍生产脚本 `scene_monitor.py` 验收，不是纸上写写：
`http=200 解析=3 新增=3`（v0.1.0 / 0.1.1 / 0.1.2 三个 tag 全回填进台账，且都被粗筛标成 `HOT`），台账 1885 → **1953** 条（同一轮里
其他源还补回了 65 条上一版被 429 挡掉的 Reddit 帖）。**`flag_arrival` 是空的**——release 标题只有版本号，凑不成"作品名+登陆动词+平台名"三者同现，
所以不进《大作登陆平台.md》；这正是想要的行为：母项目自己发版不算"大作登陆某平台"。以后每天 08:30 那轮会自动盯新版本，
新 tag 一出现就进日报；但要收到 `爆款收录/` 还需要人工过四问、往 `合法收录登记表.tsv` 里写带证据的 `filter`（见 §5.5 的判别法）。
**衍生移植仓库（3DS/PSVita/Switch 那几个）不在这个 feed 里**——它们是别人另开的仓库，只能人工搜（清单见上）。

## 5. GTA 5 on Switch：完整核实时间线（我上一轮的话要修正）



上一轮我说"不实/系炒作"。**这话下得太粗，你指出得对 —— 移植是真的存在过。**
精确版本是这样：

| 日期 | 事件 | 证据 |
|---|---|---|
| 2026-06-07 | GitHub 组织 `Paralympics-Productions` 注册 | `gh api orgs/…` |
| （期间） | 作者 **Mojso / Paralympics Productions** 做 Switch + Android 原生移植，并公开挑衅 Rockstar | IGN 2026-09-30 报道标题即 `Modder Taunts Rockstar … Gets Cease-and-Desist from Take-Two` |
| **2026-09-06** | B站玩機社发「没错！Switch玩上GTA5了！！」，简介点名 Paralympics Productions 与 we1zard.com | 视频元数据实测 |
| **2026-09-28 / 09-29** | **Take-Two 发律师函**，作者宣布"Paralympics Productions 10 月 3 日关停"；**官方不再发布可下载文件** | Kotaku 2026-09-29、Notebookcheck 2026-09-28、tribune.com.pk 2026-09-29 |
| 2026-09-25 / 09-28 | 社区衍生工具**仍在推**：`Geekmaxxer/GTA5NX-MG-Menu`（push 2026-10-09，简介直接挂 buzzheavier 文件站链接） | `gh api` |
| 2026-10-02 | `niceboat0/GTA5-Switch-Toolbox` 建档（README 全中文：DLC 管理、.nsc 脚本 mod、内置 MEGATARD **汉化**、画质预设、5 个进度存档 4%~100%） | `gh api` + README 原文 |
| 2026-10-04 | `Geekmaxxer/GTA5-NSPDRepack-GUI`（GPL-3.0，`hacpack`+`hactool` 把 `.nspd` 目录重打包成可安装 NSP，`prod.keys FW 21.2.0`） | 同上 |
| 2026-10-09 | `gabryboy12-ai/Theft4-NX`（GTA4 Switch 移植的坑位争夺，5★） | 同上 |
| **2026-10-10 建仓 / 10-13 仍在 push** | **另一条线：Apple 平台的 `c22dev/muguet`**（★569，GPL-3.0，release `0.1` 只有一个 9,018,552 B 的 `muguet-macos-arm64.zip` = wasmtime+wgpu **纯加载器**，不含任何游戏内容）。README:5-6 自述跑的是 `game.wasm` 并明写 *"It's basically the same source as the web port."*，:13 *"Because I care about me not getting sued, you will need your own copy as a `.zip`"* | `gh api repos/c22dev/muguet`（stars/push/created）+ `releases/latest` + README 原文逐行 |

**⚠ 这一条要把 §5 上面那句"移植是真的存在过"补一个限定**：Rockstar **从未**发布过 GTA V 的网页版 / WASM 版，
所以 `game.wasm` 这条链的起点只能是 2023-12-24（约 4 GB）与 2026-09-18（约 192 GB）两轮**泄露源码**的编译产物。
`muguet` 自己的代码是 GPL-3.0 且不含素材，但**它跑的东西来路不干净 ⇒ 本库不收、不下、不镜像**，
已在 `06-资讯监控/源登记表.tsv` 里登记成 `gh_muguet_refuse`（`enabled=0`，note 带实测 `http=200 解析=1`）——**可达但要点名拒用**。

**所以正确的判定是三句话**：
1. 移植**真的能跑**（Title ID `0100b00b51230000`，mod 装到
   `/atmosphere/contents/0100b00b51230000/romfs/update/update.rpf`（约 900MB）与 `update2.rpf`（约 700MB）——
   这套目录结构是社区工具箱 README 里写的，机器可读、可核对）。
2. **官方分发被律师函掐死**：作者从未把包放到公开仓库（`Paralympics-Productions` 组织 **0 个公开仓库**，实测）。
3. **社区 repack 还在继续**（`.nspd → NSP` 的重打包器、工具箱、mod menu 的推送日期**晚于**停摆日）。

→ 你要找的"发布在哪"，答案是：**代码和工具在 GitHub；游戏本体在网盘/文件站/私有群**。
后者我不搬，理由见 §6。顺带修正我自己的记录错误：上一轮我把这篇报道记成 `shattered.io`，
**实际是 Kotaku / Notebookcheck**（`shattered.io` 是 WPA3 攻击项目，不是新闻站）。

---

## 5.5 判别法落地：今天日报里四条爆款，逐个判完（可照抄的四步）

§0 那张分层表是原理，这一节是**同一条流程在 2026-10-10 当天的四次实跑**。
每条都问同样的四个问题：**①有没有一手仓库 ②许可是什么 ③要不要自备游戏数据 ④成品挂在哪个 tag**。

| 日报标题（都是 GBAtemp/Reddit 2026-10-09~10） | ①一手仓库（`gh api` 实测） | ②许可 | ③数据 | ④判定 |
|---|---|---|---|---|
| **Sega Rally（1995 街机）on Switch**：full 16:9、HD 材质、10 个 mod、回放、联网榜 | `jacquesdupontd/port0r` **51★ / push 2026-10-10** | **`null`**；README 原文 *"The app's own source code is not public for now: this repository holds the releases, the guide and the issue tracker."* | **要**：SWITCH.md L62-63 原文 *"**Your own** Sega Rally Championship arcade files, made for **MAME 0.289**: `srallyc.zip` and `segabill.zip`"* / *"Port0r never includes them and never says where to get them."* | **收作者自己发的 release 成品**（Switch zip 10,808,632 B，上游 digest 齐），**街机 ROM 不碰**。⚠ Switch 版**不在 `latest`**（latest 是 Quest APK），在 tag **`switch-v0.5.3`** |
| **SRB2 ported to PS4** | `iHaiDeeZ/SRB2-PS4` **1★ / push 2026-10-10**；上游 `STJr/SRB2` **567★ / GPL-2.0** | **GPL-2.0**（有 LICENSE 文件） | **不要**：README 明写 SRB2 2.2.15 官方免费数据（`srb2.pk3/zones.pk3/characters.pk3/music.pk3`）已在包内 | **收**（`SRB2-PS4-v01.02.pkg` 183,631,872 B，digest 齐）。四条里**法律位置最干净**的一条。灰区只有 SEGA 商标角色，两边 README 都声明不主张 |
| **Minecraft Legacy Console Edition 移植到 3DS** | **没有仓库**（UNVERIFIED）：OP *lightwo* 从 2026-03-20 开贴至今 *"I will go into details on technical features once I make a public release."*，第 4 页（2026-09-26）还在被追问"when are you gonna release it?"，主页 `lightwo.net` 是 5.7 KB 占位页 | — | — | **不收：只有帖子，没有资源**。"有讨论"≠"有下载"，这是第二种要挡掉的误报 |
| **Warnel Chawpiovs v1.7.x**（= "Marvel Champions" 变位词） | `frwololo/warnel-chawpiovs` **21★ / push 2026-10-10**（作者即 **wololo.net 本人**） | **`null`**（`/contents/LICENSE` → 404） | **不要**（包内 `README.txt` 原文 *"You might need an internet connection as the game attempts to download resource files in its first run"*，卡牌定义/卡面首次运行自行拉取） | **收 Switch 成品包**（26,962,274 B，digest 齐）。`WC.pck` 我逐路径扫过：2012 条 `res://`，图片仅 18 张且全是 `card_backs/card_shadow*.png`、`icons/checkbox_*.png` 这类通用 UI，**没有一张漫威卡面**。**卡牌数据不去镜像**（那是 FFG/Marvel 的内容） |

**这轮实跑暴露并修掉的两个真问题**（都已进代码，不是文档承诺）：

1. **只查 `releases/latest` 会"抓错平台还报成功"** → 登记表加第 10 列 `tag`，
   `scene_dl.py` 改成"填了 tag 走 `releases/tags/<tag>`，没填才用 latest"。port0r 就是这个坑的现行案例。
2. **复检闸门不区分"安装包容器"和"游戏数据"** → 自制 `.vpk` 被当成游戏数据点名（TRAX 那次）。
   现在 `.nsp/.xci/.pkg/.vpk` 按容器处理，**>200 MB 才升级到人判**，小的照样列出来（不静默跳过）。
3. **裸文件压根没被量过**（2026-10-11 才发现并修）→ `audit()` 里那句 `if not members: continue` 会把"解压不出成员"的
   `.nro/.pkg/.vpk/.bin` 全部跳过，等于**成品越大越不查**。补成"裸容器 >200 MB 进待判定、其余裸文件 >60 MB 进超大文件"之后，
   **生产脚本重跑当场点名 2 处**：`NXStation.nro` 77.0 MB、`SRB2-PS4-v01.02.pkg` 175.1 MB —— 两条都逐个给了依据（前者是 Apache-2.0 前端程序本体，后者是 GPL-2.0 且只含 SRB2 自家免费数据），
   但**"有依据"和"没检查"是两件事**，这就是把口径落成代码闸门的意义。

**顺带一个反面教材**（已作为 `enabled=0` 的靶子行登记在表里）：
`efimandreev0/minecraftpe-nx-ctr`（105★ / push 2026-06-03 / `license=null`）
—— release 里有商业 NSP（`Minecraft.PE.01b90fc1020b0000.nsp`，撞 `BAN` 黑名单），
更要命的是 `master` 树 `handheld/data/` 下实测 **232 个文件 / 3,402,645 B 原版 MCPE 素材**（含 108 个 sound）。
**商业游戏数据被直接 commit 进仓库**，所以这种连"只收源码快照"都不行。
拿它和 §3.2 的 `halo-ce-vita` 对照最清楚：**同样是用到商业游戏的移植，
一个作者主动 `exclude … extracted game data`，另一个把素材塞进仓库** —— 这一下就分辨出该不该收。

---

## 6. 边界：这份清单里我不动手收的东西

以下**只登记"它存在"，不收录链接、不代下、不写进任何脚本**：

- 商业游戏的 **NSP / XCI / VPK / pkg / 整合包**（含 GTA5 Switch 本体、任何".dump"）
  —— 注意：**`.vpk/.pkg/.nsp` 只是安装包容器，不是"商业"二字本身**。
  自制软件本来就装成 `.vpk`（VitaShell、TRAX），Switch 自制也就是一枚几百 KB 的 `.nsp`；
  **判据是"里面装的是谁的作品 + 体积和来源对不对得上一张商业本体"**，逐条判定见 §3.5 与 §5.5，
  脚本里的对应规则是"容器 >200 MB 才升级到人判"。
- **`prod.keys` / `merged_keys` / title key 转储、任何 NCA/游戏解密工具链（sigengine 一类）**
- **改存档与联机作弊**（Edizon、SysBot 系刷宝/RNG 机器人 —— 上面中文工具箱里就捆着 Edizon）
- 主机 **BIOS 合集包**（3.4 节那条 BIOS 需求总表 + 自提取路径是正解）
- 商业 ROM 全集（FC/SFC/GBA/PS1/NDS/3DS/PSP/Wii）

三条理由，都不是姿态问题：
1. **会烂**。DMCA 打击下的仓库几周就 404。本轮就撞见三个活例：`Relaax` 404、
   `halo-ce-universal` 改名成 `OpenCE`、`Xita-Project/xita` 关闭。**结构化工具和文档不会烂，链接会。**
2. **"自用"不是批量下载的免责基础**。个人使用的窄口径只覆盖"已购原件 + 自己 dump"。
3. **交付不了**。网盘包无哈希（we1zard 那条就是夸克网盘），我无法保证完整性，
   也没法在你机器上验证它没被改过。

想把卡装满的正解还是那一条：**自己 dump + 归位工具**
→ `04-游戏资源库/自己ROM放这里/README.md`（按文件头判平台、MD5 去重、落到 ArkOS 认识的 134 个目录）。
F 盘现在还剩 **2.001 TB**（2026-10-11 16:0x 复测 `df -B1 /f` 可用 = 2,001,013,383,168 B；总容量 3.0 TB、已用 999.2 GB），这部分容量是你自己能合法填的。
**别把这个数当本库账本**：本库自身实测只占 **48.09 GB（=44.78 GiB，122,560 个文件；剔掉 clone 仓库的 `.git` 内部对象后是 43.22 GB / 120,784 个文件，差的 4.87 GB 全是 git 历史）**，
所以"剩余容量比昨天少了约 41 GB"跟这里的监控/收录无关——今天 F 盘上动过的是库外的
`F:\录播工作区`（00:27 有写入）和会自己涨缩的 `F:\pagefile.sys`（5 GiB）。要清容量得去那边圈，不要动本库。

---

## 7. 复核命令（把本文数字全部重算一遍）

```bash
# 必须先设代理，匿名 api.github.com 在本机被共享 IP 打满（403）
export https_proxy=http://127.0.0.1:7890
GH=/c/Users/Administrator/.workbuddy/gh-cli/bin/gh.exe   # 已认证，有配额；不在 PATH

# 单个仓库的"活/死"三件套：stars / 最后推送 / 最新 release
for r in Atmosphere-NX/Atmosphere CTCaer/hekate ndeadly/MissionControl \
         ppkantorski/Ultrahand-Overlay WerWolv/Tesla-Menu eliboa/TegraRcmGUI \
         vitasdk/vita-toolchain isifire/halo-ce-vita BirchWoodGod/halo-ce-vita \
         christianhaitian/arkos lcdyk0517/arkos4clone EmuELEC/EmuELEC we1zard/Magic-Suite ; do
  printf "%-32s " "$r"
  $GH api "repos/$r" --jq '"push=\(.pushed_at[0:10]) star=\(.stargazers_count) lic=\(.license.spdx_id // "-")"' 2>&1 | head -1
  printf "%-32s " ""
  $GH api "repos/$r/releases/latest" --jq '"latest=\(.tag_name)@\(.published_at[0:10])"' 2>&1 | head -1
done

# 站点可达性（注意：403/000 的含义见正文，别当"站死了"）
for u in https://gbatemp.net https://wololo.net/feed/ https://switch.hacks.guide \
         https://wiki.switchroot.org https://switchbrew.org https://we1zard.com \
         https://vita.hacks.guide https://jailbreak.psp2.dev https://theofficialflow.github.io/ \
         https://muos.dev/release https://portmaster.games/harbourmaster.html https://batocera.org/download \
         https://www.reddit.com/r/ArkOS/ ; do
  printf "%-52s " "$u"; curl -s -o /dev/null -w "%{http_code}\n" --max-time 20 -A "Mozilla/5.0" "$u"
done

# 掌机这条线的四个"改名/易主"要点（§4 的数字就来自这里）
$GH search repos batocera --limit 3 --json fullName,stargazersCount,pushedAt      # 正名 batocera-linux/batocera.linux
$GH api orgs/MustardOS/repos --jq '.[]|"\(.name) \(.pushed_at[0:10]) \(.stargazers_count)"'   # muOS 的 org
$GH api repos/JustEnoughLinuxOS/distribution --jq '{archived,push:.pushed_at[0:10]}'          # true = JELOS 已归档
curl -s -A "Mozilla/5.0" -L https://jelos.org/ | grep -o '<title>[^<]*'                       # 域名已易主的直接证据
# release 资产数：ArkOS=0（GitHub 上没镜像），dArkOS=29，JELOS=releases/latest 404
for r in christianhaitian/arkos christianhaitian/dArkOS JustEnoughLinuxOS/distribution; do
  printf "%-34s " "$r"; $GH api "repos/$r/releases/latest" --jq '"\(.tag_name // .message) assets=\(.assets|length)"' 2>&1 | head -1
done
# harbourmaster 的"最后一版"证据（§4）：仓库 push 2023-09-10，release 8.4.1
$GH api repos/kloptops/harbourmaster --jq '"push=\(.pushed_at[0:10]) stars=\(.stargazers_count) archived=\(.archived)"'
curl -s -A "Mozilla/5.0" https://github.com/kloptops/harbourmaster/releases.atom | grep -o '<title>PortMaster[^<]*' | head -2

# §5.5 那四条爆款的判定，逐条重算
$GH api repos/jacquesdupontd/port0r --jq '"port0r star=\(.stargazers_count) push=\(.pushed_at[0:10]) lic=\(.license.spdx_id // "null")"'
$GH api repos/jacquesdupontd/port0r/releases/tags/switch-v0.5.3 --jq '"  switch tag=\(.tag_name) \(.assets|map("\(.name):\(.size) digest=\(.digest // "无")")|join(" | "))"'
$GH api repos/iHaiDeeZ/SRB2-PS4 --jq '"srb2-ps4 star=\(.stargazers_count) lic=\(.license.spdx_id)"'
$GH api repos/frwololo/warnel-chawpiovs/releases/latest --jq '"warnel \(.tag_name) n=\(.assets|length)"'
# 反面教材：商业素材是直接 commit 进仓库的（数一遍 handheld/data 下的 blob）
$GH api "repos/efimandreev0/minecraftpe-nx-ctr/git/trees/master?recursive=1" \
  --jq '[.tree[]|select(.path|startswith("handheld/data/"))|select(.type=="blob")]|"mcpe 仓库内素材 \(.|length) 个 / \(.|map(.size)|add) B"'
# Adrenaline：帖子说有 v8/nightly，官方仓库实测只有 v7（§3.5）
$GH api "repos/TheOfficialFloW/Adrenaline/releases?per_page=3" --jq '.[]|"  \(.tag_name) \(.published_at[0:10]) assets=\(.assets|length)"'
$GH api repos/TheOfficialFloW/Adrenaline --jq '"  push=\(.pushed_at[0:10]) branches 见下"'
$GH api repos/TheOfficialFloW/Adrenaline/branches --jq '"  branches: "+([.[].name]|join(","))'

# 移植项目"要不要自备数据"，永远读这一行
curl -s https://raw.githubusercontent.com/isifire/halo-ce-vita/master/port/vita/README.md | sed -n '1,20p'
# port0r / warnel 的数据条款也各读一行（§5.5 引的就是这两处原文）
curl -s https://raw.githubusercontent.com/jacquesdupontd/port0r/main/SWITCH.md | sed -n '60,66p'
unzip -p "04-游戏资源库/爆款收录/sw_warnel/WarnelChawpiovs_1_7_1_Switch.zip" "*/README.txt" | sed -n '1,20p'

# 监控层自己的数字（§4.5 的源数/台账数就从这里重算）
python - <<'PY'
import csv, sys, collections
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
rows = list(csv.DictReader(open("06-资讯监控/源登记表.tsv", encoding="utf-8"), delimiter="\t"))
en = [r for r in rows if r["enabled"] == "1"]
def kind(u):
    return ("reddit" if "reddit" in u else "gbatemp" if "gbatemp" in u
            else "github_atom" if "github" in u else "media")
print("登记表 %d 行 / 启用 %d 源" % (len(rows), len(en)),
      dict(collections.Counter(kind(r["url"]) for r in en)))
led = list(csv.DictReader(open("06-资讯监控/台账.tsv", encoding="utf-8"), delimiter="\t"))
hot = [r for r in led if r["flag_hot"] == "HOT"]
print("台账 %d 行 / 爆款 %d (%.1f%%) / 列数 %s"
      % (len(led), len(hot), 100*len(hot)/len(led), set(len(r) for r in led)))
arr = [r for r in led if (r["flag_arrival"] or "").startswith("ARR")]
print("大作专线 %d 条 / 判定分布 %s" % (len(arr), dict(collections.Counter(
      (r["flag_arrival"].split("|")[1], r["flag_arrival"].split("|")[2]) for r in arr))))
PY

# 专线判据本身：拿台账里的真实标题跑 arrival_of()，看方向有没有判反
py -3 -c "import sys;sys.path.insert(0,'_工具脚本');import scene_monitor as m,csv
for r in csv.DictReader(open('06-资讯监控/台账.tsv',encoding='utf-8'),delimiter='\t'):
    if (r['flag_arrival'] or '').startswith('ARR'): print(r['flag_arrival'],'<=',r['title'][:64])"

# 收录池的"产物级"对账：磁盘文件数必须等于台账行数，双向差集为空
py -3 -c "import os,csv
led=list(csv.DictReader(open('04-游戏资源库/爆款收录/收录台账.tsv',encoding='utf-8'),delimiter='\t'))
disk={os.path.relpath(os.path.join(dp,f),'04-游戏资源库/爆款收录') for dp,_,fs in os.walk('04-游戏资源库/爆款收录') for f in fs if not f.endswith(('.tsv','.md'))}
rec={os.path.relpath(r['dest'],'04-游戏资源库/爆款收录') for r in led}
print('磁盘 %d / 台账 %d / 只在磁盘 %s / 只在台账 %s'%(len(disk),len(led),sorted(disk-rec),sorted(rec-disk)))
import collections;print('verify',dict(collections.Counter(r['verify'] for r in led)))"

# 两条定时路活着没
powershell -NoProfile -Command "\$t=Get-ScheduledTask -TaskName 'Qoder_Handheld_DailyNews';\$i=\$t|Get-ScheduledTaskInfo;'\'+\$t.State+\' next=\'+\$i.NextRunTime+\' last=\'+\$i.LastRunTime+\' result=\'+\$i.LastTaskResult"
tail -20 "06-资讯监控/_schedule.log"        # 每个 run 块末尾必须有 exit=0；result=267009=正在跑，0=成功
# 10-11 新补的两条 SDK/引擎源，逐条验"活/许可"
$GH api repos/ps3dev/PSL1GHT --jq '"PSL1GHT star=\(.stargazers_count) push=\(.pushed_at[0:10]) archived=\(.archived)"'
$GH api repos/ps3dev/PSL1GHT/license --jq '"  lic=\(.license.name)"'          # 实测 MIT
$GH api repos/FWGS/xash3d-fwgs --jq '"xash3d star=\(.stargazers_count) push=\(.pushed_at[0:10])"'
$GH api repos/FWGS/xash3d-fwgs/license --jq '.message' 2>&1 | head -1          # 实测 Not Found = 没声明许可
$GH api repos/FWGS/xash3d --jq '"旧仓库: "+(.description|tostring)'            # 自标 DEPRECATED
# PS3/PSV 商店关闭的一手来源（内置网页抓取会 404，必须走代理 curl）
curl -sS -L -A "Mozilla/5.0" -o /dev/null -w "code=%{http_code} bytes=%{size_download}\n" \
  "https://blog.playstation.com/2026/07/01/an-update-on-playstation-store-for-ps3-and-ps-vita/"
```

**读法约定**：`push=` 日期决定这条信息还值不值得信；`releases n=0` 意味着作者不发预编译包，
那你看到的"下载"必然来自第三方；`403` 对 GBAtemp/Reddit 是 Cloudflare 反爬（站点活着），
`000` 是本机 TLS/代理层失败（**不是站点死亡**）。

---

## 8. 本库里与之衔接的既有文档

**本文负责"在哪里发布"，下面几份负责"每天自动抓 + 抓下来放哪 + 谁去判定"：**

- **`06-资讯监控/README.md`** —— **156 个启用源**的登记表（`源登记表.tsv` 共 **220 行** = 156 启用 + **64** 条点名拒用/实测够不着；93 GitHub `.atom` + 17 Reddit + 11 GBAtemp 分区 + **7 国外论坛** + 21 媒体/站点（含 itch、RHWeekly） + **4 YouTube 频道流** + 3 中文源）
  与 `_工具脚本/scene_monitor.py` 的用法；
  每次跑出一份日报，把 **爆款候选**（`HOT` 正则粗筛）、**大作/经典登陆平台**（`arrival_of()`，见下）和**需要人看的失败源**分列，失败不许静默跳过。
  本文 §1/§3/§4 里那些 `push=` / `releases n=` 数字，就是这套东西的输入。**§六 是两条定时路的说明与撤销命令。**
- **`06-资讯监控/大作登陆平台.md` + `06-资讯监控/大作判定.tsv`** —— 你要的那条专线：
  前者是累计清单（**2026-10-14 01:4x 现算 62 条**：已下载 21 / 只监控 16 / 待判定 23 / 拒收 2，列「作品 / 登陆到 / 从哪来 / 日期 / 原文链接 / 判定 / 本地资源路径」，已下载与可下排在最上面）；
  后者是**人工判定表**（39 行，`match→verdict→action→payload→note`），每条 note 里都要有文件级证据：帖子号→一手仓库→
  `gh api .../license` 的**正文首行原文**→要不要自备数据→成品挂在哪个 tag、多大、API 有没有给 digest。
  改完这张表跑 `py -3 _工具脚本/scene_monitor.py --relabel` 才会反映到前一份里（不联网、不改台账历史）。
  ⚠ **`--relabel` 不重写当天的日报文件**（2026-10-11 实测），要把日报里那段专线也刷成最新判定，得再跑一次完整抓取 `scene_monitor.py`（幂等，只补新消息）。
- **`04-游戏资源库/爆款收录/README.md`** —— 从日报里挑中后，用 `_工具脚本/scene_dl.py` 落地的**成品区**：
  登记表 47 条（启用 42 / 停用 5）→ **42 组 / 65 个文件 / 815.7 MB**，逐个带 `sha256_local` 与 `sha256_upstream` 双向对账（**OK 46 / LOCAL_ONLY 15 / UPSTREAM_ABSENT 4**），
  外加"解压看里面有没有游戏数据"的产物级审计（`复检.md`，**0 处**）。
  **收录台账 + 拒收理由**都在那份 README 里（nxStore 65 个 App 逐条分类、gta5_toolbox 无许可证、
  OOT-3DS 与 Sonic R PSP 属**仓库把原厂素材 commit 进源码**）。
- **`_工具脚本/盘点.py`** —— 离线"数数"：不联网，只按产物（`台账.tsv`/`大作判定.tsv`/`合法收录登记表.tsv`/`收录台账.tsv`/磁盘）重算上面那些数字并检查**磁盘与台账双向差集**。
  本文与根 README 里的"现 XX 条"**每次都以它的输出为准**；改完文档跑一遍它对账，别把文档里的旧数抄来抄去。
- **`_工具脚本/daily_run.py`** —— 定时入口，依次跑上面两个脚本，stdout/stderr 与退出码追加进 `06-资讯监控/_schedule.log`。
  Windows 计划任务 `Qoder_Handheld_DailyNews`（每天 08:30，不依赖 Qoder 开着）与 Qoder 定时任务
  `开源掌机·大作登陆判定与下载`（每天 09:30，负责把新的"待判定"走完四问并下载）都调它/围着它转。

**既有文档**：

- `04-游戏资源库/公版与开源游戏/PortMaster移植游戏指南.md` —— ports 装机细节（含 `availability` 四个字别再照字面读）
- **`01-教程库/移植原理/00-移植是怎么回事_小白完全教程.md`** —— **移植这条线的"是什么/为什么"层**：六条移植路线（官方移植 / 模拟器 / 引擎重实现 / 反编译重编译 / 包装原版可执行文件 / 只是补丁）的判据，
  为什么凡是合法移植都必写"请自备正版"（含 `GTAmodding/re3` 现在 HTTP **451 `block.reason=dmca`** 的一手响应），
  以及 GTA III/VC/SA/**V**、**Max Payne 1/2/3**、**合金装备** 的逐仓核实结论（哪些真能装在你这台 XF45V 上、哪些根本不存在、哪些是补丁不是移植）。
  本文 §1/§5 讲"在哪里发布"，那份讲"发布出来的东西属于哪一类、要不要自备什么"。
- `04-游戏资源库/公版与开源游戏/ports全量合法池/README.md` —— 632 包 / 21.32 GB 逐包清单与能否装的判定
- `04-游戏资源库/自己ROM放这里/README.md` —— 自建 dump 管道（本文 §6 的正解）
- `01-教程库/机型固件/XiFan_XF45V/00-XF45V完全指南.md` —— 你这台 1024×768 机器的机型差异
- `02-模拟器库/已clone仓库/README_inventory.md` —— 已落地仓库总账（`_工具脚本/gen_inventory.sh` 重生成）

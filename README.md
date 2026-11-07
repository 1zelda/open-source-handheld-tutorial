# 开源掌机教程库

一个本地知识库:**教程 + 模拟器 + BIOS + 游戏资源 + 机型资料**,并为 C++ 学习路线准备了可直接阅读的源码。

根目录另有一篇 **`Switch-PSVita-掌机_破解与移植发布源指北.md`**:Switch / PS Vita / 开源掌机三条线的
**发布源分层清单**(GitHub release / 指南站 / 论坛 / Reddit / Discord / 中文渠道)、Switch 破解逐步解释
(每一步在硬件层面干了什么)、GTA5-on-Switch 与 Halo-on-PSV 两条传闻的核实时间线,以及"X 能玩 Y"标题的真伪判别法。
里面每个数字都是 2026-10-10 用 `gh api`/`curl` 现场拉的,复核命令附在文末。

## 目录结构

```
01-教程库/          入门选购 / 机型固件(NGP45HT + R36S + R36MAX2 + XiFan_XF45V 四篇完全指南,外加通用刷机流程)/ 模拟器配置 / 移植原理 / 踩坑排查 / C++学习路线
02-模拟器库/        前端与系统、按平台的 core 推荐、已 clone 的 53 个仓库源码 + 系统镜像
03-BIOS库/          各平台 BIOS 需求总表、自制提取路径、校验方法、按平台放置区
04-游戏资源库/      homebrew 自制 / 公版开源(PortMaster 清单与起手包)/ 自己 ROM 放这里 + 合法下载索引
                    + **下架抢救/**(2026-10-20 新增:"会被立即下架"的珍贵资源的抢救落点 —— 源码 tarball / 页面快照 / git 裸库,带 sha256 台账)
05-硬件与机型资料/  机型支持表、**逐机型屏幕真值表(解析 dtb 得出)**、安卓与 Win 掌机对比、文件传输记录
06-资讯监控/        **228 个发布源的登记表**（共 316 行，另 88 行点名拒用或实测够不着，每行带 http 码） + 每次运行生成的资讯日报（含**「今日聚焦」段**：按 Switch移植/Vita/开源掌机固件/模拟器核心/引擎重实现/PortMaster/FPGA/中文源/源码泄露九个主题分档）与去重台账(爆款候选自动粗筛)
                    + **大作登陆平台.md**(专线累计清单) + 大作判定.tsv(人工判定,带文件级证据)
                    + **下架抢救登记表.tsv**(24 行,盯"会被立即下架"的珍贵资源) + **抢救日志.md**(逐轮记录)
                    + **PortMaster端口快照.tsv / PortMaster新端口.md**(167 个上游端口清单的每日比对,新端口/换版即时可见)
07-移植工厂/         **游戏→设备流水线(v0.2 函数级研发)**:原有接单/配方/封装内核+
                    PE32 静态分析/AI 收件箱与本地模型接口/持久化预算/受限IR转C/原指令差分;
                    研发不依赖真机;函数样本通过不等于整款游戏移植完成
08-数据看板/        **本地只读网页台**(纯 Python 标准库,不联网):把 22,105 条资讯 + 8 张游戏台账(2,909 行) +
                    8 张仓库/成品台账(620 行) + 07-移植工厂的 SQLite 状态(10 张表 7,957 行,只读打开) +
                    124 份本库自写文档 + 网盘登录现状(6 个上传档位 / 88 条上传台账)现读现切在一个页面里(八个页签);
                    只读:不写台账、不生成副本、库读完 sha256 不变(WAL 旁文件 -shm/-wal 是 SQLite 机制,非写入);
                    唯一例外是「网盘」页签:全站只收 POST /api/netdisk/action 这一条写路径,绑到非回环(--lan)时自动拒写;
                    另有一条只读 GET /api/netdisk/shot?driver=&slot=(把某个登录位的扫码窗口转成 PNG 给本页,非回环 403、窗口没开 503);
                    网盘页 connect 127.0.0.1:5244 探 OpenList 在不在,账号明细由 _工具脚本\网盘账号台.py 现算,
                    cookie/token/密文一律不读不输出(自测里有假账号库探针专门盯这条)。
                    启动:`py -3 08-数据看板/看板.py`(默认只听 127.0.0.1:8090)
                    登录网盘:`py -3 08-数据看板/start_netdisk.py`(或双击同目录 `启动网盘账号台.bat`)
                    = 拉起 OpenList + 看板并打开「网盘」页签;选盘 + 选「登录位」(每个盘 10 格,一格一个独立 profile/端口)→
                    点「▶ 打开扫码窗口」→ 手机扫码 →
                    看板服务端每 15 秒自己巡一遍在听的窗口(网页关着一登录也照收),扫上就自己抓 cookie、向网盘验身、
                    按账号 ID 尾巴起名入库并挂载并探测,收完把那一格窗口关掉;
                    多账号靠换格子登,在同一格重扫同一个号是更新凭据、不会顶掉别的号(11-05 实测:
                    日常浏览器里登着的号捞不过来,新版 Edge/Chrome 的 cookie 是 App-Bound/v20,DPAPI 解不开);
                    手填表单收在折叠区,只给百度/迅雷这种 OpenList 不吃 cookie 的盘用
                    自测:`py -3 08-数据看板/自测_看板.py`(182 项断言,期望值现从台账/SQLite 自己数);
                    成品包独立核对:`py -3 _工具脚本/核对_PS5成品包.py`(不走看板代码,walk 磁盘逐文件算 sha256)
09-刷机工具/        **刷机要用的二进制本体**(顶层 11 条目/展开 18 文件,全部带字节数与 SHA256):
                    瑞芯微 FactoryTool v1.81 + USB 驱动 v5.1.1(在稀范官方 rar 里)· Rufus · balenaEtcher · rpi-imager ·
                    USB Image Tool · SD Card Formatter · 7-Zip · RKDevTool ·
                    `dtbselect/`(RK3326 与 RK356X 两份,Actions 产物,嵌套 zip 三层哈希)·
                    台账与"哪个工具治哪一步":`09-刷机工具/README.md`
_工具脚本/          bios_check.py · dtb_peek.py · dtb_panel_sweep.py · gen_inventory.sh ·
                    refresh_clones.sh · portmaster_r36s_index.py · portmaster_starter_dl.py ·
                    portmaster_bulk_dl.py(全量合法池,MD5 逐个校验+断点续传)·
                    portmaster_data_audit.py(逐包审计"要不要自备游戏数据")·
                    gen_ports_pool_readme.py(从台账+审计表生成池 README)·
                    gen_rom_dirs.py(从 es_systems.cfg 抽 ROM 目录表)· rom_sort.py(自己的 dump 归位+去重)·
                    dl_akos4clone.sh / dl_xifan_xf45v.sh(断点续传下载器)·
                    **scene_monitor.py(拉 228 个源 → 资讯日报 + 去重台账 + 大作登陆平台.md;
                      arrival_of() 要求"作品名+登陆动词+平台名"三者同现并按动词位置判方向,
                      扫 URL 前先挖掉 base36/楼层号/sha 三类 ID 段(2026-10-20 修掉 ES-DE 帖被误判成 GTA 的假命中);
                      产品名 MiSTer 大小写敏感 + 非 GitHub 源过 NEG_COMMERCIAL 商业娱乐噪音闸门;
                      每条另打 flag_focus 主题标签,日报出「今日聚焦」段;
                      --relabel 可重算爆款/大作/聚焦标记而不动历史; --dedupe 只用来清并发写重复的行)**·
                    **rescue_watch.py(下架抢救层:登记表 24 项目标存活检查 + GitHub 雷达盯 ≤30 天新镜像 +
                      131 个已挂源存在性巡检 + 下架新闻挖链接;活着就立刻抓源码/页面快照/git 裸库镜像;
                      "消失"判定必须 gh api 与 curl 双轨确认,404/451 才算 —— 实测拦住一次 godotengine/godot 误报;
                      --watch 7200 循环模式 = 抢救窗口期的真正频率;幂等,连跑三轮抓取量 0)**·
                    **ports_watch.py(PortMaster 新端口发现层:每天比一次上游 167 个端口的 git trees,
                      新文件=新端口、sha 变=换版,只发现不下载;已标出 103 个本地池还没有的候选;
                      命名归一化后才比得上 —— 本地池小写带点 vs 上游 Title Case 带空格,实测踩过)**·
                    **scene_dl.py(按"合法收录登记表"抓上游 release 成品,双向对 sha256;每次跑完自动做扫包复检;
                      只有 --only <id> 与 --dry-run 两个参数,没有 --audit)**·
                    **daily_run.py(定时入口:上面两个一起跑,日志落 06-资讯监控/_schedule.log)**·
                    **free_assets_dl.py(抓 ports 那 77 个 needs_free 端口里"能免登录直连拿到"的免费素材;
                      只认 DIRECT 白名单里的官网直链与 GitHub 源码快照,先写 .part 再算 sha256;
                      幂等:已存在且哈希相符就跳过,--check 离线复算不联网。 itch.io 的 62 个不在里面,原因见 免费素材/README.md §三)**·
                    **netdisk_upload.py(经本机 OpenList 往夸克/百度/迅雷推产物的上传器;档位清单在 网盘上传清单.tsv,
                      台账在 06-资讯监控/网盘上传/网盘上传台账.tsv;凭据不写进本仓库,管理员密码只从环境变量读;
                      真传之前先往那一档丢 1 字节探针问让不让写,不让写就整档拦下、一个字节不动、台账里也不留 FAIL——
                      11-06 实测两个夸克号都退回 capacity limit,而它报的 use_capacity 在 NORMAL 号上是坏的,数字不能当闸门)**·
                    **网盘账号台.py(多账号凭据保管台,无界面的逻辑模块:看板「网盘」页签 import 它,
                      扫码和手填两条路都汇到它这一个写入口;DPAPI 加密写 F:\OpenList\账号库.json,
                      存下即挂载即探测,返回值只有白名单元数据 + 整本密文长度,值一个不给;
                      自带 selftest 与 qr 子命令,一键拉起见 08-数据看板\启动网盘账号台.bat)**
```

## 本地已有多少东西(2026-10-11 复测;上一版是 2026-10-02)

**单位说明**:以前这里混着写"GB",实际是按 **GiB(1024³)**算的。这次两个单位都写出来,别再猜。
复测口径:`os.walk` 逐个 `os.path.getsize` 求和(整库跑完约 103 秒,只读元数据)。

- **已 clone 源码:53 个 git 仓库**(今天用"数 `.git` 目录"重数过,仍是 53)+ 1 份手工存档,
  **13.44 GB(十进制)= 12.52 GiB**(不含下面那堆系统镜像)
  分类:R36S/XF45V 专用 17、模拟器与核心 15、工具与 ROM 管理 6、homebrew 源码 6、掌机固件与启动器 5、文档与清单 5。
  明细与上游地址、最近提交日期:`02-模拟器库/已clone仓库/README_inventory.md`(重生成:`bash _工具脚本/gen_inventory.sh`)
  更新方法:`bash _工具脚本/refresh_clones.sh`
- **系统镜像:27 个文件 / 56.56 GB(十进制)= 52.67 GiB**(2026-11-05 用 `os.walk` + `os.path.getsize` 现数,不含该目录的 `README.md`)
  覆盖 4 台机器:**R36S / R36MAX2 / XF45V(RK3326)与 NGP45HT(RK3562)**;
  里面是 ArkOS4Clone 20260930+20261008、dArkOSen 0930+1031、ROCKNIX 20260901/20261101(a、b 档)、
  AURKNIX RK3326 CI 20261021 + RK3562 CI 20261021 与 nightly 20260918、厂家稀范官方 R36MAX2/XF45V 包(TF 与 eMMC 各二)、
  第三方中文魔改 EmuELEC、PAN4ELEC。
  每个文件的字节数、SHA256、校验来源分档(【API-digest】/【作者.sha256】/【官方 .sha256】/【仅本机】)、
  分区表与 BOOT 目录解析结果,以及"这台机器能不能用"的逐行判定:`02-模拟器库/已clone仓库/系统镜像/README.md`
- **刷机工具:顶层 11 个条目、连 `dtbselect/` 子目录展开共 18 个文件**(2026-11-05 现数),含瑞芯微线刷两件
  (FactoryTool v1.81 + RK-USB-DriverAssitant v5.1.1,都装在稀范官方 `Flash-Guide.tool.rar` / `Flashing.software.rar` 里)、
  Rufus / balenaEtcher / rpi-imager / USB Image Tool / SD Card Formatter / 7-Zip / RKDevTool,以及从 Actions 产物取的
  `dtbselect`(RK3326 与 RK356X 两份,嵌套 zip 的三层哈希都记着):`09-刷机工具/README.md`
- **PortMaster 端口包本地池:632 个 zip / 目录合计 21.32 GB(十进制)= 19.86 GiB**(`04-游戏资源库/公版与开源游戏/ports全量合法池/`;上游官方清单 167 个 / 2.1 GB 每天由 `ports_watch.py` 比对,新端口与换版写 `06-资讯监控/PortMaster新端口.md`,**103 个上游有、本地池没有**的候选已逐个标出),
  目录里另有 3 个 `README.md` / `_download.log` / `_manifest.tsv`,别把它们当包数)
  632/632 逐个按上游 `source.md5` 重算校验、0 不符;逐包"要不要自备游戏数据"已审计成表:
  **548 个开箱能玩**,84 个要补素材(其中 77 个素材免费可得,来源链接在表里) ——
  `04-游戏资源库/公版与开源游戏/portmaster_自备数据审计.tsv`
- **免费素材补件区:`04-游戏资源库/公版与开源游戏/免费素材/`** —— 上面那 77 个 `needs_free` 里**能免登录直连拿到的都抓完了**:
  5 项 / 201,753,942 B = **201.8 MB(十进制)= 192.4 MiB**,逐项 sha256 记在 `免费素材台账.tsv`,幂等复跑与离线校验用
  `py -3 _工具脚本/free_assets_dl.py`(`--check` 只复算不联网)。真正能当"补件"的是 4 项(canabalt-hf / evilegg / lastscenario / thecurseofissyos,198,986,003 B),
  第 5 项 retsend 实测是**Rust 源码快照不是运行物**(该端口本来 "Ready to Run",不需要补数据)。**剩 72 个为什么没自动化**:itch.io 免登录直链实测死路
  (token 链只回 200 HTML 中转页),逐端口的手动清单 + 该放哪个目录都在 `免费素材/README.md`
- **爆款收录成品区:42 组 / 65 个文件 / 815.7 MB(十进制)= 777.9 MiB**(2026-10-14 01:47 与 01:59 两轮 `盘点.py` 现算，逐项一致),
  逐个带 `sha256_local`/`sha256_upstream` 双向对账 —— 最近一轮 `scene_dl.py` 复跑对过:**磁盘 65 个 payload 与台账 65 条 dest 完全一一对应,双向差集为空**;
  校验分布 **OK 46 / LOCAL_ONLY 15 / UPSTREAM_ABSENT 4**,扫包复检 **0 处疑似游戏数据 / 2 处超大文件 / 5 处已判定容器**(超大仍是 NXStation.nro 77.0 MB 与 SRB2-PS4.pkg 175.1 MB,两条都逐个给了依据)。
  本轮新落地两条:**风之杖 GC 版反编译源码** `sw_switchwaker_src/SwitchWaker-main.zip`(MIT,10,176,443 B,LOCAL_ONLY)与
  **Sonic CD (2011) Wii U 移植成品** `wiiu_rsdkv3_soniccd/SonicCD-WiiU-1.3.3-Beta1.zip`(自定义 RSDK 反编译许可,2,967,039 B,与上游 digest 逐字节相符 → OK;拆包只有 `.wuhb`+README+LICENSE,零原厂素材)
  22:18 又补了**用户点名问的那条**:`pc_skycraft/`(SkyCraft 0.1.2 成品,SKSE 插件 4.04 MB 的 dll + Fabric mod jar,**两个都对上上游 digest → OK**)与
  `pc_skycraft_src/`(源码快照 MIT,1172★/11 天) —— **SkyCraft 就是"把 Minecraft 塞进各种游戏"那条线的母项目**(SKSE 插件 + Fabric mod 走共享内存,
  MC 后台跑逻辑、老滚负责画);拆开验过包内**零原厂素材**(只有 Prism Launcher GPL-3.0 便携构建 + Fabric API Apache-2.0 + e4mc + Qt6),所以成品敢收。
  衍生移植(SM64/GTA IV/GTA SA/旷野之息/赛博朋克/MHW/PEAK/半条命/辐射4/古惑狼/Blender)列在 `04-游戏资源库/爆款收录/README.md` 第 40-41 项下面
  **2026-10-14 补的第 42 项**:《索尼克 2006》X360 版静态重编译的 Switch fork `ChanseyIsTheBest/MarathonRecomp-NX`(GPL-3.0) —— **只收源码快照** `sw_marathonrecomp_src/MarathonRecomp-NX-main.zip`(4,115,248 B,LOCAL_ONLY),
  这条**先收错成 61 MB 的 `.nro` 成品再退回**,退回全过程与判据写在上面那个口径段和 `04-游戏资源库/爆款收录/README.md` 第 42 项下面
- **本库 Markdown 文档:303 篇**(不含 `02-模拟器库/已clone仓库` 自带的 **811 篇**;全库一起数是 **1114 篇**)
  —— 2026-10-14 03:0x~03:3x 现算,**四条独立路径互相印证同一个数**:生产脚本 `_工具脚本/盘点.py`(03:33 那轮 = 1114)、
  Python `os.walk` 分类计数(1114 = clone 811 + 本库 303)、GNU `find . -type f -iname '*.md' -not -path '*/.git/*'`(clone 811 / all 1114)、
  两份路径清单逐行 `diff` 为 **0 行差异**。`盘点.py` 在 03:06 那一轮打的是 **1113**(少 1 篇),同一棵树 03:33 重跑就回到 1114 ——
  当时正有三个全树遍历并发跑,`os.walk` 对读不了的目录是静默跳过的,所以**单次遍历的总数不可信,要以多路径一致为准**。
  上一次记录 294/811/1105 已过期。**+9 篇的去向逐条对上**(不是估的):本轮在 `01-教程库/移植原理/` 下真正新建 3 篇
  (`01-代码级解剖…`、`02-交叉编译与打包…`、`动手实践/README`;该目录的 `README` 与 `00-…小白教程` 在上一轮 01:38 那次数里已经有了),
  另外 6 篇是解包 `orktes/max_arm64` 源码快照带进来的 `_scratch/port_code/max_arm64-main/{README,TODO,port/md/×4}.md`(现查 `find _scratch/port_code -iname '*.md'` = 6)。
  **本库 303 篇的分布**:01-教程库 253 / 03-BIOS库 12 / 04-游戏资源库 11 / `_scratch` 11(工作稿与解包件,不算教程正文)/ 06-资讯监控 8 / 02-模拟器库(非 clone)3 / 05-硬件与机型资料 2 / 根目录 3。
- **全库磁盘占用:48.09 GB(十进制)= 44.78 GiB**,122,560 个文件(2026-10-11 16:0x 实测)。分项:
  02-模拟器库 25.60 GB(121,251 个文件)/ 04-游戏资源库 22.48 GB(756 个文件)/ 其余六个目录加根目录文件合计只有 **5.65 MB**(553 个文件)
  **口径**:这个数字**含 clone 仓库的 `.git` 内部对象**;同一份文件树**剔掉 `.git` 只有 43.22 GB(40.25 GiB)/ 120,784 个文件** ——
  差出来的 **4.87 GB 全是 git 历史**,想省盘可以按仓库 `git gc` 或把不打算再更的仓库删掉 `.git`(删前先看 `02-模拟器库/已clone仓库/README_inventory.md`)。

## 资讯监控与爆款收录(2026-10-10 新增,2026-10-11 加了"大作登陆平台"专线与两个定时任务)

- **`06-资讯监控/`**:**228 个启用源**的登记表(140 个 GitHub `.atom` —— 其中 91 releases / 42 commits / **7 条移植作者级活动流**、
  24 个 Reddit RSS、11 个 GBAtemp 分区、**13 个国外论坛**(Resetera / libretro / RetroPie / SegaXtreme / RomHacking.net / EmuTalk / wololo /
  **Sega-16 / EmuCR / PPSSPP / Clockwork / Gaming Alexandria / Hidden Palace**)、
  30 家媒体/站点(含 itch.io `games/newest.xml` 与 Retro Handhelds Weekly、GamingOnLinux、4Gamer)、**4 个 YouTube 频道流**、5 个中文源(机核 / 少数派 / 吾爱 / **IT之家 / 爱范儿**));
  登记表共 **316 行**,另 **88** 行是**点名拒用或实测够不着**的,每行 `note` 都带 `http` 码与条数),`scene_monitor.py` 一次拉完 →
  台账累计 **8072 条 / 12 列 / key 全唯一**(第 12 列 `flag_focus` 是聚焦主题,3297 条带主题),**HOT 352**、**大作登陆专线 80** 条(已下载 21 / 只监控 16 / 待判定 41 / 拒收 2);
  日报出**「今日聚焦」段**按九个主题分档(Switch移植 / Vita-PSP / 开源掌机与固件 / 模拟器核心 / 引擎重实现 / PortMaster / FPGA / 中文源 / 源码泄露)。
  2026-10-20 第八轮:聚焦层上线 + 三个精准度修复(MiSTer 大小写、商业娱乐噪音闸门、URL ID 假命中)+ 扩源 96 行(72 启用),
  新源第一轮入库 1163 条;探测约 90 个候选全部实测,`re3/reVC` 实测 **451(DMCA 下架)**、Lime3DS 实测 301 合并进 Azahar,都按名字登记。
  中文层(贴吧 / A9VG / 3DM / NGA / 知乎 / B 站)依旧全部够不着,唯一通路是自建 RSSHub —— 仍是本项目唯一真缺口。
  **同日新增「下架抢救层」**(`rescue_watch.py` + `下架抢救登记表.tsv`,专盯"珍贵且会被立即下架"的资源:2026-08-17 任天堂一天扫掉 GitHub
  401 个 Switch 模拟器仓,窗口期只有小时~天):三层监控 = 登记表存活检查(活着就立刻抓源码/页面/git 裸库)+ GitHub 雷达(≤30 天新镜像一冒头就抓)
  + 已挂 131 个源的存在性巡检,外加情报面(下架新闻正文里挖 GitHub 链接)。**消失判定必须双轨确认**(gh api 404 还要 curl 复核,404/451 才算,
  实测靠它拦住一次 godotengine/godot 的误报);首日已抓 29 条 / 417.5 MB(citron-neo/emulator、suyu-v0.0.4、Ryujinx-Nextendo、hottabxp/re3、
  skyline×2、Eden 自建 git 裸库、5 站点快照、5 孤儿仓、雷达 2 个);连跑多轮抓取量 0 = 幂等通过。2 小频率的 schtasks 命令在 `06-资讯监控/README.md` §八。
  用法、429/403/000/`html_not_feed` 的读法、以及"加一个源"的格式:`06-资讯监控/README.md`
  **本轮唯一升级到"一手核实"的大消息**:PlayStation 官方博客 2026-07-01 宣布 **PS3 / PS Vita 商店**分阶段关闭
  (墨西哥等 2026-08 起、更多地区 2026 年底起、**其余国家含中国大陆 2027-07**),已购内容 `for the foreseeable future` 内仍可重下但不是永久承诺
  → Vita 线的"官方能买"这条路有截止日期,`PSVitaAlive` / `VitaDB` / `NeoVitaDB-Catalog` 要当成**关门前的备份窗口**长期盯
  (逐句摘录与可达性实测在指北 §4.5;这条超 14 天窗口,所以只在台账里、没进短名单)
- **`04-游戏资源库/爆款收录/`**:从日报里挑中后落地的成品区 —— 登记表 **47 条(启用 42 / 点名停用 5)** →
  **42 组 / 65 个文件 / 815.7 MB = 777.9 MiB**,每个都带 `sha256_local` 与 `sha256_upstream` **双向对账**
  (**46 个 OK / 15 个 LOCAL_ONLY / 4 个上游没发 digest**),并逐个解压审计"里面有没有夹带游戏数据"(**0 处**)。
  Switch 全家桶(Atmosphère 1.12.0 / hekate 6.5.4 / MissionControl / sphaira / Ultrahand / hbmenu)、
  Vita(VitaShell / Adrenaline / 官方工具链 / HENlo 源码 / **TRAX 1.0.0**)、Halo CE 四组移植引擎源码,
  2026-10-11 上午这轮加进 **NXStation(Switch 前端) / Flycast Vita / Gekko2(PCSX2-Wii)源码 / 风之杖与 SA2 的 Switch 移植源码 /
  RSDKv3-PSP 源码 / Model2 NX / SuperModel NX / DXX-3DS(Descent 1 上 3DS) / ioQuake3 全家五个平台**(PS4 五包 + PS3 五包 + Wii 五包 + PSP 三包,共 18 个文件) / ScummVM Wii U;
  下午补判这轮再加 **风之杖 GC 版反编译源码(SwitchWaker,MIT)** 与 **Sonic CD (2011) Wii U 移植成品(RSDKv3 1.3.3 Beta 1,带上游 digest → OK)**)。
  **拒收与只监控的记录也写在这份 README 里**(nxStore 65 个 App 逐条分类、gta5_toolbox 无许可证、
  OOT-3DS 与 Sonic R PSP 是**仓库里 commit 了原厂素材**)。
- **`06-资讯监控/大作登陆平台.md` —— 你要的"某大作/经典作品登陆到某平台"专线**:
  判据是 `scene_monitor.py` 的 `arrival_of()`,要求**作品名或引擎名 + 登陆类动词 + 平台名**三者同现才记,
  并**按动词位置判方向**(动词之后的平台=目的地,之前的=来源),所以 `OoT N64 3DS Port` 会写成"从 N64 登陆到 3DS"而不是两个平台混在一起。
  台账第 11 列 `flag_arrival` 存 `ARR|作品|登陆到|从哪来`;累计清单当前 **62** 条(已下载 21 / 只监控 16 / 待判定 23 / 拒收 2),
  日报每天另出一段"大作/经典登陆平台(专线,今日 N 条)"。
  **判定列不是脚本猜的,是人工表 `06-资讯监控/大作判定.tsv`**(39 条,每条 `note` 里带文件级证据:哪个帖子号→哪个一手仓库→`gh api` 的许可原文首行→要不要自备数据→成品挂在哪个 tag、多大、有没有上游 digest)。
  **收不收成品有一条明写的口径**(2026-10-11 下午从既有判定反推出来并写进 note,不是新加的偏好):
  通用**引擎/播放器/模拟器/前端**(运行时读你自备的数据,二进制里没有那款游戏的程序码)**收成品**;
  **某一款游戏的静态重编译体**(二进制就是原厂程序码翻译出来的产物,如风之杖 GC/HD、SA2、Halo CE 的 `.vpk`、《索尼克 2006》的 `MarathonRecomp.nro`)**只收源码**。
  这条口径 **2026-10-14 被我自己违反过一次并当场退回**:Marathon 那条我见它 GPL-3.0 + 上游"不含素材"就收了 61 MB 的 `.nro` 成品,复核才认出它和 sa2-nx/SwitchWaker 是同一条静态重编译路线 —— 已删文件、退台账行、登记表改成 `sw_marathonrecomp_src`(`kind=source`,4,115,248 B),教训写成判据第 15 条(见交接稿 §六)。**许可与"不含素材"两件事都不能替代"二进制里装的是谁的代码"这一问。**
  同一轮还**订正了我先前一处错判**:帖 685126 我写成"GC 版系误传",实测两个帖都同时链 `SwitchWaker`(GC) 与 `SwitchWakerHD`(Wii U),GC 版真存在,已补收其源码(指北 §4.6)。
  改这张表后要跑 `py -3 _工具脚本/scene_monitor.py --relabel`,它不联网、只重算台账标记 + 重生成 `大作登陆平台.md`。
  **注意一个坑(2026-10-11 实测)**:`--relabel` **不会重写当天已生成的日报文件**,日报里那段专线仍会显示旧的"待判定" ——
  要把当天日报刷成最新判定,得再跑一次完整抓取 `py -3 _工具脚本/scene_monitor.py`(按 sha1 去重,幂等,只会补新消息)。
- **每天自动跑,两条路都上了**:`_工具脚本/daily_run.py` 是共用入口(先抓资讯再下资源,日志落 `06-资讯监控/_schedule.log`)。
  ① **Windows 计划任务 `Qoder_Handheld_DailyNews`** —— 每天 **08:30**,`C:\Windows\py.exe -3 "…\daily_run.py"`,不依赖 Qoder 开着;
  ② **Qoder 定时任务 `开源掌机·大作登陆判定与下载`**(id `5747b09e-5e23-4d1d-8c91-5a3f49851cb5`)—— 每天 **09:30**,
  把当天新出的"待判定"大作线索逐条走四问、写回判定表、把"可下"的登记并下载。
  06:48 我手动触发①验证了生产路径(日志 `06-资讯监控/_schedule.log`:`06:48:06 scene_monitor` → `06:50:02 scene_dl` → `exit=0`):抓进 **45** 条新消息,并且**作者新挂的 `TRAX-PSP.zip` 被 `filter` 自动收到**(1,374,674 B,sha256 与上游相符)。
  **②这条 09:30 的判定任务今天没赶上**:15:21 那轮 `daily_run` 才进来两条新的大作线索(685220 / 685222),所以判定表里一度留着 4 条待判定 —— 2026-10-11 下午我在本窗口手工走完四问并清零(判到 **待判定 0**),两条落地、两条定为只监控;全过程与依据见指北 §4.6。
  **口径提醒**:①负责"抓+下",②负责"判+登记",两条都靠同一份 `大作判定.tsv` / `合法收录登记表.tsv`,所以手工补判之后不必再改脚本,但**改完表必须跑 `--relabel`**才会在两份产物里生效。
  撤销方法与两个坑(PS 5.1 把无 BOM 的 UTF-8 `.ps1` 当 ANSI 读→中文路径乱码;代理已在**用户级环境变量**里)写在 `06-资讯监控/README.md` §六。

## 五分钟上手

0. **先认清自己的机型属于哪一档**,再看对应专篇(四篇都写完了,刷机前照着走):
   - **XiFan XF45V(本机,不是 R36S)** → `01-教程库/机型固件/XiFan_XF45V/00-XF45V完全指南.md`
   - **XiFan R36MAX2** → `01-教程库/机型固件/R36MAX2/00-R36MAX2完全指南.md`
   - **Anbernic/原厂 R36S(640×480)** → `01-教程库/机型固件/R36S/00-R36S完全指南.md`
   - **XiFan NGP45HT(RK3562,不是 RK3326!)** → `01-教程库/机型固件/NGP45HT/00-NGP45HT完全指南.md`
   机型→芯片→可用固件的横向表在 `01-教程库/机型固件/00-机型固件对照表.md`;跨机型的通用步骤在 `机型固件/00-刷机通用流程与工具.md`。
   **最容易踩的一条**:XF45V / R36MAX2 / NGP45HT 都是 1024×768,照抄 R36S 的 640×480 教程(dtb、主题、端口)必错;
   而 NGP45HT 换的是芯片档(RK3562),RK3326 的镜像根本刷不进去。
0b. **要动手刷之前**:`09-刷机工具/README.md`(工具本体都已下好并记了 SHA256)+ `02-模拟器库/已clone仓库/系统镜像/README.md`
   (每个镜像对哪台机器、哈希、校验来源、分区解析结果,逐行可查)。
1. **想先跑起来** → 读 `01-教程库/入门选购/00-入门必读.md`(存储卡+固件选择是两大坑源)。
2. **想知道该装哪个模拟器** → `02-模拟器库/README.md` 的第二、三节(按平台/按芯片档)。
3. **想搞清 BIOS** → `03-BIOS库/00-BIOS需求总表.md`,再看 `校验方法.md`。
4. **想学 C++ 并读懂模拟器** → `01-教程库/00-C++学习路线.md`,配合 `02-模拟器库/已clone仓库/` 里的真实代码。
5. **手上有游戏要整理** → `04-游戏资源库/自己ROM放这里/README.md`:
   ROM 该放哪个目录(134 个,直接从本机固件的 es_systems.cfg 抽的,含 19 个"目录名≠system名"的坑)、
   `rom_sort.py` 按文件头归类+去重、`igir` 的可用参数。
   想立刻有得玩且合法 → `04-游戏资源库/00-合法可下载资源索引.md`。
6. **想搞清"移植"是怎么回事、某个大作有没有人做完了移植** → `01-教程库/移植原理/00-移植是怎么回事_小白完全教程.md`
   (六条路线的判据 + GTA III/VC/SA/V、马克思佩恩、合金装备的逐仓核实结论 + 在 XF45V 上跑通一个自备数据移植的六步命令)。
7. **想看到代码级别、想知道"移植到底改哪几行"** → `01-教程库/移植原理/01-代码级解剖_一个真实移植仓库里改了哪几处.md`
   (真仓库 `orktes/max_arm64`,七处必改点全部带文件:行号;钩子只有 3 条指令、mprotect 三态、ELF 自验、授权按文件核对)。
8. **想自己动手编一个能插卡玩的端口** → `01-教程库/移植原理/02-交叉编译与打包_从一行C到一个能插卡玩的端口.md`
   和同目录 `动手实践/`(zig 0.17.0 在本机零编译器的 Windows 上真编出 aarch64 静态二进制 1,588,784 B,
   打成 PortMaster 包 864,160 B;四条可用命令 + 五条真实翻车报错原文)。
9. **想从零做一个"真游戏"端口,而不是探针** → `01-教程库/移植原理/03-自己做一个能玩的端口_OpenTyrian实战.md`
   (OpenTyrian 52 个 `.c` → aarch64 518,624 B,成品 `Tyrian.zip` 5,039,180 B;Windows 同源实跑截图、
   `check_port.py` 22/22、上卡/SSH 测试命令;Switch 侧已用 devkitPro 实编出 `opentyrian.nro`
   18,825,002 B,附链接四连错与安装环境坑,但未上真机)。

## 关于 ROM 与 BIOS 的边界(重要)

本库**不包含**任何商业游戏 ROM 或主机 BIOS 文件的批量下载,原因见 `04-游戏资源库/README.md`:
这类内容的仓库会被 DMCA 清除、链接随时失效,且"不商用"不构成批量下载的免责基础。

替代方案本库已全部做好:
- 需要哪个 BIOS / 叫什么名字 / 放哪 → `03-BIOS库/00-BIOS需求总表.md`
- 从自有设备怎么提取 → `03-BIOS库/自制提取路径.md`(PS3 固件、PSP 官方升级包属官方免费下载)
- 放了还报错怎么查 → `03-BIOS库/校验方法.md` + `_工具脚本/bios_check.py`
- 立刻有得玩且合法 → `04-游戏资源库/00-合法可下载资源索引.md`(GB/GBA jam 合集就是上百款)

## 维护约定

- 新增源码:放进 `02-模拟器库/已clone仓库/<分类>/`,并在 `README_inventory.md` 补一行(可用脚本重生成)。
- 新增机型/固件信息:改 `01-教程库/机型固件/00-机型固件对照表.md`,并标注是否已验证。
- 所有"具体下载哪个文件"的建议都要写清**验证日期**,掌机生态半年就会变。

## 工具速查(`_工具脚本/`,2026-10-21 更新)

| 命令 | 干什么 |
|---|---|
| `py -3 _工具脚本/rsshub_ctl.py status` | 自建 RSSHub 体检(端口 1200 + 4 条路由实测);`up`/`stop`/`test` 同理 |
| `py -3 _工具脚本/搜索.py 关键词 [--scope 台账/判定/登记/源/教程] [--full]` | 全库搜索(台账 9000+ 条/判定表/登记表/源表/253 篇教程),多关键词是 AND |
| `py -3 _工具脚本/serve_library.py --lan --port 8080` | 教程库只读 HTTP 服务,给 XF45V/手机/局域网用;不加 `--lan` 只听本机 |
| `py -3 _工具脚本/backup.py --dest D:\库备份 [--with-payload]` | 备份攒出来的东西(06/01/03/05 + 三份总文档);**必须显式给目标** |
| `py -3 _工具脚本/weekly_digest.py` | 生成本周周报(daily_run 每天自动刷新) |
| `py -3 _工具脚本/scratch_tidy.py [--days 7]` | 把 `_scratch` 里 N 天前的探测残渣搬进 `_scratch/_归档/`(只搬不删) |
| `py -3 _工具脚本/scene_monitor.py --retry-failed` | 抓完对 429/000/curl_err 的源错峰重试一轮(daily_run 已默认带) |
| `py -3 _工具脚本/browser_watch.py` | 浏览器层每周补抓(patchright 无头 chromium:A9VG/MYDIGIT 实测可入账;Cloudflare 三站继续试) |

定时任务共四个：`Qoder_Handheld_DailyNews`(每天 08:30 全管线)、`Qoder_RSSHub`(开机起 RSSHub)、
`Qoder_Handheld_Backup`(每周日 10:00 备份到 D:\库备份)、`Qoder_Handheld_Browser`(每周日 11:00 浏览器层补抓)。
重建命令:`powershell -File 06-资讯监控\_register_task.ps1 -Root F:\开源掌机教程 -Name Qoder_Handheld_DailyNews`。

自建 RSSHub 在 `f:/rsshub-npm`(Node 24.19 原生跑,无 Docker;npm 装的,pnpm 的 safe-delete 会被 IDE 审批链拦死),
开机自启任务 `Qoder_RSSHub`,daily_run 每次也会先 `rsshub_ctl.py up`(幂等)。
中文层(贴吧/B站/知乎/NGA)的实测结论写在 `06-资讯监控/源登记表.tsv` 的各 `cn_rsshub_*` 行里。

TAS 通关、游戏必杀技与隐藏彩蛋：全平台实测步骤及问题回传说明书
给本地执行模型 / 自动化脚本的执行令： 本文件是实操测试与数据回传任务书。请勿回复空泛的可行性分析，直接在本地 F:\开源掌机教程\_工具脚本 目录下从 第 1 节 Step 0 开始逐项执行命令，收集真实退出码、JSON 报告、RAM 差分数据与失败报错原文，并按 第 5 节的回传模板 将结果写入 F:\开源掌机教程\测试反馈_待优化回传报告.md（同步回云盘 _Gemini轻量版 根目录），供云端模型据此进行针对性代码修复与参数调优。


________________


一、 测试总览与三大核心目标
本次实测覆盖全怀旧平台（FC/NES、街机 FBNeo、SFC/SNES、GBA、GB/GBC、MD/Genesis、PS1），分三大模块验证并收集优化依据：


1. 模块 A（TAS 整片通关与跨平台录像转换）：验证 .bk2 原生回放，以及 .fm2/.fcm（FC）、.smv（SFC）、.vbm（GBA/GB）、.gmv（MD）无损转 .bk2 后的无 desync 通关录制、WASAPI 原声对齐与天马封面边框合成。
2. 模块 B（游戏必杀技 / 全武器 / 全招式盘点）：验证「共享/独立 base.state + 原子 RAM 补丁（或 .cht 金手指 / 街机 Lua 锁满气）+ 逐帧宏触发 + 正反例同帧数视觉双闸验收」，产出 reel.mp4。
3. 模块 C（游戏隐藏要素 / 彩蛋专项验证）：验证需要「复合前置状态 + 隐藏指令/特定场景交互」才能触发的彩蛋（如 SFC《洛克人 X》波动拳胶囊、FC《热血足球 2》暂停秘籍解锁全员必杀、PS1《恶魔城：月下夜想曲》魔导器变身与全屏窃魂术、通关录像自动扫描切隐藏高光）。


________________


二、 必跑测试步骤（请按顺序在本地 PowerShell 逐条实跑并记录输出）
Step 0：环境基线、跨平台死锁修补与 395/395 离线自检
在启动任何模拟器前，先确认本地代码已打上全平台按键（28 键）与 32MB 地址空间补丁，并验证离线自检计数：


cd "F:\开源掌机教程\_工具脚本"


# 1. 自动热修补 statejump.py / showcase.py 的 NES 死锁，写入跨平台天马边框模板，并体检本地真 ROM / 存档 / 录像现状
py -3 -u -m taspipe.local_bootstrap doctor > "F:\taspipe_scratch\00_doctor_report.json" 2>&1


# 2. 挂载新增的 30 条跨平台闸门并运行全量离线自检（期望输出：SELFTEST OK 395/395）
py -3 -u -m taspipe.cross_platform_selftest_gates --inject
py -3 -u -m taspipe.selftest > "F:\taspipe_scratch\01_selftest.log" 2>&1


# 3. 盘点本地 7 大资源池（含 Eden、爆款收录、PortMaster 632 包、libretro-database 金手指）与 OpenList 网盘挂载点
py -3 -u "F:\开源掌机教程\all_sources_scanner.py" overview > "F:\taspipe_scratch\02_pools_overview.json" 2>&1

* 必查判据：
   * 01_selftest.log 末尾是否为 SELFTEST OK 395/395 且退出码为 0；若报错，请记录报错栈与断言编号。
   * 00_doctor_report.json 中 megaman1_rom_diagnosis.verdict 是否仍为 BLOCKED_NEED_CLEAN_MM1_ROM；若是，立即执行下一步从天马 6T 网盘拉取干净 ROM。


________________


Step 1：资源补齐测试（天马 6T 网盘拉取 + 现成开源库与金手指检索）
cd "F:\开源掌机教程\_工具脚本"


# 1. 从本机 OpenList 挂载的天马 6T 网盘自动拉取各盘点包所需的干净 ROM 与封面（自动过滤已知坏 dump）
py -3 -u -m taspipe.tianma_multi_fetch pull-pack-roms > "F:\taspipe_scratch\03_tianma_pull.json" 2>&1


# 2. 检索本地 libretro-database/cht 现成金手指库，生成各游戏「全武器/无限能量/全装甲/全魂」候选补丁表
py -3 -u -m taspipe.retro_cheat_runner auto-inject-cht --pack "taspipe/游戏包/megaman1_weapons.showcase.json" --cht-query "Mega Man"
py -3 -u -m taspipe.retro_cheat_runner auto-inject-cht --pack "taspipe/游戏包/snes_megaman_x_arsenal.showcase.json" --cht-query "Mega Man X"
py -3 -u -m taspipe.retro_cheat_runner auto-inject-cht --pack "taspipe/游戏包/ps1_sotn_alucard_powers.showcase.json" --cht-query "Symphony of the Night"


# 3. 检查并拉取 stable-retro / fbneo-training-mode 等现成开源库
py -3 -u "F:\开源掌机教程\现成开源库与金手指直接用\pull_opensource_repos.py" --all --pip-install > "F:\taspipe_scratch\04_opensource_repos.json" 2>&1

________________


Step 2：模块 A —— TAS 整片通关与跨平台录像转换测试
测试目标：验证「已有 TAS 录像」能否无损转 .bk2、全程不 desync、音画同步且套上天马封面边框。


cd "F:\开源掌机教程\_工具脚本"


# 1. 批量转换并跑本地已就绪的 FC 名作（如忍者龙剑传、银河战士、塞尔达传说）带原声通关片段
py -3 -u -m taspipe.local_bootstrap run-ready --out "F:\taspipe_scratch\test_module_a_tas" --frames 1200 > "F:\taspipe_scratch\05_module_a_tas.log" 2>&1


# 2. 单独测试 FCEUX (.fm2/.fcm) 录像自动转换与通关出片（以塞尔达传说 Zelda 为例）
py -3 -u -m taspipe.universal_authoring playthrough --game "Zelda" --frames 1800 --audio --template fc_tianma_cover --out "F:\taspipe_scratch\test_zelda_playthrough"


# 3. 测试跨平台录像转换器（检查本地是否有 .smv / .vbm / .gmv 可转 .bk2）
py -3 -u -m taspipe.movie_converters inspect --movie "F:\开源掌机教程\04-游戏资源库\TAS输入录像库\movies\SNES\super_metroid.smv"

* 模块 A 验收与异常记录点：
   1. cap.txt 与 *.run.json 中 desync 是否为 false、termination 是否为 complete 或 movie_end。
   2. 若发生 desync at frame N：记录具体的 pub_id、游戏名、录像原格式（.fm2/.smv/.vbm/.gmv）、ROM 的 SHA-1 以及发生 desync 的帧号 N。
   3. 检查 audio_sync_review 与 game_audio_audible：确认音量 max_volume > -90dB 且音画时长差在容差内。


________________


Step 3：模块 B —— 游戏必杀技 / 全武器 / 全招式盘点测试（主机 + 街机）
测试目标：验证「开机探路存 base.state → 原子读档+RAM补丁 → 逐帧宏释放必杀/武器 → 正反例双闸检测 → reel.mp4 合辑」在多平台上的表现。


cd "F:\开源掌机教程\_工具脚本"


# 1. 街机 FBNeo 必杀技实跑测试（《拳皇 98》草薙京 4 大必杀/超必杀：鬼烧、暗拂、大蛇薙、无式）
py -3 -u -m taspipe.backends run-move "→↓↘+A" --slug oniyaki --char kyo --out "F:\taspipe_scratch\test_kof98\oniyaki"
py -3 -u -m taspipe.backends run-move "↓↘→+A" --slug yamibarai --char kyo --out "F:\taspipe_scratch\test_kof98\yamibarai"
py -3 -u -m taspipe.backends run-move "↓↙←↙↓↘→+C" --slug orochinagi --char kyo --out "F:\taspipe_scratch\test_kof98\orochinagi"
py -3 -u -m taspipe.backends run-move "↓↘→↓↘→+A" --slug mushiki --char kyo --out "F:\taspipe_scratch\test_kof98\mushiki"


# 2. 主机/掌机多平台模拟器确定性基线验证（以 NES 热血足球2 / MD 幽游白书 / SNES 洛克人X 为例）
py -3 -u -m taspipe.statejump verify --rom "F:\taspipe_scratch\soccer2_showcase\soccer2.nes" --core NesHawk --system NES --out "F:\taspipe_scratch\verify_nes"


# 3. 跑单游戏从零自动建 base.state + 正反例像素差分自动标定 + 全量武器/必杀合辑生产
# (a) FC《魂斗罗》5 大枪械弹幕盘点
py -3 -u -m taspipe.local_bootstrap auto-showcase --rom "F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\contra_usa.nes" --preset generic_nes --pack "taspipe/游戏包/contra_weapons.showcase.json" --out "F:\taspipe_scratch\test_contra_showcase"


# (b) FC《洛克人 1》8 大武器盘点（需干净 ROM）
py -3 -u -m taspipe.local_bootstrap auto-showcase --rom "F:\开源掌机教程\04-游戏资源库\TAS输入录像库\roms_verify\NES\mega_man_usa.nes" --preset megaman1 --pack "taspipe/游戏包/megaman1_weapons.showcase.json" --out "F:\taspipe_scratch\test_mm1_showcase"


# (c) 街机《合金弹头 1》或 SFC《洛克人 X》或 MD《幽游白书》盘点包
py -3 -u -m taspipe.retro_platforms run-showcase --pack "taspipe/游戏包/snes_megaman_x_arsenal.showcase.json" --out "F:\taspipe_scratch\test_mmx_showcase" --work "F:\taspipe_scratch\test_mmx_work"

* 模块 B 验收与异常记录点：
   1. 街机必杀技：检查每个招式的 *.run.json 中 head_is_fight（第 0 帧是否为战斗画面）、game_audio_audible（是否有原声）、move_hit（对手是否掉血 damage > 0）。若某招式报空放（damage == 0），记录 approach 距离和招式名。
   2. 主机/掌机必杀与武器：检查 showcase_report.json 中每个要素的 positive.verdict（须为 pass）与 negative.rejected（须为 true）。若正反例画面完全相同，说明 RAM 补丁地址未生效 或 触发按键宏落在硬直/菜单外，需记录该要素 ID 与 ramdump 差分结果。


________________


Step 4：模块 C —— 游戏隐藏要素 / 彩蛋专项测试（Easter Eggs & Secret Unlocks）
彩蛋与普通招式的最大区别在于：彩蛋往往有严苛的隐藏前置条件（如必须满血、必须在特定关卡坐标、必须在暂停菜单输入秘籍、或必须开启隐藏 Bit 位），且容易被拿「仅修改了内存标志但画面无变化」冒充成功。请重点执行以下 3 类彩蛋测试：
1. 秘籍指令型彩蛋：FC《热血足球 2》暂停输入 AAABAAABAAAAAAA 解锁全员必杀 + 持球态求解
cd "F:\开源掌机教程\_工具脚本"


# 第一步：自动导航到 KICK OFF 画面
py -3 -u -m taspipe.universal_authoring probe-rom --rom "F:\taspipe_scratch\soccer2_showcase\soccer2.nes" --preset nekketsu_soccer2 --out "F:\taspipe_scratch\test_soccer2\nav"


# 第二步：从 KICK OFF 自动开球 -> 注入暂停全必杀彩蛋秘籍 (AAABAAABAAAAAAA) -> 短传接应锁定活球持球态 possess_base.state
py -3 -u -m taspipe.universal_authoring solve-soccer2-base --rom "F:\taspipe_scratch\soccer2_showcase\soccer2.nes" --kickoff-state "F:\taspipe_scratch\test_soccer2\nav\base.state" --out "F:\taspipe_scratch\test_soccer2\possess"


# 第三步：基于持球态自动标定并产出必杀射门合辑
py -3 -u -m taspipe.universal_authoring produce --pack "taspipe/游戏包/nekketsu_soccer2_shots.showcase.json" --out "F:\taspipe_scratch\test_soccer2\final" --work "F:\taspipe_scratch\test_soccer2\work"
2. 隐藏胶囊/满血限定型彩蛋：SFC《洛克人 X》隐藏第五胶囊「波动拳（Hadoken）」
* 测试要素：snes_megaman_x_arsenal.showcase.json 中的 hadoken_secret_capsule。
* 彩蛋机制核验：在《洛克人 X》中，即使将 WRAM 0x001F99 设为 0x8F（解锁四件装甲 + 波动拳标志位 bit7），如果角色当前血量 0x000BCF 不满 32，搓 ↓↘→+Y 也只会发出普通豆豆弹而发不出波动拳！
* 单要素专项测试命令：


py -3 -u -m taspipe.retro_platforms run-showcase `
  --pack "taspipe/游戏包/snes_megaman_x_arsenal.showcase.json" `
  --only hadoken_secret_capsule `
  --out "F:\taspipe_scratch\test_mmx_hadoken" `
  --work "F:\taspipe_scratch\test_mmx_hadoken_work"

* 验收判据：打开 evidence/hadoken_secret_capsule_positive.png，确认艾克斯摆出街霸隆的双手推出姿势并发射大型蓝白色波动气功弹；打开 negative.png 确认站立不动无气功弹。
3. 录像扫描型彩蛋/高光提取（从整片 TAS 通关视频自动扫描切出隐藏房间/变身/彩蛋）
# 对已录制的通关视频（如银河战士 Metroid 或塞尔达 Zelda），按事件视觉钩子自动扫描连续稳定帧窗并切出高光盘点段
py -3 -u -m taspipe.highlight_cutter scan-and-cut `
  --recording "F:\taspipe_scratch\test_zelda_playthrough\raw_capture.mp4" `
  --hook-pack "taspipe/游戏包/metroid_upgrade.pack.json" `
  --out "F:\taspipe_scratch\test_highlight_cut"

________________


三、 我需要你（及本地执行模型）反馈什么信息，才能继续精准优化和修复？
因为云端环境没有挂载你本地的几十 GB 游戏 ROM、BizHawk 进程与显卡/声卡硬件，要让我把每一款游戏的脚本、RAM 地址、按键时序修到 100% 全自动出片零报错，我需要本地执行模型跑完上述命令后，把以下 6 项关键诊断数据 收集并反馈给我：
1. 本地真实资产与环境探针快照（来自 00_doctor_report.json 与 02_pools_overview.json）
* 我需要知道：
   * 你本地当前实际存在的所有 ROM 文件名、所在路径与 真实 SHA-1（尤其是《洛克人 1》《洛克人 X》《魂斗罗》《恶魔城》《拳皇 98》《合金弹头》的真实文件 SHA-1）。
   * tianma_multi_fetch.py 访问本机 127.0.0.1:5244 OpenList 时，各平台目录的实际名字是什么（例如网盘里叫 SFC 还是 SFC-HD？街机叫 FBNeo 还是 MAME？），拉取是否遇到 403/412 或路径不匹配。
2. 开机导航卡点现场（来自 nav_report.json 与 step0..N.png）
* 为什么需要：不同游戏（甚至同游戏的美版/日版）开机动画时长、标题屏按 Start 还是按 A、选关界面按几次方向键完全不同。如果某款游戏 probe-rom 报 controllable: false（没进到真实关卡）：
* 请反馈给我：
   * nav_report.json 全文；
   * step0_boot.png、step1.png、step2.png、ctrl_r0/ctrl_neutral.png 分别停在什么画面（例如：“停在选存档名字界面”、“停在剧情字幕”、“还在标题屏没反应”）。
   * 我将据此为你做的修复：收到后我会直接为该游戏写出精确到帧的 GAME_NAV_PRESETS 导航宏，确保 100% 稳定进关生成 base.state。
3. RAM 补丁/金手指实机生效差分表（解决版本偏移与漏写 Owned Flag）
* 为什么需要：百科或 .cht 里的地址如果和你的 ROM 修订版差了 1~2 个字节，或者像《洛克人 1》那样「只改了武器能量 0x006B..0x0071 和当前武器 0x005F，但没改武器拥有标志位（Owned Flags）」，按攻击键是发不出特殊武器的。
* 请反馈给我：
   * 哪些要素在跑 calibrate 时报了 RuntimeError: 正反例帧序列几乎完全相同，说明触发宏或前置补丁未使要素生效！；
   * 在游戏内真正拿到武器或打开武器菜单前后，用 sess.ramdump() 导出的两份 2KB 内存文件中有变化的地址与数值对（addr: old_val -> new_val）。
   * 我将据此为你做的修复：直接锁定你手头那份 ROM 100% 准确的 owned_flags 与 current_weapon 地址并写死进 .showcase.json。
4. 正反例像素标定（calibrate）实测数值与视觉误判反馈
* 为什么需要：自动标定器会算出 frame、region、rgb、pos_fraction、neg_fraction。但有些招式（如全屏闪白、30Hz 隔帧闪烁的雷电、或者角色走动移位导致背景色进入检测框）可能出现「正反例区分度不够」或「框到了角色身体而非武器弹丸」。
* 请反馈给我：
   * calibrate 打印出的每一行 [标定完成] <element_id>: frame=... region=... rgb=... pos=... neg=... -> min_fraction=...；
   * 抽看 evidence/<element_id>_positive.png 时，哪些要素的截图里没有拍到招式最帅的那一帧（例如截早了还在抬手前摇，或截晚了弹丸已经飞出屏幕）。
   * 我将据此为你做的修复：调整该要素的 trigger.macro 按住时长、extra 尾帧长度，或为该要素加上「特效色 + HUD 能量消耗」双 Check 复合判据。
5. 街机（FBNeo tas_rig）招式命中与距离参数反馈
* 为什么需要：街机格斗招式（特别是投技、近身必杀、多段超必杀）对起手距离（approach）和收尾等待帧（tail）非常敏感。
* 请反馈给我：
   * run-move 生成的 *.run.json 中，哪些招式的 move_hit 为 inconclusive（即 damage == 0 空放未打中对手），或者视频结尾在对手还没落地时就切掉了。
   * 我将据此为你做的修复：利用 search.py (M7) 为未命中的招式调整 approach 走位帧数、起手 .fs 快照与 tail 帧数。
6. TAS 录像转换与回放 Desync 帧号报告
* 请反馈给我：
   * 跑 .fm2 / .smv / .vbm / .gmv 转换后的 .bk2 时，哪些 pub_id 报了 desync at frame X，以及该录像头部的 emuVersion、NewPPU 或 SyncSettings 警告信息。


________________


四、 一键收集所有测试证据的自动打包脚本（供本地直接运行）
在本地跑完测试后，无需手动翻找各个目录的日志，请在 F:\开源掌机教程\_工具脚本 下运行以下一行命令，即可将所有测试报告汇总为一个 JSON：


py -3 -c "import json, glob, pathlib; out={p: json.loads(pathlib.Path(p).read_text(encoding='utf-8', errors='replace')) for p in glob.glob('F:/taspipe_scratch/**/*.json', recursive=True) if pathlib.Path(p).stat().st_size < 200000}; pathlib.Path('F:/开源掌机教程/测试反馈_汇总数据.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8'); print('已汇总', len(out), '份报告 -> F:/开源掌机教程/测试反馈_汇总数据.json')"

________________


五、 给本地执行模型的标准回传模板（请填实后直接发回或写入云盘）
请本地执行模型在完成上述步骤后，严格按照以下格式生成 测试反馈_待优化回传报告.md 并发回：


# TAS / 必杀技 / 游戏彩蛋 实测回传报告


## 1. 基线自检与环境体检结果
- **离线自检 (`taspipe.selftest`)**：退出码 = `___` ，通过数 = `___ / ___`（若有失败，贴出报错栈原文）
- **本地已确认可用的干净 ROM 清单（含 SHA-1）**：
  - 洛克人 1 (NES)：路径 = `___` ，SHA-1 = `___` ，是否已跳过 CLEAR POINTS 异常 = `是/否`
  - 热血足球 2 (NES)：路径 = `___` ，SHA-1 = `___`
  - 魂斗罗 (NES)：路径 = `___` ，SHA-1 = `___`
  - 洛克人 X (SNES)：路径 = `___` ，SHA-1 = `___`
  - 拳皇 98 / 合金弹头 (FBNeo)：路径 = `___` ，`.fs` 存档列表 = `___`
  - 恶魔城月下 (PS1)：路径 = `___` ，BIOS (`scph5501.bin`) 是否就绪 = `是/否`
- **天马 6T 网盘 (`tianma_multi_fetch`) 状态**：OpenList 连通性 = `___` ，实际扫描到的平台子目录名 = `___`


## 2. 模块 A（TAS 通关与跨平台录像转换）实测结果
- **已跑通出片的出版物 (`pub_id` + 游戏名 + 帧数 + 音频状态)**：
  - `___`
- **发生 Desync 或转换报错的条目**：
  - `pub_id`: `___` | 原格式: `.fm2/.smv/.vbm/.gmv` | Desync 帧号: `___` | 报错/原因: `___`


## 3. 模块 B（游戏必杀技与全武器盘点）实测结果
- **导航与 `base.state` 生成状态**：
  - 成功进入受控 Gameplay 的游戏：`___`
  - 卡在半路的游戏：`___` ，停滞画面描述（`stepN.png`）：`___`
- **各要素正反例标定 (`calibrate`) 与双闸验收明细**：
  | 游戏 / 要素 ID | 正例得分 (`pos_fraction`) | 反例得分 (`neg_fraction`) | 阈值 (`min_fraction`) | 判定 (`verdict`) | 证据帧画面是否真实准确（有无截早/截晚/RAM未生效） |
  |---|---|---|---|---|---|
  | `___` | `___` | `___` | `___` | `pass/fail/inconclusive` | `___` |
- **街机必杀技 (`FBNeo run-move`) 命中与原声结果**：
  - `oniyaki` / `yamibarai` / `orochinagi` / `mushiki` 掉血比例 (`damage`) 与存在问题：`___`


## 4. 模块 C（游戏彩蛋与隐藏要素）实测结果
- **热血足球 2 暂停秘籍 (`AAABAAABAAAAAAA`) + 持球态求解 (`solve-soccer2-base`)**：
  - 命中的开球接球候选名 (`candidate_used`) = `___` ，起跳必杀射门是否成功触发 = `是/否`
- **洛克人 X 隐藏波动拳胶囊 (`hadoken_secret_capsule`)**：
  - `WRAM 0x1F99=143` + `0x0BCF=32` 写入后，`↓↘→+Y` 是否成功发出蓝白波动拳 = `是/否`（若未发出，贴出 `evidence/hadoken_secret_capsule_positive.png` 画面表现）
- **其他彩蛋 / 高光自动切片 (`highlight_cutter`) 结果**：`___`


## 5. 需云端模型下一轮修复与调优的具体问题清单
1. `___`
2. `___`
3. `___`

# 已验证代码库（分游戏归档 · 可复用）

> 立规出处：用户 2026-11-14「所有的测试成功过使用的代码要分文件夹保留起来 之后可以复用」。
> 本目录 = 实跑成功过的脚本/标定产物的**副本**（原件仍在 F:\taspipe_scratch 与生产路径，字节不动）。
> 每个脚本头部注明：归属游戏、用途、成功证据、复用入口。状态分三档：
> **成品级**（出过片/过闸门）／**探针级**（实跑拿到状态或结论）／**求解中**（尚未过验收）。
> 复用方式：脚本内 ROM/BH/WORK 路径为绝对路径，换机器改头部常量即可；生产入口优先走
> `taspipe/showcase.py`、`taspipe/universal_authoring.py`，本库脚本是 authoring/探针工具。

## contra_要素/（魂斗罗 FC · 成品级）

成功证据：解说成片 `F:\电竞 音乐 动漫 科普 奇葩 考研 盘点视频项目\topics\game_commentary\outputs\projects\20261114_182513\video_beat.mp4`
（review 闸门 ok，五要素 frac 0.88/0.88/0.88/0.88/0.81）；QC 抽帧表 `F:/taspipe_scratch/weap_check2/final_sheet.png`；
素材包 `04-游戏资源库/TAS输入录像库/交接包/contra_elements_d1`；知识包 `_工具脚本/taspipe/游戏包/contra_weapons.showcase.json`。

| 脚本/产物 | 用途 |
|---|---|
| anim_probe.py / fc_probe2.py / settle_sweep.py | 导航/落地 settling 探针（nav_*.json 出处） |
| wedge_test.py | 楔形输入时序测试 |
| weapon_hold.py / weapon_vs_idle.py | 写 0x00AA 武器寄存器后按住/对照采集 |
| weapon_blobs.py / weapon_bullets.py / weapon_measure.py / weapon_sheet.py | 弹幕 blob/子弹测量与 QC 拼表 |
| detector_search.py / detector_pick.py / detector_palette.py / detector_calib.py | 检测器区域/颜色/阈值自动标定 |
| detector_dist.py / detector_matrix.py / detector_apply.py | 正负例分布/矩阵/应用复核 |
| pack_calib.py / pack_write_detectors.py | 标定结果写回 showcase 包 |
| bundle_frame_check.py / bundle_mapping_check.py / bundle_zoom_check.py | bundle 帧数/映射/放大抽帧校验 |
| detector_final.json / detector_dist.json / detector_matrix.json / pack_calib.json / weapon_detector_calib.json | 标定产物（正过全负拒） |

## megaman_洛克人/（洛克人 FC · 探针级）

成功证据：`F:/taspipe_scratch/megaman/`、`mmhd/` 的 base.state + 逐段截图（boot→可控制 gameplay）。
要素级采集未做（P2b 泛化待启动）。probe_mmhd.py 对应 megamanhd.nes（HD 改版），其余对应 mega_man_usa.nes。

| 脚本 | 用途 |
|---|---|
| probe_boot.py / probe_enter.py / probe_dump_enter.py | boot→标题→进关输入链 |
| probe_input.py / probe_ingame.py / probe_gameplay.py | 输入锁定期/可控制性判定 |
| probe_clearflag.py / probe_guts.py | 清旗/关卡状态 RAM 探针 |
| probe_mmhd.py | HD 改版对照探针 |

## nekketsu_soccer/（热血足球联盟 CN jf · 导航成品级 / 持球 base 成品级 / 必杀触发求解中）

成功证据：`04-游戏资源库/TAS输入录像库/验证/t3_soccer2_moves/probe9_cn/`（nav2–nav7 逐轮截图 + kickoff.state + kickoff.png）；
`probe10_cn/`（OAM 球权闸门求出的 possess_base.state + chase_log + super_timeline）；
`probe11_menu/roster_zoom.png`（游戏内 12 人背号名单：默认 1P MF=元永#1，国夫=#9 FW）。
必杀全清单（证据级）：`_工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md`。
**生产函数在 `taspipe/universal_authoring.py`**：`soccer2_oam_parse` / `soccer2_dir_toward` /
`solve_soccer2_possession_base`（追球控制器+OAM 球权闸门+金手指+脱压+必杀触发窗）；selftest `test_soccer2_oam` 14 断言含反证格。

| 脚本 | 用途 | 状态 |
|---|---|---|
| probe_soccerctl.py | 控制/暂停会话探针 | 探针级 |
| soccer2_base_cn.py | 导航→KICK OFF 冻结→生产求解器求持球 base | 成品级导航（11-14：A 确认休息室/横幅判据/双后缀） |
| soccer2_solve_cn.py | 直调生产求解器（kickoff 资产→possess_base+super 时间线） | 成品级入口 |
| soccer2_possess_chase.py | RAM 反馈追球控制器原型（2 步持球，已并入生产） | 已并入生产 |
| soccer2_oam_probe.py / soccer2_ram_probe.py | OAM/RAM diff 标定探针（球 tile/号码标记/队伍 palette） | 探针级（结论已进生产常量） |
| soccer2_ctl_probe.py / soccer2_ctl_probe2.py | 受控球员/暂停假设探针（证实金手指尾 Start 再暂停） | 探针级 |
| soccer2_dribble_probe.py / soccer2_trigger_probe.py | 带球/触发正反例 dump（像素差假阳性案发现场） | 探针级（判据已作废改 OAM） |
| soccer2_idle_supers.py | 60s 无输入扫描 AI 必杀（难度判定证据：0 事件⇒疑容易难度） | 探针级 |
| soccer2_menu_probe.py / menu_probe2.py / meet_probe.py / swap_probe.py | 休息室/战术/会议/换位菜单光标图探针 | 探针级 |
| soccer2_wl_probe.py / soccer2_wl_chase.py | wl 变体导航图（队选 Start/设置 Start/VS 自动→休息室/开球 Start）+ 追球语义 | 探针级（wl_field.state） |
| soccer2_hack_buttons.py | hack 按键图（B 射/A 传/AB 跳/Select 换人）+ KICK OFF 锁定实证 | 探针级（hack_field.state，决定性） |
| soccer2_hack_probe.py | hack 净持球 base（holder_team==1 且 \|holder_dist−dist\|<0.6 且 opp>40）+ 触发链拼表 | 成品级 base（hack_possess.state） |
| soccer2_possess_scan.py | 持球判据扫描（假持球/邻敌反例） | 探针级（判据已进生产） |
| soccer2_vs_apex.py / vs_jumpcal.py / vs_ballhigh.py / vs_sweep.py | 挑球/跳跃语义 1 帧分辨率测量（方向+AB=纯挑球、静止 AB=人跳球不动、hack 无人球同跳） | 探针级（决定性） |
| soccer2_diff_ram.py | mode 屏 ←→/Down RAM 逐字节 diff（←→=人数列、Down=光标行、$716-767=OAM 噪声） | 探针级（决定性） |
| soccer2_difficulty_row.py | Down 梯×6 + ←→ 实证难度行不可达（光标在模式行回绕，简单/普通/困难无光标） | 探针级（决定性，难度锁定） |
| soccer2_base_diffnav.py | 难度盲操导航尝试（Left×2 归零再 Right×N，行为反证） | 探针级 |
| soccer2_user_route.py | 用户路线：开球传→要回传→接球瞬间立即触发+逐帧球权（证"被抢/动作晚"假说不成立） | 探针级（received.state，决定性） |
| soccer2_aerial_combo.py | 用户空中连段：静止AB挑球→隔d2二跳接→隔d3空中B/AB，12组时序×6帧（证"挑→接→空中及时AB"在hack不成立） | 探针级（aerial_sheet 12×6，决定性） |
| soccer2_unlock_code.py | 暂停秘技 A3B1A3B1A7 正确复核：暂停→输入→抓得分框"必杀技OK"签名（probe18 曾看错签名） | 探针级（before/coded/unpaused_box） |
| soccer2_unlock_timing.py | 暂停秘技按压节奏扫 (2,2)/(4,4)/(6,8)/(2,6)/(8,4)×3 offset 抓 OK 瞬态 | 探针级（timing_sheet） |
| soccer2_correct_triggers.py | 攻略正确触发族：平地步数B/跳最高点B/前B头球/后B倒钩 12 变体×5帧（中场） | 探针级（trigger_sheet 12×5） |
| soccer2_inbox_super.py | 进禁区+高空球B/前B/燕返B/最高点B 9 变体（possess 全 True） | 探针级（inbox_sheet 9×4） |
| soccer2_catch_fine.py / soccer2_wl_catch.py | 用户静止双AB接球+B 逐帧 t1..20（jump/wl）：接球不成形=非小辫子 | 探针级（catch_fine，角色门控证据） |
| soccer2_wl_unlock.py | wl 基版暂停秘技复核（未进暂停，计时照走，待复核） | 探针级（wl_unlock_box） |
| soccer2_live_capture.py | **真人实时操作捕获**：刷 BizHawk 键位(WASD+JKL;)→`joypad.get(1)` 逐帧录真人输入→`taspipe.fceux.to_bk2` 生成 .bk2→`StateSession(movie=)` 确定性回放；**11-15 复验 selftest 9/9**（本表原先记的 9/9 当天实跑只有 3/9，见下方坑） | 成品级（live.bk2/live_end.state/live_frames.json，跨游戏可复用） |

### nekketsu_soccer 必杀触发证据链（11-15 更正：撤回"版本/ROM 阻断"，改为角色/位置/输入问题）

**11-15 用户更正+攻略证实**：指令跨版本基本不变、变的是招式样式；**一个角色只懂一个必杀，须换角色采全**（日本队12人+11对手队=23）；
头球/倒钩时机另有讲究。故 11-14 的"CN/hack 族不可触发/需日版原版"结论**撤回**——先前负证据可由错角色+错位置+错输入解释：
- **燕返=方向+A+B 仅小辫子(赖常)独有** ⇒ "hack 无人球同跳"是角色特异（默认控的非小辫子），非版本删除。
- 正确触发族=跳最高点B / 前B头球 / 后B倒钩 / 平地步数(3或8)后B / **高空球在禁区必出必杀**；先前全在中场且输入不符。
- 暂停秘技 A3B1A3B1A7 签名=**得分框"必杀技OK"**（解锁全员），非燕返翻转 ⇒ probe18 看错签名误判无效。
复核实测（仍无必杀，但已用对部分输入）：probe36/37 暂停成功、5 节奏未现"必杀技OK"(jump)；probe38 平地/最高点B/前B/后B 12 变体中场仍普通球。
**下一步=角色感知采集（已换成真人操作捕获）**：不再由我猜连段——真人打，工具录。
`soccer2_live_capture.py` 实测：BizHawk 2.8 Lua **没有 `movie.record`**（nil），`client.speedmode` 只收数字（传 "normal" 直接 LuaScriptException），
`joypad.get(1)` 返回**裸按钮名**且含真人键盘当前状态 ⇒ 逐帧采样 `joypad.get(1)` 就是输入录像；停录再落 `live.bk2` 与 `live_end.state`。
自测：合成真实按键 D/J+K/L/; → 录到 Right/A/B(同帧20)/Select/Start，闸门 9/9 PASS，回放 300 帧出图 15 张（8 张互异，证明确实在放）。
其余仍待验：换/传至目标角色(含小辫子)+进禁区+按该角色步数/高空球触发；暂停秘技换节奏/变体再验。
历史探针（保留备查，结论已更正）：难度行不可达(`soccer2_difficulty_row.py`)、跳跃语义(`vs_jumpcal/vs_apex`)、
probe33 用户路线、probe34 空中连段、probe18 秘技(看错签名)。
证据目录：`F:/taspipe_scratch/soccer2_diff{,row}/{jf,jump}/`、`probe30_wl/31_hackjump/32_hackse/33_userroute/34_aerial/36_unlock/37_timing/38_triggers/`。

### nekketsu_soccer 内存逆向批次（11-15，为"练必杀时别被打断"做的因果定位）

基线件：`soccer2_practice_setup.py` 导航到 KICK OFF 冻结画面存 `field.state`，并证明**冻结即零漂移**
（存完再跑 60 帧，精灵探针逐字节相同）⇒ 之后"写一个字节看变化"是因果而非相关性。
产物目录 `F:/taspipe_scratch/soccer2_practice/`（`field.state`、`entity_map.tsv`、`traj.bin`、`glue_find.tsv`、`statue.tsv`）。

| 脚本 | 结论（含负结果） |
|---|---|
| `soccer2_poke_sweep.py` | 2048 字节逐字节 +0x40 因果扫描：`#ctrl_diff 0`（冻结态零漂移），**114 个字节有可见效应** |
| `soccer2_poke_attr.py` | +1 微增定倍率/轴向：`$0314`=球X(1:1)、`$0386`=球Y(反向)、`$0F0/$0F2`=镜头X/Y |
| `soccer2_poke_entities.py` / `soccer2_poke_shots.py` | 按"移动精灵集合"聚类 + 逐候选截图（`montage9.png` 人眼复核） |
| `soccer2_entity_map.py` | 逐字节报"屏幕上哪团人跳到哪"：74 有效地址聚成 13 团；`$3F6/$42E` 成对(X/Y 差 0x38)，冻结态原值全 0 ⇒ 事件脉冲/输出量，**不是**逐实体坐标 |
| `soccer2_traj_dump.py` | 全 2KB 逐帧轨迹（Right/Down/空闲三段）：只有 9 个字节平滑移动，人物坐标不在 `$314-$340` |
| `soccer2_follow_probe.py` | 跟球走的只有 `$314/$316/$318/$323` = **球自己的多份副本**（否掉 19 字节记录表假说） |
| `soccer2_glue_test.py` | 黏球失败并有原因：镜头跟球 ⇒ 写球的屏幕坐标推走的是整个世界（球屏幕 x 恒 80-95，间距 30-63px） |
| `soccer2_glue_find.py` | 行为判据 20 个候选写入 `$314`：6 帧后球全落回同一点 (94,88) ⇒ **比赛中 `$314` 是只读输出量**；同时证明带球时球本来就贴脚 8px，"黏球"需求不成立 |
| `soccer2_statue_test.py` | **可用能力**：每帧清 `$3F6-$465` ⇒ 对照组 6/6 团会动，清零组 0/6 会动（残差 ±8px 是镜头）＝全场雕像；但 1P 一起冻住，且找不到"只冻对手"的槽位（`$3F6+` 与输入无相关性：Right 段平均速度 ±0.4，空闲段反而 +32） |

**这批的总结论**：内存路线能做的只有"全场静止"（可当暂停替代/摆位用），做不到"只去掉对手"——
要精确点名对手得进 6502 反汇编找实体表，不是继续猜字节。
**"搓不出必杀"的正解是宏**：`_工具脚本/taspipe/游戏包/nekketsu_soccer2_{shots,honest}.showcase.json`
已带逐必杀的逐帧 trigger 宏与检测判据（apex_super_shot / overhead_bicycle_shot / diving_header_shot /
ground_power_shot / heel_lift_toss / lob_pass / player_jump），不需要人手掐时机。

## 来源库/（复古游戏文献检索系统 · 成品级，跨游戏通用）

成功证据（2026-11-18 实跑）：`py -3 -u -m taspipe.sources_selftest_gates` => **66/66**（63 闸门 + 3 真实文件反查）；
`--inject` 后全量 `py -3 -u -m taspipe.selftest` => **589/589**（注入前基线 523/523，**+66**）；
真实库 `sources audit` => 8 pass / 0 fail / 1 inconclusive（79 来源、19 包、79 要素有支撑，其中 **43 个只有快照级支撑**）。
闸门口径与踩坑见根目录 `测试问题与闸门说明书.md` §27；操作路线见 `taspipe/要素盘点路线模板.md` S1/G1。

| 件 | 位置 | 用途 |
|---|---|---|
| sources.py | **生产原件** `_工具脚本/taspipe/sources.py`（43,960B，不复制副本以免两份真相） | route/log/ingest/claim-absence/render/audit/recheck/show |
| sources_selftest_gates.py | **生产原件** `_工具脚本/taspipe/sources_selftest_gates.py`（26,499B） | 66 条闸门 + `--inject` 幂等挂载 |
| sources.json | `_工具脚本/taspipe/游戏包/来源库/sources.json` | 唯一主数据（79 条，15 层×15 要素×13 平台；★11-18 新增 MOBILE 关住手游错配） |
| migrate_pack_sources.py | 本目录（16,850B，一次性迁移脚本副本） | 把 15 个知识包的自由文本 sources 迁成结构化引用；幂等，备份在 `游戏包/_备份_来源迁移前_20261118/` |
| 复用说明.md | 本目录 | 换游戏怎么填槽、探针隔离契约、命令清单 |

## 知识库/（本地文献正文检索 · 成品级，跨游戏通用）

成功证据（2026-11-18 实跑）：`py -3 -u -m taspipe.kb_selftest_gates` => **60/60**（56 编号闸门 + 4 真实文件反查）；
`--inject` 后全量 `py -3 -u -m taspipe.selftest` => **649/649**（来源库注入后基线 589，**+60**）；
`kb build` => **562 块 / 19 份入索引 / 6 份显式排除**，再跑一次 19 份全复用（词数/字节随说明书自身正文变动，以 `kb show` 现查为准）；
`kb audit` => 6 pass / 0 fail / 1 inconclusive（4 个版本没有 verified_read+authoritative 正文）。
身份门 A/B：同一条 `俱乐部飞标 ↓↘→+B或D`，问 `kof98um` => pass；问 `kof98eck` => inconclusive
（reason 点名最高分是 98UM 跨版本表 78.6 分、本版本权威件只在 26.3 分位）。
闸门口径与本轮 6 个真缺陷见根目录 `测试问题与闸门说明书.md` §28。

| 件 | 位置 | 用途 |
|---|---|---|
| kb.py | **生产原件** `_工具脚本/taspipe/kb.py`（不复制副本以免两份真相） | clean/chunk_prose/chunk_table/tokens/build/query/audit/show |
| kb_selftest_gates.py | **生产原件** `_工具脚本/taspipe/kb_selftest_gates.py` | 60 条闸门 + `--inject` 幂等挂载 |
| corpus_map.json | `_工具脚本/taspipe/游戏包/知识库/corpus_map.json` | 语料唯一主数据：正文绑 source_id + revision（版本身份）+ authority（四档权威级） |
| index.json | 同目录（GENERATED，原子写） | BM25 倒排；每块带 chunk_id/path#L/source_id/status/authority/text_sha；`pipeline` 字段守清洗/分词/切块版本 |
| 复用说明.md | `来源库/复用说明.md` | 来源库 + 知识库合并说明：命令清单、填槽步骤、探针隔离契约、不许做的事 |

## 通用与联线/

| 脚本 | 用途 |
|---|---|
| verify_render.py | 成片×素材逐相位像素闸门（16 相位分布判据）。**生产原件**在盘点视频项目 `pipeline/gameplay/verify_render.py`，此处为复用副本 |

## 复用注意（踩坑闸门；总路线与闸门见 `_工具脚本/taspipe/目标与实施路线.md`）

- 中文路径进 Lua io 会坏：状态/截图先落 ASCII 工作目录（`StateSession.use_state`）。
- `StateSession.save(name)` 自己补 `.state`；传带后缀名字会落 `*.state.state`。
- 金手指尾 Start 可能在作弊成功自动恢复后**再次暂停**：setup 后必须活 play 自检。
- 判定"宏有效"必须同总帧数中立对照 + 差异像素数阈值（天气粒子 ~40px 会假阳性）。
- 联赛首场场地可能是土场：场地判据别写死绿茵。
- **开录即清空旧录制**：`soccer2_live_capture.py start` 见到 `inputs.tsv` 已有 >2 帧就拒启，须先归档或显式 `--force`；
- **★11-15 坑：合成按键全空 = 抢前台静默失败，不是录制器坏。** `selftest` 当天实跑 3/9：录到 287–331 帧但
  `按下帧数={}`。根因是跨进程 `SetForegroundWindow` 受 Windows 前台锁限制返回成功也没用，
  `SendInput` 投出去了而 BizHawk（WinForms 轮询键盘）一帧都收不到；`SendInput` 的返回值同样骗人。
  修法 = `focus()`：`AttachThreadInput(前台线程, 目标线程, TRUE)` 后 `ShowWindow(SW_RESTORE)` +
  `BringWindowToTop` + `SetActiveWindow` + `SetForegroundWindow`，再**轮询 `GetForegroundWindow()==hwnd` 才算到手**。
  复验：9/9，且 `replay` 抽样 5 张里 4 张互不相同（证明 .bk2 真在放，不是黑屏充数）。
  ⇒ 通用规矩：**凡是"注入输入"的自检，必须把"窗口到手了吗"单独断言**，否则坏的是采集端却会被读成"游戏没反应"。
  自测跑独立目录 `soccer2_live_selftest`，子命令分派写死 `elif` 且未知子命令直接报错，**不许 else 兜底**
  （11-15 就是 else=selftest() 把用户 451 秒真人录制清成了 309 帧合成帧，无备份可恢复）。
- 判"某字节能不能控制某对象"只认行为判据：写入后跑几帧看它落不落回原位（`soccer2_glue_find.py` 那套），
  数值/轨迹"接近"是假证据（`$07xx` 那批只是凑巧落在球的数值区间里）。
- 冻结基线才配做因果归因：先证零漂移（`soccer2_practice_setup.py` 存完再跑 60 帧探针相同），
  否则写一个字节的变化里混着自然演化。
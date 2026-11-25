# 《恶魔城：晓月圆舞曲》中文版 RAM 校准：缺口与复用方案

更新：2026-11-25  
适用 ROM：`F:/BaiduNetdiskDownload/rom/gba/恶魔城晓月圆舞曲.gba`  
ROM SHA1：`40aab076a528f52e93260bb98d91a40039e0da02`  
实测核心：BizHawk 2.11.1 / `BizHawk.Emulation.Cores.Nintendo.GBA.MGBAHawk`

## 1. 当前结论

已从“候选地址可写”推进到三条真实 gameplay 正反例，以及一条真实物品消费正反例：

1. 红魂 ID=4 半鱼人：Up+B 水流；空红魂无水流，MP 80→69 / 80→80。
2. 红魂 ID=24 魔鸟：真实菜单装备、关闭回游戏、重开持久化；Up+B 出现翅膀状刀刃，同状态清空槽后消失；当前规范配方实跑为 MP 80→56 / 80→80，历史战斗样本为 80→59 / 80→80，早期菜单配方样本为 80→57 / 80→80。不同样本不固定化为统一消耗常量。
3. 黄魂 ID=22 骷髅战士：真实菜单装备、关闭回游戏、重开持久化；同一僵尸、同一帧、同一武器，近战伤害 22；空槽伤害 17。
4. 物品 ID=1 回复药：人工置入数量 1 后从真实 ITEM USE 菜单使用；HP 100→200、`0x13288` 数量 1→0；满 HP 320 时拒绝使用且数量保持 1。只证明该物品的消费点，不证明真实拾取或整段物品数组。

GBA 平台生产闸门仍为 `showcase.PLATFORM_PROFILES["GBA"]["verified"] = False`。上述字段不能自动解锁整个平台或未验收字段。

## 2. 地址与验收层级

地址均为 mGBA `EWRAM` 域内偏移；不要把 `0x01325D` 再写成 `0x0201325D` 传给 EWRAM 域。

| 字段 | 地址 | 宽度 | 当前层级 | 证据与边界 |
|---|---:|---:|---|---|
| 红魂装备 ID | `0x1325D` | 1 | gameplay | 0=空；ID=4、24 已做真实输入正反例 |
| 蓝魂装备 ID | `0x1325E` | 1 | gameplay | 0=空；ID=4 布艾尔 R 双火焰 |
| 黄魂装备 ID | `0x1325F` | 1 | gameplay | 0=空；ID=22 对僵尸伤害 22，空槽 17 |
| Lv | `0x1326D` | 1 | menu | STATUS 直写显示；99 是示例，不是实测上限 |
| 当前 HP | `0x1326E` | 2 LE | menu | STATUS/HUD 显示变化；上限未验 |
| 当前 MP | `0x13270` | 2 LE | menu + 消耗 | 菜单显示；半鱼人、魔鸟消耗正反例 |
| 最大 HP | `0x13272` | 2 LE | menu | 上限未验 |
| 最大 MP | `0x13274` | 2 LE | menu | 上限未验 |
| 基础 STR | `0x13276` | 2 LE | menu | 不是 STATUS 实时总 STR；黄魂不会直接改写它 |
| CON/DEF | `0x13278` | 2 LE | menu | 游戏标签为 CON；上限未验 |
| INT | `0x1327A` | 2 LE | menu | 旧字典误标为 HP，已纠正 |
| LCK | `0x1327C` | 2 LE | menu | 上限未验 |
| EXP | `0x13280` | 4 LE | menu | 社区宽度；仅显示验收，未逐字节验收 |
| GOLD | `0x13284` | 4 LE | menu | 社区宽度；仅显示验收，未逐字节验收 |

`verified=true` 只表示该地址在标明的层级成立，不表示所有写法、上限或玩法用途都已验证。

### 已废弃/不得继续使用的外推

- 装备槽相对 USA 的 `-0x0C` 不能外推到 HP、MP、统计区或魂库存。
- 旧 `hp=0x1327A` 实际是 INT；旧 `mp=0x1327E` 无证据。
- 不能把 `0x13286/0x13287` 当已装备魂寄存器；真实 Up+B/R 已反证。
- RAM 可写、菜单变化、装备持久化、玩法触发是四层不同证据。

## 3. 已验收的菜单序列

从干净 gameplay 状态开始，宏 token 用逗号分隔，每个 token 一帧。

- 红魂预览：`Start, A, A`；预览态每次单帧 Down 使 ID 增加 2；12 次 Down 后 A 确认为 ID=24 魔鸟。
- 黄魂预览：`Start, A, Down, Down, A`；预览态 11 次 Down 后 A 确认为 ID=22 骷髅战士。
- 普通列表 `B,B` 回游戏；预览页 `B,B,B` 回游戏。
- 基态库存已为全魂；不要再补写 `0x1336C=1`，选择性库存会改变候选起点，曾使 11 次 Down 错选 ID=23。

标定报告：`证据/晓月圆舞曲/menu_steps_report.json`。

## 4. 魔鸟、飞骷髅、飞冰魂的身份边界

- 中文菜单 ID=24 名“魔鸟”，描述“投出刀刃般的羽毛”。
- 美版 matching decomp 对应英文名 Harpy / Wing Cutter，默认 Up+B 触发。
- 社区同字节还列出“狼人”；它与“飞骷髅”不是同一个中文名。
- “飞冰魂”是用户俗称，目前没有可靠来源证明它就是 ID=24 魔鸟，更不能与“飞骷髅”混用。
- 因此项目记录为“魔鸟/Wing Cutter 的玩法已验收；飞冰魂别名未确认”。

ID=24 菜单 USE 显示 25；历史战斗样本实测 MP 80→59（消耗 21），早期菜单配方为 80→57（消耗 23），当前规范配方为 80→56（消耗 24）。差异尚未解释，不能把菜单 USE 或某一次实测值直接写成固定实际 MP 消耗。

## 5. 黄魂 ID=22 的验收与纠错

- ID=21 是石像魔，社区描述为石化攻击无效，不是 STR+1。
- ID=22 是骷髅战士，社区描述为 STR+1。
- ID=22 装备后 `0x13276` 基础 STR 仍为 10；STATUS 菜单实时显示 STR 14。两者不矛盾，不能用基础字段不变判黄魂无效。
- 有效 gameplay 验收位于“荒城回廊”：从同一稳定状态只改黄槽，向右 80 帧后 B 攻击 5 帧。第 90 帧伤害数字 ID=22 为 22、空槽为 17；攻击前画面完全一致。
- 早期近战探针的“正例”漏写 ID=22，且误打 Graham 剧情 NPC，故全零差分不能作为黄魂无效证据。该错误已纠正，不作验收依据。

gameplay 报告：`证据/晓月圆舞曲/yellow_gameplay_report.json`。

## 6. 社区与 GitHub 复用成果

### 百度社区金手指表

来源：`https://zhidao.baidu.com/question/266472901.html`

复用价值：

- 统计字段地址与当前菜单实测一致。
- 给出红、蓝、黄魂库存分组起点。
- 给出魔鸟、石像魔、骷髅战士的中文名称与效果描述。

限制：页面没有 ROM SHA1、汉化版标识或内核信息；所有地址仍须按当前 ROM 重验。完整取证见 `来源库/取证/castlevania_aria_gba_baidu_cheats_20261125.md`。

### GitHub `testyourmine/cvaos`

来源：`https://github.com/testyourmine/cvaos`

复用价值：

- USA matching decomp，不是当前中文版，但提供结构关系与算法。
- 魂库存低/高 nibble 解码。
- 已装备魂在菜单计数中额外加 1。
- 红/蓝/黄/能力魂数量 `55/24/35/8`；`0x8` 是能力魂循环上界，不是末项索引。
- 红魂触发流程及“当前 MP 必须严格大于消耗值”的规则。
- 可继续复用的库存、转移、施法函数，不必从零重写解码器。

限制：USA ROM SHA1 为 `abd71fe01ebb201bcc133074db1dd8c5253776c7`，与当前中文版不同；绝对地址不可直接搬。完整取证见 `来源库/取证/castlevania_aria_gba_cvaos_20261125.md`。

### 通用工具

优先复用 BizHawk RAM Search / Watch / Lua、ScriptHawk、Libretro mGBA 内存监控与 cheats。本次按“可直接调用 / 仅候选或辅助 / 不可直接调用”完成分级取证，见 `来源库/取证/ram_calibration_community_tooling_20261125.md`。

- 可直接使用：BizHawk `memory/mainmemory` 分域读写、`joypad` 逐帧输入、TAStudio 输入提交接口、核心已支持的 `addcheat/removecheat`。
- 仅候选或辅助：mGBA-http（第三方、网络延迟，不适合逐帧唯一执行器）、ScriptHawk（游戏专用模块集合，本次未命中本作）、RAM Watch GUI。
- 不可直接调用：`openramsearch/openhexeditor` 只开 GUI；RAM Search 没有完整稳定条件/结果 Lua API；mGBA Qt 搜索/金手指完整操作仅 GUI；mGBA 官方 Lua 无搜索筛选或金手指管理 API。
- 本作绑定中文 SHA1 `40aab076…` 与 USA SHA1 `abd71fe0…` 的现成自动菜单 Lua/宏，本次 GitHub 代码检索未命中。受登录与索引限制，不能声称不存在；项目当前宏为自有并已固化到规范配方。
- 金手指边界：Code Breaker 仅未加密写与 4 型半字滑动写候选，条件码等阻塞；Game Genie 只分类未解码；IPS/BPS 尚未接入。不得把这些候选当作 gameplay 证据。

## 7. 精确缺口

### P0：身份与证据归档

- “飞冰魂”是否指 ID=24 魔鸟：缺可靠中文俗称到 ID 的直接来源。
- ID=24 菜单 USE 25 与不同样本消耗 21/23/24：缺当前版本函数或受击/计时条件解释。
- 将红魂、黄魂报告与关键截图固化到项目；已完成，见 `证据/晓月圆舞曲/`。

### P1：魂库存

候选范围：

- 红魂 `0x13310–0x1332B`，55 项。
- 蓝魂 `0x13348–0x13353`，24 项。
- 黄魂 `0x13362–0x13373`，35 项。
- 能力魂候选 `0x13386–0x13389`，8 项；来自 USA 结构 `0x13392` 减已命中的 `0x0C` 位移，尚未经中文版消费点或玩法验收。

缺口不是“能否写入”，而是：

1. 中文版对应消费函数在哪里。
2. 每组首地址、末项和间隔是否与 USA 一致。
3. 拾取、消耗、删除、转移时各 nibble 如何变化。
4. 已装备魂是否只在菜单计数时额外加 1，还是也参与其他逻辑。
5. 能力魂候选 `0x13386–0x13389` 的逐 nibble 消费点与真实被动效果；旧候选 `0x133D3/0x133D7/0x133DB` 无证据，已废弃。

### P1：物品清单与背包消费

已收敛一个真实消费样本：

- 物品 ID=1 是回复药，数量字节 `0x13288`。
- HP 100 时从 ITEM USE 菜单按 A：HP 100→200，数量 1→0。
- 满 HP 320 时同样输入：HP 320→320，数量保持 1；这是合法规则，不是补丁失败。
- 证据：`证据/晓月圆舞曲/item_use_report.json`。

剩余缺口：

- ITEM/EQUIP/SOUL 菜单清单已定位到 USA 地址减 `0x0C` 的显示层；这不等于背包数组或消费函数。
- `0x13288` 起 32 项的完整边界、其余物品编码、真实拾取/删除/装备状态仍未验收。
- 缺中文版新增、删除、使用、装备函数的对应地址。
- 下一步应复用 `cvaos` 相关函数，先找中文版消费点，再做菜单与 gameplay 双层验收。

### P2：源码与外部交叉核验

- 补全 `cvaos` 玩家结构、魂结构、物品结构定义。
- 核验 `sub_08021344`、`sub_08032D58`、`sub_08034624` 的完整汇编与调用关系。
- DataCrystal、Fandom、StrategyWiki 尚未形成本作可用 RAM 表；保留为候选，不把“未找到”写成“不存在”。
- 统计字段 `max=99/999/9999999` 目前是示例值，不是游戏真实上限；需要真实升级/成长或溢出测试。

## 8. 下一步复用顺序

1. 从 `cvaos` 的库存函数建立测试预言机，先只做解码与数量正反例，不直接改连续内存。
2. 用菜单真实拾取/使用动作前后 EWRAM 差分定位中文版消费区，并以等级地址作正控制。
3. 先验收一个物品的数量增减，再扩展装备数组；拒绝用“RAM 可写”替代消费证据。
4. 补齐能力魂绝对地址后，单独验收每个被动；不借黄魂 ID=22 的通过外推其他黄魂。
5. 只有当前 ROM、当前核心、真实画面正反例全部通过的字段才晋升；GBA 平台闸门另行评估。

## 9. 关键证据文件

- `证据/晓月圆舞曲/menu_steps_report.json`
- `证据/晓月圆舞曲/wingcutter_combat_report.json`
- `证据/晓月圆舞曲/wingcutter_combat_diff_sheet.png`
- `证据/晓月圆舞曲/aria_showcase3_report.json`
- `证据/晓月圆舞曲/aria_showcase3_reel_event_01.png`
- `证据/晓月圆舞曲/aria_showcase3_reel_event_02.png`
- `证据/晓月圆舞曲/aria_showcase3_reel_event_03.png`
- `证据/晓月圆舞曲/aria_showcase3_reel_event_04.png`
- `证据/晓月圆舞曲/wingcutter_mp_report.json`（历史报告；其中黄魂基础 STR 判据无效，不作为拒绝黄魂 ID=22 的依据）
- `证据/晓月圆舞曲/yellow_gameplay_report.json`
- `证据/晓月圆舞曲/item_use_report.json`
- `F:/开源掌机教程/04-游戏资源库/TAS输入录像库/状态资产/castlevania_aria_gba/aria_us_40aab076/r20261125T120000/evidence/state_gate_empty_red.json`
- `F:/开源掌机教程/04-游戏资源库/TAS输入录像库/状态资产/castlevania_aria_gba/aria_us_40aab076/r20261125T120000/evidence/state_gate_yellow_damage_route.json`
- `证据/晓月圆舞曲/potion_full_hp_rejected.png`
- `证据/晓月圆舞曲/potion_damaged_hp_menu.png`
- `证据/晓月圆舞曲/potion_damaged_hp_consumed.png`
- `证据/晓月圆舞曲/red24_menu.png`
- `证据/晓月圆舞曲/yellow22_menu.png`
- `证据/晓月圆舞曲/red24_up_b_f0012.png`
- `证据/晓月圆舞曲/red24_clear_up_b_f0012.png`
- `证据/晓月圆舞曲/yellow22_damage22.png`
- `证据/晓月圆舞曲/yellow0_damage17.png`
- `证据/晓月圆舞曲/ram_calibration_red24_installed_v5/report.json`
- `证据/晓月圆舞曲/ram_calibration_red24_package_v6/report.json`
- `来源库/取证/ram_calibration_community_tooling_20261125.md`

## 11. 通用流水线、v5/v6 与第二游戏验收

### 当前规范配方与证据

规范配方：`F:/开源掌机教程/_工具脚本/taspipe/校准配方/castlevania_aria_cn.red24.json`。宏链已固化：真实菜单装备 ID=24（353 帧）→ 关闭回 gameplay（112 帧）→ 重开菜单确认持久化（95 帧）。`prepare` 每步同时有 RAM 断言和画面锚点，禁止用补丁冒充装备。

正式 case `red24_vs_empty` 从 `red24_game` 分叉：正例保持 ID=24，负例在同一基态一次性清空红槽；两者都执行 `Up+B` 30 帧。RAM 断言为正例 ID=24、MP<80，负例 ID=0、MP=80；第 12、20、final 帧必须出现真实画面差异。

| 版本 | 状态来源 | 结果 | 实测与人工画面 |
|---|---|---|---|
| installed_v5 | 项目根态经真实菜单链形成 | pass | 正例 MP 80→56，负例 80→80；第 12/20/final 帧差 752/743/419 像素；正例有两组羽刃，负例只有基础攻击对应效果，不能表述为空槽完全无动作 |
| package_v6 | 新 revision 的 `clean_gameplay` 经同一菜单链形成 | pass | 与 v5 读数、像素差完全一致；9 张关键 PNG 的 SHA256 相同，v5 人工验收覆盖 v6；再次运行同一命令 `reused=true` |

v6 缓存键：`3ba70299f3d615044454a720de621c9bd769b72af3194c1f736668e2dc10d6b2`。`verified_fields` 仅含 `red_soul_equipped_id=0x1325D` 与 `current_mp=0x13270`；不外推全部红魂，不确认“飞冰魂”别名。

正式归档：

- `F:/开源掌机教程/_工具脚本/taspipe/游戏包/证据/晓月圆舞曲/ram_calibration_red24_installed_v5/`
- `F:/开源掌机教程/_工具脚本/taspipe/游戏包/证据/晓月圆舞曲/ram_calibration_red24_package_v6/`

各含 report、完整 recipe、manifest 与 29 份 evidence，SHA256 可复核；旧归档未覆盖。

### 新状态包 revision

`F:/开源掌机教程/04-游戏资源库/TAS输入录像库/状态资产/castlevania_aria_gba/aria_us_40aab076/r20261125T025337/`

从旧 revision 复制后新增 `clean_gameplay`、`red24_menu`、`red24_game`、`red24_reopen`，每套状态登记 ZIP 条目 CRC 内容指纹；收入 v5 配方、报告、manifest 和关键截图，并记录 `calibration:red24_clean_gameplay_installed_v5=pass`。旧 revision 保持原样。

该新包目前是 `resources_ready`，不是 `state_verified`：根态和菜单中间态尚未完成独立跨进程状态验收，且 GBA 平台总闸门仍关闭。v6 运行后没有继续改写此包，避免状态包内容变化反过来使 v6 缓存键失效。revision 字符串 `r20261125T025337` 在字典序上小于历史 `r20261125T120000`，当前规范配方用精确 revision，不受影响；未来依赖 `latest()` 的新 revision 应使用更大的时间戳。

### 缓存与验证边界

缓存键覆盖 `ram_calibration.py`、`statejump.py`、`tas_replay.py`、完整配方、ROM SHA1、EmuHawk、根态/case 独立基态、GBA `mgba.dll` 与状态包 JSON。协议或状态变化会使旧通过报告失效。RAM-only `attempt` 现在也传递 `probe_domain` 到 p10；否则 GBA dump 会误用默认域，该缺陷曾使 EWRAM 红魂 ID 读错。

离线自检 36/36 通过，并已接入共享 `python -m taspipe.selftest`。关键回归覆盖：准备阶段禁止补丁、claim 不得外推断言地址、逐帧补丁拒绝、零长度 RAM 拒绝、内存域传递、独立基态、隔离槽、协议源码缓存失效、证据 SHA256 与非空归档拒绝覆盖。

### 第二游戏复用结果

同一配方协议已用于 NES《魂斗罗》，不是为每个游戏重写执行器：

- `weapon_spread_vs_rifle_final_v3`：pass，`current_weapon=0xAA`；同基态散弹与步枪真实弹道不同。
- `movement_right_vs_neutral_final_v2`：pass，故意 `verified_fields=[]`；只证明持续 Right 与中立产生真实位移，不把场景状态寄存器误命名为移动寄存器。

正式归档位于 `证据/魂斗罗/weapon_spread_vs_rifle_final_v3/` 与 `证据/魂斗罗/movement_right_vs_neutral_final_v2/`，各含完整配方、报告、manifest 和逐帧 evidence。换游戏仍需提供 ROM/核心身份、稳定根态、真实菜单/导航宏、地址断言与画面预言机；执行、正反例、缓存和归档机制可直接复用。

### 仍未完成

- 中文版魂库存、能力魂、完整物品数组与真实拾取/删除函数的逐项玩法验收。
- 新 Aria revision 根态与中间态的独立跨进程状态验收；通过前不得标为 `state_verified`。
- Game Genie 解码、IPS/BPS 生产解析与应用、Code Breaker 条件码等格式。
- 魔鸟不同样本 MP 消耗差异的规则解释，以及“飞冰魂”别名的可靠来源。
- GBA 平台总闸门保持 `verified=False`；上述单游戏与字段结论不自动放行平台生产。

## 12. 收尾验证（2026-11-25）

- 完整共享回归：`SELFTEST OK 1489/1489`；其中包含 RAM 校准 36/36。
- 来源库独立闸门：`SOURCES_SELFTEST OK 71/71`。`absence_claims` 现区分“不存在声称”（game/want/date/support，必须有过 miss 台账）与“取回限制”（claim/checked_on/method/result/not_a_claim_of）；旧记录不再被静默跳过，混合或缺失字段拒绝入库。
- 跨平台闸门：33/33；金手指候选：56 PASS / 0 FAIL。
- 来源审计：8 pass / 0 fail / 1 inconclusive；唯一 inconclusive 是其他既有知识包仍只有 candidate/snippet/unreachable 支撑。
- 知识库审计：6 pass / 0 fail / 3 inconclusive。inconclusive 仍为既有权威就绪、二手继承与撤回片段；Aria 的 evidence coverage、source binding、identity、index sync、chunk provenance 均通过。重建结果为 811 块、26 份入索引、22 份显式排除。
- 四份正式归档（Aria v5/v6、魂斗罗武器/移动）的 report、recipe 与逐份 evidence SHA256 全部复算通过；新状态包 9 套状态与 44 份登记实物的 SHA256 全部通过，状态保持 `resources_ready`。
- 已跟踪的本次改动文件 `git diff --check` 通过；新增文本文件另做逐行空白与 EOF 检查。全仓检查另发现 `测试问题与闸门说明书.md:2227` 的既有 EOF 空行，不属于本次 RAM 校准改动，未改写该文件。

## 10. 可复用状态包与校准配方（2026-11-25 实跑）

正式状态包：

`F:/开源掌机教程/04-游戏资源库/TAS输入录像库/状态资产/castlevania_aria_gba/aria_us_40aab076/r20261125T120000/`

包内冻结 `base`、`empty_red`、`merman`、`blue_buer`、`yellow_damage_route` 五套状态，以及菜单装备导航输入、历史证据和本轮校准证据。包状态已升为 `state_verified`：五套状态均通过独立零帧回存 profile gate；GBA 平台总闸门仍未放行。

- 本轮补齐 `empty_red` 与 `yellow_damage_route` 的 gate，证据分别为包内 `evidence/state_gate_empty_red.json`、`evidence/state_gate_yellow_damage_route.json`。
- 两套都在全新 GBA/mGBA 隔离槽中通过 memory domains、framebuffer、SyncSettings、BizVersion 身份检查。`yellow_damage_route` 的序列化 `Core.bin.zst` 首差异偏移为 8225，但上述语义判据全部一致；生产 gate 的通过依据是语义一致性，不把 ZIP 内核心序列化字节相等当作唯一标准。
- `state_verified` 只表示这五套状态可加载、回存复现；不代表完整技能表、库存/物品系统或 GBA 平台已验收。

可复用配方：

- `F:/开源掌机教程/_工具脚本/taspipe/校准配方/castlevania_aria_gba.red24_menu.json`
- `F:/开源掌机教程/_工具脚本/taspipe/校准配方/castlevania_aria_gba.soul_effects.json`

两份配方只描述源 BizHawk 安装、ROM/状态包、宏、正反例和断言；`isolated_slot=true` 让 `ram_calibration` 按 `GBA/mGBA` 现场创建隔离副本，不再引用某次并行任务遗留的临时槽路径。无 `prepare` 的 case 可分别引用独立场景状态，缓存键会纳入这些额外状态。

| case | 实跑结果 | 关键读数 |
|---|---|---|
| `red24_vs_empty` | pass | 真实菜单选中红魂 24，关闭回游戏、重开仍为 24；Up+B 后 MP 80→57，空槽 80→80 |
| `wingcutter_same_state` | pass | 同一 `base` 只改红槽 24/0；羽刃正反例画面在 8/12/20/60/final 均不同，MP 80→57 / 80→80 |
| `guardian_same_state` | pass | 同一 `blue_buer` 只改蓝槽 4/0；R 键正反例在 12/60/final 分别相差 280/291/250 像素 |
| `yellow_damage_same_state` | pass | 同一路线只改黄槽 22/0；80/85 帧完全相同，86 帧起分离；伤害 22 / 17 |

完整报告、配方副本、证据清单和 SHA256 归档在：

`F:/开源掌机教程/04-游戏资源库/TAS输入录像库/状态资产/castlevania_aria_gba/aria_us_40aab076/r20261125T120000/calibration/`

本轮只验证上述 ID 与场景，不代表 55 个红魂、24 个蓝魂、35 个黄魂或完整技能表已验收；自动检测器候选生成仍须保留正例通过与负例失败两道闸门。

## 13. 配置驱动批量候选扫描（2026-11-25）

`ram_calibration` 已从逐 case 执行扩展为可复用批跑入口，游戏特定信息仍只放在配方中：

- `matrix.case_id/values/template` 用 `{value}` 一次展开 ID、分支名、补丁值与断言值；`values` 只允许唯一 0..255 整数，展开后仍走原有 validate/compile/生产执行路径。
- `scout` 与 `verify` 共用逐帧像素比较；scout 只写 `candidate_comparisons`、RAM diff 和 `verified_fields=[]`，不会把候选升级成字段验收。
- `run_many()` 用线程池并行运行全部 case；单 case 异常记录为 `error`，不中断其余 case。CLI 为 `--all --workers N`。
- 复用要求同时匹配 cache key、目标状态且 evidence 文件齐全；scout 缺证据时拒绝复用并重跑。
- targeted 自检 `ram_calibration_selftest` 43/43，通过生产函数入口覆盖 matrix 展开、重复值拒绝、scout 视觉候选、全量批跑、失败隔离、幂等复用与缺证据重跑。

第一份批量配方为 `F:/开源掌机教程/_工具脚本/taspipe/校准配方/castlevania_aria_gba.red_soul_sweep.json`，展开红魂 ID 1–55，共 55 个 case；每个 case 只比较同一战斗初态下的目标红魂与空红槽。扫描命中仅代表候选，后续仍须抽真实帧、核对菜单身份、补 verify 正反例，再进入 detector 标定与 showcase catalog。

## 14. 全量魂菜单目录（2026-11-25）

生产采集模块 `menu_catalog/1.1` 已完成红魂 55、蓝魂 24、黄魂 35 的全量真实菜单导航。三项均从同一已验证 `base` 出发，以两列网格真实按键选择，不写装备槽；每项同时保存整图、状态和名称身份区，并回读目标槽位。

| 组 | 数量 | 装备槽 | 名称身份区 | 结果 |
|---|---:|---:|---|---|
| 红魂 | 55 | `0x1325D` | `[45,20,135,32]` | 55/55 captured，readback 全对，identity 全唯一 |
| 蓝魂 | 24 | `0x1325E` | `[45,38,135,50]` | 24/24 captured，readback 全对，identity 全唯一 |
| 黄魂 | 35 | `0x1325F` | `[45,50,120,65]` | 35/35 captured，readback 全对，identity 全唯一 |

合计 114/114：整图 114 唯一、identity 114 唯一，实际核心全部为 `BizHawk.Emulation.Cores.Nintendo.GBA.MGBAHawk`，无缺文件。导航宏由生产函数 `selection_macro()` 生成，所有条目 `patches=[]`。

### 名称与效果观察

- 114 个中文名从真实 identity crop 逐项人工读出；蓝魂 16“亚祖拉”、黄魂 21“石化魔”、红魂 33 与蓝魂 9 的“卡格布雷巴斯”做了第二遍 16 倍放大复核。
- 114 条效果文本从同一批真实菜单截图逐项读出。效果区是两行排版，正确裁切为 `[45,118,238,153]`；早期只取 `y=118..134` 会漏掉第二行，不能作为正式文本来源。
- 菜单中文名是 8 像素高、宽度可变的比例字体。旧 `build_menu_glyph_inventory.py` 按固定 8 像素 cell 切分得到的 179 个 bitmap cluster 不是 179 个汉字；`glyph_labels_draft.json`、`name_solver_result.json` 和旧 fixed-cell glyph detail 均不得作为正式名称映射。
- 外部 NewWise 与 Castlevania Dungeon 只用于交叉核名和效果候选；目录正文以当前 ROM 的真实菜单观察为准。

### 正式产物

可检索目录：`F:/开源掌机教程/_工具脚本/taspipe/游戏包/gba_aria_of_sorrow_souls.menu_catalog.json`

每条包含：组、ID、槽位地址、中文魂名、效果文本、真实导航宏、readback、整图/状态/identity SHA256，以及名称和效果的观察方法。`gameplay_verified` 与 `detector_verified` 全部显式为 `false`。

新状态 revision：

`F:/开源掌机教程/04-游戏资源库/TAS输入录像库/状态资产/castlevania_aria_gba/aria_us_40aab076/r20261125T145623/`

该包从 `r20261125T120000` 完整复制后新增目录、报告、观察 JSON、10 页效果联系表、4 张名称复核图及 342 份逐项菜单证据；旧 revision 未改写。413 个登记文件 SHA256 复算通过，五套状态仍可解析，`latest()` 现返回新 revision。

### 旧写槽位目录差集审计

旧 `menu_catalog/1.0` 写槽位采集与真实导航目录按相同 identity region 逐像素比较：114/114 身份区完全相同，最佳匹配全部是同 ID，没有选错魂。但旧截图效果区 0/114 与真实导航相同；三项旧效果区都只剩固定占位符，真实导航截图才有逐项描述。也就是说，旧目录可复用身份，不可复用效果文本，也不能用旧截图证明描述刷新。

审计报告：`F:/开源掌机教程/_工具脚本/taspipe/游戏包/证据/晓月圆舞曲/menu_patch_vs_nav_audit.json`

真实对照图：`F:/开源掌机教程/_工具脚本/taspipe/游戏包/证据/晓月圆舞曲/menu_patch_nav_effect_compare_red001.png`

### 边界

- 新包保持 `state_verified`，含义仍只是五套状态可加载、回存复现。
- 114 项目录只完成“真实菜单身份 + RAM 回读 + 名称/效果观察”，不代表 114 项玩法、消耗、伤害或 detector 已验收。
- 能力魂 8 项不在这份目录中，中文版绝对地址仍是候选。
- `showcase.PLATFORM_PROFILES["GBA"]["verified"]` 仍为 `False`，正式 showcase 不得因此直接放行。

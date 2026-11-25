# 选题规则：只测最出名的作品（2026-11-22）

> 用户原话：「只测试最出名的游戏，大家玩的多的，不要再测试一些冷门作品了。」
> 本文件是这条规则的**权威正文**；机器执行的是代码闸门，两者必须一致。
> 数据文件：`_工具脚本/taspipe/popular_titles.json`（唯一权威名单）
> 闸门代码：`_工具脚本/taspipe/popularity.py` + `_工具脚本/taspipe/control.py` + `_工具脚本/taspipe/auto.py` + `_工具脚本/taspipe/matrix.py`
> 名单版本：`2026-11-22（193 行 / 可用 134 行 / 待核 4 行）`

---

## 0. 一句话规则

**只跑「大众真的在玩」的作品。** 判定不靠感觉、不靠销量大小、也不靠 ROM 好不好找，
只靠三条硬证据：该平台畅销表里的实数行、中文怀旧层的点名、以及名作的编号正传续作。
三条都不满足 ⇒ 冷门 ⇒ 不占测试格。

---

## 1. 档位定义

| 档 | 判定条件 | 能否占测试格 |
|---|---|---|
| **T1** | 该平台英文维基「最畅销作品表」里有一行**销量 ≥ 1,000,000 的实数行** | 可以（除非该行带降级标记） |
| **T2** | 中文怀旧/合集层点名过的作品，**或** T1 系列的编号正传续作（初代、2、3、4 这种） | 可以（除非带待核标记） |
| **off_list** | 以上两条都不满足 | **不可以** |

三个关键词：

- **实数行**：表里必须真的写了销量数字。写「100 万+」「约 200 万」这种模糊行不算实数行。
- **编号正传续作**：`Mega Man`（初代，因为 2/3 有行）、`Ninja Gaiden II`、`Contra III` 这类。
  同人、移植、ROM hack、合集拼盘**不算**正传续作。
- **降级行**：行上写了 `demote` 的，即使有 100 万销量也不进名单（见 §4）。
- **待核行**：行上写了 `under_review` 的，身份没核实前**不占测试格**（宁漏不错认）。

平台隔离：NES 的《Super Mario World》和 SNES 的《Super Mario World》是两行，匹配按平台分格，
SNES 的行放行不了 NES 的行。

---

## 2. 名单来源（证据表）

| 来源 | 用途 | 位置 |
|---|---|---|
| EN NES 畅销表 | NES 的 T1 实数行 | <https://en.wikipedia.org/wiki/List_of_best-selling_Nintendo_Entertainment_System_video_games> |
| EN SNES 畅销表 | SNES 的 T1 实数行 | <https://en.wikipedia.org/wiki/List_of_best-selling_Super_Nintendo_Entertainment_System_video_games> |
| 中文维基 FC/SFC 作品页 | 中文译名与作品身份 | `zh.wikipedia.org/w/index.php?oldid=92833426`（FC）、`oldid=92831668`（SFC） |
| 新浪科技 2011《十大最受欢迎的 FC 系列游戏》 | 中文层 T2 点名 | <http://tech.sina.com.cn/h/2011-05-19/05101756925.shtml>（用到第 2~11 页：第一名~第十名系列 + 「未上榜的英雄们」10 条 + 「非系列作品中的经典」） |
| 海外网 2016 怀旧榜 | 中文层 T2 点名 | <http://news.haiwainet.cn/n/2016/0830/c3541840-30269475-4.html> |
| 腾讯新闻「科乐美老四强」/ 32r 红白机合集榜 | 中文层点名补证 | 见名单文件内对应行的 `basis` |

**中文层点名的具体名次（新浪 2011 FC 系列榜）**：第二名 魂斗罗系列、第三名 热血系列、
第四名 冒险岛系列、第六名 双截龙系列、第七名 洛克人系列、第八名 忍者龙剑传系列；
「未上榜的英雄们」另列《吃豆人》《三国系列》《圣斗士之黄金十二宫》《忍者神龟系列》。

**中文层也能单独放行的例子**：《魂斗罗》《吃豆人》**在英文 NES 畅销表里根本没有行**，
它们进名单完全靠中文层点名 + 续作身份，名单文件里明确标注「不引用销量」。
反过来《热血足球》的日文原名 `Nintendo World Cup` 在英文表里有销量行，
但用户点名它是热血足球的中文记忆载体，因此该行**取消降级**、保留在名单内
（此前把它按「授权体育」降级是错的，已改判，见 §9 改判记录）。

---

## 3. 有销量 ≠ 进名单

英文畅销表里销量百万的行有几十行，但很多是**买不到门票**的。降级理由分五类，
全部写进名单文件该行的 `demote` 字段：

| 类 | 含义 | 实例（销量在括号里） |
|---|---|---|
| A 外设 | 靠专用外设才能玩，掌机给不了这个输入 | World Class Track Meet 3,080,000（Power Pad 体感垫）、Hogan's Alley 1,270,000（光枪）、Mario Paint 2,310,000（SFC 鼠标）、Super Scope 6 1,650,000（Scope 光枪） |
| B 授权 | 联盟/电影/体育授权，中文怀旧层根本没把它当代表作 | Tecmo Super Bowl 1,190,000、Pro Wrestling 2,400,000、Top Gun 2,000,000、NBA Jam 1,220,000（本地也没这张 ROM） |
| C 日本本土向 | 日本本土怀旧向，中文玩家层没有对应记忆 | Baseball 3,200,000、Ice Hockey 2,420,000、Tennis 2,170,000、Mah-Jong 2,140,000 |
| D 合集/同作重复 | 拼盘、拆卡、同一 ROM 的另一区划行 | Donkey Kong Classics 1,560,000、Super Mario Bros. 2（日版行）2,650,000、Super Puyo Puyo 2 + Bombliss 1,000,000 |
| E 题材/观赏性 | 偏模拟经营或观赏性弱，中文层不认 | Pilotwings 2,000,000、SimCity 1,980,000、Doraemon 1,150,000 |

**用户点名降级**单独记一类：The Lion King（1,270,000）—— 用户 2026-11-22 明确说狮子王是冷门，
所以它有百万销量行也不进名单。这条降级理由在名单文件里逐字保留，将来谁翻到这一行
都能看到「为什么销量百万还在门外」。

---

## 4. 匹配口径（为什么不会把 ROM hack 放进来）

- **规范化后精确相等，绝不用子串**。`Rockman Claw`、`Kaizo Mario World`、
  `Super Metroid: Kaizo Edition`、`I Wanna Be the Guy` 都因为「不是正作精确名」而被挡在外面；
  子串匹配会把这些同人/改版当成名作放行。
- 规范化 = 全角转半角 + 小写 + 去变音符 + 标点折叠成空格。
- **两把键**：`word` 键保留空格（`Dragon Quest I & II` ≠ `Dragon Quest III`），
  `tight` 键去掉空格（`R.C. Pro-Am` = `RC Pro-Am`）。
- **撞键作废**：任何一个键（word 或 tight）在同一平台下指向 **超过一个** 作品时，
  这个键整条禁用，宁可漏判也不能错认成另一部作品。
  目前实测撞键只有一处：`(SNES, dragonquestiii)` → `Dragon Quest I & II` 与 `Dragon Quest III`。
- **平台隔离**：匹配键是 `(平台, 标题键)`，SNES 的行放行不了 NES 的同名作品。

---

## 5. 执行机制：规则怎么变成硬闸门

三层，缺一层就等于没执行：

### 5.1 选景点（正向筛，冷门根本进不了跑批）

| 位置 | 作用 |
|---|---|
| `_工具脚本/taspipe/matrix.py` → `famous_playthrough_cells()` | 从真台账取 replayable 且在名单上的名作建格 |
| `_工具脚本/taspipe/local_bootstrap.py` → `run_all_ready_now()` | FCEUX 转换循环与通关循环都先过名单判定；被跳过的冷门**逐条留名**（`off_popularity_list`），免得「跑了 0 部」被误当故障 |
| `_工具脚本/taspipe/popularity.py` → `classify_spec()` | 唯一的匹配实现，两个选景点共用，不各写一套 |

### 5.2 启动前硬闸门（任何入口都拦得住）

两道启动闸门，用的是同一把尺子（`popularity.gate_blocker`）：

| 落点 | 覆盖的入口 |
|---|---|
| `control.plan()` | control CLI（`control run` / `control batch`） |
| `auto.orchestrate()` / `auto.plan()` | registry 编排层（`auto run/plan`、`matrix`、`local_bootstrap` 的通关与要素任务） |

编排层这一道是后补的：`control.plan` 只管 control CLI，走 registry 的电影任务
**根本不经过 `control.plan`**，冷门作品曾经能被直接开跑。现在编排层按
**解析出的出版物身份**（`pub.game` + 平台）判，不靠用户口述的名字。

```python
# control.py（control CLI）
_pop = popularity.gate_blocker(normalized)
if _pop:
    blockers.append(_pop)

# auto.py（registry 编排层）
gate, warnings = _selection_gate(pub, assess, spec, allow)
if gate:
    # 停在 selection 阶段，不进采集
```

闸门码：

| code | 含义 | 可否 `--allow` 放行 |
|---|---|---|
| `title_off_popularity_list` | 这部作品不在热门名单 | 可（留痕，见 5.3） |
| `popularity_game_field_missing` | 平台在管辖范围内但 spec 没写 `game`，无从判断 | **不可**（写错字段不是降级理由） |
| `popularity_list_missing` | 名单文件读不到 | **不可**（宁可不跑也不放冷门过去） |

选景点是「正向白名单」，启动闸门是「负向兜底」。两道都灵，才叫严格执行。

### 5.3 降级留痕（`--allow` 不是后门，是有记录的后门）

真跑一次降级是什么样：

```
status: ready | blockers: [] | warnings: ['title_off_popularity_list']
```

降级记录会写进产物的 `plan.json` / `result.json` / `job.json`，所以「谁在什么时候放跑了冷门」
在产物里查得到，不是查不到。谁要降级，必须在命令行显式写
`--allow title_off_popularity_list`（`auto run` / `matrix run` / `matrix famous` 都支持）。

### 5.4 改名单的规矩

`popular_titles.json` 是唯一权威，`popularity.py` **不内置任何标题**。
新增一行必须同时给出：`title` / `platform` / `tier` / `basis`（证据出处），
以及 `sales`（T1 必填实数）或 `cn` + 点名来源（T2 必填）。
没有证据的行不准进名单，也不准用「我记得挺多人玩」这种说法进名单。

---

## 6. 本机实测覆盖（真台账现查，非估计）

跑 `python -m taspipe.popularity audit`（只读台账，不动任何产物）：

```
名单 2026-11-22（193 行 / 可用 134 行 / 待核 4 行） | 管辖平台 ['NES','SNES']
台账条目 25 -> 命中 15 / 未命中 10
分档：{"NES": {"T1": 8, "T2": 3}, "SNES": {"T1": 2, "T2": 2}}
名单里有、本地库没有的行：15
```

被拦掉的 10 条就是用户口中的那批冷门，逐条可查：

| # | 作品 | 拦下理由 |
|---|---|---|
| 4776 / 4831 | Alwa's Awakening: The 8-Bit Edition | 无百万行、无中文点名、非续作 |
| 4791 | I Wanna Be the Guy | 同上（且是同人向） |
| 5246 / 5784 | Nova the Squirrel | 同上 |
| 6113 / 6164 | Rondo of Blood | 同上 |
| 5009 | Lester the Unlikely | 同上 |
| 5283 | Out of This World | 同上 |
| 6987 | The Lion King | 用户点名冷门（即便有 1,270,000 销量行） |

`Super Mario Bros.`、`Metroid`、`The Legend of Zelda`、`Contra`、`Ninja Gaiden`、
`Mega Man`、`Donkey Kong`、`Duck Hunt`、`Kung Fu` 等名家全部在名单内，正常占格。

生产选景函数在真台账上的真实产物（`matrix.famous_playthrough_cells()`，frames=600）：

```
NES  Donkey Kong 5254 / Duck Hunt 5280 / Kung Fu 6908 / Metroid 6725
     Super Mario Bros. 6012 / The Legend of Zelda 3232
SNES DKC2 6849 / F-Zero 7406 / Mega Man 7 6092 / Mega Man X2 5628
```

本轮覆盖结果（报告：`F:/taspipe_scratch/famous_run_20261122/matrix_report.json`）：10 格中 6 格复用既有合格产物，3 格新跑完成，1 格失败；因此按格计为 **9/10 有效通过、1/10 未通过**。唯一失败是 Mega Man X2（5628）的 capture：0/600 帧、`stalled_killed`、无 `cap.txt`、无视频。其电影 Header 声明 `Core=BSNES` 和 `SNES_Firmware_CX4`，而同版本 BizHawk 2.9.1 的 Mega Man 7（6092）使用 `BSNESv115+` 且成功；这说明当前是 X2 启动/核心/固件准入问题，不能把它写成“SNES 不能跑”，也不能把失败重试伪装成通过。

成功的 DKC2 成片已抽帧核看（`F:/taspipe_scratch/famous_run_20261122/snes_dkc2_frame300.png`、`snes_dkc2_frame480.png`），确认输出来自真实 SNES 回放链路；但 600 帧只是生产捕获/导出 smoke run，不等于整部游戏 TAS 通关。完整 TAS 仍须另有 gameplay 与 completion 证据。

`Ninja Gaiden` 在默认排除表里（已出过片，不重复跑同一个游戏）。

---

## 7. 候选：还没进名单的知名作品，以及进名单需要什么证据

这些作品「大家都玩过」，但**目前手上没有能进名单的硬证据**，所以它们现在仍然被闸门拦着。
把证据补齐就能进，不需要改代码：

| 候选 | 需要什么证据 |
|---|---|
| 泡泡龙 / 影子传说 / 马戏团 / 雪人兄弟 / 古巴战士 | 需要点名这些标题的中文榜出处（现有中文榜的正文没有点到它们） |
| EarthBound（SFC） | 需要 SFC 口径的中文点名或官方出货数；现列 `under_review` |
| NES 上的《街头霸王 II》 | NES 官方未发行街霸 II，本地那张 ROM 到底是什么待核实；现列 `under_review` |
| 本地「超级魔法气泡 2」/「星之卡比 魔法气泡」 | 日版超级魔法气泡 2 与美版 Kirby's Avalanche 是同一玩法的两种区划命名，本地这张是哪一版待核实；两行都 `under_review` |
| 《热血足球》 | 已在名单（`Nintendo World Cup` 行，见 §9 改判） |

---

## 8. 这条规则管到哪、哪些轴不受它影响

选题闸门管的是「**这部作品值不值得占测试格**」，它跟下面这些轴是分开的，不要混着报：

- **执行轴**：跑没跑起来（模拟器、ROM、电影、依赖）——由资源闸门管。
- **完成轴**：跑完没有（帧数、退出码、产物在不在）——由验收闸门管。
- **同步轴**：字幕/音轨/水印对不对——由导出闸门管。
- **判据轴**：结论对不对（通关旗标 vs 末帧状态指纹）——由判据规格管。

一条冷门被拦下，只能说「没占格」，不能说「跑失败」；同理一部名作的片没出，
也不能说「因为它在名单上所以应该有」。

---

## 9. 改判记录

- **2026-11-22｜Nintendo World Cup 取消降级。** 此前按「授权体育」把它降级，
  但它的日文原名正是中文层的《热血足球》（用户自己最熟的那批记忆），
  降级等于和用户口径对着干。已恢复为可用行，备注写明中文名对应关系。
- **2026-11-22｜The Lion King 新增「用户点名」降级。** 理由逐字写入该行 `demote` 字段。
- **2026-11-22｜Super Puyo Puyo / Kirby's Avalanche 别名互相顶掉。**
  两行原本互为别名，导致「可用行解析回自己」这条自检失败。已去掉互指别名，
  两行都改 `under_review`，核实前不占测试格。
- **2026-11-22｜撞键守卫的真 bug。** 守卫原本拿字符串键去比集合（集合里存的是元组），
  导致 `DragonQuestI&II` 会静默命中 `Dragon Quest III` 行。已修为元组键比较，
  并加了恒量反证测试盯着。

---

## 10. 怎么用

```bash
# 打印名单（按平台分档，含销量与降级原因）
python -m taspipe.popularity report

# 对照本地台账，报命中/未命中/名单空行
python -m taspipe.popularity audit

# 判单个标题
python -m taspipe.popularity check "Super Mario Bros." --platform NES

# 跑名作矩阵（冷门不占格）
python -m taspipe.matrix famous --out F:/taspipe_scratch/famous_run --frames 600
```

自检：`python -m taspipe.selftest`（1088/1088 OK）、
`python -m taspipe.control_selftest`（270/270 OK）。

---

## 11. SNES 热门格实测结论（2026-11-22 晚，全部走生产入口 `tas_replay.py`）

| 作品（名单档位） | 电影 id | 整片帧数 | 本轮 600 帧结果 | 判读 |
|---|---|---|---|---|
| F-Zero（T1，2,850,000） | 7406 | 141,904 | `status=complete`、`desync=False`、elapsed 44.6s | **链路通了，且画面是真玩法**：末帧是 Mute City 起跑画面带 HUD，不再是 logo 帧 |
| Mega Man X2（T2，洛克人X 系列 1,160,000） | 5628 | 111,725 | 0 帧 `stalled_killed` → 修看门狗后仍 0 帧 | **卡在缺 CX4 固件**（见说明书 §35），不是版本、不是速度 |
| Mega Man X3（T2） | 3241/3247 | — | 未跑 | 同一份 `cx4.bin` 解锁，等批准 |
| Mega Man 7（T2） | 6092 | 148,644 | 采到 600 帧，但 30 点采样里多数帧 mean_luma≈3.6（近黑），最高 126（标题/厂标），没进玩法 | **600 帧窗口不够**：这段还在开机/黑场期，不能拿来判"跑不通"（原文写"画面全黑"是我早先只看了 3 个时间点的过度概括，已按逐帧亮度更正） |
| Donkey Kong Country 2（T1，5,150,000） | 6849 | 96,538 | t=3/6/9.5s 分别 = 黑场 / Rareware / Nintendo PRESENTS，整窗 mean_luma 最高 45.5 | 同上，600 帧只走到厂标；DKC2 的片头本身就超 600 帧 |
| The Legend of Zelda（NES，对照） | 3232 | 80,384 | 已通关实物 | NES 线另有档位，不与 SNES 混算 |

- **`dismissed` 这个数字不能再单独读**：旧代码 `dismissed=1` 只说明"点了一轮"，不说明"只弹了一个框"。X2 真机第二次跑 `dismissed=2` 才把 `privileged` + `Couldn't find firmware SNES+CX4` 两个框都记下来。归因看 `dismissed_dialogs` / `stall_windows` / `windows_at_kill` 三样（§34）。
- **帧预算的口径问题**：`python -m taspipe.matrix famous --frames 600` 这个例子对 NES 够，对 SNES 大片头不够。600 帧采到黑帧 ≠ 游戏跑不通，只等于"窗口开小了"。要判 SNES 格是否真能进玩法，帧预算得按该片头长度给（下一轮补测，不擅自改矩阵默认值）。
- **吞吐还没定论**：300/900/1500 三档实测正在跑，用来算 SNES 稳态帧率；不许拿 NES 的 145–160 fps 外推（§36 落数）。
- **名单侧结论**：热门闸门本身没漏放冷门——本轮所有 SNES 格都是名单上的 T1/T2；卡住的是固件准入（要用户批）和窗口长度（我的测试参数），不是选题规则。

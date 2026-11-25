# 洛克人 1（NES/USA）知识候选目录

> 任务 C 交付件入口。游戏 = **Mega Man (NES, USA, 1987 Capcom)**，目录名 `megaman1_nes_us` 携带游戏+版本。
> 本目录是**文献候选层**，不是生产知识包；不改 `sources.json`/生产包/代码（任务书 §7 约束）。
> 调研日期 2026-11-20（UTC）。运行时零 LLM，本轮未启动模拟器、未生成媒体、未下载 ROM。

## 状态一句话

**文献研究已完成（8 要素候选齐全、来源三级分级、矛盾已裁定）。~~唯一硬阻塞 = 缺干净 ROM~~ 已被 2026-11-20 复测推翻：三份 ROM 均可正常入关实玩（见 `复测结论_2026-11-20.md`）。** 剩余缺口 = 版本身份钉死（NTSC 选 hd）/ mm_showcase 路径缺失 / 包无 rom_sha1 / RAM 与检测器实证，**不再是"进不了 gameplay"**。

> ⚠️ 复测轮（2026-11-20 晚）启动了**隔离** BizHawk 副本做 fresh-boot 截图复测（零存档零补丁、
> 原件只读），与上面"文献轮未启动模拟器"不冲突；旧 `blocked_resource` 三条异常全部撤回。

## 文件导航

| 文件 | 内容 |
|---|---|
| `候选表.md` | 8 要素 × 13 字段逐要素候选表 + 共性检测风险（角色变色/HUD 碰撞/有 block≠释放/飞行≠爆炸等） |
| `来源清单.md` | 来源三级分级（全文 10 / 摘要 20 / 未访问 14）+ 逐字原文 + 矛盾台账 M1–M8 + 不可靠来源 + 尚需探针清单 |
| `本地版本与资源缺口.md` | 两个异常 ROM 哈希/字节/mapper、干净开局签名 4 条件、mm_showcase 缺失资源、RAM 缺口、blocked_resource 分支 |
| `完整性差集与名单边界.md` | expected_total=8 推导（1 默认+6 Boss+1 辅助）、ID 差集机器核对=0、逐要素真实状态、与验收差距 |
| `证据快照/` | 10 份全文来源本地快照（防临时文件 7 天清理），字节数见来源清单 §1 |

## 关键结论速览

1. **名单 8 项完备**：Mega Buster(默认) + Rolling Cutter/Ice Slasher/Hyper Bomb/Fire Storm/Thunder Beam/Super Arm(6 Boss) + Magnet Beam(关卡辅助)。
   MM1 只有 6 Robot Masters（VideoChums 全文），Magnet Beam 是 Elec Man 关卡隐藏房间获取（**非 Boss 奖励**），无第 9 项。
2. **最强来源 = TMMN 武器专文**（MM1 NES 本体逐项分析，全文已读）：确立满能量条 28 单位、各武器同屏上限、能量消耗、弹道/护盾/爆炸/举块/平台机制。
3. **能量消耗裁定**：Buster 0 / Cutter·Ice·Fire·Thunder 各 1 / Hyper Bomb 2（全文+摘要互证）/ Super Arm·Magnet Beam 2（28/14 推导，须探针）。
   旧"Thunder Beam 2 单位"记忆**已撤回**（TMMN 全文 + Whammychip 摘要一致 = 1）。
4. **粉丝引擎陷阱已排除**：MegaManMaker Wiki 的 freeze 4s / shield 1s / 十字爆炸 / 轨迹控制 / 6 tiles 全是 Maker 值，**不导入 MM1**；
   只取其定性身份 + 5 色 Guts block 分布（Cut 绿/Elec 黄/Guts 棕/Wily1 灰/Wily3 深绿）。
5. **不可靠来源已标**：Facebook fb-answers"打败 Elec Man 拿 Magnet Beam"与多源矛盾，不采纳。
6. **检测最大风险 = 角色变色假阳**：6 件武器改角色配色，近全屏颜色分数检测会把"装备"当"释放"；中立反例共享 patches 正是为暴露此问题。
7. **RAM 硬缺口**：current_weapon / owned_flags 地址未知（showcase addr95 是猜的）；只写能量+猜选武器可能放不出武器，必须 gameplay 差分。

## 需用户判断的问题（仅 1 项硬阻塞）

**请提供干净 Mega Man 1 USA [!]/No-Intro ROM**，须同时满足（任务书 §4 第 1 步）：
① 标题/选关方向键可移动；② 能进可控制角色的真实关卡；③ 未战斗不反复进 CLEAR POINTS 退回选关；④ 武器菜单/HUD 可观察操作。

本地两个候选（`mega_man_usa.nes` sha1 d8b8c5e2… / `megamanhd.nes` sha1 2f883815…，均 131088 B mapper2）
均出现"选关方向无效 + 未战斗直跳 CLEAR POINTS + 能量预满"异常组合，`clean_boot_verified=false`，不得用于 authoring。

（可选非阻塞：DataCrystal RAM map 离线副本可加速地址定位，但没有也能靠差分发现。）

其余问题（名单边界、能量、检测设计、版本目标）均已由文献/机器核对自解决，不需用户判断。

## 取得干净 ROM 后的续跑路径（任务书 L1 §4）

补 rom_sha1 → 导航存 base.state/base.png（跨进程复核）→ Super Arm 专用 base_guts_block.state →
RAM A/B 差分（current_weapon/owned_flags/能量映射）→ 先闭环 mega_buster（`--only`）→ 逐项添加其余 7 项 →
八项齐全 `plan` ready → `auto run --source showcase --template fc_tianma_mask` 正式合辑 → 抽帧验收 → 立规交付。
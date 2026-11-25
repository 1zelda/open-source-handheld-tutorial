# 洛克人2生产技术域生产验收

- 生成时间：`2026-11-25T15:09:19Z`
- 总结论：**pass**
- 范围：TASVideos 原文明确记载的 Rockman 2 技术子域，不是整款游戏知识库。
- 边界：不证明 PAL/美版/日版 ROM 等价；候选说明书、内存字典、目录与 TAS 元数据不升格。

## 1. 生产正例与七文件覆盖

- 正例：32/32
- 覆盖取证：7/7 份

| ID | 问题 | 取证文件 | 必须命中 | default/auto | strict/auto |
|---|---|---|---|---|---|
| MM2T01 | 洛克人2 X 坐标向哪个方向增加？ | `mm2_tasvideos_coordinates_20261125.txt` | `right` | 通过 | 通过 |
| MM2T02 | 洛克人2 跳跃时 Y speed 初始值是什么？ | `mm2_tasvideos_jump_20261125.txt` | `04.DF` | 通过 | 通过 |
| MM2T03 | 洛克人2 攀爬速度是多少？ | `mm2_tasvideos_climb_transform_20261125.txt` | `00.C0` | 通过 | 通过 |
| MM2T04 | 洛克人2 跳跃时 X speed 是什么？ | `mm2_tasvideos_jump_horizontal_20261125.txt` | `01.50` | 通过 | 通过 |
| MM2T05 | 洛克人2 步行速度是多少？ | `mm2_tasvideos_walking_20261125.txt` | `01.60` | 通过 | 通过 |
| MM2T06 | 洛克人2 从静止加速需要多少帧？ | `mm2_tasvideos_acceleration_20261125.txt` | `7 frames` | 通过 | 通过 |
| MM2T07 | 洛克人2 从全速停止需要多少帧？ | `mm2_tasvideos_acceleration_20261125.txt` | `8 (decimal) frames` | 通过 | 通过 |
| MM2T08 | 洛克人2 Xspd 内存地址范围是什么？ | `mm2_tasvideos_object_table_20261125.txt` | `$600:$620` | 通过 | 通过 |

## 2. 失败关闭与恒量反证

| ID | 探针 | 预期 | 实际 | 结果 |
|---|---|---|---|---|
| MM2R01 | 洛克人2 PAL 版 walking speed | `version_not_collected` | `version_not_collected` | 通过 |
| MM2R02 | MM2 JP ROM 的 walking speed 是什么？ | `version_not_collected` | `version_not_collected` | 通过 |
| MM2R03 | 洛克人2 NTSC 美版 walking speed | `version_not_collected` | `version_not_collected` | 通过 |
| MM2R04 | 洛克人2 出招表 | `move_list_not_collected` | `move_list_not_collected` | 通过 |
| MM2R05 | Mega Man 2: The Power Fighters walking speed | `ambiguous_series` | `ambiguous_series` | 通过 |
| MM2R06 | 洛克人2 有几个对象 | `candidate_evidence_insufficient` | `candidate_evidence_insufficient` | 通过 |
| MM2R07 | 洛克人2 的 walking speed 和拳皇98 的必杀射门分别是什么？ | `candidate_only` | `multi_domain_needs_split` | 通过 |
| MM2R08 | 洛克人2 内存地址是什么 | `revision_not_produced` | `revision_not_produced` | 通过 |
| MM2R09 | 洛克人2 销量是多少 | `revision_not_produced` | `revision_not_produced` | 通过 |
| MM2R10 | 洛克人2 TAS 有哪些 | `revision_not_produced` | `revision_not_produced` | 通过 |
| MM2R11 | 洛克人2 步行速度是多少？（索引缺失反证） | `candidate_only` | `candidate_unavailable` | 通过 |
| MM2R12 | 洛克人2 跳跃时 X speed 是什么？ | `candidate_only` | `candidate_evidence_invalid` | 通过 |
| MM2R13 | 洛克人2 跳跃时 Y speed 是什么？ | `candidate_only` | `candidate_evidence_invalid` | 通过 |
| MM2R14 | 洛克人2美版官方说明书里 Metal Blade 的投掷方向、数量和用途是什么？ | `candidate_only` | `True` | 通过 |

## 3. 选题对照与出卡

- crosscheck：8/8 通过，unanchored 降级 0。
- 选题卡：8/8 张带唯一出证。
- 卡片由真实 `知识对照.crosscheck()` 结果送入现有 `选题卡.render_card_md()`，不是手写证据摘要。

## 4. 审计与共享状态

| 审计 | pass | fail | inconclusive | 状态 |
|---|---:|---:|---:|---|
| 生产 base | 6 | 0 | 3 | inconclusive |
| 生产 hybrid | 6 | 0 | 3 | inconclusive |
| 来源库 | 8 | 0 | 1 | inconclusive |

- 评测期间共享文件漂移：0。
- 生产索引 SHA-256：`05907ec85146f386325285ccd4d2008d8bc28d50d8ec4e2461c14a9351f03f7d`
- hybrid 索引 SHA-256：`c478a8d3e830530f56882e8d9a0b3c7adae6521c897f7b03bfb9c84c95a40fb8`

## 5. 复现与产物

- [生产契约](contract.json)
- [范围与未覆盖项](scope.json)
- [评测脚本](eval_production_technical.py)
- [机器可读报告](eval_report.json)
- [生产查询日志](qc/production_query_log.jsonl)
- [crosscheck 日志](qc/crosscheck_query_log.jsonl)
- [选题卡 JSON](cards.json)
- [选题卡 Markdown](cards.md)

外部生成模型调用 0；付费 API 调用 0；未重启后端；strict 只作显式影子臂，dense/NLI 未评也未升默认。

# 洛克人1候选v2生产自动路由验收

## 结论

- 生产入口：`taspipe.kb.query_auto`；候选域：`megaman1`。
- 冻结 23 题：auto default 23/23；auto strict 23/23。
- 隔离消费方：direct default 23/23；direct strict 23/23。
- 路由边界：15/15；失败关闭：2/2。
- 错误候选出证：0；阻断外层出证：0。
- 共享状态、旧候选与当前候选输入：全部未变。
- 范围为 NTSC 美版 RAM/工具方法 + 官方说明书扫描核验短摘录；不是整款游戏知识库。

## 逐题

| ID | 类型 | default | strict | default 出证 | strict 出证 |
|---|---|---|---|---|---|
| MM01 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_coordinate_facts_20261125.txt#L1-L25 | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_coordinate_facts_20261125.txt#L1-L25 |
| MM02 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_object_ram_table_20261125.txt#L1-L17 | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_object_ram_table_20261125.txt#L1-L17 |
| MM03 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_object_ram_table_20261125.txt#L1-L17 | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_object_ram_table_20261125.txt#L1-L17 |
| MM04 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_object_ram_table_20261125.txt#L1-L17 | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_object_ram_table_20261125.txt#L1-L17 |
| MM05 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_object_ram_table_20261125.txt#L1-L17 | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_object_ram_table_20261125.txt#L1-L17 |
| MM06 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_bizhawk_memory_write_fact_20261125.txt#L1-L10 | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_bizhawk_memory_write_fact_20261125.txt#L1-L10 |
| MM07 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_local_weapon_ram_excerpt_20261125.txt#L4-L7 | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_local_weapon_ram_excerpt_20261125.txt#L4-L7 |
| MM08 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_local_weapon_ram_excerpt_20261125.txt#L4-L7 | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_local_weapon_ram_excerpt_20261125.txt#L4-L7 |
| MM09 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_local_position_probe_excerpt_20261125.txt#L5-L17 | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_local_position_probe_excerpt_20261125.txt#L5-L17 |
| MM10 | refuse | inconclusive | inconclusive | — | — |
| MM11 | refuse | inconclusive | inconclusive | — | — |
| MM12 | refuse | inconclusive | inconclusive | — | — |
| MM13 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_manual_controls_20261125.txt#L1-L13 | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_manual_controls_20261125.txt#L1-L13 |
| MM14 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_manual_controls_20261125.txt#L1-L13 | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_manual_controls_20261125.txt#L1-L13 |
| MM15 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_manual_stage_select_20261125.txt#L1-L13 | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_manual_stage_select_20261125.txt#L1-L13 |
| MM16 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_manual_energy_20261125.txt#L1-L10 | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_manual_energy_20261125.txt#L1-L10 |
| MM17 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_manual_bonus_items_20261125.txt#L1-L13 | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_manual_bonus_items_20261125.txt#L1-L13 |
| MM18 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_manual_bonus_items_20261125.txt#L1-L13 | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_manual_bonus_items_20261125.txt#L1-L13 |
| MM19 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_manual_magnet_beam_20261125.txt#L1-L10 | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_manual_magnet_beam_20261125.txt#L1-L10 |
| MM20 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_manual_robot_masters_20261125.txt#L1-L22 | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_manual_robot_masters_20261125.txt#L1-L22 |
| MM21 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_manual_progression_rewards_20261125.txt#L1-L13 | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_manual_progression_rewards_20261125.txt#L1-L13 |
| MM22 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_manual_victory_scores_20261125.txt#L1-L10 | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_manual_victory_scores_20261125.txt#L1-L10 |
| MM23 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_manual_progression_rewards_20261125.txt#L1-L13 | 知识库P1_20261118/megaman1_candidate_v2_manual_20261125/evidence/mm1_manual_progression_rewards_20261125.txt#L1-L13 |

## 边界

- 新增说明书题必须命中官方手册来源且保持唯一证据；旧 RAM/工具题仍命中原来源。
- 中英文、全角与多空格别名自动进入候选；显式 revision 可提供缺别名问句身份。
- 系列泛词要求补代次；洛克人10/20 不误路由；PAL-B/欧版拒答。
- 多域问题保留域内证据，但外层不合并成 pass，也不给外层出证。
- 索引缺失、哈希不符或出证资格失败均失败关闭，不回退生产文本索引。
- MM10 目标时刻续作、MM11 角色创建系统、MM12 PAL-B 跨版等价仍拒答。
- 完整商业手册扫描未进入候选或交付目录。

## 产物

- 完整 JSON：`知识库P1_20261118/megaman1_route_v2_manual_20261125/eval_report.json`
- 生产查询日志：`知识库P1_20261118/megaman1_route_v2_manual_20261125/production_auto_query_log_20261125.jsonl`
- 消费链日志：`知识库P1_20261118/megaman1_route_v2_manual_20261125/consumer_query_log_20261125.jsonl`

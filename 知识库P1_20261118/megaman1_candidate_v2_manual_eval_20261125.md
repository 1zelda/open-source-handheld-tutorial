# 洛克人1候选v2说明书扩展隔离评测

## 结论

- 候选索引：17 块，SHA-256 `d8de2bcf742e5a7df4df86a29b6162bcc815c1977719009b5cfe3542bc86c6be`。
- 冻结题：23 题（20 事实题、3 拒答题）。
- default：23/23；strict：23/23。
- 错误出证：default 0，strict 0。
- 共享状态与候选输入：全部未变。
- 官方手册只收扫描核验短摘录；完整手册未进入候选目录。

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

- MM01–MM12 原题保留并重新锚定；新增 MM13–MM23 只覆盖官方说明书短摘录。
- MM10 目标时刻续作、MM11 角色创建系统、MM12 PAL-B 跨版等价仍拒答。
- 说明书覆盖操作、选关、能量、道具、Magnet Beam、Robot Master、奖励与得分；不是整款游戏知识库。
- 零外部生成式模型调用、零付费 API。

- 完整 JSON：`知识库P1_20261118/megaman1_candidate_v2_manual_eval_20261125.json`
- 隔离日志：`知识库P1_20261118/megaman1_candidate_v2_manual_20261125/qc/isolated_eval_query_log_20261125.jsonl`

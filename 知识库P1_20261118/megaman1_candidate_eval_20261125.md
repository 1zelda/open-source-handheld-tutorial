# 洛克人1隔离候选子域评测（2026-11-25）

## 结论

- 候选索引：9 块，SHA-256 `5e126eddf0eae98e6b8a446cd54f37400b861d5e93ecf89d3004f16d3a252581`。
- 默认生产查询：12/12；strict 影子臂：12/12。
- 错误出证：默认 0，strict 0。
- 真实 index / corpus map / sources / query log / 电竞 DB / 新闻快照：全部未变。
- 范围仅为 NTSC 美版洛克人1的 RAM 与工具方法；未接生产路由，不是整款游戏知识库。

## 逐题结果

| ID | 类型 | 默认 | strict | 默认出证 | strict 出证 |
|---|---|---|---|---|---|
| MM01 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_20261125/evidence/mm1_coordinate_facts_20261125.txt#L1-L25 | 知识库P1_20261118/megaman1_candidate_20261125/evidence/mm1_coordinate_facts_20261125.txt#L1-L25 |
| MM02 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_20261125/evidence/mm1_object_ram_table_20261125.txt#L1-L17 | 知识库P1_20261118/megaman1_candidate_20261125/evidence/mm1_object_ram_table_20261125.txt#L1-L17 |
| MM03 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_20261125/evidence/mm1_object_ram_table_20261125.txt#L1-L17 | 知识库P1_20261118/megaman1_candidate_20261125/evidence/mm1_object_ram_table_20261125.txt#L1-L17 |
| MM04 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_20261125/evidence/mm1_object_ram_table_20261125.txt#L1-L17 | 知识库P1_20261118/megaman1_candidate_20261125/evidence/mm1_object_ram_table_20261125.txt#L1-L17 |
| MM05 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_20261125/evidence/mm1_object_ram_table_20261125.txt#L1-L17 | 知识库P1_20261118/megaman1_candidate_20261125/evidence/mm1_object_ram_table_20261125.txt#L1-L17 |
| MM06 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_20261125/evidence/mm1_bizhawk_memory_write_fact_20261125.txt#L1-L10 | 知识库P1_20261118/megaman1_candidate_20261125/evidence/mm1_bizhawk_memory_write_fact_20261125.txt#L1-L10 |
| MM07 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_20261125/evidence/mm1_local_weapon_ram_excerpt_20261125.txt#L4-L7 | 知识库P1_20261118/megaman1_candidate_20261125/evidence/mm1_local_weapon_ram_excerpt_20261125.txt#L4-L7 |
| MM08 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_20261125/evidence/mm1_local_weapon_ram_excerpt_20261125.txt#L4-L7 | 知识库P1_20261118/megaman1_candidate_20261125/evidence/mm1_local_weapon_ram_excerpt_20261125.txt#L4-L7 |
| MM09 | strict_pass | pass | pass | 知识库P1_20261118/megaman1_candidate_20261125/evidence/mm1_local_position_probe_excerpt_20261125.txt#L5-L17 | 知识库P1_20261118/megaman1_candidate_20261125/evidence/mm1_local_position_probe_excerpt_20261125.txt#L5-L17 |
| MM10 | refuse | inconclusive | inconclusive | — | — |
| MM11 | refuse | inconclusive | inconclusive | — | — |
| MM12 | refuse | inconclusive | inconclusive | — | — |

## 冻结与边界

- 9 道事实题按候选索引真实 chunk 重锚；3 道缺证/版本边界题冻结为拒答。
- MM10 只有 segmented TAS 通用术语与 FM2 导入参考流程，不能证明洛克人1的目标时刻续作流程。
- MM11 缺官方说明书级角色创建证据；MM12 缺 PAL-B 与 NTSC 美版等价证据。
- 题集保留原草案文件不覆盖；问句细化理由逐题写入冻结 JSON。
- 本轮零外部生成式模型调用、零付费 API；生产默认参数未改。

## 复核入口

- 冻结题集：`知识库P1_20261118/megaman1_questions_frozen_20261125.json`
- 候选索引：`知识库P1_20261118/megaman1_candidate_20261125/index.json`
- 隔离查询日志：`知识库P1_20261118/megaman1_candidate_20261125/eval_query_log.jsonl`
- 完整 JSON：`知识库P1_20261118/megaman1_candidate_eval_20261125.json`

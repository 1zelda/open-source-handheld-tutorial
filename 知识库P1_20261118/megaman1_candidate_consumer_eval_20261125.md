# 洛克人1候选路由与消费方验收 · 2026-11-25

- 范围：NTSC 美版洛克人1的 RAM/工具方法隔离候选；不是整款游戏知识库。
- 路由反例：13/13
- 冻结题消费：default 12/12；strict 12/12
- 错误出证：default 0；strict 0
- 候选消费日志：24 行；失败关闭检查 4/4
- 真实共享状态前后一致：True

## 路由反例

| 用例 | 判定 | 通过 |
|---|---|---|
| R01 | candidate | True |
| R02 | candidate | True |
| R03 | candidate | True |
| R04 | candidate | True |
| R05 | ambiguous_series | True |
| R06 | ambiguous_series | True |
| R07 | ambiguous_series | True |
| R08 | version_not_collected | True |
| R09 | version_not_collected | True |
| R10 | not_matched | True |
| R11 | multi_domain_needs_split | True |
| R12 | not_matched | True |
| R13 | candidate | True |

## 冻结题逐题

| 题 | 档 | default | strict | 出证定位 |
|---|---|---|---|---|
| MM01 | strict_pass | True | True | 知识库P1_20261118/megaman1_candidate_20261125/evidence/mm1_coordinate_facts_20261125.txt#L1-L25 |
| MM02 | strict_pass | True | True | 知识库P1_20261118/megaman1_candidate_20261125/evidence/mm1_object_ram_table_20261125.txt#L1-L17 |
| MM03 | strict_pass | True | True | 知识库P1_20261118/megaman1_candidate_20261125/evidence/mm1_object_ram_table_20261125.txt#L1-L17 |
| MM04 | strict_pass | True | True | 知识库P1_20261118/megaman1_candidate_20261125/evidence/mm1_object_ram_table_20261125.txt#L1-L17 |
| MM05 | strict_pass | True | True | 知识库P1_20261118/megaman1_candidate_20261125/evidence/mm1_object_ram_table_20261125.txt#L1-L17 |
| MM06 | strict_pass | True | True | 知识库P1_20261118/megaman1_candidate_20261125/evidence/mm1_bizhawk_memory_write_fact_20261125.txt#L1-L10 |
| MM07 | strict_pass | True | True | 知识库P1_20261118/megaman1_candidate_20261125/evidence/mm1_local_weapon_ram_excerpt_20261125.txt#L4-L7 |
| MM08 | strict_pass | True | True | 知识库P1_20261118/megaman1_candidate_20261125/evidence/mm1_local_weapon_ram_excerpt_20261125.txt#L4-L7 |
| MM09 | strict_pass | True | True | 知识库P1_20261118/megaman1_candidate_20261125/evidence/mm1_local_position_probe_excerpt_20261125.txt#L5-L17 |
| MM10 | refuse | True | True | - |
| MM11 | refuse | True | True | - |
| MM12 | refuse | True | True | - |

## 边界

- 只有显式洛克人1别名，或调用方显式提供该 revision 上下文，才进入候选检索。
- PAL-B/欧版、系列泛词、其他作品、跨游戏合并问题均不进入候选检索。
- 索引缺失或 SHA 不符时失败关闭，不回退生产索引。
- 本消费方未改生产 DOMAINS、生产 corpus map、生产 index 或知识对照.py。
- 官方说明书级玩法语料和整款游戏覆盖仍是后续门槛。

# 洛克人1生产自动路由验收

## 结论

- 生产入口：`taspipe.kb.query_auto`；候选域：`megaman1`。
- 冻结 12 题：default 12/12；strict 12/12。
- 隔离消费方回归：default 12/12；strict 12/12。
- 路由边界：15/15；失败关闭：2/2。
- 错误候选出证：0；阻断外层出证：0。
- 共享状态与候选输入：全部未变。
- 范围仍只是 NTSC 美版洛克人1的 RAM/工具方法；不是整款游戏知识库。

## 逐题

| ID | 类型 | default | strict | default 出证 | strict 出证 |
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

## 边界

- 中英文、全角与多空格别名自动进入候选；显式 revision 可提供缺别名问句的游戏身份。
- 系列泛词要求补代次；洛克人10/20 不误路由到洛克人1。
- PAL-B/欧版拒答；官方说明书级玩法缺证拒答。
- 多域问题保留域内证据，但外层不合并成 pass，也不给外层出证。
- 索引缺失、哈希不符、主数据解析失败或出证资格失败均失败关闭，不回退生产文本索引。
- 选题知识对照已识别 megaman1 内容域，候选 SHA 与唯一证据可透传。
- FM2 导入与 segmented TAS 仍只是 reference_only，不能证明洛克人1目标时刻续作流程。

## 回归

- 知识库自检：326/326。
- 选题层自检：166/166。
- P1 路由与意图自检：37/37。
- 全域评测：16/16。
- 26 题盲测：26/26，隔离检查通过。
- 项目自检：1513/1513。
- 全部回归结束后，共享状态与候选输入仍相对验收快照零变化。

## 产物

- 完整 JSON：`知识库P1_20261118/megaman1_route_20261125/eval_report.json`
- 生产范围声明：`知识库P1_20261118/megaman1_route_20261125/scope_production_20261125.json`
- 最终清单：`知识库P1_20261118/megaman1_route_20261125/final_manifest.json`
- 生产查询日志：`知识库P1_20261118/megaman1_route_20261125/production_auto_query_log_20261125.jsonl`
- 消费链日志：`知识库P1_20261118/megaman1_route_20261125/consumer_query_log_20261125.jsonl`

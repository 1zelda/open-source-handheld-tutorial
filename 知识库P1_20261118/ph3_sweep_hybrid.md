# 选择器接线扫描 · 2026-11-23 23:15:47

- 臂：`hybrid_union12`；索引：`index_hybrid.json` sha16 db21095794629388（745 块）；候选池 top30
- 代码指纹：kb=be187b2ea50a0730，kb_selector=50350f10cc1355d4，kb_route=bd7bf902222ae613，kb_dense=76ae1934b59d798b，eval_common=461aad1af957eacc

## 接法：replace

- v2 判分：生产 22/26 → 接线后 20/26
- 四分类：{'unchanged_ok': 20, 'unchanged_fail': 4, 'regressed': 2}
- 错误出证：生产 ['Q06', 'Q08', 'Q10', 'Q16', 'Q18', 'P22', 'P23', 'P24'] → 接线后 ['Q07', 'Q08', 'Q10', 'Q17']
- 漏答：生产 ['Q17', 'P19'] → 接线后 ['Q03', 'Q05', 'Q06', 'Q16', 'Q18', 'P19', 'P22', 'P23', 'P24']
- 仍 pass 但出证块被换：['Q06', 'Q07', 'Q11', 'Q16', 'Q17', 'P22', 'P23', 'P24']
- 问句事实类分布：{'count': 3, 'role_attribution': 1, 'None': 16, 'capability': 3, 'player_role': 1, 'exact_value': 2}
- 金标首次被选中所需窗口：{'Q01': 3, 'Q02': None, 'Q03': None, 'Q04': 3, 'Q05': None, 'Q06': None, 'Q07': None, 'Q08': None, 'Q09': None, 'Q10': None, 'Q11': None, 'Q12': None, 'Q13': None, 'Q14': None, 'Q15': None, 'Q16': None, 'Q17': None, 'Q18': None, 'P19': None, 'P20': None, 'P21': None, 'P22': None, 'P23': None, 'P24': None, 'P25': None, 'P26': None}
- 探针(带标签30)：{'insufficient_source': {'newly_passed': 4, 'still_refused': 6, 'intercepted': 9}, 'positive_control': {'intercepted': 2, 'newly_passed': 1}, 'ambiguous': {'still_refused': 1}, 'true_negative': {'still_refused': 5, 'intercepted': 2}}
- 探针(基础30，只看状态变化)：{'intercepted': 14, 'newly_passed': 3, 'still_passed': 2, 'still_refused': 11}

| 题 | 档 | 分类 | 事实类 | 生产 | 接线后 | 选中位 | 生产出证块 | 接线后出证块 |
|---|---|---|---|---|---|---|---|---|
| Q01 | strict_pass | unchanged_ok | count | True | True | 3 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L3-L7 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L3-L7 |
| Q02 | strict_pass | unchanged_fail | role_attribution | False | False | None | None | None |
| Q03 | strict_pass | regressed | None | True | False | None | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 | None |
| Q04 | gold_in_topk | unchanged_ok | capability | True | True | 1 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 |
| Q05 | strict_pass | regressed | None | True | False | None | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 | None |
| Q06 | gold_in_topk | unchanged_ok | count | True | True | None | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md#L7-L10 | None |
| Q07 | gold_in_topk | unchanged_ok | count | True | True | 2 | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L76-L85 | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md#L21-L22 |
| Q08 | gold_in_topk | unchanged_fail | player_role | False | False | 2 | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md#L7-L10 | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md#L7-L10 |
| Q09 | refuse | unchanged_ok | exact_value | True | True | None | None | None |
| Q10 | strict_pass | unchanged_fail | capability | False | False | 6 | F:/tas_rig/docs/素材生产规范.md#L18-L31 | F:/tas_rig/docs/素材生产规范.md#L34-L59 |
| Q11 | version_guard | unchanged_ok | None | True | True | None | F:/tas_rig/docs/素材生产规范.md#L140-L155 | None |
| Q12 | refuse | unchanged_ok | None | True | True | None | None | None |
| Q13 | refuse | unchanged_ok | None | True | True | None | None | None |
| Q14 | refuse | unchanged_ok | None | True | True | None | None | None |
| Q15 | refuse | unchanged_ok | None | True | True | None | None | None |
| Q16 | gold_in_topk | unchanged_ok | None | True | True | None | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md#L54-L57 | None |
| Q17 | gold_in_topk | unchanged_ok | capability | True | True | 3 | None | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L216-L225 |
| Q18 | strict_pass | unchanged_fail | None | False | False | None | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L137-L158 | None |
| P19 | gold_in_topk | unchanged_ok | None | True | True | None | None | None |
| P20 | refuse | unchanged_ok | None | True | True | None | None | None |
| P21 | refuse | unchanged_ok | exact_value | True | True | None | None | None |
| P22 | gold_in_topk | unchanged_ok | None | True | True | None | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md#L73-L74 | None |
| P23 | gold_in_topk | unchanged_ok | None | True | True | None | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md#L3-L4 | None |
| P24 | gold_in_topk | unchanged_ok | None | True | True | None | 测试问题与闸门说明书.md#L924-L939 | None |
| P25 | refuse | unchanged_ok | None | True | True | None | None | None |
| P26 | refuse | unchanged_ok | None | True | True | None | None | None |

| 探针 | 标签 | 分类 | 事实类 | 选中位 | 生产状态 | 选择器原因 |
|---|---|---|---|---|---|---|
| X01 | insufficient_source | newly_passed | exact_value | 3 | inconclusive | 第3位块过七项核查 |
| X02 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X03 | positive_control | intercepted | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X04 | ambiguous | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X05 | insufficient_source | intercepted | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X06 | insufficient_source | newly_passed | count | 1 | inconclusive | 第1位块过七项核查 |
| X07 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X08 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X09 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X10 | insufficient_source | newly_passed | count | 2 | inconclusive | 第2位块过七项核查 |
| X11 | true_negative | still_refused | capability | None | inconclusive | 无块同时过七项核查（初筛可答≠合格证据） |
| X12 | true_negative | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X13 | true_negative | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X14 | true_negative | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X15 | positive_control | newly_passed | count | 4 | inconclusive | 第4位块过七项核查 |
| X16 | insufficient_source | newly_passed | capability | 2 | inconclusive | 第2位块过七项核查 |
| X17 | insufficient_source | intercepted | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X18 | insufficient_source | intercepted | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X19 | insufficient_source | intercepted | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X20 | insufficient_source | intercepted | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X21 | positive_control | intercepted | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X22 | true_negative | intercepted | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X23 | insufficient_source | intercepted | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X24 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X25 | true_negative | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X26 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X27 | insufficient_source | intercepted | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X28 | true_negative | intercepted | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X29 | insufficient_source | intercepted | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X30 | insufficient_source | intercepted | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |

## 接法：scoped

- v2 判分：生产 22/26 → 接线后 22/26
- 四分类：{'unchanged_ok': 22, 'unchanged_fail': 4}
- 错误出证：生产 ['Q06', 'Q08', 'Q10', 'Q16', 'Q18', 'P22', 'P23', 'P24'] → 接线后 ['Q07', 'Q08', 'Q10', 'Q16', 'Q17', 'Q18', 'P22', 'P23', 'P24']
- 漏答：生产 ['Q17', 'P19'] → 接线后 ['Q06', 'P19']
- 仍 pass 但出证块被换：['Q06', 'Q07', 'Q17']
- 问句事实类分布：{'count': 3, 'role_attribution': 1, 'None': 16, 'capability': 3, 'player_role': 1, 'exact_value': 2}
- 金标首次被选中所需窗口：{'Q01': 3, 'Q02': None, 'Q03': None, 'Q04': 3, 'Q05': None, 'Q06': None, 'Q07': None, 'Q08': None, 'Q09': None, 'Q10': None, 'Q11': None, 'Q12': None, 'Q13': None, 'Q14': None, 'Q15': None, 'Q16': None, 'Q17': None, 'Q18': None, 'P19': None, 'P20': None, 'P21': None, 'P22': None, 'P23': None, 'P24': None, 'P25': None, 'P26': None}
- 探针(带标签30)：{'insufficient_source': {'newly_passed': 4, 'still_refused': 6, 'still_passed': 9}, 'positive_control': {'still_passed': 2, 'newly_passed': 1}, 'ambiguous': {'still_refused': 1}, 'true_negative': {'still_refused': 5, 'still_passed': 2}}
- 探针(基础30，只看状态变化)：{'still_passed': 15, 'newly_passed': 3, 'still_refused': 11, 'intercepted': 1}

| 题 | 档 | 分类 | 事实类 | 生产 | 接线后 | 选中位 | 生产出证块 | 接线后出证块 |
|---|---|---|---|---|---|---|---|---|
| Q01 | strict_pass | unchanged_ok | count | True | True | 3 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L3-L7 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L3-L7 |
| Q02 | strict_pass | unchanged_fail | role_attribution | False | False | None | None | None |
| Q03 | strict_pass | unchanged_ok | None | True | True | None | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 |
| Q04 | gold_in_topk | unchanged_ok | capability | True | True | 1 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 |
| Q05 | strict_pass | unchanged_ok | None | True | True | None | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 |
| Q06 | gold_in_topk | unchanged_ok | count | True | True | None | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md#L7-L10 | None |
| Q07 | gold_in_topk | unchanged_ok | count | True | True | 2 | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L76-L85 | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md#L21-L22 |
| Q08 | gold_in_topk | unchanged_fail | player_role | False | False | 2 | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md#L7-L10 | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md#L7-L10 |
| Q09 | refuse | unchanged_ok | exact_value | True | True | None | None | None |
| Q10 | strict_pass | unchanged_fail | capability | False | False | 6 | F:/tas_rig/docs/素材生产规范.md#L18-L31 | F:/tas_rig/docs/素材生产规范.md#L34-L59 |
| Q11 | version_guard | unchanged_ok | None | True | True | None | F:/tas_rig/docs/素材生产规范.md#L140-L155 | F:/tas_rig/docs/素材生产规范.md#L140-L155 |
| Q12 | refuse | unchanged_ok | None | True | True | None | None | None |
| Q13 | refuse | unchanged_ok | None | True | True | None | None | None |
| Q14 | refuse | unchanged_ok | None | True | True | None | None | None |
| Q15 | refuse | unchanged_ok | None | True | True | None | None | None |
| Q16 | gold_in_topk | unchanged_ok | None | True | True | None | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md#L54-L57 | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md#L54-L57 |
| Q17 | gold_in_topk | unchanged_ok | capability | True | True | 3 | None | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L216-L225 |
| Q18 | strict_pass | unchanged_fail | None | False | False | None | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L137-L158 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L137-L158 |
| P19 | gold_in_topk | unchanged_ok | None | True | True | None | None | None |
| P20 | refuse | unchanged_ok | None | True | True | None | None | None |
| P21 | refuse | unchanged_ok | exact_value | True | True | None | None | None |
| P22 | gold_in_topk | unchanged_ok | None | True | True | None | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md#L73-L74 | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md#L73-L74 |
| P23 | gold_in_topk | unchanged_ok | None | True | True | None | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md#L3-L4 | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md#L3-L4 |
| P24 | gold_in_topk | unchanged_ok | None | True | True | None | 测试问题与闸门说明书.md#L924-L939 | 测试问题与闸门说明书.md#L924-L939 |
| P25 | refuse | unchanged_ok | None | True | True | None | None | None |
| P26 | refuse | unchanged_ok | None | True | True | None | None | None |

| 探针 | 标签 | 分类 | 事实类 | 选中位 | 生产状态 | 选择器原因 |
|---|---|---|---|---|---|---|
| X01 | insufficient_source | newly_passed | exact_value | 3 | inconclusive | 第3位块过七项核查 |
| X02 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X03 | positive_control | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X04 | ambiguous | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X05 | insufficient_source | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X06 | insufficient_source | newly_passed | count | 1 | inconclusive | 第1位块过七项核查 |
| X07 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X08 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X09 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X10 | insufficient_source | newly_passed | count | 2 | inconclusive | 第2位块过七项核查 |
| X11 | true_negative | still_refused | capability | None | inconclusive | 无块同时过七项核查（初筛可答≠合格证据） |
| X12 | true_negative | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X13 | true_negative | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X14 | true_negative | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X15 | positive_control | newly_passed | count | 4 | inconclusive | 第4位块过七项核查 |
| X16 | insufficient_source | newly_passed | capability | 2 | inconclusive | 第2位块过七项核查 |
| X17 | insufficient_source | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X18 | insufficient_source | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X19 | insufficient_source | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X20 | insufficient_source | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X21 | positive_control | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X22 | true_negative | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X23 | insufficient_source | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X24 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X25 | true_negative | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X26 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X27 | insufficient_source | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X28 | true_negative | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X29 | insufficient_source | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X30 | insufficient_source | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |

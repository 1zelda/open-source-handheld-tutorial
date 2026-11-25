# 选择器生产接线实测 · 2026-11-24 23:15:03

- 索引：`index.json` sha16 2a93e76d5876c118（773 块）；候选 top30，生产窗口 3
- 代码指纹：kb=1844d8baceb5ce65，kb_answer=da05727ede62ffb3，kb_selector=5843b007d66e88e2，kb_route=a22fe95be89c1c57，kb_dense=76ae1934b59d798b，kb_provenance=4bcf3411ab460320，eval_common=461aad1af957eacc，producer=4112752fecdad192

## 总结（生产基线 26/26）

| 模式 | v2 | 修好 | 打坏 | 错误出证 | 仍pass但换证 | 探针新放行 | 探针拦截 |
|---|---|---|---|---|---|---|---|
| scoped | 26/26 | 0 | 0 | [] | ['Q06', 'Q07'] | [] | [] |
| scoped_beyond | 26/26 | 0 | 0 | [] | ['Q06', 'Q07'] | ['X11'] | [] |
| replace | 23/26 | 0 | 3 | [] | ['Q06', 'Q07', 'P22', 'P23', 'P24'] | [] | ['X03', 'X04', 'X05', 'X17', 'X19', 'X20', 'X21', 'X22', 'X23', 'X30'] |
| strict_fragments | 21/26 | 0 | 5 | [] | ['Q04'] | [] | ['X03', 'X04', 'X05', 'X17', 'X19', 'X20', 'X22', 'X23', 'X30'] |

## scoped

| 题 | 档 | 分类 | 基线 | 接线后 | 选中位 | 基线出证 | 接线后出证 |
|---|---|---|---|---|---|---|---|
| Q01 | strict_pass | unchanged_ok | True | True | 3 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L3-L7 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L3-L7 |
| Q02 | strict_pass | unchanged_ok | True | True | 1 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L70-L85 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L70-L85 |
| Q03 | strict_pass | unchanged_ok | True | True | None | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 |
| Q04 | gold_in_topk | unchanged_ok | True | True | 1 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 |
| Q05 | strict_pass | unchanged_ok | True | True | None | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 |
| Q06 | gold_in_topk | unchanged_ok | True | True | None | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L47-L48 | None |
| Q07 | gold_in_topk | unchanged_ok | True | True | None | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L76-L85 | None |
| Q08 | gold_in_topk | unchanged_ok | True | True | 2 | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L47-L48 | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L47-L48 |
| Q09 | refuse | unchanged_ok | True | True | None | None | None |
| Q10 | strict_pass | unchanged_ok | True | True | 1 | F:/tas_rig/docs/素材生产规范.md#L185-L190 | F:/tas_rig/docs/素材生产规范.md#L185-L190 |
| Q11 | version_guard | unchanged_ok | True | True | None | None | None |
| Q12 | refuse | unchanged_ok | True | True | None | None | None |
| Q13 | refuse | unchanged_ok | True | True | None | None | None |
| Q14 | refuse | unchanged_ok | True | True | None | None | None |
| Q15 | refuse | unchanged_ok | True | True | None | None | None |
| Q16 | gold_in_topk | unchanged_ok | True | True | None | None | None |
| Q17 | gold_in_topk | unchanged_ok | True | True | None | None | None |
| Q18 | strict_pass | unchanged_ok | True | True | None | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L251-L259 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L251-L259 |
| P19 | gold_in_topk | unchanged_ok | True | True | None | None | None |
| P20 | refuse | unchanged_ok | True | True | None | None | None |
| P21 | refuse | unchanged_ok | True | True | None | None | None |
| P22 | gold_in_topk | unchanged_ok | True | True | None | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L327-L341 | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L327-L341 |
| P23 | gold_in_topk | unchanged_ok | True | True | None | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L267-L288 | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L267-L288 |
| P24 | gold_in_topk | unchanged_ok | True | True | None | 测试问题与闸门说明书.md#L76-L79 | 测试问题与闸门说明书.md#L76-L79 |
| P25 | refuse | unchanged_ok | True | True | None | None | None |
| P26 | refuse | unchanged_ok | True | True | None | None | None |

| 探针 | 标签 | 分类 | 事实类 | 选中位 | 状态 | 选择器原因 |
|---|---|---|---|---|---|---|
| X01 | insufficient_source | still_refused | exact_value | None | inconclusive | 无块同时过七项核查（初筛可答≠合格证据） |
| X02 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X03 | positive_control | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X04 | ambiguous | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X05 | insufficient_source | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X06 | insufficient_source | still_refused | count | None | inconclusive | 无块同时过七项核查（初筛可答≠合格证据） |
| X07 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X08 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X09 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X10 | insufficient_source | still_refused | count | None | inconclusive | 无块同时过七项核查（初筛可答≠合格证据） |
| X11 | true_negative | still_refused | capability | 12 | inconclusive | 第12位块过七项核查 |
| X12 | true_negative | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X13 | true_negative | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X14 | true_negative | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X15 | positive_control | still_refused | count | None | inconclusive | 无块同时过七项核查（初筛可答≠合格证据） |
| X16 | insufficient_source | still_refused | capability | None | inconclusive | 无块同时过七项核查（初筛可答≠合格证据） |
| X17 | insufficient_source | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X18 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X19 | insufficient_source | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X20 | insufficient_source | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X21 | positive_control | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X22 | true_negative | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X23 | insufficient_source | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X24 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X25 | true_negative | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X26 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X27 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X28 | true_negative | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X29 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X30 | insufficient_source | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |

## scoped_beyond

| 题 | 档 | 分类 | 基线 | 接线后 | 选中位 | 基线出证 | 接线后出证 |
|---|---|---|---|---|---|---|---|
| Q01 | strict_pass | unchanged_ok | True | True | 3 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L3-L7 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L3-L7 |
| Q02 | strict_pass | unchanged_ok | True | True | 1 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L70-L85 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L70-L85 |
| Q03 | strict_pass | unchanged_ok | True | True | None | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 |
| Q04 | gold_in_topk | unchanged_ok | True | True | 1 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 |
| Q05 | strict_pass | unchanged_ok | True | True | None | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 |
| Q06 | gold_in_topk | unchanged_ok | True | True | None | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L47-L48 | None |
| Q07 | gold_in_topk | unchanged_ok | True | True | None | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L76-L85 | None |
| Q08 | gold_in_topk | unchanged_ok | True | True | 2 | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L47-L48 | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L47-L48 |
| Q09 | refuse | unchanged_ok | True | True | None | None | None |
| Q10 | strict_pass | unchanged_ok | True | True | 1 | F:/tas_rig/docs/素材生产规范.md#L185-L190 | F:/tas_rig/docs/素材生产规范.md#L185-L190 |
| Q11 | version_guard | unchanged_ok | True | True | None | None | None |
| Q12 | refuse | unchanged_ok | True | True | None | None | None |
| Q13 | refuse | unchanged_ok | True | True | None | None | None |
| Q14 | refuse | unchanged_ok | True | True | None | None | None |
| Q15 | refuse | unchanged_ok | True | True | None | None | None |
| Q16 | gold_in_topk | unchanged_ok | True | True | None | None | None |
| Q17 | gold_in_topk | unchanged_ok | True | True | None | None | None |
| Q18 | strict_pass | unchanged_ok | True | True | None | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L251-L259 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L251-L259 |
| P19 | gold_in_topk | unchanged_ok | True | True | None | None | None |
| P20 | refuse | unchanged_ok | True | True | None | None | None |
| P21 | refuse | unchanged_ok | True | True | None | None | None |
| P22 | gold_in_topk | unchanged_ok | True | True | None | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L327-L341 | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L327-L341 |
| P23 | gold_in_topk | unchanged_ok | True | True | None | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L267-L288 | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L267-L288 |
| P24 | gold_in_topk | unchanged_ok | True | True | None | 测试问题与闸门说明书.md#L76-L79 | 测试问题与闸门说明书.md#L76-L79 |
| P25 | refuse | unchanged_ok | True | True | None | None | None |
| P26 | refuse | unchanged_ok | True | True | None | None | None |

| 探针 | 标签 | 分类 | 事实类 | 选中位 | 状态 | 选择器原因 |
|---|---|---|---|---|---|---|
| X01 | insufficient_source | still_refused | exact_value | None | inconclusive | 无块同时过七项核查（初筛可答≠合格证据） |
| X02 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X03 | positive_control | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X04 | ambiguous | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X05 | insufficient_source | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X06 | insufficient_source | still_refused | count | None | inconclusive | 无块同时过七项核查（初筛可答≠合格证据） |
| X07 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X08 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X09 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X10 | insufficient_source | still_refused | count | None | inconclusive | 无块同时过七项核查（初筛可答≠合格证据） |
| X11 | true_negative | newly_passed | capability | 12 | pass | 第12位块过七项核查 |
| X12 | true_negative | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X13 | true_negative | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X14 | true_negative | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X15 | positive_control | still_refused | count | None | inconclusive | 无块同时过七项核查（初筛可答≠合格证据） |
| X16 | insufficient_source | still_refused | capability | None | inconclusive | 无块同时过七项核查（初筛可答≠合格证据） |
| X17 | insufficient_source | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X18 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X19 | insufficient_source | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X20 | insufficient_source | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X21 | positive_control | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X22 | true_negative | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X23 | insufficient_source | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X24 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X25 | true_negative | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X26 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X27 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X28 | true_negative | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X29 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X30 | insufficient_source | still_passed | None | None | pass | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |

## replace

| 题 | 档 | 分类 | 基线 | 接线后 | 选中位 | 基线出证 | 接线后出证 |
|---|---|---|---|---|---|---|---|
| Q01 | strict_pass | unchanged_ok | True | True | 3 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L3-L7 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L3-L7 |
| Q02 | strict_pass | unchanged_ok | True | True | 1 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L70-L85 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L70-L85 |
| Q03 | strict_pass | regressed | True | False | None | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 | None |
| Q04 | gold_in_topk | unchanged_ok | True | True | 1 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 |
| Q05 | strict_pass | regressed | True | False | None | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 | None |
| Q06 | gold_in_topk | unchanged_ok | True | True | None | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L47-L48 | None |
| Q07 | gold_in_topk | unchanged_ok | True | True | None | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L76-L85 | None |
| Q08 | gold_in_topk | unchanged_ok | True | True | 2 | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L47-L48 | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L47-L48 |
| Q09 | refuse | unchanged_ok | True | True | None | None | None |
| Q10 | strict_pass | unchanged_ok | True | True | 1 | F:/tas_rig/docs/素材生产规范.md#L185-L190 | F:/tas_rig/docs/素材生产规范.md#L185-L190 |
| Q11 | version_guard | unchanged_ok | True | True | None | None | None |
| Q12 | refuse | unchanged_ok | True | True | None | None | None |
| Q13 | refuse | unchanged_ok | True | True | None | None | None |
| Q14 | refuse | unchanged_ok | True | True | None | None | None |
| Q15 | refuse | unchanged_ok | True | True | None | None | None |
| Q16 | gold_in_topk | unchanged_ok | True | True | None | None | None |
| Q17 | gold_in_topk | unchanged_ok | True | True | None | None | None |
| Q18 | strict_pass | regressed | True | False | None | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L251-L259 | None |
| P19 | gold_in_topk | unchanged_ok | True | True | None | None | None |
| P20 | refuse | unchanged_ok | True | True | None | None | None |
| P21 | refuse | unchanged_ok | True | True | None | None | None |
| P22 | gold_in_topk | unchanged_ok | True | True | None | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L327-L341 | None |
| P23 | gold_in_topk | unchanged_ok | True | True | None | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L267-L288 | None |
| P24 | gold_in_topk | unchanged_ok | True | True | None | 测试问题与闸门说明书.md#L76-L79 | None |
| P25 | refuse | unchanged_ok | True | True | None | None | None |
| P26 | refuse | unchanged_ok | True | True | None | None | None |

| 探针 | 标签 | 分类 | 事实类 | 选中位 | 状态 | 选择器原因 |
|---|---|---|---|---|---|---|
| X01 | insufficient_source | still_refused | exact_value | None | inconclusive | 无块同时过七项核查（初筛可答≠合格证据） |
| X02 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X03 | positive_control | intercepted | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X04 | ambiguous | intercepted | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X05 | insufficient_source | intercepted | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X06 | insufficient_source | still_refused | count | None | inconclusive | 无块同时过七项核查（初筛可答≠合格证据） |
| X07 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X08 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X09 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X10 | insufficient_source | still_refused | count | None | inconclusive | 无块同时过七项核查（初筛可答≠合格证据） |
| X11 | true_negative | still_refused | capability | 12 | inconclusive | 第12位块过七项核查 |
| X12 | true_negative | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X13 | true_negative | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X14 | true_negative | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X15 | positive_control | still_refused | count | None | inconclusive | 无块同时过七项核查（初筛可答≠合格证据） |
| X16 | insufficient_source | still_refused | capability | None | inconclusive | 无块同时过七项核查（初筛可答≠合格证据） |
| X17 | insufficient_source | intercepted | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X18 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X19 | insufficient_source | intercepted | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X20 | insufficient_source | intercepted | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X21 | positive_control | intercepted | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X22 | true_negative | intercepted | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X23 | insufficient_source | intercepted | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X24 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X25 | true_negative | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X26 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X27 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X28 | true_negative | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X29 | insufficient_source | still_refused | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |
| X30 | insufficient_source | intercepted | None | None | inconclusive | 复杂问题（因果/比较/攻略综合）暂返回材料+缺口，不强行下结论 |

## strict_fragments

| 题 | 档 | 分类 | 基线 | 接线后 | 选中位 | 基线出证 | 接线后出证 |
|---|---|---|---|---|---|---|---|
| Q01 | strict_pass | regressed | True | False | None | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L3-L7 | None |
| Q02 | strict_pass | regressed | True | False | None | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L70-L85 | None |
| Q03 | strict_pass | regressed | True | False | None | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 | None |
| Q04 | gold_in_topk | unchanged_ok | True | True | None | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 | None |
| Q05 | strict_pass | regressed | True | False | None | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 | None |
| Q06 | gold_in_topk | unchanged_ok | True | True | None | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L47-L48 | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L47-L48 |
| Q07 | gold_in_topk | unchanged_ok | True | True | None | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L76-L85 | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L76-L85 |
| Q08 | gold_in_topk | unchanged_ok | True | True | None | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L47-L48 | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L47-L48 |
| Q09 | refuse | unchanged_ok | True | True | None | None | None |
| Q10 | strict_pass | unchanged_ok | True | True | None | F:/tas_rig/docs/素材生产规范.md#L185-L190 | F:/tas_rig/docs/素材生产规范.md#L185-L190 |
| Q11 | version_guard | unchanged_ok | True | True | None | None | None |
| Q12 | refuse | unchanged_ok | True | True | None | None | None |
| Q13 | refuse | unchanged_ok | True | True | None | None | None |
| Q14 | refuse | unchanged_ok | True | True | None | None | None |
| Q15 | refuse | unchanged_ok | True | True | None | None | None |
| Q16 | gold_in_topk | unchanged_ok | True | True | None | None | None |
| Q17 | gold_in_topk | unchanged_ok | True | True | None | None | None |
| Q18 | strict_pass | regressed | True | False | None | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L251-L259 | None |
| P19 | gold_in_topk | unchanged_ok | True | True | None | None | None |
| P20 | refuse | unchanged_ok | True | True | None | None | None |
| P21 | refuse | unchanged_ok | True | True | None | None | None |
| P22 | gold_in_topk | unchanged_ok | True | True | None | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L327-L341 | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L327-L341 |
| P23 | gold_in_topk | unchanged_ok | True | True | None | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L267-L288 | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L267-L288 |
| P24 | gold_in_topk | unchanged_ok | True | True | None | 测试问题与闸门说明书.md#L76-L79 | 测试问题与闸门说明书.md#L76-L79 |
| P25 | refuse | unchanged_ok | True | True | None | None | None |
| P26 | refuse | unchanged_ok | True | True | None | None | None |

| 探针 | 标签 | 分类 | 事实类 | 选中位 | 状态 | 选择器原因 |
|---|---|---|---|---|---|---|
| X01 | insufficient_source | still_refused | None | None | inconclusive | None |
| X02 | insufficient_source | still_refused | None | None | inconclusive | None |
| X03 | positive_control | intercepted | None | None | inconclusive | None |
| X04 | ambiguous | intercepted | None | None | inconclusive | None |
| X05 | insufficient_source | intercepted | None | None | inconclusive | None |
| X06 | insufficient_source | still_refused | None | None | inconclusive | None |
| X07 | insufficient_source | still_refused | None | None | inconclusive | None |
| X08 | insufficient_source | still_refused | None | None | inconclusive | None |
| X09 | insufficient_source | still_refused | None | None | inconclusive | None |
| X10 | insufficient_source | still_refused | None | None | inconclusive | None |
| X11 | true_negative | still_refused | None | None | inconclusive | None |
| X12 | true_negative | still_refused | None | None | inconclusive | None |
| X13 | true_negative | still_refused | None | None | inconclusive | None |
| X14 | true_negative | still_refused | None | None | inconclusive | None |
| X15 | positive_control | still_refused | None | None | inconclusive | None |
| X16 | insufficient_source | still_refused | None | None | inconclusive | None |
| X17 | insufficient_source | intercepted | None | None | inconclusive | None |
| X18 | insufficient_source | still_refused | None | None | inconclusive | None |
| X19 | insufficient_source | intercepted | None | None | inconclusive | None |
| X20 | insufficient_source | intercepted | None | None | inconclusive | None |
| X21 | positive_control | still_passed | None | None | pass | None |
| X22 | true_negative | intercepted | None | None | inconclusive | None |
| X23 | insufficient_source | intercepted | None | None | inconclusive | None |
| X24 | insufficient_source | still_refused | None | None | inconclusive | None |
| X25 | true_negative | still_refused | None | None | inconclusive | None |
| X26 | insufficient_source | still_refused | None | None | inconclusive | None |
| X27 | insufficient_source | still_refused | None | None | inconclusive | None |
| X28 | true_negative | still_refused | None | None | inconclusive | None |
| X29 | insufficient_source | still_refused | None | None | inconclusive | None |
| X30 | insufficient_source | intercepted | None | None | inconclusive | None |

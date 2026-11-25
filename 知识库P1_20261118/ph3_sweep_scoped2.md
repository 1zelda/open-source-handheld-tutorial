# 选择器接线扫描 · 三种接法对照（派生自 ph3_sweep_{bm25,hybrid}.json）

## bm25（`bm25_only`，index.json 731 块，2026-11-23 23:14:06）

| 接法 | v2 判分 | 修好 | 打坏 | 错误出证 | 探针变化 |
|---|---|---|---|---|---|
| 生产现状 | 22/26 | — | — | ['Q08', 'Q16', 'Q18', 'P24'] | — |
| 整体替换 | 21/26 | 1 题 | 2 题 | 见 sweep | insufficient_source:newly_passed=4；insufficient_source:intercepted=5；positive_control:intercepted=1；true_negative:newly_passed=1；true_negative:intercepted=1 |
| 五类全接（scoped） | 22/26 | 1 题 | 1 题 | ['Q06', 'Q10', 'Q16', 'Q17', 'Q18', 'P24'] | insufficient_source:newly_passed=4；true_negative:newly_passed=1 |
| **只接归属+分工两类** | 23/26 | ['Q02'] | [] | ['Q16', 'Q18', 'P24'] | 无 |

- 只接两类的漏答：生产 ['Q02', 'Q03', 'Q17', 'P19'] → 接线后 ['Q03', 'Q17', 'P19']
- 出证块被换（仍 pass）：{'Q08': ['_工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L376-L401', '_工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L47-L47']}
- 被选中块所在位次：{'Q02': 10, 'Q08': 19}

## hybrid（`hybrid_union12`，index_hybrid.json 745 块，2026-11-23 23:15:47）

| 接法 | v2 判分 | 修好 | 打坏 | 错误出证 | 探针变化 |
|---|---|---|---|---|---|
| 生产现状 | 22/26 | — | — | ['Q06', 'Q08', 'Q10', 'Q16', 'Q18', 'P22', 'P23', 'P24'] | — |
| 整体替换 | 20/26 | 0 题 | 2 题 | 见 sweep | insufficient_source:newly_passed=4；insufficient_source:intercepted=9；positive_control:newly_passed=1；positive_control:intercepted=2；true_negative:intercepted=2 |
| 五类全接（scoped） | 22/26 | 0 题 | 0 题 | ['Q07', 'Q08', 'Q10', 'Q16', 'Q17', 'Q18', 'P22', 'P23', 'P24'] | insufficient_source:newly_passed=4；positive_control:newly_passed=1 |
| **只接归属+分工两类** | 22/26 | [] | [] | ['Q06', 'Q08', 'Q10', 'Q16', 'Q18', 'P22', 'P23', 'P24'] | 无 |

- 只接两类的漏答：生产 ['Q17', 'P19'] → 接线后 ['Q17', 'P19']
- 出证块被换（仍 pass）：{}
- 被选中块所在位次：{'Q02': None, 'Q08': 2}

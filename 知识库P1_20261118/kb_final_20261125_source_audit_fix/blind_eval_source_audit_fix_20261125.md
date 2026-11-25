# 隔离盲测 · 2026-11-25 01:32:23

- 严格通过：26/26
- API：`query_auto`；topk=30；top_window=3
- 索引：`F:\开源掌机教程\_工具脚本\taspipe\游戏包\知识库\index.json` sha256 `fe56dc5427418a6c5a4d60cc16610e1920ea0fafa4ba42ce479c294e80f95f8b`
- 真实状态隔离：PASS
- 隔离查询日志：未启用

## 分档

| 档 | 通过 | 总数 |
|---|---:|---:|
| strict_pass | 6 | 6 |
| gold_in_topk | 10 | 10 |
| refuse | 9 | 9 |
| version_guard | 1 | 1 |

## 逐题

| 题 | 档 | 结果 | 状态/拒答 | 出证定位 | 说明 |
|---|---|---|---|---|---|
| Q01 | strict_pass | True | pass/- | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L3-L7 | status=pass, selected_gold=True, direct_recall=True |
| Q02 | strict_pass | True | pass/- | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L70-L85 | status=pass, selected_gold=True, direct_recall=True |
| Q03 | strict_pass | True | pass/- | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 | status=pass, selected_gold=True, direct_recall=True |
| Q04 | gold_in_topk | True | pass/- | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 | status=pass, gold_in_top30=True |
| Q05 | strict_pass | True | pass/- | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 | status=pass, selected_gold=True, direct_recall=True |
| Q06 | gold_in_topk | True | pass/- | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L47-L48 | status=pass, gold_in_top30=True |
| Q07 | gold_in_topk | True | pass/- | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L76-L85 | status=pass, gold_in_top30=True |
| Q08 | gold_in_topk | True | pass/- | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L47-L48 | status=pass, gold_in_top20=True |
| Q09 | refuse | True | inconclusive/unanswerable | - | status=inconclusive（pass 即失败：缺证据不许冒充事实） |
| Q10 | strict_pass | True | pass/- | F:/tas_rig/docs/素材生产规范.md#L185-L190 | status=pass, selected_gold=True, direct_recall=True |
| Q11 | version_guard | True | inconclusive/- | - | status=inconclusive, um_hits=2, top1_um=True, sel_um=False, warned=True |
| Q12 | refuse | True | miss/out_of_scope | - | status=miss（pass 即失败：缺证据不许冒充事实） |
| Q13 | refuse | True | miss/out_of_scope | - | status=miss（pass 即失败：缺证据不许冒充事实） |
| Q14 | refuse | True | miss/out_of_scope | - | status=miss（pass 即失败：缺证据不许冒充事实） |
| Q15 | refuse | True | inconclusive/unanswerable | - | status=inconclusive（pass 即失败：缺证据不许冒充事实） |
| Q16 | gold_in_topk | True | inconclusive/- | - | status=inconclusive, gold_in_top30=True |
| Q17 | gold_in_topk | True | inconclusive/- | - | status=inconclusive, gold_in_top28=True |
| Q18 | strict_pass | True | pass/- | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L251-L259 | status=pass, selected_gold=True, direct_recall=True |
| P19 | gold_in_topk | True | inconclusive/- | - | status=inconclusive, gold_in_top30=True |
| P20 | refuse | True | miss/out_of_scope | - | status=miss（pass 即失败：缺证据不许冒充事实） |
| P21 | refuse | True | inconclusive/unanswerable | - | status=inconclusive（pass 即失败：缺证据不许冒充事实） |
| P22 | gold_in_topk | True | pass/- | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L327-L341 | status=pass, gold_in_top30=True |
| P23 | gold_in_topk | True | pass/- | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L267-L288 | status=pass, gold_in_top30=True |
| P24 | gold_in_topk | True | pass/- | 测试问题与闸门说明书.md#L76-L79 | status=pass, gold_in_top30=True |
| P25 | refuse | True | inconclusive/unanswerable | - | status=inconclusive（pass 即失败：缺证据不许冒充事实） |
| P26 | refuse | True | miss/out_of_scope | - | status=miss（pass 即失败：缺证据不许冒充事实） |

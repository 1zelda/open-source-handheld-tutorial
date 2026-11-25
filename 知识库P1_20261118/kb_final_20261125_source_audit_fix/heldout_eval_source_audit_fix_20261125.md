# 隔离盲测 · 2026-11-25 01:32:25

- 严格通过：16/16
- API：`query_auto`；topk=30；top_window=3
- 索引：`F:\开源掌机教程\_工具脚本\taspipe\游戏包\知识库\index.json` sha256 `fe56dc5427418a6c5a4d60cc16610e1920ea0fafa4ba42ce479c294e80f95f8b`
- 真实状态隔离：PASS
- 隔离查询日志：未启用

## 分档

| 档 | 通过 | 总数 |
|---|---:|---:|
| strict_pass | 12 | 12 |
| refuse | 3 | 3 |
| version_guard | 1 | 1 |

## 逐题

| 题 | 档 | 结果 | 状态/拒答 | 出证定位 | 说明 |
|---|---|---|---|---|---|
| H01 | strict_pass | True | pass/- | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L307-L323 | status=pass, selected_gold=True, direct_recall=True |
| H02 | strict_pass | True | pass/- | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L307-L323 | status=pass, selected_gold=True, direct_recall=True |
| H03 | strict_pass | True | pass/- | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L327-L341 | status=pass, selected_gold=True, direct_recall=True |
| H04 | strict_pass | True | pass/- | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L376-L401 | status=pass, selected_gold=True, direct_recall=True |
| H05 | strict_pass | True | pass/- | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L88-L98 | status=pass, selected_gold=True, direct_recall=True |
| H06 | strict_pass | True | pass/- | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L70-L85 | status=pass, selected_gold=True, direct_recall=True |
| H07 | strict_pass | True | pass/- | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L70-L85 | status=pass, selected_gold=True, direct_recall=True |
| H08 | strict_pass | True | pass/- | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 | status=pass, selected_gold=True, direct_recall=True |
| H09 | strict_pass | True | pass/- | _工具脚本/taspipe/游戏包/来源库/取证/manual_熱血格闘伝説_TJC-NA_说明书摘录_20261124.md#L21-L24 | status=pass, selected_gold=True, direct_recall=True |
| H10 | strict_pass | True | pass/- | _工具脚本/taspipe/游戏包/来源库/取证/manual_熱血格闘伝説_TJC-NA_说明书摘录_20261124.md#L21-L24 | status=pass, selected_gold=True, direct_recall=True |
| H11 | strict_pass | True | pass/- | _工具脚本/taspipe/游戏包/来源库/取证/manual_熱血格闘伝説_TJC-NA_说明书摘录_20261124.md#L35-L37 | status=pass, selected_gold=True, direct_recall=True |
| H12 | strict_pass | True | pass/- | _工具脚本/taspipe/游戏包/来源库/取证/manual_熱血格闘伝説_TJC-NA_说明书摘录_20261124.md#L35-L37 | status=pass, selected_gold=True, direct_recall=True |
| H13 | refuse | True | inconclusive/unanswerable | - | status=inconclusive（pass 即失败：缺证据不许冒充事实） |
| H14 | version_guard | True | inconclusive/unanswerable | - | status=inconclusive, um_hits=2, top1_um=False, sel_um=False, warned=True |
| H15 | refuse | True | miss/out_of_scope | - | status=miss（pass 即失败：缺证据不许冒充事实） |
| H16 | refuse | True | miss/out_of_scope | - | status=miss（pass 即失败：缺证据不许冒充事实） |

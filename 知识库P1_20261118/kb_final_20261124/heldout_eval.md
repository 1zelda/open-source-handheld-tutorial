# 隔离盲测 · 2026-11-24 17:20:32

- 严格通过：6/16
- API：`query_auto`；topk=30；top_window=3
- 索引：`F:\开源掌机教程\_工具脚本\taspipe\游戏包\知识库\index.json` sha256 `80900ea3833ad64375c0b5f6872fa6bb6abdef47ba30eeb0100b3f300d837f40`
- 真实状态隔离：PASS
- 隔离查询日志：F:\开源掌机教程\知识库P1_20261118\kb_final_20261124\heldout_eval.query_log.jsonl

## 分档

| 档 | 通过 | 总数 |
|---|---:|---:|
| strict_pass | 4 | 12 |
| refuse | 2 | 3 |
| version_guard | 0 | 1 |

## 逐题

| 题 | 档 | 结果 | 状态/拒答 | 出证定位 | 说明 |
|---|---|---|---|---|---|
| H01 | strict_pass | False | inconclusive/- | - | status=inconclusive, selected_gold=False, direct_recall=True |
| H02 | strict_pass | False | pass/- | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L430-L453 | status=pass, selected_gold=False, direct_recall=True |
| H03 | strict_pass | False | pass/- | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L307-L323 | status=pass, selected_gold=False, direct_recall=True |
| H04 | strict_pass | False | inconclusive/- | - | status=inconclusive, selected_gold=False, direct_recall=True |
| H05 | strict_pass | False | inconclusive/- | - | status=inconclusive, selected_gold=False, direct_recall=True |
| H06 | strict_pass | False | inconclusive/- | - | status=inconclusive, selected_gold=False, direct_recall=True |
| H07 | strict_pass | False | inconclusive/- | - | status=inconclusive, selected_gold=False, direct_recall=True |
| H08 | strict_pass | True | pass/- | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 | status=pass, selected_gold=True, direct_recall=True |
| H09 | strict_pass | True | pass/- | _工具脚本/taspipe/游戏包/来源库/取证/manual_熱血格闘伝説_TJC-NA_说明书摘录_20261124.md#L21-L24 | status=pass, selected_gold=True, direct_recall=True |
| H10 | strict_pass | False | pass/- | _工具脚本/taspipe/游戏包/来源库/取证/manual_熱血格闘伝説_TJC-NA_说明书摘录_20261124.md#L35-L37 | status=pass, selected_gold=False, direct_recall=True |
| H11 | strict_pass | True | pass/- | _工具脚本/taspipe/游戏包/来源库/取证/manual_熱血格闘伝説_TJC-NA_说明书摘录_20261124.md#L35-L37 | status=pass, selected_gold=True, direct_recall=True |
| H12 | strict_pass | True | pass/- | _工具脚本/taspipe/游戏包/来源库/取证/manual_熱血格闘伝説_TJC-NA_说明书摘录_20261124.md#L35-L37 | status=pass, selected_gold=True, direct_recall=True |
| H13 | refuse | False | pass/- | F:/tas_rig/docs/素材生产规范.md#L18-L31 | status=pass（pass 即失败：缺证据不许冒充事实） |
| H14 | version_guard | False | inconclusive/unanswerable | - | status=inconclusive, um_hits=2, top1_um=False, sel_um=False, warned=False |
| H15 | refuse | True | miss/out_of_scope | - | status=miss（pass 即失败：缺证据不许冒充事实） |
| H16 | refuse | True | miss/out_of_scope | - | status=miss（pass 即失败：缺证据不许冒充事实） |

# 来源继承修正逐臂审计 · 2026-11-24

- 冻结金标未改；X23 保留 `insufficient_source`。
- strict 仍为显式影子臂；默认 `fragment_policy=None`。
- hybrid 仅用于探针，未获批准投产；稠密件已移出生产自动选臂路径。

## 四臂汇总

| 臂 | status=pass | status=inconclusive | status=miss | v2 通过 | v2 失败 | 错误出证 | 漏答 |
|---|---:|---:|---:|---:|---|---|---|
| base_default | 13 | 8 | 5 | 26/26 | 无 | 无 | Q16, Q17, P19 |
| base_strict | 7 | 14 | 5 | 21/26 | Q01, Q02, Q03, Q05, Q18 | 无 | Q01, Q02, Q03, Q04, Q05, Q16, Q17, Q18, P19 |
| hybrid_default | 14 | 7 | 5 | 22/26 | Q02, Q08, Q10, Q18 | Q06, Q08, Q10, Q16, Q18, P22, P23, P24 | Q02, Q17, P19 |
| hybrid_strict | 10 | 11 | 5 | 19/26 | Q01, Q02, Q03, Q05, Q08, Q10, Q18 | Q05, Q06, Q08, Q10, Q16, P22, P23 | Q01, Q02, Q03, Q04, Q17, Q18, P19 |

v2 的 `gold_in_topk` 档只要求金标进入候选并检查召回，不能把 `status=pass` 或正确出证混为一谈；Q04 即为 strict 状态 `inconclusive` 但 v2 仍通过的例子。

## 错误出证与漏答明细

| 题 | 臂 | 状态 | v2 | 正确证据 | 错误证据 | 漏答 | 选中定位 |
|---|---|---|---:|---|---|---|---|
| Q01 | base_strict | inconclusive | False | False | False | True | 无 |
| Q01 | hybrid_strict | inconclusive | False | False | False | True | 无 |
| Q02 | base_strict | inconclusive | False | False | False | True | 无 |
| Q02 | hybrid_default | inconclusive | False | False | False | True | 无 |
| Q02 | hybrid_strict | inconclusive | False | False | False | True | 无 |
| Q03 | base_strict | inconclusive | False | False | False | True | 无 |
| Q03 | hybrid_strict | inconclusive | False | False | False | True | 无 |
| Q04 | base_strict | inconclusive | True | False | False | True | 无 |
| Q04 | hybrid_strict | inconclusive | True | False | False | True | 无 |
| Q05 | base_strict | inconclusive | False | False | False | True | 无 |
| Q05 | hybrid_strict | pass | False | False | True | False | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L101-L119 |
| Q06 | hybrid_default | pass | True | False | True | False | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md#L7-L10 |
| Q06 | hybrid_strict | pass | True | False | True | False | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md#L7-L10 |
| Q08 | hybrid_default | pass | False | False | True | False | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md#L7-L10 |
| Q08 | hybrid_strict | pass | False | False | True | False | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md#L7-L10 |
| Q10 | hybrid_default | pass | False | False | True | False | F:/tas_rig/docs/素材生产规范.md#L18-L31 |
| Q10 | hybrid_strict | pass | False | False | True | False | F:/tas_rig/docs/素材生产规范.md#L18-L31 |
| Q16 | base_default | inconclusive | True | False | False | True | 无 |
| Q16 | base_strict | inconclusive | True | False | False | True | 无 |
| Q16 | hybrid_default | pass | True | False | True | False | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md#L54-L57 |
| Q16 | hybrid_strict | pass | True | False | True | False | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md#L54-L57 |
| Q17 | base_default | inconclusive | True | False | False | True | 无 |
| Q17 | base_strict | inconclusive | True | False | False | True | 无 |
| Q17 | hybrid_default | inconclusive | True | False | False | True | 无 |
| Q17 | hybrid_strict | inconclusive | True | False | False | True | 无 |
| Q18 | base_strict | inconclusive | False | False | False | True | 无 |
| Q18 | hybrid_default | pass | False | False | True | False | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L137-L158 |
| Q18 | hybrid_strict | inconclusive | False | False | False | True | 无 |
| P19 | base_default | inconclusive | True | False | False | True | 无 |
| P19 | base_strict | inconclusive | True | False | False | True | 无 |
| P19 | hybrid_default | inconclusive | True | False | False | True | 无 |
| P19 | hybrid_strict | inconclusive | True | False | False | True | 无 |
| P22 | hybrid_default | pass | True | False | True | False | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md#L73-L74 |
| P22 | hybrid_strict | pass | True | False | True | False | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md#L73-L74 |
| P23 | hybrid_default | pass | True | False | True | False | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md#L3-L4 |
| P23 | hybrid_strict | pass | True | False | True | False | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md#L3-L4 |
| P24 | hybrid_default | pass | True | False | True | False | 测试问题与闸门说明书.md#L925-L940 |

## 重点探针

| ID | 冻结标签 | base 默认 | base strict | hybrid 默认 | hybrid strict |
|---|---|---|---|---|---|
| X03 | positive_control | pass | inconclusive | pass | inconclusive |
| X04 | ambiguous | pass | inconclusive | pass | inconclusive |
| X21 | positive_control | pass | pass | pass | pass |
| X23 | insufficient_source | pass | inconclusive | pass | inconclusive |

## 来源事实

- 《必杀全清单》整件仍为 `authoritative`；S1/S3/S8 别名均解析为 `reference_only`。
- S1 含 23 种总量：`False`；S3：`True`。
- S1 含 `ひっさつOK`：`False`；S8：`True`。
- Q18 源文已改为分别记载 S1 发动音效与 S8 得分框签名；不声称两源一致。

## 判定

- 基础默认臂 v2 26/26，且相对旧交付的状态与出证定位逐格不变。
- 基础 strict v2 21/26，撤销 Q01/Q02/Q03/Q05/Q18 的二手假放行；不是为评分改金标。
- hybrid 默认 22/26、strict 19/26；Q02/Q08/Q10/Q18 漂移与全部错误出证逐题入账，错误出证集合以汇总表为准。
- X23 的 legacy pass 归为文件级权威洗白；冻结标签不改。

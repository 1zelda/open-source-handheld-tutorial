# 来源继承修正生产回归 · 2026-11-24

- 生成时间：2026-11-25 00:18:39
- 生产默认不变：`top_window=3`、`fragment_policy=None`、`fact_selector=None`。
- 题集与探针冻结标签未改；X23 仍为 `insufficient_source`。
- 全部确定性检查：`True`

## 26 题 v2 严格出证

| 臂 | 通过 | 失败题 |
|---|---|---|
| base_default | 26/26 | 无 |
| base_strict | 21/26 | Q01, Q02, Q03, Q05, Q18 |
| hybrid_default | 22/26 | Q02, Q08, Q10, Q18 |
| hybrid_strict | 19/26 | Q01, Q02, Q03, Q05, Q08, Q10, Q18 |

## 来源事实核对

- 《必杀全清单》整件资格：`authoritative`。
- S1 含 23 种总量：`False`；S3 含 23 种总量：`True`。
- S1 含ひっさつOK：`False`；S8 含ひっさつＯＫ：`True`。
- Q18 原文已改为分别记载 S1 音效与 S8 得分框签名，不再声称两源一致。

## 历史标注冲突（不改冻结判据）

- Q01：冻结 strict_pass 与来源资格冲突：23 种仅见搜狐 S3，S1 无可核验总量。
- Q02：冻结 strict_pass 与来源资格冲突：金表 L70-L85 属 S1 二手操作表。
- Q03：冻结 strict_pass 与来源资格冲突：按键序列属 S1 二手操作表。
- Q04：冻结 strict_pass 与来源资格冲突：难度句属 S1 二手操作表。
- Q05：冻结 strict_pass 与来源资格冲突：换人规则属 S1 二手操作表。
- Q18：新发现历史标注冲突：S1 只写发动音效，S8 才写ひっさつＯＫ且为二手件。
- X03：冻结 positive_control 与当前严格出证冲突：默认选中 S1 汇总表，官方件未进窗口。
- X04：冻结 ambiguous 与 legacy pass 冲突：S1/S8 发动法相反且无本地实测裁决。
- X23：按用户要求保留 insufficient_source 冻结标签；legacy pass 是文件级权威洗白。

## 重点逐臂

| ID | 冻结标签 | base 默认 | base strict | hybrid 默认 | hybrid strict |
|---|---|---|---|---|---|
| Q01 | strict_pass | pass | inconclusive | pass | inconclusive |
| Q02 | strict_pass | pass | inconclusive | inconclusive | inconclusive |
| Q03 | strict_pass | pass | inconclusive | pass | inconclusive |
| Q04 | gold_in_topk | pass | inconclusive | pass | inconclusive |
| Q05 | strict_pass | pass | inconclusive | pass | pass |
| Q18 | strict_pass | pass | inconclusive | pass | inconclusive |
| X03 | positive_control | pass | inconclusive | pass | inconclusive |
| X04 | ambiguous | pass | inconclusive | pass | inconclusive |
| X21 | positive_control | pass | pass | pass | pass |
| X23 | insufficient_source | pass | inconclusive | pass | inconclusive |

## 旧交付保护

- 旧 strict 交付目录只读；本回归逐格对比旧默认臂状态与出证定位。
- 旧默认臂变化：`[]`。

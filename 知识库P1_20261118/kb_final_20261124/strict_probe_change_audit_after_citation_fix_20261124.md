# strict 裸引用修正：探针变化审计（2026-11-24）

- 索引：770 块，`01ba5d9cd9e0e5c1…`。
- 生产默认未变：`top_window=3`、`fragment_policy=None`、`fact_selector=None`。
- 冻结探针标签未修改；本件只登记口径变化与冲突，不把历史标签偷偷改成通过。

## 总结

- strict `grade_v2`：22/26 → 25/26。
- 相对旧 strict 恢复：X03, X04, X23。
- 相对当前默认臂新增放行：无。
- 当前 strict 仍拦截：X05, X17, X19, X20, X22, X30。

## Q02–Q05：合法题恢复且金标未换

| ID | 默认臂 | strict | 金标一致 |
|---|---|---|---|
| Q02 | pass | pass | 是 |
| Q03 | pass | pass | 是 |
| Q04 | pass | pass | 是 |
| Q05 | pass | pass | 是 |

## X03 / X04 / X23 逐臂对照

| ID | 冻结 kind | 旧 strict | 当前默认 | 当前 strict | 相对默认新增放行 |
|---|---|---|---|---|---|
| X03 | positive_control | inconclusive | pass | pass | 否 |
| X04 | ambiguous | inconclusive | pass | pass | 否 |
| X23 | insufficient_source | inconclusive | pass | pass | 否 |

## X23 的处置

冻结说明把 S1 直接视为二手 reference_only；修正后的规则只把显式转述、参考段、待核段与撤回段降级，裸来源编号本身不构成二手证据。X23 与 Q02-Q05 同属该规则变化，不能单独改标签凑满分。

- 判定：`frozen_annotation_conflict`。
- 动作：`retain_frozen_label_and_keep_strict_shadow_only`。
- 生产影响：none; fragment_policy=None remains the production default。
- 后续：如需重审 S1 文件级权威，应统一审计 corpus_map 与来源资格，不得只针对 X23 加特例。

## 隔离

- 真实状态隔离：PASS；变化路径 0。

# 选择器生产接线摘要

## ph3_selector_strict_20261124_bm25.json

- 时间：2026-11-24 05:11:05；索引：`index.json` sha16 `ecc7bbcce5dcd64f`（757 块）
- 生产基线严格出证：23/26

| 模式 | 严格出证 | 修好 | 打坏 | 错误出证 | 仍pass但换证 | 探针新放行 | 探针拦截 |
|---|---|---|---|---|---|---|---|
| scoped | 23/26 | 0 | 0 | [] | ['Q07'] | [] | [] |
| scoped_beyond | 24/26 | 1 | 0 | [] | ['Q07', 'Q08'] | ['X11'] | [] |
| replace | 21/26 | 0 | 2 | [] | ['Q07', 'P22', 'P23', 'P24'] | [] | ['X05', 'X17', 'X19', 'X20', 'X21', 'X22', 'X30'] |
| strict_fragments | 21/26 | 0 | 2 | [] | ['Q04'] | [] | ['X05', 'X17', 'X19', 'X20', 'X22', 'X30'] |

### strict_fragments 逐格

- 修好：无；打坏：['Q01', 'Q05']
- 仍未过：['Q02', 'Q03', 'Q06']
- 拦截探针：[{'id': 'X05', 'kind': 'insufficient_source'}, {'id': 'X17', 'kind': 'insufficient_source'}, {'id': 'X19', 'kind': 'insufficient_source'}, {'id': 'X20', 'kind': 'insufficient_source'}, {'id': 'X22', 'kind': 'true_negative'}, {'id': 'X30', 'kind': 'insufficient_source'}, {'id': 'W10', 'kind': None}, {'id': 'W30', 'kind': None}]
- 新放行探针：无


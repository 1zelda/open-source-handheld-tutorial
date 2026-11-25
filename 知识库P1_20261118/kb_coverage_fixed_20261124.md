# 全域知识库覆盖看板 · 2026-11-24T07:36:04Z

- 文本索引：757 块；审计 `fail`；sha256 `ecc7bbcce5dcd64fbbb4064d3fbcdde21ee18fdb4da1dec428040ca6356a1c60`
- 电竞库：schema `v3`；实体 1066；证据 1066；快照 3
- 状态计数：{'verified': 3, 'partial': 0, 'present_unverified': 0, 'registered_empty': 8, 'not_registered': 0, 'stale': 12, 'unknown': 0}

## 文本审计缺口

- `index_sync`：索引漂移
  - 测试问题与闸门说明书.md: 源文件已变，索引是旧的（重 build）

## 生产评测

基线严格评测：26/26

| 模式 | 严格评测 | 修好 | 打坏 | 错误出证 | 新放行探针 |
|---|---|---|---|---|---|
| scoped | 26/26 | 0 | 0 | [] | [] |
| scoped_beyond | 26/26 | 0 | 0 | [] | ['X11'] |
| replace | 23/26 | 0 | 3 | [] | [] |
| strict_fragments | 22/26 | 0 | 4 | [] | [] |

按域成绩（域级题数，不摊到每个版本或知识类型）：

| 域 | 题数 | 基线评测通过 | 通过率 |
|---|---|---|---|
| esports_dota | 2 | 2 | 1.0 |
| esports_lol | 2 | 2 | 1.0 |
| kof98 | 3 | 3 | 1.0 |
| modern_games | 1 | 1 | 1.0 |
| project_docs | 3 | 3 | 1.0 |
| retro_soccer | 12 | 12 | 1.0 |

## 查询日志健康度

- 日志：`F:\开源掌机教程\知识库P1_20261118\blind_eval_fixed_20261124.query_log.jsonl`（存在）；有效行 26；独立问题 26；最近 2026-11-24T07:30:11Z
- 状态计数：{'pass': 11, 'inconclusive': 10, 'miss': 5}；选中证据 11 行（0.4231）
- 诊断行 26；多域调用 0；逐域证据 1；入口 {'blind_eval': 26}；路由模式 {'explicit': 20, 'single': 6}；平均耗时 83.825ms
- 异常：坏行 0；空问题 0；缺索引指纹 0；缺状态 0；pass无证据 0；非pass带证据 0

- 口径：当前只有隔离盲测日志，不是真实使用记录，也不能当作独立盲测集。

| 域 | 有效行 | 独立问题 | pass | miss | inconclusive | 证据选中率 | 最近查询 |
|---|---|---|---|---|---|---|---|
| esports_dota | 2 | 2 | 0 | 2 | 0 | 0.0 | 2026-11-24T07:30:11Z |
| esports_lol | 2 | 2 | 0 | 2 | 0 | 0.0 | 2026-11-24T07:30:10Z |
| kof98 | 3 | 3 | 1 | 0 | 2 | 0.3333 | 2026-11-24T07:30:10Z |
| modern_games | 1 | 1 | 0 | 1 | 0 | 0.0 | 2026-11-24T07:30:10Z |
| project_docs | 3 | 3 | 3 | 0 | 0 | 1.0 | 2026-11-24T07:30:11Z |
| retro_soccer | 12 | 12 | 5 | 0 | 7 | 0.4167 | 2026-11-24T07:30:11Z |
| unrouted | 3 | 3 | 2 | 0 | 1 | 0.6667 | 2026-11-24T07:30:10Z |

## 覆盖矩阵

| 域 | 类目 | 游戏 | 知识类型 | 地区/平台 | 版本 | 状态 | 块/强证据 | 实体/证据 | 缺口 |
|---|---|---|---|---|---|---|---|---|---|
| arcade_hacks | text | multi | text_documents | 本地身份分区/ARCADE | arcade_hack_multi | stale | 336/0 | 0/0 | 没有 verified_read + authoritative 正文 |
| esports_cs2 | registered | - | all | 未登记/- | - | registered_empty | 0/0 | 0/0 | 域已注册但本地无语料；未收集不等于不存在 |
| esports_dota | registered | - | all | 未登记/- | - | registered_empty | 0/0 | 0/0 | 域已注册但本地无语料；未收集不等于不存在 |
| esports_lol | structured | lol | game_character | zh_CN locale/- | 16.23.1 | verified | 0/0 | 173/173 | - |
| esports_lol | structured | lol | game_item | zh_CN locale/- | 16.23.1 | verified | 0/0 | 859/859 | - |
| esports_lol | structured | lol | game_spell | zh_CN locale/- | 16.23.1 | verified | 0/0 | 34/34 | - |
| esports_lol | structured | lol | membership | 未登记/- | - | registered_empty | 0/0 | 0/0 | 真实记录为0；待获准来源，不能用合成夹具顶替 |
| esports_lol | structured | lol | patch_deployment | 未登记/- | - | registered_empty | 0/0 | 0/0 | 真实记录为0；待获准来源，不能用合成夹具顶替 |
| esports_lol | structured | lol | series | 未登记/- | - | registered_empty | 0/0 | 0/0 | 真实记录为0；待获准来源，不能用合成夹具顶替 |
| esports_lol | structured | lol | transfer_event | 未登记/- | - | registered_empty | 0/0 | 0/0 | 真实记录为0；待获准来源，不能用合成夹具顶替 |
| esports_valorant | registered | - | all | 未登记/- | - | registered_empty | 0/0 | 0/0 | 域已注册但本地无语料；未收集不等于不存在 |
| kof98 | text | kof98 | text_documents | 本地身份分区/ARCADE | kof98eck | stale | 18/18 | 0/0 | - |
| kof98 | text | kof98 | text_documents | 本地身份分区/ARCADE | kof98um | stale | 7/0 | 0/0 | 没有 verified_read + authoritative 正文 |
| modern_games | registered | - | all | 未登记/- | - | registered_empty | 0/0 | 0/0 | 域已注册但本地无语料；未收集不等于不存在 |
| project_docs | text | multi | text_documents | 本地身份分区/ANY | project_docs | stale | 197/197 | 0/0 | - |
| retro_fighting | text | nekketsu_kakutou_densetsu | text_documents | 本地身份分区/NES | nekketsu_kakutou_densetsu_fc_jp | stale | 12/8 | 0/0 | - |
| retro_fighting | text | nekketsu_kakutou_densetsu | text_documents | 本地身份分区/NES | nekketsu_kakutou_densetsu_fc_revB_patch | stale | 3/0 | 0/0 | 没有 verified_read + authoritative 正文 |
| retro_soccer | text | nekketsu_soccer2 | text_documents | 本地身份分区/NES | nekketsu_soccer2_fc_cn_hack | stale | 1/0 | 0/0 | 没有 verified_read + authoritative 正文 |
| retro_soccer | text | nekketsu_soccer2 | text_documents | 本地身份分区/NES | nekketsu_soccer2_fc_jp | stale | 122/38 | 0/0 | - |
| retro_soccer | text | nekketsu_soccer2 | text_documents | 本地身份分区/NES | nekketsu_soccer2_fc_unspecified | stale | 29/0 | 0/0 | 没有 verified_read + authoritative 正文 |
| retro_soccer | text | nekketsu_soccer2 | text_documents | 本地身份分区/NES | nekketsu_soccer2_multi | stale | 26/26 | 0/0 | - |
| tooling | text | multi | text_documents | 本地身份分区/ANY | project_docs | stale | 197/197 | 0/0 | - |
| unrouted_text | text | nekketsu_soccer_mobile | text_documents | 本地身份分区/MOBILE | nekketsu_soccer_mobile | stale | 6/0 | 0/0 | 没有 verified_read + authoritative 正文 |

## 电竞来源权限口径

| 来源 | 自动访问 | 本地留存 | 商用 | 引用 | 再分发 | 授权引用 |
|---|---|---|---|---|---|---|
| E01 | unknown | unknown | unknown | unknown | unknown | - |
| E02 | allowed | unknown | unknown | unknown | unknown | - |
| E03 | allowed | unknown | unknown | unknown | unknown | - |
| E04 | unknown | unknown | unknown | unknown | unknown | - |
| E05 | unknown | unknown | denied | unknown | unknown | - |
| E06 | unknown | unknown | unknown | unknown | unknown | - |
| E07 | unknown | unknown | unknown | unknown | unknown | - |
| E08 | unknown | unknown | unknown | unknown | unknown | - |
| E09 | allowed | unknown | unknown | unknown | unknown | - |
| E10 | unknown | unknown | unknown | unknown | unknown | - |
| E11 | allowed | unknown | denied | unknown | unknown | - |
| E12 | denied | unknown | unknown | unknown | unknown | - |
| E13 | denied | unknown | unknown | unknown | unknown | - |
| E14 | unknown | unknown | unknown | unknown | unknown | - |
| E15 | unknown | unknown | unknown | unknown | unknown | - |
| E16 | denied | unknown | denied | unknown | unknown | - |
| E17 | unknown | unknown | unknown | unknown | unknown | - |
| E18 | unknown | allowed | unknown | unknown | unknown | - |
| E19 | unknown | unknown | unknown | unknown | unknown | - |

`unknown` 不等于已获商用/再分发授权；未获明确许可的维度保持待核。

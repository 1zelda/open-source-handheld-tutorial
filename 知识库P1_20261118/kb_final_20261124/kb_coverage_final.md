# 全域知识库覆盖看板 · 2026-11-24T10:47:46Z

- 文本索引：770 块；审计 `inconclusive`；sha256 `01ba5d9cd9e0e5c18d47531d81bdee09d3fa027da021c67173e9465222de9d47`
- 电竞库：schema `v3`；实体 1066；证据 1066；快照 3
- 状态计数：{'verified': 9, 'partial': 0, 'present_unverified': 6, 'registered_empty': 8, 'not_registered': 0, 'stale': 0, 'unknown': 0}

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

- 日志：`F:\开源掌机教程\知识库P1_20261118\kb_final_20261124\blind_eval_final.query_log.jsonl`（存在）；有效行 26；独立问题 26；最近 2026-11-24T10:45:22Z
- 状态计数：{'pass': 13, 'inconclusive': 8, 'miss': 5}；选中证据 13 行（0.5）
- 诊断行 26；多域调用 0；逐域证据 1；入口 {'blind_eval': 26}；路由模式 {'explicit': 20, 'single': 6}；平均耗时 130.204ms
- 异常：坏行 0；空问题 0；缺索引指纹 0；缺状态 0；pass无证据 0；非pass带证据 0

- 口径：当前只有隔离盲测日志，不是真实使用记录，也不能当作独立盲测集。

| 域 | 有效行 | 独立问题 | pass | miss | inconclusive | 证据选中率 | 最近查询 |
|---|---|---|---|---|---|---|---|
| esports_dota | 2 | 2 | 0 | 2 | 0 | 0.0 | 2026-11-24T10:45:22Z |
| esports_lol | 2 | 2 | 0 | 2 | 0 | 0.0 | 2026-11-24T10:45:21Z |
| kof98 | 3 | 3 | 1 | 0 | 2 | 0.3333 | 2026-11-24T10:45:20Z |
| modern_games | 1 | 1 | 0 | 1 | 0 | 0.0 | 2026-11-24T10:45:20Z |
| project_docs | 3 | 3 | 3 | 0 | 0 | 1.0 | 2026-11-24T10:45:21Z |
| retro_soccer | 12 | 12 | 6 | 0 | 6 | 0.5 | 2026-11-24T10:45:22Z |
| unrouted | 3 | 3 | 3 | 0 | 0 | 1.0 | 2026-11-24T10:45:21Z |

## 覆盖矩阵

| 域 | 类目 | 游戏 | 知识类型 | 地区/平台 | 版本 | 状态 | 块/强证据 | 实体/证据 | 缺口 |
|---|---|---|---|---|---|---|---|---|---|
| arcade_hacks | text | multi | text_documents | 本地身份分区/ARCADE | arcade_hack_multi | present_unverified | 336/0 | 0/0 | 没有 verified_read + authoritative 正文 |
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
| kof98 | text | kof98 | text_documents | 本地身份分区/ARCADE | kof98eck | verified | 18/18 | 0/0 | - |
| kof98 | text | kof98 | text_documents | 本地身份分区/ARCADE | kof98um | present_unverified | 7/0 | 0/0 | 没有 verified_read + authoritative 正文 |
| modern_games | registered | - | all | 未登记/- | - | registered_empty | 0/0 | 0/0 | 域已注册但本地无语料；未收集不等于不存在 |
| project_docs | text | multi | text_documents | 本地身份分区/ANY | project_docs | verified | 210/210 | 0/0 | - |
| retro_fighting | text | nekketsu_kakutou_densetsu | text_documents | 本地身份分区/NES | nekketsu_kakutou_densetsu_fc_jp | verified | 12/8 | 0/0 | - |
| retro_fighting | text | nekketsu_kakutou_densetsu | text_documents | 本地身份分区/NES | nekketsu_kakutou_densetsu_fc_revB_patch | present_unverified | 3/0 | 0/0 | 没有 verified_read + authoritative 正文 |
| retro_soccer | text | nekketsu_soccer2 | text_documents | 本地身份分区/NES | nekketsu_soccer2_fc_cn_hack | present_unverified | 1/0 | 0/0 | 没有 verified_read + authoritative 正文 |
| retro_soccer | text | nekketsu_soccer2 | text_documents | 本地身份分区/NES | nekketsu_soccer2_fc_jp | verified | 122/38 | 0/0 | - |
| retro_soccer | text | nekketsu_soccer2 | text_documents | 本地身份分区/NES | nekketsu_soccer2_fc_unspecified | present_unverified | 29/0 | 0/0 | 没有 verified_read + authoritative 正文 |
| retro_soccer | text | nekketsu_soccer2 | text_documents | 本地身份分区/NES | nekketsu_soccer2_multi | verified | 26/26 | 0/0 | - |
| tooling | text | multi | text_documents | 本地身份分区/ANY | project_docs | verified | 210/210 | 0/0 | - |
| unrouted_text | text | nekketsu_soccer_mobile | text_documents | 本地身份分区/MOBILE | nekketsu_soccer_mobile | present_unverified | 6/0 | 0/0 | 没有 verified_read + authoritative 正文 |

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

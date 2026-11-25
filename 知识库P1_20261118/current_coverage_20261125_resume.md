# 全域知识库覆盖看板 · 2026-11-25T12:23:28Z

- 文本索引：826 块；审计 `inconclusive`；sha256 `05907ec85146f386325285ccd4d2008d8bc28d50d8ec4e2461c14a9351f03f7d`
- 电竞库：schema `v3`；实体 1066；证据 1066；快照 3
- 状态计数：{'verified': 11, 'partial': 0, 'present_unverified': 6, 'registered_empty': 9, 'not_registered': 0, 'stale': 0, 'unknown': 0}

## 查询日志健康度

- 日志：`F:\开源掌机教程\_工具脚本\taspipe\游戏包\知识库\query_log.jsonl`（存在）；有效行 1；独立问题 1；最近 2026-11-23T19:58:34Z
- 状态计数：{'pass': 1}；选中证据 1 行（1.0）
- 诊断行 0；多域调用 0；逐域证据 0；入口 {}；路由模式 {}；平均耗时 Nonems
- 异常：坏行 0；空问题 0；缺索引指纹 1；缺状态 0；pass无证据 0；非pass带证据 0

| 域 | 有效行 | 独立问题 | pass | miss | inconclusive | 证据选中率 | 最近查询 |
|---|---|---|---|---|---|---|---|
| retro_soccer | 1 | 1 | 1 | 0 | 0 | 1.0 | 2026-11-23T19:58:34Z |

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
| megaman1 | registered | - | all | 未登记/- | - | registered_empty | 0/0 | 0/0 | 域已注册但本地无语料；未收集不等于不存在 |
| megaman2 | text | megaman2 | text_documents | 本地身份分区/NES | megaman2_nes_tasvideos_rockman2 | verified | 9/9 | 0/0 | - |
| modern_games | registered | - | all | 未登记/- | - | registered_empty | 0/0 | 0/0 | 域已注册但本地无语料；未收集不等于不存在 |
| project_docs | text | multi | text_documents | 本地身份分区/ANY | project_docs | verified | 215/215 | 0/0 | - |
| retro_fighting | text | nekketsu_kakutou_densetsu | text_documents | 本地身份分区/NES | nekketsu_kakutou_densetsu_fc_jp | verified | 12/8 | 0/0 | - |
| retro_fighting | text | nekketsu_kakutou_densetsu | text_documents | 本地身份分区/NES | nekketsu_kakutou_densetsu_fc_revB_patch | present_unverified | 3/0 | 0/0 | 没有 verified_read + authoritative 正文 |
| retro_soccer | text | nekketsu_soccer2 | text_documents | 本地身份分区/NES | nekketsu_soccer2_fc_cn_hack | present_unverified | 1/0 | 0/0 | 没有 verified_read + authoritative 正文 |
| retro_soccer | text | nekketsu_soccer2 | text_documents | 本地身份分区/NES | nekketsu_soccer2_fc_jp | verified | 122/38 | 0/0 | - |
| retro_soccer | text | nekketsu_soccer2 | text_documents | 本地身份分区/NES | nekketsu_soccer2_fc_unspecified | present_unverified | 29/0 | 0/0 | 没有 verified_read + authoritative 正文 |
| retro_soccer | text | nekketsu_soccer2 | text_documents | 本地身份分区/NES | nekketsu_soccer2_multi | verified | 26/26 | 0/0 | - |
| tooling | text | multi | text_documents | 本地身份分区/ANY | project_docs | verified | 215/215 | 0/0 | - |
| unrouted_text | text | CastlevaniaAriaOfSorrow_GBA | text_documents | 本地身份分区/GBA | castlevania_aria_gba | verified | 42/32 | 0/0 | - |
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

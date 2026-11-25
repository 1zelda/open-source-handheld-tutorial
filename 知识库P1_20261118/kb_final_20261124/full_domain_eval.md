# 全域生产评测 · 2026-11-24 16:41:24

- 严格通过：16/16
- 代码指纹：{'kb': '104c29c06a985254f7d21cf61361dfd3cee8f12af2a99ad7c1198f36ceba2a41', 'kb_answer': '49e52e09d4d5811a7ce7e979bb9d3f2f449b0271a01985e27bd758b4d882c338', 'kb_esports': '581dc5a328e4abab77c563b419faa4d2f65c2301379cce791a1b5c0aeabbc9db', 'kb_provenance': '0ff8d170bbcf624b522b1e3b348eac14680fef8f2319a3b992c9ed4d76804b29', 'kb_route': '45181c432e4f45b9a05b1ee712d9a43c189ebf02310d5176d45f3c226b79aadd', 'kb_selector': '5843b007d66e88e2d6ac2d6d7fd3a62249d80308d6f153879739227af358be71', 'producer': '1f1873c864fbdb7d854718002d1602cae175b98e36071372794e0730306d6f90'}
- 索引 sha256：80900ea3833ad64375c0b5f6872fa6bb6abdef47ba30eeb0100b3f300d837f40
- 电竞库 sha256：32f029f41629cb3774e701a705d521aa49550c76deabbc0affc760bec264d5c1

## 分类计数

- esports_static: 4/4
- time_trap: 4/4
- esports_dynamic: 2/2
- esports_other: 2/2
- modern_games: 1/1
- cross_domain: 1/1
- retro_regression: 2/2

## 逐题

| 题 | 类目 | 结果 | 状态/拒答 | 证据定位 | 失败检查 |
|---|---|---|---|---|---|
| F01 | esports_static | True | pass/evidence_bound | /data/Yasuo | - |
| F02 | esports_static | True | pass/evidence_bound | /data/1001 | - |
| F03 | esports_static | True | pass/evidence_bound | /data/SummonerFlash | - |
| F04 | time_trap | True | miss/version_not_collected | - | - |
| F05 | esports_static | True | miss/not_collected | - | - |
| F06 | esports_dynamic | True | miss/out_of_scope | - | - |
| F07 | esports_dynamic | True | miss/out_of_scope | - | - |
| F08 | time_trap | True | miss/out_of_scope | - | - |
| F09 | time_trap | True | miss/out_of_scope | - | - |
| F10 | esports_other | True | miss/out_of_scope | - | - |
| F11 | esports_other | True | miss/out_of_scope | - | - |
| F12 | time_trap | True | miss/out_of_scope | - | - |
| F13 | modern_games | True | miss/out_of_scope | - | - |
| F14 | cross_domain | True | miss/out_of_scope | - | - |
| F15 | retro_regression | True | pass/- | _工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书扫描_20261118.md#L327-L341 | - |
| F16 | retro_regression | True | pass/- | F:/tas_rig/docs/素材生产规范.md#L185-L190 | - |

# 全域生产评测 · 2026-11-24 18:46:20

- 严格通过：16/16
- 代码指纹：{'kb': '6ee930803ab891535351c0a77c97b4bb8f6950364e9c1a9af66d5101f77ca4ad', 'kb_answer': 'da05727ede62ffb378817179b2f2ff8ff856ff3e9bd963b6b4dc3712f9074023', 'kb_esports': '581dc5a328e4abab77c563b419faa4d2f65c2301379cce791a1b5c0aeabbc9db', 'kb_provenance': 'faf451a1c42d1e6d3594babccf1d48c83d2e49b8747b743b2c7cbe99a765e499', 'kb_route': 'a22fe95be89c1c5758add431b1615c7f2305c0d719fc81cef161e262179e5084', 'kb_selector': '5843b007d66e88e2d6ac2d6d7fd3a62249d80308d6f153879739227af358be71', 'producer': '1f1873c864fbdb7d854718002d1602cae175b98e36071372794e0730306d6f90'}
- 索引 sha256：01ba5d9cd9e0e5c18d47531d81bdee09d3fa027da021c67173e9465222de9d47
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

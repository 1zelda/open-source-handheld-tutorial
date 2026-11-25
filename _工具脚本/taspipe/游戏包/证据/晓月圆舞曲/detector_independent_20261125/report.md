# 视觉检测器候选标定

> 标定与验收使用不同样本集；independent_capture 必须绑定不同进程的强制运行、源报告与逐帧 SHA256。确定性回放允许不同进程采集到逐帧相同的画面，但不得复用同一运行或源报告。验收覆盖验收采集的全部正反例帧和显式时间窗，不等于技能身份、整套玩法、平台准入或未采集时间轴。

- 配方：`F:\开源掌机教程\_工具脚本\taspipe\校准配方\castlevania_aria_gba.soul_detector_candidates_independent_20261125.json`
- 配方 SHA256：`6b2e9ff41d17415e70f2a86987034e550a1adee5a49694ae5df45a9aaa943edd`
- 总数：3；状态逐格计数：`{'pass': 3}`
- detector 实现 SHA256：`c23390172ebb298e1cc49bc77b70b8c8fbabeb48c4351cf06fc6410c06737977`

| ID | 方法 | 状态 | frame | 局部/颜色正例 | 反例 | 控制 | 全帧审计 |
|---|---|---|---:|---:|---:|---:|---|
| red_soul_35_camera_aligned | aligned_difference | pass | 11 | 0.1526 | fail | 3/3 | 90 对帧 / 2/2 时间窗 |
| red_soul_47_local_attack | aligned_difference | pass | 18 | 0.0991 | fail | 4/4 | 90 对帧 / 4/4 时间窗 |
| yellow_soul_10_healing_popup | color_region | pass | 109 | 0.122 | fail | 6/6 | 226 对帧 / 5/5 时间窗 |

## 时间轴边界

### red_soul_35_camera_aligned
- 样本分离：`independent_capture`；标定集 `red_soul_35_camera_aligned_independent_calibration`；验收集 `red_soul_35_camera_aligned_independent_acceptance`
- 正例逐格计数：`{'fail': 2, 'pass': 88}`；反例逐格计数：`{'fail': 90}`
- 反例控制：`same_empty_frame_self_difference`；全负例拒绝：`True`
- 帧内容指纹：标定 `90dcc2ea477e07722101016d7a823e4a9ce24d7aea31eb271a52372efff044f2`；验收 `90dcc2ea477e07722101016d7a823e4a9ce24d7aea31eb271a52372efff044f2`
- 独立标定采集：进程 `51252`；运行 `71391fa86ebf4082855a7b703c39018a`；源报告 `F:\taspipe_scratch\gba_parallel_20261124\aria_soul_detector_independent_v1_20261125\calibration\red_soul_35_resource_verify\report.json`；报告 SHA256 `245dcc9eb3e6c10ede8b657b49bd2ae0bd6872cdca9c8673946d4b5bf5a31d49`
- 独立验收采集：进程 `52564`；运行 `314cc3a6e4884cad8cabd2d71e6cf3fa`；源报告 `F:\taspipe_scratch\gba_parallel_20261124\aria_soul_detector_independent_v1_20261125\acceptance\red_soul_35_resource_verify\report.json`；报告 SHA256 `aef30e2395dd025c920d5eb44a95bf1ced5ece6f035938f477d672e4d79e0e4b`
- before_paired_attack：positive 0..1 要求 all_fail，实测 `{'fail': 2}`，PASS
- paired_attack_window：positive 2..89 要求 all_pass，实测 `{'pass': 88}`，PASS

### red_soul_47_local_attack
- 样本分离：`independent_capture`；标定集 `red_soul_47_local_attack_independent_calibration`；验收集 `red_soul_47_local_attack_independent_acceptance`
- 正例逐格计数：`{'fail': 50, 'pass': 40}`；反例逐格计数：`{'fail': 90}`
- 反例控制：`same_empty_frame_self_difference`；全负例拒绝：`True`
- 帧内容指纹：标定 `8b6d14ac53bb7787db9fff152cdcba8f45d857d89f1a3034f23760b66172d151`；验收 `8b6d14ac53bb7787db9fff152cdcba8f45d857d89f1a3034f23760b66172d151`
- 独立标定采集：进程 `51252`；运行 `60d412d0ca9647bbafa7cbcc2563f7e8`；源报告 `F:\taspipe_scratch\gba_parallel_20261124\aria_soul_detector_independent_v1_20261125\calibration\red_soul_47_resource_verify\report.json`；报告 SHA256 `42eb55fabeda9829da2c67d3fb03febce29ae8a4189aa5e8e517aec1b22eff63`
- 独立验收采集：进程 `52564`；运行 `d7aa9b04099641e8a049e57690027b5a`；源报告 `F:\taspipe_scratch\gba_parallel_20261124\aria_soul_detector_independent_v1_20261125\acceptance\red_soul_47_resource_verify\report.json`；报告 SHA256 `03bd9e946fb7b0486e7e5d1dd1b4c42eef377c4a016a4d680faea4cd62c98856`
- before_local_attack：positive 0..1 要求 all_fail，实测 `{'fail': 2}`，PASS
- local_attack_window：positive 2..41 要求 all_pass，实测 `{'pass': 40}`，PASS
- after_local_attack：positive 42..80 要求 all_fail，实测 `{'fail': 39}`，PASS
- fullscreen_flash_window_rejected：positive 81..89 要求 all_fail，实测 `{'fail': 9}`，PASS

### yellow_soul_10_healing_popup
- 样本分离：`independent_capture`；标定集 `yellow_soul_10_healing_popup_independent_calibration`；验收集 `yellow_soul_10_healing_popup_independent_acceptance`
- 正例逐格计数：`{'fail': 190, 'pass': 36}`；反例逐格计数：`{'fail': 226}`
- 反例控制：`empty_soul_frame_color_absence`；全负例拒绝：`True`
- 帧内容指纹：标定 `88b46e538530feec120498a28f2e133ff78d1879c9804e057a6f78b0caf8651c`；验收 `88b46e538530feec120498a28f2e133ff78d1879c9804e057a6f78b0caf8651c`
- 独立标定采集：进程 `32148`；运行 `22f1f2b4ffbd444f8a859378217ae5b5`；源报告 `F:\taspipe_scratch\gba_parallel_20261124\aria_soul_detector_independent_v1_20261125\calibration\yellow_soul_10_hp_advantage\report.json`；报告 SHA256 `11a4bff3cd2a7acbbb7f0b952553f12ea74fa770d16aa230d6fdf41e191864d4`
- 独立验收采集：进程 `18764`；运行 `7f8f22dc52074a12a2cecf00e0664f39`；源报告 `F:\taspipe_scratch\gba_parallel_20261124\aria_soul_detector_independent_v1_20261125\acceptance\yellow_soul_10_hp_advantage\report.json`；报告 SHA256 `566c132f9469e7c291a076a3d090db0ff673f2553dbdd29fa167324e4ec5fb90`
- before_first_popup：positive 0..108 要求 all_fail，实测 `{'fail': 109}`，PASS
- first_popup_window：positive 109..126 要求 all_pass，实测 `{'pass': 18}`，PASS
- between_popups：positive 127..169 要求 all_fail，实测 `{'fail': 43}`，PASS
- second_popup_window：positive 170..187 要求 all_pass，实测 `{'pass': 18}`，PASS
- after_second_popup：positive 188..225 要求 all_fail，实测 `{'fail': 38}`，PASS


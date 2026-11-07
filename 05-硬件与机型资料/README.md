# 硬件与机型资料

## 机型支持 / 屏幕真值(本目录的核心产物)

- `devices.json` — 有效 JSON。前半是 `southoz/dArkOSRE-R36` wiki 承认的 **39 个 R36S 家族板型**(带状态与 dtb 路径),
  末尾 `local_device` 是本机 XiFan XF45V 的完整记录,`scope_note` 说明了这份名单**不覆盖**哪些厂商。
- `arkos4clone_devices.json` — **109 个机型条目**(来自 119 个 `.dtb`),每条含接口、分辨率、像素时钟、lanes、
  面板 compatible,以及 join 上游 `console-detect` 得到的**固件行为参数**(机型名/热键类型/摇杆数/旋转/LED/音量读法/识别状态)。
  生成:`py -3 _工具脚本/dtb_panel_sweep.py`。
- `屏幕真值表.md` — 上面那份 JSON 的人类可读版,含"相对 640×480 的渲染倍率"排序,以及**为什么 `尺寸mm/寸/DPI` 三列整列不可信**的说明。
- `panel_specs.tsv` — 同一份数据的表格版(119 行 × 21 列),要在 Excel 里筛就用它。

## 对比表与实操记录

- `安卓掌机对比表.txt` — 安卓/Linux 掌机机型参数(型号、SoC、内存、屏、电池、价格)。
- `Win掌机对比表.txt` — x86 掌机参数(GPD/OneXPlayer/AYANEO/ROG Ally/Steam Deck/Legion Go)。
- `Win掌机链接步骤.txt`、`win掌机文件传输共享.txt` — 掌机与电脑之间的文件传输/共享实操记录。

以上两份对比表是本机之前采集的数据(2026 年),价格仅供参考,二手价波动大。
选购逻辑见 `../01-教程库/入门选购/00-入门必读.md`;刷机方案见 `../01-教程库/机型固件/00-机型固件对照表.md`;
本机专篇见 `../01-教程库/机型固件/XiFan_XF45V/00-XF45V完全指南.md`。

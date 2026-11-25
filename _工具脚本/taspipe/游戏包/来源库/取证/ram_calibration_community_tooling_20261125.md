# RAM 校准工具复用取证（2026-11-25）

## 结论口径

本次只回答“哪些已有能力可以直接接入逐帧校准”，不把能打开 GUI 等同于可稳定自动化，也不把某次 GitHub 代码搜索未命中等同于“社区没有实现”。当前中文版 ROM SHA1 为 `40aab076a528f52e93260bb98d91a40039e0da02`；USA matching decomp ROM SHA1 为 `abd71fe01ebb201bcc133074db1dd8c5253776c7`。

## 可直接使用

### BizHawk Lua：分域内存与逐帧输入

来源：

- <https://tasvideos.org/Bizhawk/LuaFunctions>
- <https://raw.githubusercontent.com/TASEmulators/BizHawk/2.8/src/BizHawk.Client.Common/lua/CommonLibs/MemoryLuaLibrary.cs>
- <https://raw.githubusercontent.com/TASEmulators/BizHawk/2.8/src/BizHawk.Client.EmuHawk/tools/Lua/Libraries/TAStudioLuaLibrary.cs>
- <https://raw.githubusercontent.com/TASEmulators/BizHawk/2.11/src/BizHawk.Client.EmuHawk/tools/Lua/Libraries/TAStudioLuaLibrary.cs>

可复用：

- `memory` / `mainmemory` 按域读写：NES 探针与 dump 用 `System Bus`；GBA 用 `EWRAM` 或 `Combined WRAM`，不可混传地址。
- `joypad` 逐帧输入：适合从稳定状态施加完全相同的正反例输入。
- TAStudio `submit*`、`applyinputchanges`：适合编辑输入轨道；必须 engaged，BizHawk 2.11 禁止在 input/memory 回调内调用 apply。
- `client.addcheat/removecheat`：仅适合当前核心已支持格式，不能视为跨核心通用金手指接口。

本项目的 Lua 原子 `attempt` 已采用分域探针、帧对齐 RAM dump、截图和一次性补丁；因此上述能力属于复用现有官方接口，而不是另造输入或内存协议。

### 本项目的配方与宏入口

- 通用入口：`_工具脚本/taspipe/ram_calibration.py`，命令 `python -m taspipe.ram_calibration run`。
- `prepare` 通过真实菜单/导航形成基态，禁止补丁；case 从该基态分别执行正反例。
- `verify` 输出字段级结论；`scout` 只产生候选，不写 `verified_fields`。
- 结果按配方、源码、ROM、核心、状态文件指纹缓存；证据归档含 report/recipe/manifest/SHA256。
- 晓月圆舞曲当前规范配方：`_工具脚本/taspipe/校准配方/castlevania_aria_cn.red24.json`。

## 只能作为候选或辅助

### RAM Watch / RAM Search / Hex Editor

- RAM Watch 没有稳定、完整的高层 Lua 搜索/结果 API；`openramwatch` 只负责打开 GUI。
- `openramsearch`、`openhexeditor` 只打开 GUI，不是搜索条件或结果的编程接口。
- 因此 RAM Search 可辅助人工探索，但不能替代本项目的 RAM expect、同输入正反例与画面验收。

### mGBA-http

来源：<https://github.com/nikouu/mGBA-http>

- 作者为 nikouu 的第三方项目，需 mGBA 0.10.2+。
- 可作为远程读内存和调试辅助；网络延迟使其不适合作为逐帧精确校准的唯一执行器。
- 当前项目没有引入该依赖，继续使用 BizHawk/mGBA 本地原子 attempt。

### ScriptHawk

来源：<https://github.com/Isotarge/ScriptHawk>

- 定位是游戏专用 Lua/RAM watch 模块集合，不是通用 RAM Search 或 HTTP 服务。
- 当前检索未发现本作《恶魔城：晓月圆舞曲》条目；即便未来命中游戏模块，也只能作为地址线索，仍需当前中文 ROM 的正反例验收。

### mGBA Qt / 官方 Lua

来源：

- <https://mgba.io/docs/scripting.html>
- <https://github.com/mgba-emu/mgba>

- mGBA Qt 的 Memory Search / Cheats 有完整 GUI，但官方 Lua 文档未提供搜索筛选或金手指管理 API。
- GUI 操作不能直接转成可复现的自动化校准步骤。

## 金手指与 ROM 补丁边界

| 类型 | 当前实现 | 生产边界 |
|---|---|---|
| GBA Code Breaker | 未加密 GBA 8/16 位写、4 型半字滑动写；重复数 1–4096，步长为正偶数 | 只输出 candidate/blocked；条件码等阻塞；逐帧重写可能掩盖游戏消费，正式玩法验收使用原子 load 后一次性补丁 |
| GBA Game Genie | 只识别、分类；未解码 | `patches=[]`，不可用于验收 |
| IPS / BPS | 未找到项目内生产解析器、应用器或专门测试 | 待补，不得声称已支持 |
| 定长 ROM 文件偏移补丁 | 已带原 SHA1 与原字节校验，生成副本 | 是 ROM 改版，不是 RAM 地址证据；不得混入 calibrated fields |

## 本作现成宏检索

绑定以下两个 SHA1 的 GitHub 全站代码检索均未命中可直接使用的自动菜单 Lua/宏：

- `40aab076a528f52e93260bb98d91a40039e0da02`（当前中文版）
- `abd71fe01ebb201bcc133074db1dd8c5253776c7`（USA）

检索入口：

- <https://github.com/search?q=%2240aab076a528f52e93260bb98d91a40039e0da02%22&type=code>
- <https://github.com/search?q=%22abd71fe01ebb201bcc133074db1dd8c5253776c7%22&type=code>

GitHub 全站代码搜索受登录与索引限制，因此结论仅是“本次检索未命中”，不是“不存在”。项目当前菜单 token 为自有，已把真实装备、关闭、重开持久化固化为规范配方；换游戏时应优先找目标游戏社区模块，找不到再按同一协议编写配方。

## 对下一款游戏的最小复用步骤

1. 固定 ROM SHA1、核心、内存域和可加载根态；根态先通过独立跨进程验收。
2. 查来源库与游戏社区模块，复用宏/结构/地址线索，不直搬跨版本地址。
3. 在 `prepare` 用真实菜单/导航形成基态，每步写 RAM 断言与画面锚点，禁止内存补丁冒充菜单装备。
4. case 从同一基态施加相同输入，只改变一个目标条件；负例必须真实发生并保留失败证据。
5. 比较帧对齐 RAM 与真实画面；字段通过后才写入地址表，scout 候选不得晋升。
6. 归档配方、报告、manifest 与 SHA256；模拟器、协议源码、状态或配方变化必须使缓存失效。
7. 平台总闸门独立评估，单游戏通过不得自动放行整个平台。

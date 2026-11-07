# 移植工厂（v0.3 通用移植流水线）

三个入口：`port` 是给一个游戏的源码就能出掌机包的通用流水线（见 [通用移植流水线](通用移植流水线.md)）；`job` 处理已有移植配方的构建、验收和封装；`research` 处理商业程序快照、静态逆向、AI 模块重写、编译和原指令行为对照。研发不要求连接真机，也不会将研发结果自动发布成游戏。

基础内核使用 Python 标准库；研发依赖固定在 `requirements-research.txt`，使用项目专用环境 `F:\_scratch\portfactory_env`。`工厂.py` 自动使用此环境，也可用自己的环境执行 `python -m portfactory`。

## 现在能做什么

- 登记游戏文件（文件或目录），识别 PE / ELF / NRO / NSP / XCI / XBE / XEX / ISO / ZIP 等格式，记录 SHA256
- 登记设备档案（平台族、架构、能力、是否已接线验证）
- 配方（recipe）：声明支持的平台、阶段、构建/封装步骤和每阶段闸门
- 执行任务并按阶段续跑；已通过阶段默认不重跑
- 闸门结果逐项计数：通过 / 失败 / 阻塞 / 未测试 / 不适用；没有“未发现失败＝通过”
- 真机验收只接受带证据的验收记录，且记录必须绑定本任务
- 封装包生成 `MANIFEST.json`，整包复算每条文件的大小与 SHA256，拒绝多余或越界条目
- 生成 Markdown 报告；本地 HTTP 看板查看任务详情
- 任务运行锁：检测到仍在运行的进程时拒绝重复启动
- **通用移植流水线**：一份声明式 spec（源码 commit、工具链档案、构建适配器、打包与闸门）经 prepare→fetch→build→package→verify 出 PortMaster 包，可断点续跑；同一份 spec 换 profile 即出 aarch64 / Windows / Switch 目标
- **输入分流**：`port route` 只读扫描任意输入目录/文件，判定 B-source / B-recomp / A1 / A2 / 数据 / 现有制品 / 模拟器 / 压缩包，并给出下一命令；不解压、不执行
- **一条命令接单**：`port new <源码目录> --id <游戏id>` 把路线判定接到 spec 草稿上，判定 JSON 的哈希写进草稿；源码以外的路线只报原因，不留文件
- **接单到出包**：`port new` 生成的草稿人工填完后直接进流水线，本机已用 OpenTyrian 快照跑到 R3（aarch64 包 5,049,758 B、七个闸门全绿）
- **成品资格**：`port status` 把已有构建与运行记录换算成 R0–R6，逐格复核文件哈希；R5 真机与 R6 发布永远不会自动通过

## 通用流水线（port）

```bash
py -3 工厂.py port route <目录或文件>                 # 只读判定走 A/B 哪条路线，不执行
py -3 工厂.py port new <源码目录> --id mygame        # 按判定生成待填 spec；非源码路线拒收
py -3 工厂.py port draft <源码目录> --id mygame        # 扫源码生成待填 spec
py -3 工厂.py port plan  specs/duke3d.json --target handheld   # 只打印将执行的命令
py -3 工厂.py port build specs/duke3d.json --target handheld [--force] [--dry-run]
py -3 工厂.py port run   specs/duke3d.json --target handheld --plan plans/run.json  # 采集主机运行证据
py -3 工厂.py port status specs/duke3d.json --target handheld  # 评估成品资格 R0–R6
py -3 工厂.py port list  --dir specs
```

实测（2026-10-30，本机一条命令跑完）：

| spec | 目标 | 结果 |
|---|---|---|
| `specs/duke3d.json` | handheld | EDuke32 从 `voidpoint.io` 的 `ec5824d` 取源 → 打进 ALSA 补丁 → aarch64 交叉编译 → `Duke3D.zip` 1,631,625 B / 7 条目，7 项闸门全过（数据玩家自备） |
| `specs/duke3d.json` | windows | 同一 spec、mingw64 档案 + 目标专属补丁 → `Duke3D-win-proof.zip` 2,573,198 B，5 项闸门全过（验证用） |
| `specs/tyrian.json` | handheld | OpenTyrian 从 `opentyrian` 的 `ac5d0e7` 取源 → 下载并校验 Tyrian 2.1 免费数据（sha256 钉死）→ `Tyrian.zip` 5,046,805 B / 112 条目，7 项闸门全过；重跑字节一致 |
| `specs/tyrian.json` | switch | 同一 spec、devkitpro 档案（走 devkitPro 自带 msys2 bash）+ libnx Makefile → `Tyrian-switch.zip` 7,753,487 B / 3 条目（`opentyrian.nro` 18,820,906 B + 许可证 + README），NRO/no_build_paths/licenses/deterministic_zip 四项闸门全过；数据走 romfs；全量重跑两次字节一致；未做真机验收 |

详见 [通用移植流水线](通用移植流水线.md)、`specs/`。

### P0：可信续跑与工程交接（2026-10-30）

当前 `port` 为 admit → prepare → fetch → build → package → verify。此节的续跑和输出位置说明取代上方历史记录及旧通用指南中的对应描述。

- **不再凭旧绿灯跳过**：源码、补丁、构建配置、工具内容、已声明依赖及构建实现进入阶段摘要；缓存命中还会复算输出哈希。启用构建缓存时，只改打包资料不会重编；上游失败会把下游状态置为未运行。
- **编译缓存默认保守**：只有工具可识别且 `build.cache_inputs` 明确列出完整的编译器、SDK、外部脚本/库等依赖路径时才复用编译结果。路径相对 spec 所在目录解析，也支持绝对路径。未声明不报假成功，而是每次新副本重建；现有 Tyrian spec 尚未声明，所以仍会重新编译。依赖不完整或构建涉及未固定外部输入时，不应启用复用。
- **原件和旧副本保留**：输入变化、产物损坏或 `--force` 会使用目标目录下新的 `attempts/<标识>/` 工作副本，不覆盖旧源码和包。准确输出路径见本次报告及 `port_<标识>.json`，不再假定固定 `dist` 位置。
- **包有明确身份**：验证本次打包返回的确切路径、大小和 SHA256；旁边放一个旧 ZIP 不会被误验。准入、工具检查和闸门每次重跑，计划模式不修改真实阶段状态或历史包。
- **交接分类型**：清单绑定完整工程文件集合、逐文件 SHA256、spec、生产者、源平台和未解决项。`analysis_only`、`module_source` 及有未解决依赖的工程不能进入构建；`buildable_project`/`aot_project` 只是工程类型声明，仍需真实构建验证，不授予整游戏或发布资格。清单和工作目录必须放在源工程之外，当前拒绝符号链接/junction。

```bash
py -3 工厂.py port handoff <工程目录> --spec <spec.json> --kind buildable_project --producer <生产者标识> --source-platform <源平台> --out <工程外的handoff.json>
py -3 工厂.py port check-handoff <handoff.json> --for-build
py -3 工厂.py port build <spec.json> --target <目标> --handoff <handoff.json>
```

使用 `--handoff` 时，实际复制并构建清单中的工程，不再从 spec 的原取源位置获取另一份代码；工程或 spec 变化后必须重新冻结清单。直接输入源码的旧命令仍可用；非 Git 本地目录现在可只给 `source.local`，Git 源必须给完整的 40 位提交哈希。

本轮定点测试 **57 项通过**：原 portkit 23 项、续跑/工具身份 22 项、交接清单 12 项；另实际跑过原 job/封装/CLI 相关的 15 项基础回归。这些测试不是整游戏行为验收，也不是当前全部研发测试的总数。

真实入口验证：

- [AArch64 编译与续跑记录目录](file:///F:/_scratch/portfactory_p0_20261030/compiler-work/compiler-smoke/)：自己编写的 C 验证件经 CLI 清单导出、接收、Zig 编译和封装；重复运行复用经哈希核对的 fetch/build/package；改源码后旧清单退出码为 2，重新冻结后产出不同哈希的 ELF，旧 ELF 保留。该验证件不是游戏，也未执行。
- [源码变化时的阻塞记录](file:///F:/_scratch/portfactory_p0_20261030/compiler-work/compiler-smoke/port_414eaa3d8f634548910ee9f7005f642e.json)：停在 admit，未沿用旧成功状态。
- [OpenTyrian Switch 本轮构建记录](file:///F:/_scratch/portfactory_p0_20261030/tyrian-work/tyrian/port_39b0a5b00e534d0e952247034a924c63.json)：既有 spec 在新工作目录完成真实编译与四项静态检查，ZIP 为 7,753,487 字节，SHA256 `3c4605f8316f6181a8dade96c8b9688cac6db219f9be92afaebcab441cf95c5c`，与历史包字节摘要一致；**未做真机测试，不能标为验收成品**。

P0 没有安装 Ghidra/ReXGlue，也没有实现 AI 编译修复。下一批按计划进入 P1-A（成熟逆向后端）与 P1-B（受控补丁修复）；现有研究模块仍保持标量研究范围，尚未自动导出完整游戏工程。

### P1-B：受控构建修复闭环（2026-10-31）

失败不再只是日志：真实构建失败会生成一份自足的修复请求，外部 AI（或人）只交补丁，是否修好由生产 runner 决定。

- **请求是证据包，不是转述**：记录 spec 哈希、失败阶段与原因、失败命令的日志尾部、源码快照的文件清单；编译器报错里点到的源文件会自动摘录进请求，也可用 `--include` 补。提示词、硬约束和提交命令写在同目录的 `.md` 里，可直接交给任何模型。
- **补丁只进隔离副本**：提交的补丁按内容哈希存到 `repair/incoming/`，随 fetch 应用到本次全新 `attempts/<标识>/` 快照；原始源码、旧包和旧补丁都不改动，补丁哈希进入 fetch 阶段摘要，缓存不会把旧结果当成新补丁的结果。
- **接受条件是真实重建 + 全部闸门**：`build → package → verify` 全通过才写入 `repair/accepted/`；构建过但闸门失败、补丁打不上、产物身份缺失都算拒绝。模型自述、自加的“已验证”字段不参与判定。补丁本身仍可改源码和构建脚本，静态闸门不能替代整游戏行为与真机验证。
- **补丁边界写死**：只接受 unified diff 文本；最多 12 个文件 / 600 行 / 256 KiB；拒绝二进制补丁、删除文件、改权限位、绝对路径与 `..` 越界；拒绝改 `.git`、本次 spec、portkit 闸门与流水线代码。
- **有预算、可结束**：每个 spec/目标记录 `repair/history.json`；预算用完或补丁与历史完全重复即停止，不会无限试。被拒后会按新失败重新生成下一次请求。
- **结论不上调**：接受补丁只表示这一轮构建、打包和静态闸门通过；记录里仍固定 `device_test: not_run`、`release_allowed: false`。

```bash
py -3 工厂.py port repair-request <spec.json> --target <目标> --work <工作目录> --budget 3
py -3 工厂.py port repair-submit <request.json> --patch <补丁.diff> --producer <模型或人名>
py -3 工厂.py port build <spec.json> --target <目标> --repair-patch <已接受的.diff>
```

真实入口验证（非游戏验证件，未执行、未上真机）：

- [修复请求 attempt-01](file:///F:/_scratch/portfactory_p1b_20261031/work/repair-smoke/repair/requests/attempt-01.md)：Zig 交叉编译真实报 `main.c:6:15: error: expected ';' after expression`，请求自动带上了 `main.c` 全文。
- [被接受的补丁](file:///F:/_scratch/portfactory_p1b_20261031/work/repair-smoke/repair/accepted/attempt-01-7909165e.diff)与[修复历史](file:///F:/_scratch/portfactory_p1b_20261031/work/repair-smoke/repair/history.json)：补丁 `+1/-1` 行，重建后 ELF（AArch64 / 64 位，SHA256 `5ba449b8…`）与 ZIP（1,607 B，SHA256 `f05a3854…`）经 elf/no_build_paths/portmaster_layout/deterministic_zip 四项闸门全过；原始 `source/main.c` 保持缺分号不变。
- 修复闭环同时修出一个真实缺陷：源码快照若位于别的 Git 仓库内部（例如宿主目录本身是仓库），`git apply` 会按外层仓库根解释路径并**静默跳过**；现在把仓库发现限制在快照内（`GIT_CEILING_DIRECTORIES`），补丁未真正落地时不会报成功。
- [OpenTyrian Switch 回归构建](file:///F:/_scratch/portkit_p1b/tyrian/port_bfc447b018344d94853a421c348225b3.json)：补丁应用改动之后全量重跑，ZIP 仍为 7,753,487 字节、SHA256 `3c4605f8…`（与历史包一致），NRO/no_build_paths/licenses/deterministic_zip 四项闸门全过；未做真机验收。

本轮新增定点测试 **11 项**：正常接受闭环、拒绝后重新生成请求、重复补丁、预算耗尽、补丁打不上、构建过但闸门失败、路径越界/spec 篡改、二进制/模式/删除补丁、数量与字节上限、请求后改 spec、诊断路径回指源码。全量 `unittest discover -s tests` 实测 204 项通过（256.0 秒）。

P1-A 没有开工：本机 `java` 不在 PATH，`JAVA_HOME` 指向不存在的 `f:\jdk-24.0.2`，也没有 Ghidra 或 GhidraMCP。安装 JDK 21 + Ghidra 12.1.4 + GhidraMCP 属于新增外部工具，需要单独授权后才能接入；当前逆向仍只有自研 Capstone 路径。

### P3-A：主机侧运行证据（2026-10-31）

构建通过不再等于“跑过”。`port run` 在独立运行目录里启动已构建产物，只有进程实际输出、且被机器观测到的检查点才算数。

- **产物绑定**：只认本 spec/目标最近一次 `build` 与 `verify` 都通过、且运行前后 SHA256 未变的产物；产物必须位于任务工作目录内。构建后被人改过的文件直接拒绝。
- **隔离运行**：每次运行新建 `work/<spec>/<目标>/runtime/run_<id>/run` 作为工作目录；stdout/stderr 全文落盘（默认上限 4 MiB），超限截断后仍继续扫描检查点，不会因为刷屏把后面的标记漏掉。
- **检查点协议**：计划 JSON 声明超时（1–300 秒）、检查点前缀和有序列表；按首次出现记时，缺一即失败，`ordered: false` 时才允许乱序。没有任何检查点的计划直接拒绝——跑起来不等于玩到了。默认直接执行构建产物；`program` 可换成启动器（例如宿主机上的 Python），此时 `args` 仍只是 argv 尾部。计划等于要执行的命令，只接受可信来源，未知字段会被拒绝。
- **超时树杀**：Windows 用 `taskkill /F /T`，POSIX 用进程组 SIGKILL；结果写 `timed_out`，被杀的退出码不会被当成正常退出。
- **复制项有边界**：只允许从 spec 所在目录或任务工作目录复制；`copy.dst` 必须是运行目录内的相对路径，重复或越界直接拒绝。
- **结论不上调**：会话 JSON 固定 `whole_game_behavior: not_run`、`device_test: not_run`、`release_allowed: false`；`kind: device` 当场拒绝，真机链路留给 P3-B。
- **退出码**：0 表示通过或 dry-run，2 表示未通过或前置条件不满足；dry-run 只校验前置并打印命令，不启动进程、不改状态。

```bash
py -3 工厂.py port run <spec.json> --target <目标> --work <工作目录> --plan <计划.json>
py -3 工厂.py port run <spec.json> --target <目标> --work <工作目录> --plan <计划.json> --dry-run
```

计划最小形态：

```json
{"schema": 1, "id": "host-boot-menu", "timeout": 30,
 "checkpoints": ["boot", "menu"], "checkpoint_prefix": "[PF] ",
 "args": ["ok"], "require_exit": 0, "ordered": true}
```

真实入口验证（自己编写的 C 验证件，经 Zig 交叉编译为 Windows x86_64；不是游戏，未上真机）：

- [运行状态与产物绑定](file:///F:/_scratch/portfactory_p3_20261031/work/runtime-smoke/state.json)：产物 `checkpoints.exe` 220,672 B、SHA256 `c9bcd2899a343704…`；`runtime.status=pass` 并记录计划哈希与产物哈希。
- [通过会话](file:///F:/_scratch/portfactory_p3_20261031/work/runtime-smoke/host/runtime/run_4f314497ce1f4430b1a174add1f0b7f0/session.json)：`boot`/`menu` 在 0.011 秒到达，退出码 0，运行前后产物未变。
- [超时会话](file:///F:/_scratch/portfactory_p3_20261031/work/runtime-smoke/host/runtime/run_0667267c007c4913bf03d32e5291b5e1/session.json)：上限 2 秒，进程被树杀（退出码 1、`timed_out: true`），只观测到 `boot`。
- [缺检查点会话](file:///F:/_scratch/portfactory_p3_20261031/work/runtime-smoke/host/runtime/run_fae6eb25e24a4a9fba0dde061adf9a6d/session.json)：进程正常退出，但只出现 `boot`，判失败并列出缺失的 `menu`、`title`。
- [构建记录](file:///F:/_scratch/portfactory_p3_20261031/work/runtime-smoke/port_f35d30c4f09441af95ce716f3d09b189.json) 与 [spec](file:///F:/_scratch/portfactory_p3_20261031/spec.json)、[通过/超时/缺失计划](file:///F:/_scratch/portfactory_p3_20261031/plans/)：均由生产 CLI 走完整 `build → package → verify` 后运行。

本轮新增定点测试 **15 项**：检查点通过、缺失、顺序与乱序放行、退出码、超时树杀、`${spec}` 复制、截断后继续扫描、构建后产物被改、无构建、device 拒绝、越界复制、dry-run 无副作用、计划 schema/未知字段校验、重建后证据失效。全量 `unittest discover -s tests` 实测 **219 项通过（256.5 秒）**。

注意：系统 `py -3` 没装 capstone，跑全量时会在原逆向单测上出现 1 项环境错误；上面的 219 项是用装了 capstone 的项目环境 `F:/_scratch/portfactory_env/Scripts/python.exe` 跑的。

### P3-C：成品资格阶梯 R0–R6（2026-10-31）

已有记录现在可以直接换算成“走到哪一步”，不用靠口头判断。`port status` 只读状态和会话记录、重算文件哈希，不执行构建或运行。

- **R0 准入**：spec 哈希与本次构建记录一致（spec 改过就作废），admit 通过。
- **R1 源码冻结**：fetch 快照仍在，内容和当时一致。
- **R2 可构建**：build 产物身份存在，哈希未被改。
- **R3 静态闸门**：package 与 verify 都通过，声明的每个闸门都是 `pass`，包在验证后没被改动。
- **R4 主机运行**：当前产物的运行证据为 `pass`、运行期间产物未变、检查点齐全、计划哈希与登记一致（计划改过要重跑）。
- **R5 真机 / R6 发布**：永远 `blocked`。portkit 还没有真机执行器与验收入口，发布资格也不由本地状态自动授予。
- **逐格计数**：某一级未过，后面的等级直接 `not_run`；verify 里任何一个闸门非 `pass` 都会让 R3 失败，不会因为构建成功就算过。
- `--require R4` 可当 CI 闸门，未达到时退出码 2；`--out` 把报告落盘，便于交接。

```bash
py -3 工厂.py port status <spec.json> --target <目标> --work <工作目录>
py -3 工厂.py port status <spec.json> --target <目标> --work <工作目录> --require R4 --out 资格报告.md
```

真实入口验证（同一个 Zig 验证件，不是游戏、未上真机）：

- [R4 评估报告](file:///F:/_scratch/portfactory_p3_20261031/qualification.md)：最新一次运行通过后评为 **R4 主机运行**，R5/R6 仍 blocked。
- [运行失败后的评估](file:///F:/_scratch/portfactory_p3_20261031/qualification-runtime-failed.md)：把缺检查点的运行留在状态里，评估回落到 **R3** 并给出“运行证据未通过”。
- [spec 被改后的评估](file:///F:/_scratch/portfactory_p3_20261031/qualification-spec-changed.md)：只改标题（id 不变）也判 **未达到 R0**，理由是 spec 在构建之后被改动；同一工作目录不能被旧证据复用。
- [OpenTyrian Switch 真实构建的评估](file:///F:/_scratch/portkit_p1b/tyrian-qualification.md)：R0–R3 全 pass（源码快照、NRO、ZIP 哈希都复核过），R4 因没有主机运行证据被挡，R5/R6 仍 blocked——真实游戏在当前流水线上就是 R3，不能因为包能解压就称可玩。
- `--require R4` 实测退出码 0，`--require R5` 退出码 2。

本轮新增定点测试 **10 项**：构建后 R3、运行后 R4、失败运行回落、产物被改挡在 R2、spec 改动挡在 R0、闸门失败停在 R2、无构建时不创建目录、`--require` 退出码、`--out` 落盘、未知等级拒绝。全量 `unittest discover -s tests` 实测 **229 项通过（420.5 秒）**。

### P3-D：输入分流——给一个路径就知道该走哪条路（2026-10-31）

`port route` 只读扫描目录或文件（文件名、构建入口、文件头魔数、包内清单），输出路线判定与下一命令。**不解压、不执行、不加载任何游戏程序**，也不写任何东西到被扫描的目录。

| 路线 | 判定依据 | 结论 |
|---|---|---|
| `B-source` 源码移植 | Makefile / CMakeLists / meson / configure / sln / gradle / Cargo.toml + 源码文件 | 直接进 `port draft → build → status` |
| `B-recomp` 反编译重建 | `symbols.txt`、`splits.txt`、`objdiff.json`、`asm/`、`expected/`、`orig/` | 需匹配版本的原版数据与编译器，构建入口要手写 |
| `A1-ghidra` 二进制逆向 | PE / DOS MZ / ELF / XBE / DOL / PS4 PKG 文件头 | 现在只能走自研 Capstone 函数级研究；完整工程导出要授权装 Ghidra |
| `A2-rexglue` Xbox 360 | `XEX2` 文件头 | ReXGlue 未接入，未获安装授权 |
| `existing-artifact` 现有制品 | 偏移 0x10 处 `NRO0` 魔数 | 只能登记与校验，**不能算移植** |
| `data-only` 只有数据 | `.grp .rts .mix .mpq .wad .pk3 .bsa .pak` 等 | 缺引擎或原版程序，无法自动出原生包 |
| `emulation` 模拟器 | `.gba .nds .iso .wbfs .chd` 等与 `PFS0/HEAD/CD001` | 明确写“模拟器不是目标平台产物” |
| `android-apk` | zip 清单里有 `AndroidManifest.xml` + `classes.dex` | Android 目标未接入 |
| `archive` 压缩包 | zip/7z/rar/tar 等 | 只列包内前 500 条名字，**不自动解压** |
| `unrouted` | 上面都没命中 | 退出码 2，让输入侧补信息 |

```bash
py -3 工厂.py port route "<目录或文件>"
py -3 工厂.py port route "<目录或文件>" --json --out 判定.json
```

判定包含 `signals`（证据）、`blockers`（阻断）、`cautions`（许可/数据政策/构建入口缺失等提醒）、`next_steps`（可复制的命令）和 `limits`；扫描有界（默认 3 层、4000 个文件，跳过 `.git`、`build` 等目录与符号链接，链接会计数并列出）。判定不是授权，也不等于资格等级——R0–R6 仍由 `port status` 按记录评。

真实入口验证（生产 CLI 直接跑的五个输入，2026-11-01 用最终代码重跑）：

- [OpenTyrian 源码快照 → B-source/高](file:///F:/_scratch/portfactory_route_20261031/tyrian-source.md)：137 个文件，认出 `Makefile`、`visualc/*.sln`、`src/*.c` 与 GPL-2.0 许可，下一步给出 `port new`。
- [opentyrian.nro → existing-artifact](file:///F:/_scratch/portfactory_route_20261031/opentyrian-nro.md)：NRO 魔数命中，阻断写明“不能算移植、真机验收仍为零”。
- [eduke32.exe → A1-ghidra](file:///F:/_scratch/portfactory_route_20261031/eduke32-pe.md)：识别 PE / x86-64，阻断是 Ghidra 未安装/未授权，下一命令指向 `research new`。
- [DUKE3D 数据目录 → data-only](file:///F:/_scratch/portfactory_route_20261031/duke-data.md)：只有 `.grp/.rts` 与两个 zip，判定缺引擎源码；旁边的 zip 只列名不解压。
- [eduke32_latest.zip → archive](file:///F:/_scratch/portfactory_route_20261031/eduke32-zip.md)：包内清单里看到 `COMMIT.EXE`，但没有解压、没有当成源码工程。

本轮新增定点测试 **17 项**：CMake 源码、反编译标记、源码+数据提示政策、纯数据、NRO 制品、PE、ELF、XEX2、ROM、zip 不解压、APK、无法判定退出码、输入不存在、只读性（扫描前后文件清单与 mtime 一致）、`--json` 与 `--out`、Markdown 落盘、符号链接跳过。该批完成时全量 `unittest discover -s tests` 实测 **246 项通过（219.07 秒）**。


### P3-E：一条命令接单——路径 → 路线 → 待填 spec（2026-11-01）

`port new <源码目录> --id <游戏id>` 把 `port route` 的判定直接接到 `port draft` 上：

- **只有可重建的源码路线会出草稿**：`B-source` → `family: source-port`，`B-recomp` → `family: recomp`；同时把只读判定写成 `<id>.route.json`，并把它的 SHA256 记进草稿的 `_draft.route.decision_sha256`，事后能核对“这份草稿当初是按哪条路线、哪次扫描生成的”。
- **其他路线一律拒收**：`data-only`、`A1-ghidra`、`A2-rexglue`、`existing-artifact`、`emulation`、`archive`、`android-apk`、`unrouted` 都只打印原因与阻塞项，**不生成任何文件**，退出码 2。不给商业数据或二进制造一份填了也跑不动的假 spec。
- **单文件不算工程**：只给一个 `.c` 会被拒（`port new` 需要源码目录）。
- **不许静默覆盖**：同名草稿或判定已存在时报错，要覆盖必须显式 `--force`。
- **草稿仍是待填**：源码 commit、构建参数、数据政策、打包信息要人工填；填完删掉 `_draft` 另存为 `<id>.json` 才能 `port plan/build`。生成草稿不代表能编译、能玩或能发布。

```bash
py -3 工厂.py port new <源码目录> --id <游戏id> [--out-dir specs] [--force]
```

真实入口验证（生产 CLI，非脚本）：

- [对 OpenTyrian 快照接单](file:///F:/_scratch/portfactory_onboard_20261101/new-source.md) → [待填草稿](file:///F:/_scratch/portfactory_onboard_20261101/specs/opentyrian-snapshot.draft.json)：137 个文件判为 `B-source`，草稿里自动带上 `commit ac5d0e71…`、GPL-2.0 与 SDL2 依赖证据，并留下构建目标 `TODO`；配套的 [路线判定 JSON](file:///F:/_scratch/portfactory_onboard_20261101/specs/opentyrian-snapshot.route.json) 的哈希已写进草稿。
- [DUKE3D 数据目录 → 拒收](file:///F:/_scratch/portfactory_onboard_20261101/refused-data.md)：退出码 2，specs 目录里没多出任何文件。
- [eduke32.exe → 拒收](file:///F:/_scratch/portfactory_onboard_20261101/refused-pe.md)：A1 路线，阻断写的是 Ghidra 未安装/未授权。
- [opentyrian.nro → 拒收](file:///F:/_scratch/portfactory_onboard_20261101/refused-nro.md)：现有制品只能登记校验，不能当移植工程。

本轮新增定点测试 **14 项**：源码树生成草稿并绑定判定哈希、反编译工程用 recomp 家族、`--out-dir`、数据/二进制/制品/压缩包/单文件五种拒收且不留文件、覆盖保护与 `--force`、非法 id、输入不存在、扫描前后源码树逐字节不变、直接调用返回 refused、渲染文案（接单才提草稿，拒收不提草稿）。该批完成时全量 `unittest discover -s tests` 实测 **260 项通过（251.33 秒）**。

### P3-F：接单产物真跑通到 R3——草稿 → spec → aarch64 包（2026-11-01）

拿 P3-E 对 OpenTyrian 快照生成的草稿做人工填写，验证"接单"不是只出一张纸：

- **人工填的三件事**：删掉 `_draft` 另存 [opentyrian-snapshot.json](file:///F:/_scratch/portfactory_onboard_20261101/specs/opentyrian-snapshot.json)；按事实把家族从草稿猜的 `source-port` 改判为 `open-engine`（Tyrian 2.1 数据是作者免费发布，不是商业数据自备，依据写进 `data.rights_proof`）；构建参数复用同一 commit 上已经跑通的命令（`custom` + zig-aarch64 + SDL2），产物 `opentyrian`。
- **`port plan` 只打印命令**，三条真实编译命令行可直接核对；**`port build --target handheld`** 五阶段全绿、七个闸门全绿（见 [report-handheld.md](file:///F:/_scratch/portkit/opentyrian-snapshot/report-handheld.md)）：`opentyrian-snapshot.zip` 5,049,758 B、sha256 `c321e1329795e729…`、112 个条目 = 启动脚本 + `port.json` + `gameinfo.xml` + `licenses/COPYING`(18,326 B) + `screenshot.png`(53,804 B) + 106 个游戏数据文件，引擎二进制 518,592 B 的 aarch64 ELF。
- **成品资格**：`port status` 评到 **R3 静态闸门**，R4 主机运行 / R5 真机 / R6 发布三条全部 blocked 并写明原因；`--require R2`、`--require R3` 返回 0，`--require R4` 返回 2。
- **到不了的地方说清楚**：本机没有 Windows 侧的 SDL2 开发库，这份 spec 也没声明 host 目标，所以 R4 现在拿不到运行证据；这不是"再跑一次就好"，缺的是主机构建目标或真机（P3-B）。
- **顺带修掉接单落盘带出的缺陷**：`port list --dir` 原先会把 `<id>.draft.json`、`<id>.route.json` 当 spec 校验（判定记录直接报"缺少字段 id"）。现在两类侧文件都跳过，并在末尾点名跳过了几个、分别是谁；新增定点测试 1 项。

本轮新增定点测试 **1 项**（`port list` 跳过草稿与判定侧文件，`test_portkit_onboard.py` 涨到 15 项）。全量 `unittest discover -s tests` 实测 **261 项通过（226.90 秒，见下方自测表）**。


## 快速开始

在 `F:\开源掌机教程\07-移植工厂` 下执行：

```bash
py -3 -m portfactory init
py -3 -m portfactory device add devices/switch-local.json
py -3 -m portfactory device list
py -3 -m portfactory recipe list

# 校准配方只接受现成 OpenTyrian NRO，不接受任意商业游戏目录
py -3 -m portfactory game intake "F:\开源掌机教程\01-教程库\移植原理\动手实践\switch\opentyrian.nro" --name "OpenTyrian 校准"

# 接单（用上一步打印的 game_xxx；商业程序改用下方 research 入口）
py -3 -m portfactory job new --game game_xxx --device switch-local --recipe switch-opentyrian-calibration
py -3 -m portfactory job run job_xxx

py -3 -m portfactory job status job_xxx
py -3 -m portfactory job report job_xxx
py -3 -m portfactory serve --port 8765
```

看板：<http://127.0.0.1:8765/>

## 已跑通的校准任务

以真实制品 `01-教程库/移植原理/动手实践/switch/opentyrian.nro` 为输入：

| 项 | 结果 |
|---|---|
| 任务 | `job_8a3011d7c7c5` |
| 制品 | NRO / aarch64 / 18,825,002 B |
| 原始 SHA256 | `0ca87dfcf71e7a780147700f9419617f75c924f224f7ea9d66ee3497faa72f6a` |
| 闸门 | 通过 7 / 失败 0 / 阻塞 1 / 未测试 0 |
| 阶段 | 制品通过 → 封装通过 → 真机验收**阻塞** → 发布未执行 |
| 结论 | **阻塞，不能当成品交付**（缺 Switch 真机验收记录） |
| 封装包 | `jobs/job_8a3011d7c7c5/dist/OpenTyrian-calibration.zip`，7,746,479 B |

这是刻意留下的正确结果：本机没有 Switch 真机，系统不允许把“编出来了”冒充“能玩”。

## 目录

```
07-移植工厂/
  portfactory/          内核（标准库）
    intake.py           游戏指纹
    sniff.py            格式/架构识别
    engine.py           任务状态机、阶段、续跑、运行锁
    gates.py            闸门实现
    packaging.py        整包生成与校验
    report.py           Markdown / HTML
    server.py           本地看板（现有 job 任务）
    research.py         研发队列、预算、响应绑定与恢复
    reverse.py          PE32/x86 静态分析与模块证据
    behavior.py         IR 转 C、编译、原指令差分
    rd_provider.py      本机模型 HTTP 接口
    rd_worker.py        受超时约束的分析/模型子进程
    cli.py              命令行
    portkit/            通用移植流水线
      spec.py           声明式 spec 校验
      runner.py         阶段执行、续跑、内容寻址缓存
      route.py          输入只读扫描与 A/B 路线分流
      onboard.py        路线判定 → 待填 spec 的一条命令接单
      runtime.py        主机侧运行证据与检查点
      ladder.py         成品资格阶梯 R0–R6
      repair.py         构建失败修复请求与补丁验收
      gates.py          ELF/NRO/确定性 ZIP 等闸门
  工厂.py              自动使用本项目 Python 环境的入口
  requirements-research.txt  研发依赖版本
  recipes/switch/       配方
  devices/              设备档案
  jobs/<任务>/          日志、证据、产物、report.md
  state/factory.db      任务、闸门、研发队列与预算
  tests/                基础内核与研发专项自测
```

## 闸门口径

必需闸门只有全部为“通过”，或“不适用且配方写明理由”，发布闸门才会放行。任何“阻塞”都会让任务停住；“未测试”不计为通过。

| 闸门 | 用途 |
|---|---|
| `file_exists` / `sha256` | 输入或产物存在、大小、哈希 |
| `elf_arch` | ELF 架构与 ABI 线索 |
| `nro_header` | Switch NRO 魔数、入口分支、哈希 |
| `package_integrity` | 整包 MANIFEST 与逐文件哈希 |
| `command` | 构建或探测命令，非零退出即失败；工具缺失记为阻塞 |
| `manual_attestation` | 真机验收：记录绑定任务、必需检查项全部通过、每项有非空证据文件 |
| `release_ready` | 汇总此前所有必需闸门，决定是否允许发布 |

## 真机验收怎么接

```bash
py -3 -m portfactory job attest-template job_xxx
```

把截图/录像放进任务证据目录，填好模板里的 `tester`、`device`、`date`，然后：

```bash
py -3 -m portfactory job attest job_xxx 路径\device_test.template.json --run
```

系统会复制证据、重跑真机阶段与发布阶段。记录里的 `job_id` 必须是本任务；声称通过但没有证据文件会直接判失败。

## 加配方 / 加设备

参照 `recipes/switch/opentyrian-calibration.json` 和 `devices/switch-local.json`。配方支持：

- `${input}`、`${input_dir}`、`${job_dir}`、`${work_dir}`、`${evidence_dir}`、`${dist_dir}`、`${recipe_dir}`
- 步骤：`command`（构建/探测）、`package`（生成带 MANIFEST 的 zip）
- 每个阶段必须至少有一个闸门，禁止“只有步骤、没有验收”

设备平台族目前有 `switch-homebrew`、`linux-handheld`。RG DS / Duo / 天玑设备必须按实际型号和系统登记，不能拿芯片名代替平台档案。

## 研发入口

```bash
py -3 工厂.py research new "G:\天马5T\750A218G\PC\幻世录II\HSLPRE.EXE" --target switch-homebrew --max-modules 3 --max-requests 9 --max-context-bytes 240000 --max-seconds 900
py -3 工厂.py research analyze rd_xxx
py -3 工厂.py research work rd_xxx
py -3 工厂.py research status rd_xxx
py -3 工厂.py research report rd_xxx
```

1. 原文件只读，只复制指定程序到 `F:\_scratch\portfactory_research\rd_xxx`，完整 SHA256 冻结输入；不复制整套游戏素材。
2. PE32/x86 分析器读取节、导入、导出和调用关系，记录函数边界证据、汇编与排除原因；额外扫描不可写的可执行代码节中的直接调用目标，并明确标记为启发式发现。函数发现是有界静态分析，不是完整游戏覆盖率。
3. 自动派发符合有限 cdecl/uint32 观察契约的纯标量叶子函数；直接调用链在通过独立校验后做**有界内联组合**（每个被调函数仍按自己的证据单独证明，调用点按“实参依赖→返回值依赖”原子建模，环、跨边界、间接调用和不合格被调函数一律拒绝），组合上限为 6 个函数 / 160 条指令 / 8,192 字节。函数内允许有界回边，但只有每条条件分支都能由常量决定（固定次数循环，上限 64 次）时才接受，循环次数作为证据交给重写提示词；继续与否取决于参数、内存或未知标志的循环一律按 `unproven_loop_condition` 拒绝，不做近似展开。未恢复完整原始类型或未使用的尾参数。涉及图形、声音、指针、全局状态或不明边界的模块保留为 `unsupported`，超出本批规模的候选为 `deferred`，都不算通过。
4. AI 根据本模块证据生成受限运算 IR；组合模块的提示词会附带被调函数反汇编供内联，固定次数循环会附带回边地址与次数证据，IR 本身仍无循环语句，由重写方按次数展开。程序验证 IR，再生成真实 C，通过 Zig 编译成 i386 ELF；没有任意 C/脚本执行入口。
5. 原始机器码和重写 ELF 分别在 Unicorn 受限地址空间执行，比较边界和固定随机输入下的返回值、栈及 ABI；组合模块会把所有成员字节段按页合并映射，函数间空隙零填充且永不执行。Unicorn 仅是函数对照工具，不作为最终游戏运行器。
6. 对照失败生成反例供下一轮修复；重复相同 IR、达到重试上限或预算耗尽即停止。操作系统文件锁防双 worker，中断请求保留预算，不静默重发。

### AI 如何接入

- 默认 `inbox`：命令生成本地 `request.json`，当前 Qoder 会话中的研发代理领取并回填响应，再执行 `research submit rd_xxx response.json`、`research work rd_xxx`。命令行本身不调用 Qoder 云端 API；无人领取时状态为 `waiting_ai`。
- 自运行：`research work rd_xxx --provider local --endpoint http://127.0.0.1:端口/v1 --model 模型名`。只接受本机 IP 字面地址，禁代理与重定向，不发送到远端。模型服务需要已运行，工厂不会暗中下载或启动模型。
- 每个响应必须绑定请求、原文件、模块的 SHA256。模型不能修改对照器、测试样本和验收状态；编译与差分结论由程序生成。
- 三项预算分别是请求次数、保守的请求/响应 UTF-8 字节预留、worker 活跃秒数；失败与中断不退预留。**这些不是 Qoder 积分或模型账单限额**；离线代理耗时与计费不在本地 worker 的观测范围内。上游提供 usage 时另行记录。

### 真实游戏样本实跑（2026-10-29）

样本为《幻世录II》目录中的 `HSLPRE.EXE`，1,190,912 字节；任务 `rd_3363716d7c5e`。原件与独立快照 SHA256 均为 `8f8dc358447baf43f6aadb331e61a04feb8dcc1783a0b95e3e972631de28a922`，执行后重新计算确认未变化；没有启动游戏 EXE。

静态分析产生 1,860 条模块记录：13 条满足当前候选规则，本批派发 3 条、延期 10 条；另外 1,847 条不支持。这不是全游戏函数总数或移植完成比例。三个选中函数各 20 字节，其游戏业务用途尚未确认。

| 模块 | 边界/随机输入对照通过 | 失败 | 未执行 |
|---|---:|---:|---:|
| `fn_004855d0` | 153 | 0 | 0 |
| `fn_004855f0` | 153 | 0 | 0 |
| `fn_00485610` | 153 | 0 | 0 |
| 合计 | 459 | 0 | 0 |

这次 AI 通过当前 Qoder 会话领取收件箱并生成 IR，三份响应均经过正式 `submit → work` 入口：验证绑定、生成 C、真实 Zig 编译、Unicorn 原码/新码差分后，任务才进入 `module_batch_verified`。计入 3/9 次请求、43,082/240,000 字节预留；再次 `work` 后请求数与字节预留未增加，源码、ELF、编译日志、对照报告的哈希和修改时间均未变。

[完整研发报告](file:///F:/_scratch/portfactory_research/rd_3363716d7c5e/research-report.json)包含明确的延期/不支持状态；[重写产物目录](file:///F:/_scratch/portfactory_research/rd_3363716d7c5e/rewrites/)中每个模块的 `1` 子目录保存 `source.c`（可读重写源码）、`rewritten.elf`（差分用 x86 编译产物）、`comparison.json`（逐输入原/新结果与哈希）、编译日志。保留该研发目录和工厂数据库才能继续核验与恢复；这些不是 Switch 安装包。

查看已有任务无需重新接单：

```bash
py -3 工厂.py research status rd_3363716d7c5e
py -3 工厂.py research report rd_3363716d7c5e
```

此前仙剑 `PALOLD.DLL`、`PAL.DLL` 的分析未筛出符合当时规则的候选，报告保持 `blocked`，没有拿它们凑通过。本地模型接口经过临时 HTTP 服务测试，但尚未连接真实模型服务；此次真实 AI 证据仅来自收件箱路径。

### 组合扩展后的复跑（2026-10-30）

用同一份 `HSLPRE.EXE`（取上一任务冻结的 `input.exe` 副本，SHA256 仍为 `8f8dc358447baf43f6aadb331e61a04feb8dcc1783a0b95e3e972631de28a922`，复跑后重新计算确认未变）重跑加入了内联组合的分析器，任务 `rd_1c74a142dea1`。静态分析仍是 1,860 条模块记录：13 个候选（3 派发 / 10 延期），1,847 不支持。

新增的有界内联组合在本样本上证明 **0 个**调用者。697 个含直接调用的模块在组合阶段被拒，按模块计：`callee_not_independently_validated` 172、`incomplete_callee_boundary` 232、`indirect_call` 292、`loop_or_backward_branch` 1。唯一"全部直接被调函数都已是合格叶子"的调用者 `fn_00484b50 → fn_00484b40`，因调用者本身体内含循环而被拒。这是能力边界的真实结果，不是接线未生效：组合只覆盖"其余部分已是纯标量、且所有直接被调函数已独立证明"的调用者。

本批三个模块仍是此前的叶子函数，每模块 153 例全通过：

| 模块 | 边界/随机输入对照通过 | 失败 | 未执行 |
|---|---:|---:|---:|
| `fn_004855d0` | 153 | 0 | 0 |
| `fn_004855f0` | 153 | 0 | 0 |
| `fn_00485610` | 153 | 0 | 0 |
| 合计 | 459 | 0 | 0 |

预算计入 3/12 次请求、43,136/240,000 字节预留、59.67/600 秒活跃时间；三个模块均为单段 `original_ranges`、`composition: None`，源码、ELF 与对照报告全部由编译和差分程序生成。[完整研发报告](file:///F:/_scratch/portfactory_research/rd_1c74a142dea1/research-report.json)

### 有界定次循环扩展后的复跑（2026-10-30）

同一份 `HSLPRE.EXE`（仍用冻结副本，复跑后重新计算 SHA256 为 `8f8dc358447baf43f6aadb331e61a04feb8dcc1783a0b95e3e972631de28a922`，未变化）在加入“常量可判定的固定次数循环 + 完整 x86 标志位建模”后重新开批：`rd_251868a086a0`。静态分析仍是 1,860 条模块记录、14 个候选（3 派发 / 11 延期）、1,846 条不支持；全程没有启动原版 EXE。

分析器这次把回边从“一律拒绝”改成有界抽象解释：按地址出队，用常量解析条件分支依赖的 CFG/SF/ZF/OF/PF，只有函数内每条条件分支都能由常量决定（固定次数循环，上限 64 次、每块 512 次访问）才接受，并把 `{back_edge, target, iterations}` 写进模块证据与提示词；`inc/dec` 之后依赖进位标志的分支、以及次数依赖参数或内存的循环继续拒绝。

本样本上的真实结果：

- 13 → 14 个候选：新增的 `fn_004818a0`（3 参数 / 66 字节，带符号差值折返 + 镜像钳位 + 低字节归一）上一轮因 `unproven_branch_flags` 被拒，靠完整标志位建模才达标，它本身不含循环。
- 带 `loops` 证据的模块 **0 个**；15 个条件无法由常量决定的循环函数被明确记为 `unproven_loop_condition`，没有做任何近似展开。
- 内联组合仍是 **0 个**，697 个含直接调用的模块按 172/232/292/1 分桶拒绝，与上一轮一致。

| 模块 | 边界/随机输入对照通过 | 失败 | 未执行 |
|---|---:|---:|---:|
| `fn_004818a0` | 193 | 0 | 0 |
| `fn_004855d0` | 153 | 0 | 0 |
| `fn_004855f0` | 153 | 0 | 0 |
| 合计 | 499 | 0 | 0 |

三份 IR 先在本机用同一套 uint32 语义对 4,021 组边界/随机输入预对过，再走正式 `submit → work`：绑定请求/原文件/模块 SHA256、生成 C、真实 Zig 编译、Unicorn 原码/新码差分。预算计入 3/9 次请求、45,252/240,000 字节预留、44.14/900 秒活跃时间；三个模块均为单段 `original_ranges`、`composition: None`。

第一次开批 `rd_21b0c910918d` 在 `fn_004818a0` 的第 0 例上误报超时：旧的 50ms 单例预算把 Unicorn 引擎构造和分页映射也算进去了，实际只执行 1 条指令。现已把计时起点移到 `emu_start` 之前，并把单例预算放宽到 0.5s（10,000 条指令上限仍是主约束）；`test_behavior` 35 项随之全绿。上面这批是在修正后的代码上重新跑的，旧批次连同失败记录保留在磁盘上供审计。

[完整研发报告](file:///F:/_scratch/portfactory_research/rd_251868a086a0/research-report.json)；[重写产物目录](file:///F:/_scratch/portfactory_research/rd_251868a086a0/rewrites/)逐模块保存 `source.c`、`rewritten.elf`、`comparison.json` 与编译日志。这些是 x86 差分测试产物，不是 Switch 安装包。

### 当前研发边界

已实现的是函数级研发闭环，不是任意商业游戏的完整自动重建。PS3 SELF、Xbox XEX、加密/加壳程序、复杂内存/图形/音频/输入/存档模块与整场游戏回放仍需扩展适配器；本轮没有绕过 DRM，也不包含这些功能的假实现。Ghidra/Java 尚未接入，本机分析用 Capstone。`module_batch_verified` 只表示选定函数样本通过有限差分测试，不代表全部输入上的数学等价，更不代表 Switch 可玩。

内联组合只覆盖可直接内联、规模有界（6 个函数 / 160 条指令 / 8,192 字节）且每个被调函数已独立证明的调用者；被调函数按摘要原子建模，不重新解释为调用者自己的栈帧，因此不恢复跨函数结构体、全局状态或间接调用。本样本上组合解锁为 0。

循环同样只覆盖次数可由常量判定、且不超过 64 次的纯标量循环；本样本没有任何函数带回边，固定次数循环目前只在合成夹具上验证过。依赖参数、内存或全局状态的循环仍按 `unproven_loop_condition` 拒绝。

Switch 真机自动部署与回放留待后续；研发报告将其标为 `not_run`，而非阻塞研发。原有 `job` 真机验收仍只校验记录绑定和证据文件存在，不能证明截图语义或防伪。

## 自测

在工厂目录使用装有研发依赖的解释器运行：

```bash
F:/_scratch/portfactory_env/Scripts/python.exe -m unittest discover -s tests -v
```

本轮实测：`unittest discover -s tests` 全量 **261 项通过（226.90 秒）**，分项如下：

| 专项 | 实跑结果 | 重点 |
|---|---|---|
| `test_factory.py` | 15 项通过 | 原有指纹、状态、封装与真机证据闸门 |
| `test_handoff.py` | 12 项通过 | 工程交接清单冻结、复核与“工程变了就拒绝” |
| `test_portkit.py` | 23 项通过 | spec 校验、五阶段流水线、续跑与工具身份 |
| `test_portkit_cache.py` | 22 项通过 | 内容寻址缓存、产物身份、链接与篡改拒绝 |
| `test_portkit_repair.py` | 11 项通过 | 修复请求→补丁→真实重建→闸门验收 |
| `test_portkit_runtime.py` | 15 项通过 | 主机运行证据：检查点、超时、产物绑定、计划哈希 |
| `test_portkit_ladder.py` | 10 项通过 | 成品资格 R0–R6 逐级复核与 `--require` 退出码 |
| `test_portkit_route.py` | 17 项通过 | 输入分流：路线判定、阻断说明、只读性与 CLI 输出 |
| `test_portkit_onboard.py` | 15 项通过 | 一条命令接单：源码路线出草稿并绑定判定哈希、其余路线拒收不留文件、`port list` 跳过草稿与判定侧文件 |
| `test_reverse.py` | 50 项通过 | PE/CFG、候选排除、直接调用链组合证明、固定次数循环与标志位拒绝 |
| `test_behavior.py` | 35 项通过 | 真实 Zig 编译、错误重写反例、内存/ABI/超时拒绝、多段原码映射对照 |
| `test_rd_provider.py` | 17 项通过 | 本机 HTTP 协议、IPv6、拒代理/重定向/工具调用 |
| `test_research.py` | 19 项通过 | 预算、锁、哈希绑定、恢复、重复 IR 停止 |

这些定点测试验证的是流水线自身的判定与闸门，不是整游戏行为验收，也不等于真机通过。

调度测试会模拟部分编译/模型返回值以验证状态机，不能当作真实游戏对照证据；真实游戏结果只认上面的真实样本批次与逐例产物。看板接口测试也不等于浏览器人工验收。另经普通 Python 实际调用 `工厂.py`：查询真实任务返回 0，错误参数返回 2，确认切换项目环境后不会把失败误报为成功。

## 后续扩展

先沿真实样本扩展全局状态、结构体、资源解析与跨函数依赖，并加入整场游戏的原版回放对照；随后才是目标平台链接、封装与真机回归。`--target` 当前登记研发目标，不能把 x86 差分测试产物当作 Switch 游戏。

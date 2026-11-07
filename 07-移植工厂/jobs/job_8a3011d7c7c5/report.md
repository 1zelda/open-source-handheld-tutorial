# 移植任务报告 · job_8a3011d7c7c5

- 游戏：OpenTyrian Switch 校准制品（F:\开源掌机教程\01-教程库\移植原理\动手实践\switch\opentyrian.nro）
- 目标设备：Switch 1（本机构建，真机待接线）（switch-homebrew）
- 配方：switch-opentyrian-calibration
- 接入路径：F:\开源掌机教程\01-教程库\移植原理\动手实践\switch\opentyrian.nro
- 任务状态：**阻塞**（`blocked`）
- 执行时间：2026-10-29T06:36:59+00:00 → 2026-10-29T06:41:07+00:00（UTC）

## 结论

任务被阻塞，不能当作成品交付。

### 下一步

- device_test / device_proof：缺少真机验收记录
- → 存在未执行阶段；修复上面的阻塞后重新运行。

## 闸门计数（逐项计数，不以未命中倒推）

- 全部闸门：待执行 0 / 执行中 0 / 通过 7 / 失败 0 / 阻塞 1 / 未测试 0 / 不适用 0
- 必需闸门：待执行 0 / 执行中 0 / 通过 7 / 失败 0 / 阻塞 1 / 未测试 0 / 不适用 0

## 阶段

| 顺序 | 阶段 | 状态 | 开始（UTC） | 结束（UTC） |
|---|---|---|---|---|
| 1 | artifact | 通过 | 2026-10-29T06:41:06+00:00 | 2026-10-29T06:41:06+00:00 |
| 2 | package | 通过 | 2026-10-29T06:41:06+00:00 | 2026-10-29T06:41:07+00:00 |
| 3 | device_test | 阻塞 | 2026-10-29T06:41:07+00:00 | 2026-10-29T06:41:07+00:00 |
| 4 | release | 待执行 | - | - |

## 闸门明细

### preflight

| 闸门 | 必需 | 状态 | 证据 | 说明 |
|---|---|---|---|---|
| device_family | 是 | 通过 | - |  |
| device_capabilities | 是 | 通过 | - |  |
| input_present | 是 | 通过 | - |  |

### artifact

| 闸门 | 必需 | 状态 | 证据 | 说明 |
|---|---|---|---|---|
| nro_present | 是 | 通过 | opentyrian.nro |  |
| nro_header | 是 | 通过 | opentyrian.nro | sha256=0ca87dfcf71e7a780147700f9419617f75c924f224f7ea9d66ee3497faa72f6a |
| nro_sha256 | 是 | 通过 | opentyrian.nro | sha256=0ca87dfcf71e7a780147700f9419617f75c924f224f7ea9d66ee3497faa72f6a |

### package

| 闸门 | 必需 | 状态 | 证据 | 说明 |
|---|---|---|---|---|
| package_integrity | 是 | 通过 | OpenTyrian-calibration.zip | 1 个文件 / 包 sha256=a3856043624f0643… |

### device_test

| 闸门 | 必需 | 状态 | 证据 | 说明 |
|---|---|---|---|---|
| device_proof | 是 | 阻塞 | - | 缺少真机验收记录 |

## 产物

| 文件 | 类型 | 大小 | SHA256 |
|---|---|---|---|
| OpenTyrian-calibration.zip | switch-nro-package | 7.4 MiB | `a3856043624f064347862ad01e681b65c9395c14d0e4335afe8329512af35401` |

## 最近事件

- 2026-10-29T06:36:59+00:00 · job.created · 接单：OpenTyrian Switch 校准制品 → Switch 1（本机构建，真机待接线） / switch-opentyrian-calibration
- 2026-10-29T06:41:06+00:00 · job.run · 开始执行
- 2026-10-29T06:41:06+00:00 · stage.start · 阶段 artifact 开始
- 2026-10-29T06:41:06+00:00 · stage.end · 阶段 artifact -> pass
- 2026-10-29T06:41:06+00:00 · stage.start · 阶段 package 开始
- 2026-10-29T06:41:07+00:00 · stage.end · 阶段 package -> pass
- 2026-10-29T06:41:07+00:00 · stage.start · 阶段 device_test 开始
- 2026-10-29T06:41:07+00:00 · stage.end · 阶段 device_test -> blocked
- 2026-10-29T06:41:07+00:00 · job.end · 任务状态 -> blocked

## 口径

- “未测试”不等于“通过”；没有真机证据时不能称成品。
- 只有全部必需闸门为通过（或不适用且写明理由）时，发布闸门才会放行。
- 本报告由闸门实际结果生成，不包含人工宣称的通过。

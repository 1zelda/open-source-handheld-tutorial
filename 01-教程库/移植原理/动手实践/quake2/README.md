# Quake II on YamagiQ2 → R36S / ARM Linux

第四个端口，也是第一个“大作本体”——但走的是**引擎全开源、商业数据用户自备**这条路：
Yamagi Quake II 是 Quake II 引擎的 GPL-2.0 源码实现，引擎代码、渲染器、
`baseq2/game.so` 全部可以从源码编出来；**原版 `baseq2/pak*.pak` 属于 id Software 的商业数据，
包里一个字节都不带**。

| 东西 | 值 |
|---|---|
| 引擎 | Yamagi Quake II `9dbf699`（2026-10-15，v8.71pre；GPL-2.0） |
| 主程序 | `quake2.aarch64` **705,264 B**，依赖 `libSDL2-2.0.so.0 / libm / libc / libdl` |
| 渲染器 | `ref_gles1.so` 282,568 B（默认）、`ref_gl1.so` 276,000 B、`ref_soft.so` 263,592 B |
| 游戏模块 | `baseq2/game.so` **651,712 B**（Yamagi 自带 game 源码编出的共享库） |
| 最高 ABI | `GLIBC_2.29`（`min_glibc` 按此填） |
| 成品包 | `package/Quake2.zip` **1,509,627 B**，sha256 `932ad1a4a2d8946561f1a5c0e2b2f39280fa1829e95766657f4f5f58f25a2336` |
| 自检 | `check_port.py` **39/39 通过** |
| 数据 | **不带**。要用户把自己的 `baseq2/pak0.pak`（及 pak1/pak2）放进 `ports/quake2/baseq2/` |

## 目录

```
quake2/
├─ build.sh              # 从源码建 aarch64 二进制 + 重打 zip（一条命令，字节级可复现）
├─ check_port.py         # 包校验器（由 quake/ 那份复制，加了渲染器/导出符号/数据边界断言）
├─ README.md             # 本页
└─ package/
   ├─ Quake2.sh          # 启动器（缺 pak 时双语提示并退出）
   ├─ Quake2.zip         # 成品
   └─ quake2/
      ├─ quake2.aarch64
      ├─ ref_gles1.so     # 默认渲染器：Mali 原生 GLES1，硬件加速
      ├─ ref_gl1.so       # 桌面 GL 走 SDL_GL_GetProcAddress，不链 libGL
      ├─ ref_soft.so      # 软件渲染兜底
      ├─ baseq2/game.so   # GPL-2.0 游戏逻辑
      ├─ baseq2/PUT YOUR PAK FILES HERE.txt
      ├─ port.json        # rtr=false / min_glibc 2.29 / arch aarch64
      ├─ gameinfo.xml
      ├─ quake2.gptk      # 只占 start/back，其余交给引擎原生 SDL2 手柄
      ├─ screenshot.png   # 640×480，Windows 实跑 Quake II demo 开局关
      └─ COPYING.GPL-2.0
```

## 和官方 Quake II 端口的差别

PortMaster 官方 `Quake.2.zip` 带 `gl1 / gl3 / soft` 三个渲染器、默认 `soft`（纯 CPU）。
RK3326 的 Mali-G31 跑软件渲染很吃力，所以这个包：

1. **默认 `vid_renderer gles1`** —— 用 Yamagi 的 `-DYQ2_GL1_GLES` + glad-gles1 编出来的
   GL1 渲染器，走的是设备自带 EGL/GLES1，硬件加速；
2. 同时保留 `ref_gl1.so`（桌面 GL1）和 `ref_soft.so`（软件）作为兜底，
   引擎自己的回退链是 `gl3 → gles3 → gl1 → gles1 → soft`；
3. 想换渲染器不用改脚本：`QUAKE2_RENDERER=gl1 ./Quake2.sh` 或 `=soft`。

没有 `gl3`/`gles3`：gl3 需要 glslang/SPIR-V 那一串依赖，先把能跑的三条路做扎实。

## 构建与复现

```bash
bash "01-教程库/移植原理/动手实践/quake2/build.sh"
```

脚本做的事：锁 commit 拉 Yamagi 源码 → 下 SDL2-2.30.9 头文件 → 从 Debian arm64
`.deb` 里抠出 `libSDL2-2.0.so.0`（仅链接用）和 GL 头 → 用 zig 0.17.0 交叉编译
`-target aarch64-linux-gnu` → 打 zip（固定时间戳）→ 跑自检。

编译分组（文件清单直接抄 Makefile 的 `*_OBJS_`，外加 Linux 条件项）：

| 组 | 文件数 | 产物 |
|---|---|---|
| client | 72 | `quake2.aarch64` |
| refresh/gl1 | 24 + glad（仅 GLES 版） | `ref_gles1.so` / `ref_gl1.so` |
| refresh/soft | 27 | `ref_soft.so` |
| game | 48 | `baseq2/game.so` |

把 `__DATE__` 由 `-DBUILD_DATE="Oct 28 2026"` 钉死，`Wl,-s` 去符号表，zip 里
时间戳固定 `2026-10-28 00:00:00`，因此同一 commit + 同一工具链跑出来的字节一致。

**实测**：删掉整个 `F:/_scratch/quake2_build`（连源码、头、下载缓存一起）重跑一遍，
五个二进制与 `Quake2.zip` 的 sha256 与首轮逐字节相同：

```
quake2.aarch64  e6ceff833b124fd8146d0877d1aa5cd248d14ce25c383625665c8118d59627e5  705,264 B
ref_gles1.so    0710c62e96481cdd3b79e46b729acfb3ad9f6186f88c1f175a971708cd708046  282,568 B
ref_gl1.so      82f036ebff9fb2c78e1a1799a6dadc943c8a24b4e514919a31a507d190f69bff  276,000 B
ref_soft.so     7948bfeb73eb940fc67bcad7f98875a5aedf135f4e48222ccfbd44c9cc000645  263,592 B
game.so         0cce86acca80ee896a11fa4b8bb83f3f6d213541525b92edd94eb26f565cad59  651,712 B
Quake2.zip      932ad1a4a2d8946561f1a5c0e2b2f39280fa1829e95766657f4f5f58f25a2336  1,509,627 B
```

## 验证到哪一步

**本机实测（Windows x86_64，同一份游戏代码 + id 官方 Quake II demo 数据）**

- 载入 `pak0.pak` 进开局关，640×480 全屏跑通：画面里有箱子、Strogg、手中武器、HUD，
  截图 `shot_fs2.png` 就是那一刻（原样作为包内 `screenshot.png`）。
- 控制台无缺失资源报错；`game.so` 被正常加载（`GetGameAPI` 链接成功，见断言）。
- demo 数据只放在 `F:/_scratch` 里做验证，**没有进包**。

**只做了静态验证（不冒充跑过）**

- aarch64 二进制：`e_machine=183`、`NEEDED` 只有 SDL2/libm/libc/libdl、
  最高 `GLIBC_2.29`；
- 三个渲染器都真的导出 `GetRefAPI`、`game.so` 导出 `GetGameAPI`
  （用 `.dynsym` 逐符号查 `st_shndx != 0`，空壳 `.so` 过不了这条）；
- 包内没有任何 `baseq2/pak*.pak`，`rtr=false`。

**未实测（不冒充）**

- 真机 R36S 插卡启动：本机没接掌机。R36S 的 ArkOS/JELOS 一般 glibc ≥ 2.36、带 GLES1/EGL，
  满足 2.29 门槛；GLES1 在 Mali-G31 上是最省的一条路，但**帧率没在真机上量过**。
- 手柄手感：Yamagi 原生读 SDL2 手柄，`quake2.gptk` 只把 Start→Esc、Back→Delete，
  摇杆灵敏度和按键映射都在引擎菜单里调（Options → Controls）。
- 音乐：不打包任何音频数据；用户自备的 pak 里如果是 OGG 版配乐，引擎会走 `snd_ogg`
  （ogg 解码器已编进 client）。

## 安装

1. 把 `Quake2.zip` 放到 `ports/` 下用 PortMaster 安装（或直接解到 `ports/quake2/`）；
2. 把自己的 `baseq2/pak0.pak`（有 pak1/pak2 也一起）拷进 `ports/quake2/baseq2/`；
3. 启动 `Quake II (YamagiQ2)`。缺 pak 时脚本会打印双语提示、6 秒后退出；
4. 日志在 `ports/quake2/log.txt`。

## 法律

- Yamagi Quake II：仓库根 `LICENSE` 是**逐组件许可清单**（Quake II 原版 GPL-2.0、
  SDL2 zlib、zlib、miniz、stb、curl 等），整包随附 `COPYING.GPL-2.0`。
- `baseq2/game.so` 由 Yamagi 的 `src/game/` 编出，同为 GPL-2.0。
- **不含** id Software 的商业 `pak0/pak1/pak2`，`port.json` 里 `rtr=false`，
  `inst` 明确要求用户自备；`check_port.py` 把“包里不许出现 `baseq2/pak*.pak`”写成硬断言。
- 想合法验证不用买游戏：id 官方 Quake II demo（`q2-314-demo-x86.exe`）里的 `pak0.pak`
  就能把这个端口跑起来，只是只有第一关。

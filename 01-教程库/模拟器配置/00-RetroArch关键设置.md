# RetroArch 关键设置(按"影响体验的大小"排序)

在掌机上这些项通常藏在 `Settings`(全局)和 `Quick Menu > Options`(单核心)两层。**单核心选项优先于全局**。

## 1. 性能三件套(先调这三个再谈画质)
| 设置 | 位置 | 建议 | 症状对应 |
|---|---|---|---|
| Hardware GPU / Shaders | 全局 `Driver` | 低端 Linux 掌机选 `gl`/`opegl`,别选 vulkan(多数便宜芯片驱动不稳) | 黑屏/崩溃 → 换 driver |
| Video > Synchronization > Refresh Rate / Bypass VSync | 全局 | 保持 VSync **开**;爆音时才动 | 撕裂可接受,掉帧不可接受 |
| Audio > Audio Buffer Length | 全局 | Mali-G31/V3s 机型从默认 64ms 提到 96–128ms | 声音咔哒/断续 |
| Core options > CPU Overclock | Quick Menu | **关**。PS1/N64 超频会引入随机 bug | 游戏行为怪异(速度、碰撞) |
| Frame Skip | 全局 | 只在明确要"更快但跳帧"时设 1 | 画面一顿一顿 |

## 2. 画面比例与裁剪(最容易看错的一项)
- `Crop Overscan`:SFC/PS1 建议**开**,否则四周有垃圾像素;GB/GBA 关掉(画面本来就精确)。
- `Aspect Ratio`:GB/GBC 用 `1:1`(方屏),SFC 用 `4:3` 或 `8:7`(SFC 输出实际是 8:7)。设错会让文字变形——很多人以为是模拟器问题。
- Integer Scaling:开。否则画面模糊或有边框抖动。

## 3. 路径与 BIOS(排错必查)
- `Settings > Directory > BIOS / System Files Directory`:记下实际路径,把 `03-BIOS库` 里的文件放这里(或复制)。
- `Save Load State` 与 `Save RAM` 目录分开:前者是即时存档(.state),后者是游戏自带记忆(.srm)。**换核心 .state 不通用**。

## 4. 输入
- `Settings > Input > RetroPad Binds`:先在这里把手柄映射设好,再去 `Menu Controls` 单独设菜单层,避免"游戏里能用、菜单里不能用"。
- `Analog to Digital Type`:掌机摇杆建议设为 `left analog`,玩需要十字键的游戏时摇杆当方向键。

## 5. 存档与即时存档
- `Save States Slot` 默认可见;开 `Auto Save State` 会被"上次退出状态"绑住,老手通常关掉手动管理。
- `Sram` 要开(`Settings > Saving > Save on Quit` 必须为开),否则关机丢游戏内进度。

## 6. 着色器(画质党最后再碰)
- crt-royale / mega-beam 在 PC 上没问题,在 Mali-G31 级别芯片上直接砍半帧率。
- 便宜机上要 CRT 感,用 `crt-switchres`(轻量)或 `scanline` 类,别用 mega-beam。

## 7. 网络与奖杯
- RetroAchievements:`Settings > Achievements` 登录后可给原生 ROM 加成就,是"自制/正版 ROM 都合法启用"的功能,强烈建议开——它让老游戏重新有目标感。

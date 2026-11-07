## OpenTyrian 掌机端口（教程示例）

- 引擎源码：https://github.com/opentyrian/opentyrian （GPL-2.0，COPYING 已随包）
- 游戏数据：Tyrian 2.1，原作者免费发布（4.75 MB zip，解出 106 个文件）
- 构建方式：`zig cc -target aarch64-linux-gnu`，动态链接系统 SDL2
- 运行时依赖：`libSDL2-2.0.so.0`（掌机系统自带）、`libm`、`libc`
- 二进制要求最高 `GLIBC_2.29`

### 相对上游的两处改动

1. 编译时补 `-include stdlib.h -include string.h`：clang 20 把隐式函数声明当错误，
   而 `src/animlib.c`、`src/editship.c` 漏了 `<stdlib.h>`。
2. 启动时加 `-j`（`--no-joystick`）：关掉引擎自带手柄轮询，按键统一走 gptokeyb。

### 打包结构

```
Tyrian.sh                      启动脚本（PortMaster 规范）
tyrian/opentyrian.aarch64      交叉编译产物，518,624 B
tyrian/data/                   Tyrian 2.1 数据，106 个文件
tyrian/tyrian.gptk             手柄→键盘映射
tyrian/conf/opentyrian/        配置/存档（fullscreen=0）
tyrian/port.json               端口元数据
tyrian/gameinfo.xml            EmulationStation 条目
tyrian/screenshot.png          640x400 实机截图（本机 Windows 版）
```

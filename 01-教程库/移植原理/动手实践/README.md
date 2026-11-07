# 动手实践：一个从零编出来、能插进掌机 SD 卡的端口

配套正文：`../02-交叉编译与打包_从一行C到一个能插卡玩的端口.md`。
这里放的是**那篇教程里每一个产物的原件**，不是截图、不是描述。

## 目录里有什么（实测字节数，2026-10-14 02:47）

| 文件 | 字节 | 说明 |
|---|---|---|
| `fbcheck.c` | 3,984 | 源码。只做三件事：读 `/dev/fb0`、读 `/dev/input/eventN`、往显存涂色 |
| `fbcheck.sh` | 2,321 | PortMaster 启动脚本，结构照 `orktes/max_arm64` 的 `Max Payne.sh`（2,225 B） |
| `port.json` | 804 | 端口元数据。顶层 5 键 + `attr` 12 键，对照 `PortMaster/pylibs/harbourmaster/info.py:18-40` |
| `make_package.py` | 1,951 | 校验 port.json + 压出 zip |
| `inspect_elf.py` | 1,098 | 读 ELF 头 / 程序头 / 二进制里的 `.so`、`GLIBC_x.y` 字符串 |
| `编译命令.txt` | 4,076 | 所有真实命令 + 5 条翻车报错原文 |
| `package/fbcheck.zip` | 864,160 | 成品包，sha256 前 32 位 `72871952cd953ad7c2532a3ecf83a91e` |
| `package/fbcheck/fbcheck_a64_musl_static` | 1,588,784 | aarch64 全静态，sha256 `a01295fa03dcdb4c8d636a136cfed7ff` |
| `package/fbcheck/fbcheck_armhf_musl_static` | 1,537,812 | armv7 全静态，sha256 `cb6ef9630510074cd9870baf6bca36d6` |

上表 9 行是本目录的**产物**；把这份 `README.md` 自己算进去，`find . -type f | wc -l` = **10 个文件**（03:0x 实测，含 `package/fbcheck/` 里那两个二进制）。

## 三个"我已经验过"的断言，你可以复验

1. **它是 64 位 ARM 的**：`py -3 -X utf8 inspect_elf.py` →
   `64位 AArch64 类型=EXEC 段数=8 动态链接=False`，段列表里没有 `PT_INTERP`、没有 `PT_DYNAMIC`。
   （脚本会自己 `cd` 到 `F:\开源掌机教程\_scratch\port_build` 去读原件，那儿还留着 glibc 动态版对照件 23,624 B。）
2. **它不依赖任何库**：同一脚本输出 `musl 静态 aarch64 → .so 串: [] / INTERP: [] / GLIBC 版: []`。
3. **包结构合规**：`py -3 -X utf8 make_package.py` →
   `顶层键齐全: True` / `attr 键齐全: True 缺失: []` / `items 里的 .sh: ['fbcheck.sh']`。

## 放到机器上跑（最短路径：SSH，绕开所有前端）

```bash
# 电脑和掌机连同一个 WiFi，掌机 IP 在固件的 Wi-Fi 设置里看
ssh root@<掌机IP>            # ArkOS/muOS 常见口令见机型篇
cd /tmp
# 从 SD 卡拷过去，或者 scp -r package/fbcheck root@<IP>:/tmp/
chmod +x fbcheck_a64_musl_static
./fbcheck_a64_musl_static            # 只看探测结果
./fbcheck_a64_musl_static --green    # 真把整屏涂绿
```

看到 `1024x768 … bpp=… 显存…B` 和 `/dev/input/eventN … 有方向键=是` 就算成功。
XF45V 正常是 1024×768；若打印 640×480，那是 R36S 那档的机器，不是这台。

要走 PortMaster/EmulationStation 前端：把 `fbcheck.sh` 放到 SD 卡 `roms/ports/`，
把 `package/fbcheck/` 整个目录放到 `roms/ports/fbcheck/`，重启前端。
日志在 `roms/ports/fbcheck/log.txt`——**掌机端口出问题只有这里能看，别盯着屏幕**。

## 边界

这个包 100% 是我自己的代码，不含任何商业游戏内容，可以随便转。
**但同一套打包流程如果装的是别人的游戏（.so / APK / OBB / ROM），性质立刻变了**：
那种只能收源码，不能分发成品。判据与本库口径见 `../02-…打包….md` 第十节。

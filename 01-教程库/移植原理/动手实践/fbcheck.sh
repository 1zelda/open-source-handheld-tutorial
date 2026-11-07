#!/bin/bash
#
# fbcheck.sh -- PortMaster 端口的标准启动脚本（最小可用版）
# 结构照抄 orktes/max_arm64 的 "Max Payne.sh"，变量名全部来自本机
# PortMaster-GUI/PortMaster/control.txt 与 funcs.txt 的真实定义。
#
# 文件名必须出现在 port.json 的 items[] 里，且以 .sh 结尾：
# harbour.py 就是按 ".sh" 后缀认哪个是启动脚本的（port_info 检查处
# 见到 item.casefold().endswith('.sh')）。

# ① 找到 PortMaster 本体。四种固件放的位置不一样，四个都得试。
#    （control.txt:32-40 用的是同一套判断顺序。）
if [ -d "/PortMaster/" ]; then
    controlfolder="/PortMaster"
elif [ -d "/opt/system/Tools/PortMaster/" ]; then
    controlfolder="/opt/system/Tools/PortMaster"
elif [ -d "/opt/tools/PortMaster/" ]; then
    controlfolder="/opt/tools/PortMaster"
else
    controlfolder="/$directory/ports/PortMaster"
fi

if [ ! -d "$controlfolder" ]; then
    echo "找不到 PortMaster（$controlfolder），退出"
    exit 1
fi

# ② 一句话拿到全部公共变量。control.txt 会自己再 source
#    device_info.txt（决定 DEVICE_ARCH / CAPS）和 funcs.txt（决定
#    pm_finish 等收尾函数），所以端口脚本里不用重复实现。
source $controlfolder/control.txt
get_controls

# ③ 本端口的家目录。PortMaster 把端口装在 /$directory/ports/<名字>/。
GAMEDIR="/$directory/ports/fbcheck"
cd "$GAMEDIR" || exit 1

# ④ 日志同时落到 log.txt：真机出问题只能靠它。
: >"$GAMEDIR/log.txt"
exec > >(tee -a "$GAMEDIR/log.txt") 2>&1

echo "架构=$DEVICE_ARCH  设备GUID=$DEVICE  端口目录=$GAMEDIR"

# ⑤ 按架构挑二进制。DEVICE_ARCH 由 device_info.txt:178-182 从 uname -m 推出来，
#    只有 aarch64 / armhf / x86_64 / x86 四种取值。
BIN="./fbcheck_armhf_musl_static"
if [ "$DEVICE_ARCH" == "aarch64" ]; then
    BIN="./fbcheck_a64_musl_static"
fi
chmod +x "$BIN" 2>/dev/null

# ⑥ 手柄 → 键盘。本程序自己读 /dev/input，所以 gptokeyb 对它其实是多余的，
#    但 99% 的真实端口都要：那些老程序只认键盘，不认游戏手柄。
$GPTOKEYB "fbcheck" &
GPID=$!

"$BIN" "$@"
RET=$?

$ESUDO kill -9 $GPID 2>/dev/null
# pm_finish（funcs.txt:146）负责杀掉 gptokeyb、清屏、恢复 oga_events
pm_finish
exit $RET

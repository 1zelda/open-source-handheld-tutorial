#!/bin/bash

XDG_DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}

if [ -d "/opt/system/Tools/PortMaster/" ]; then
  controlfolder="/opt/system/Tools/PortMaster"
elif [ -d "/opt/tools/PortMaster/" ]; then
  controlfolder="/opt/tools/PortMaster"
elif [ -d "$XDG_DATA_HOME/PortMaster/" ]; then
  controlfolder="$XDG_DATA_HOME/PortMaster"
else
  controlfolder="/roms/ports/PortMaster"
fi

source $controlfolder/control.txt
[ -f "${controlfolder}/mod_${CFW_NAME}.txt" ] && source "${controlfolder}/mod_${CFW_NAME}.txt"
get_controls

GAMEDIR="/$directory/ports/cnc"
GAMESUB="$GAMEDIR/cnc/td"

> "$GAMEDIR/log.txt" && exec > >(tee "$GAMEDIR/log.txt") 2>&1

export DEVICE_ARCH="${DEVICE_ARCH:-aarch64}"
# OpenAL 随包带（CFW 不一定有），SDL2 用 CFW 自带的
export LD_LIBRARY_PATH="$GAMEDIR/cnc/libs.${DEVICE_ARCH}:$LD_LIBRARY_PATH"

cd "$GAMESUB"

if [ ! -f "$GAMESUB/CONQUER.MIX" ]; then
  echo "没有找到命令与征服（泰伯利亚黎明）的游戏数据 CONQUER.MIX。"
  echo "No C&C data found (CONQUER.MIX is missing)."
  echo "把正版 C&C Gold 或 2007 年免费版 GDI95 的 *.MIX 放进 ports/cnc/cnc/td/ 再启动。"
  echo "Copy the *.MIX files from C&C Gold (or the 2007 freeware GDI95 release) into ports/cnc/cnc/td/."
  sleep 6
  exit 1
fi

# CONQUER.INI 就放在二进制旁边 => 引擎进"便携模式"，配置和存档都写在这个目录里
if [ ! -f "$GAMESUB/CONQUER.INI" ]; then
  cat > "$GAMESUB/CONQUER.INI" <<'EOF'
[Mouse]
ControllerEnabled=yes

[Video]
Windowed=false
; 640x400 铺满 640x480 掌机屏，跟原版 CRT 的 4:3 一致
Boxing=false
FrameLimit=60
EOF
fi

export SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"

$ESUDO chmod +x "./vanillatd.${DEVICE_ARCH}"

pm_platform_helper "$GAMESUB/vanillatd.${DEVICE_ARCH}"

"./vanillatd.${DEVICE_ARCH}"

pm_finish
printf "\033c" >> /dev/tty1

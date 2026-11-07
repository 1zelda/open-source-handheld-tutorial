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
GAMESUB="$GAMEDIR/cnc/ra"

> "$GAMEDIR/log.txt" && exec > >(tee "$GAMEDIR/log.txt") 2>&1

export DEVICE_ARCH="${DEVICE_ARCH:-aarch64}"
export LD_LIBRARY_PATH="$GAMEDIR/cnc/libs.${DEVICE_ARCH}:$LD_LIBRARY_PATH"

cd "$GAMESUB"

if [ ! -f "$GAMESUB/REDALERT.MIX" ]; then
  echo "没有找到红色警戒（Red Alert 1）的游戏数据 REDALERT.MIX。"
  echo "No Red Alert data found (REDALERT.MIX is missing)."
  echo "把正版 Red Alert 或 2008 年免费版的 *.MIX 放进 ports/cnc/cnc/ra/ 再启动。"
  echo "Copy the *.MIX files from Red Alert (or the 2008 freeware release) into ports/cnc/cnc/ra/."
  sleep 6
  exit 1
fi

# REDALERT.INI 放在二进制旁边 => 便携模式，配置和存档留在这个目录
if [ ! -f "$GAMESUB/REDALERT.INI" ]; then
  cat > "$GAMESUB/REDALERT.INI" <<'EOF'
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

$ESUDO chmod +x "./vanillara.${DEVICE_ARCH}"

pm_platform_helper "$GAMESUB/vanillara.${DEVICE_ARCH}"

"./vanillara.${DEVICE_ARCH}"

pm_finish
printf "\033c" >> /dev/tty1

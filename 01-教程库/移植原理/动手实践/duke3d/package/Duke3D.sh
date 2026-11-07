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
GAMEDIR="/$directory/ports/duke3d"
> "$GAMEDIR/log.txt" && exec > >(tee "$GAMEDIR/log.txt") 2>&1
export DEVICE_ARCH="${DEVICE_ARCH:-aarch64}"
cd "$GAMEDIR"
if [ ! -f "$GAMEDIR/DUKE3D.GRP" ]; then
  echo "缺少 DUKE3D.GRP：请把你的正版或免费分享版 DUKE3D.GRP 放到 ports/duke3d/ 目录。"
  echo "Missing DUKE3D.GRP: copy your own copy into ports/duke3d/."
  sleep 6
  exit 1
fi
export SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"
$ESUDO chmod +x "./eduke32"
pm_platform_helper "./eduke32"
"./eduke32"
pm_finish
printf "\033c" >> /dev/tty1

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

GAMEDIR="/$directory/ports/wolf3d"

> "$GAMEDIR/log.txt" && exec > >(tee "$GAMEDIR/log.txt") 2>&1

export DEVICE_ARCH="${DEVICE_ARCH:-aarch64}"
export LD_LIBRARY_PATH="$GAMEDIR/libs.${DEVICE_ARCH}:$LD_LIBRARY_PATH"

cd "$GAMEDIR"

# 引擎本体不含游戏数据：分享版 WL1 / 正式版 WL6 / 资料片 SOD 由玩家自备
if ! ls "$GAMEDIR"/*.WL1 "$GAMEDIR"/*.WL6 "$GAMEDIR"/*.SOD "$GAMEDIR"/*.pk3 >/dev/null 2>&1; then
  echo "没有找到 Wolfenstein 3D 数据文件（*.WL1 / *.WL6 / *.SOD）。"
  echo "把分享版或正式版的游戏数据放进 ports/wolf3d/ 再启动。"
  echo "Put your Wolfenstein 3D data files (*.WL1 / *.WL6 / *.SOD) into ports/wolf3d/ first."
  sleep 6
  exit 1
fi

mkdir -p "$GAMEDIR/saves"

export SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"

$ESUDO chmod +x "./ecwolf.${DEVICE_ARCH}"

# 手柄走 gptk 的键盘映射，避免各家 CFW 的 SDL 手柄数据库差异
$GPTOKEYB "ecwolf.${DEVICE_ARCH}" -c "$GAMEDIR/ecwolf.gptk" &
pm_platform_helper "$GAMEDIR/ecwolf.${DEVICE_ARCH}"

"./ecwolf.${DEVICE_ARCH}" \
  --config "$GAMEDIR/ecwolf.cfg" \
  --savedir "$GAMEDIR/saves" \
  --fullscreen \
  --res 640 480 \
  --joystick -1

pm_finish
printf "\033c" >> /dev/tty1

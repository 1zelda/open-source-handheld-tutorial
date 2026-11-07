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

GAMEDIR="/$directory/ports/quake2"

> "$GAMEDIR/log.txt" && exec > >(tee "$GAMEDIR/log.txt") 2>&1

export DEVICE_ARCH="${DEVICE_ARCH:-aarch64}"
export LD_LIBRARY_PATH="$GAMEDIR/libs.${DEVICE_ARCH}:$LD_LIBRARY_PATH"

cd "$GAMEDIR"

if [ ! -f "$GAMEDIR/baseq2/pak0.pak" ]; then
  echo "把原版 Quake II 的 baseq2/pak*.pak 放进 ports/quake2/baseq2/ 再启动。"
  echo "Put your Quake II baseq2/pak*.pak files into ports/quake2/baseq2/ first."
  sleep 6
  exit 1
fi

# 渲染器默认 gles1（Mali 原生 GLES1，硬件加速）；改 QUAKE2_RENDERER=gl1 / soft 可切换。
RENDERER="${QUAKE2_RENDERER:-gles1}"

$ESUDO chmod +x "./quake2.${DEVICE_ARCH}"

$GPTOKEYB "quake2.${DEVICE_ARCH}" -c "$GAMEDIR/quake2.gptk" &
pm_platform_helper "$GAMEDIR/quake2.${DEVICE_ARCH}"

SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig" \
  "./quake2.${DEVICE_ARCH}" -datadir "$GAMEDIR" -portable \
  +set vid_renderer "$RENDERER" +set vid_fullscreen 1 +set in_initjoy 1

pm_finish

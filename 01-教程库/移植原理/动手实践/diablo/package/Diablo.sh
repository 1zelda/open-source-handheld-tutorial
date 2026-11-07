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

GAMEDIR="/$directory/ports/diablo"

> "$GAMEDIR/log.txt" && exec > >(tee "$GAMEDIR/log.txt") 2>&1

export DEVICE_ARCH="${DEVICE_ARCH:-aarch64}"
export LD_LIBRARY_PATH="$GAMEDIR/libs.${DEVICE_ARCH}:$LD_LIBRARY_PATH"

cd "$GAMEDIR"

# 引擎与界面资源在包内，游戏数据必须玩家自备：
#   正式版 -> DIABDAT.MPQ（GOG 版可改名）    分享版 -> spawn.mpq（免费）
if ! ls "$GAMEDIR"/assets >/dev/null 2>&1; then
  echo "包不完整：assets/ 目录不见了，请重新解压 Diablo.zip。"
  echo "Package incomplete: assets/ is missing, re-extract Diablo.zip."
  sleep 6
  exit 1
fi
if [ -z "$(find "$GAMEDIR" -maxdepth 1 -type f -iname '*.mpq' -print -quit)" ]; then
  echo "没有找到 Diablo 数据文件（DIABDAT.MPQ 或 spawn.mpq）。"
  echo "把正版 DIABDAT.MPQ 或免费分享版 spawn.mpq 放进 ports/diablo/ 再启动。"
  echo "Put DIABDAT.MPQ (retail) or spawn.mpq (free shareware) into ports/diablo/ first."
  sleep 6
  exit 1
fi

mkdir -p "$GAMEDIR/saves"

export SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"

$ESUDO chmod +x "./devilutionx.${DEVICE_ARCH}"

# DevilutionX 自带 SDL2 手柄支持（左右摇杆 + ABXY），不用 gptokeyb 抢设备
pm_platform_helper "$GAMEDIR/devilutionx.${DEVICE_ARCH}"

"./devilutionx.${DEVICE_ARCH}" \
  --data-dir "$GAMEDIR" \
  --save-dir "$GAMEDIR/saves" \
  --config-dir "$GAMEDIR"

pm_finish
printf "\033c" >> /dev/tty1

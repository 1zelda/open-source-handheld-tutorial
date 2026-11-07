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

GAMEDIR="/$directory/ports/openttd"
GAMESUB="$GAMEDIR/openttd"
GAMEBIN="openttd.${DEVICE_ARCH:-aarch64}"

> "$GAMEDIR/log.txt" && exec > >(tee "$GAMEDIR/log.txt") 2>&1

cd "$GAMESUB"

# 便携模式：配置和存档写进包目录（$HOME/.openttd），不污染 CFW 的家目录
export HOME="$GAMESUB"
export SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"

# 第一次启动写一份最小配置：全屏 + 640x480，跟掌机屏幕一致
if [ ! -f "$GAMESUB/.openttd/openttd.cfg" ]; then
  mkdir -p "$GAMESUB/.openttd"
  cat > "$GAMESUB/.openttd/openttd.cfg" <<'EOF'
[misc]
fullscreen = true
resolution = 640,480
EOF
fi

# 手柄 -> 鼠标：OpenTTD 没有手柄支持，用 PortMaster 自带的 gptokeyb 把左摇杆当鼠标
$ESUDO chmod +x "$GAMESUB/$GAMEBIN"
$GPTOKEYB "$GAMEBIN" -c "$GAMESUB/openttd.gptk" &
GPID=$!

pm_platform_helper "$GAMESUB/$GAMEBIN"
"./$GAMEBIN" -v sdl -s sdl

kill -9 $GPID 2>/dev/null
pm_finish
printf "\033c" >> /dev/tty1

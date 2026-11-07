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

GAMEDIR="/$directory/ports/quake3"

> "$GAMEDIR/log.txt" && exec > >(tee "$GAMEDIR/log.txt") 2>&1

export DEVICE_ARCH="${DEVICE_ARCH:-aarch64}"

cd "$GAMEDIR"

if [ ! -f "$GAMEDIR/baseq3/pak0.pk3" ]; then
  echo "把原版 Quake III Arena 的 baseq3/pak*.pk3 放进 ports/quake3/baseq3/ 再启动。"
  echo "Put your Quake III Arena baseq3/pak*.pk3 files into ports/quake3/baseq3/ first."
  sleep 6
  exit 1
fi

# 有些 CFW 没有桌面 GL，只能走 gl4es：PortMaster 的 libgl_<CFW>.txt 会把 LIBGL_FB 设为非空
if [ -f "${controlfolder}/libgl_${CFW_NAME}.txt" ]; then
  source "${controlfolder}/libgl_${CFW_NAME}.txt"
else
  source "${controlfolder}/libgl_default.txt"
fi
if [ "$LIBGL_FB" != "" ] && [ -f "$GAMEDIR/gl4es.${DEVICE_ARCH}/libGL.so.1" ]; then
  # 只在真需要 gl4es 时才把它的目录加进搜索路径，否则会把系统的 libGL 也顶掉
  export LD_LIBRARY_PATH="$GAMEDIR/gl4es.${DEVICE_ARCH}:$LD_LIBRARY_PATH"
  export SDL_VIDEO_GL_DRIVER="$GAMEDIR/gl4es.${DEVICE_ARCH}/libGL.so.1"
  export SDL_VIDEO_EGL_DRIVER="$GAMEDIR/gl4es.${DEVICE_ARCH}/libEGL.so.1"
  echo "Using gl4es for OpenGL: $LIBGL_FB"
fi

export SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"

$ESUDO chmod +x "./quake3.${DEVICE_ARCH}"

$GPTOKEYB "quake3.${DEVICE_ARCH}" -c "$GAMEDIR/quake3.gptk" &
pm_platform_helper "$GAMEDIR/quake3.${DEVICE_ARCH}"

# ioquake3 的渲染器是运行时 dlopen 的 renderer_opengl1.so，默认 cvar 是 opengl2，这里必须指定
"./quake3.${DEVICE_ARCH}" \
  +set fs_homepath "$GAMEDIR" \
  +set cl_renderer opengl1 \
  +set r_mode -1 +set r_customwidth 640 +set r_customheight 480 \
  +set r_fullscreen 1 +set in_joystick 0

pm_finish
printf "\033c" >> /dev/tty1

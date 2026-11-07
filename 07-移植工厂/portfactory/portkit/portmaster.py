from __future__ import annotations

import json
import os
import re
import shutil
import stat
import zipfile
from pathlib import Path

# 全项目统一的打包时间戳：同一份输入两次打包必须字节相同
PACK_EPOCH = (2026, 10, 29, 0, 0, 0)

LAUNCHER = """\
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

GAMEDIR="/$directory/ports/@PORT_DIR@"
@GAMESUB@
> "$GAMEDIR/log.txt" && exec > >(tee "$GAMEDIR/log.txt") 2>&1

export DEVICE_ARCH="${DEVICE_ARCH:-aarch64}"
@LIBS@
cd "@CD_DIR@"
@MKDIRS@
@DATA_CHECK@
@FIRST_RUN@
@ENV@

export SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"

$ESUDO chmod +x "@BIN@"

pm_platform_helper "@BIN@"

"@BIN@"

pm_finish
printf "\\033c" >> /dev/tty1
"""


def _shell_quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$") + '"'


def render_launcher(cfg: dict) -> str:
    port_dir = cfg["port_dir"]
    game_sub = cfg.get("game_sub")
    lines_sub = f'GAMESUB="$GAMEDIR/{game_sub}"' if game_sub else ""
    cd_dir = "$GAMESUB" if game_sub else "$GAMEDIR"
    libs = cfg.get("libs", [])
    lib_line = ""
    if libs:
        joined = ":".join(f'"$GAMEDIR/{lib}"' for lib in libs)
        lib_line = f'export LD_LIBRARY_PATH={joined}:$LD_LIBRARY_PATH'
    mkdirs = "\n".join(f'mkdir -p "$GAMEDIR/{d}"' for d in cfg.get("mkdirs", []))
    data_check = ""
    required = cfg.get("data_required", [])
    if required:
        checks = " || ".join(f'[ ! -f "$GAMEDIR/{f}" ]' for f in required)
        echo = cfg.get("data_message", "缺少游戏数据文件。").split("\n")
        echo_en = cfg.get("data_message_en", "").split("\n") if cfg.get("data_message_en") else []
        body = "\n".join(f"  echo {_shell_quote(line)}" for line in echo + echo_en if line)
        data_check = (f"if {checks}; then\n{body}\n  sleep 6\n  exit 1\nfi")
    first_run = ""
    for rel, content in (cfg.get("first_run_files") or {}).items():
        first_run += (f'if [ ! -f "$GAMEDIR/{rel}" ]; then\n'
                      f"  cat > \"$GAMEDIR/{rel}\" <<'EOF'\n{content}\nEOF\nfi\n")
    env = "\n".join(f"export {k}={v}" for k, v in (cfg.get("env") or {}).items())
    text = (LAUNCHER
            .replace("@PORT_DIR@", port_dir)
            .replace("@GAMESUB@", lines_sub)
            .replace("@LIBS@", lib_line)
            .replace("@CD_DIR@", cd_dir)
            .replace("@MKDIRS@", mkdirs)
            .replace("@DATA_CHECK@", data_check)
            .replace("@FIRST_RUN@", first_run)
            .replace("@ENV@", env)
            .replace("@BIN@", cfg.get("binary", "./game")))
    return "\n".join(line for line in text.splitlines() if line.strip() != "") + "\n"


def render_port_json(cfg: dict, items: list[str]) -> dict:
    attr = cfg["attr"]
    required = {"title", "desc", "inst", "genres", "porter", "image", "rtr",
                "exp", "runtime", "min_glibc", "reqs", "arch"}
    missing = sorted(required - set(attr))
    if missing:
        raise ValueError(f"port.json attr 缺字段：{missing}")
    return {
        "version": 4,
        "name": cfg["zip_name"],
        "items": items,
        "items_opt": None,
        "attr": attr,
    }


_XML_ESCAPE = re.compile(r"[&<>]")


def _xml(text: str) -> str:
    return _XML_ESCAPE.sub(lambda m: {"&": "&amp;", "<": "&lt;", ">": "&gt;"}[m.group(0)], text)


def render_gameinfo(cfg: dict, entries: list[dict]) -> str:
    rows = []
    for entry in entries:
        rows.append("\t<game>")
        rows.append(f"\t\t<path>./{_xml(entry['script'])}</path>")
        rows.append(f"\t\t<name>{_xml(entry['name'])}</name>")
        rows.append(f"\t\t<desc>{_xml(entry.get('desc', ''))}</desc>")
        rows.append("\t\t<image>./screenshot.png</image>")
        if entry.get("genre"):
            rows.append(f"\t\t<genre>{_xml(entry['genre'])}</genre>")
        for key in ("developer", "publisher"):
            if entry.get(key):
                rows.append(f"\t\t<{key}>{_xml(entry[key])}</{key}>")
        if entry.get("releasedate"):
            rows.append(f"\t\t<releasedate>{entry['releasedate']}</releasedate>")
        rows.append("\t</game>")
    return '<?xml version="1.0"?>\n<gameList>\n' + "\n".join(rows) + "\n</gameList>\n"


def _add(zf: zipfile.ZipFile, name: str, data: bytes, mode: int) -> None:
    info = zipfile.ZipInfo(name, date_time=PACK_EPOCH)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | mode) << 16
    info.create_system = 3
    zf.writestr(info, data)


def build_zip(staging: Path, output: Path) -> dict:
    """确定性打包：条目排序、固定时间戳、显式权限。"""
    staging = Path(staging)
    # 按归档名排序（不是按宿主路径排序）：Windows 的路径比较不分大小写，
    # 用 Path 排出来的顺序和 zip 里看到的条目顺序会不一致，自检就会判"未排序"
    entries = sorted(((p.relative_to(staging).as_posix(), p)
                      for p in staging.rglob("*") if p.is_file()), key=lambda e: e[0])
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel, path in entries:
            if rel.lower().endswith(".sh"):
                mode = 0o755
            elif os.access(path, os.X_OK) and path.suffix in ("", ".aarch64", ".nro"):
                mode = 0o755
            else:
                mode = 0o644
            _add(zf, rel, path.read_bytes(), mode)
    tmp.replace(output)
    import hashlib
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return {"path": str(output), "size": output.stat().st_size, "sha256": digest,
            "files": len(entries)}


def stage_launcher(staging: Path, cfg: dict) -> Path:
    script = staging / cfg["launcher_file"]
    script.write_text(render_launcher(cfg), encoding="utf-8", newline="\n")
    try:
        script.chmod(0o755)
    except OSError:
        pass
    return script


def copy_member(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)

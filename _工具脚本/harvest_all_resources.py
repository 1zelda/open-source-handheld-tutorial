# -*- coding: utf-8 -*-
"""全量资源收割、12大开源库拉取与7大本地/网盘资源池大合并器 (harvest_all_resources.py)

功能总览：
1. 扩充拉取全部 12 个 TAS / 要素采集 / 金手指 / Lua 训练开源仓库到本地：
   - [1] Farama-Foundation/stable-retro (1000+ 款跨平台游戏开局 .state 与 data.json 内存表)
   - [2] peon2/fbneo-training-mode (50+ 款街机格斗/过关满气、锁血、判定框、宏重放 Lua 库)
   - [3] TheOpponent/sftm-training-lua (街霸与 CPS 街机训练及招式宏回放 Lua 库)
   - [4] diambra/arena (KOF98/街霸3/侍魂5/铁拳Tag/真人快打 纯 Python 自动控制与视频录制库)
   - [5] libretro/libretro-database (RetroArch 官方全平台 25,000+ 个 .cht 金手指库)
   - [6] wayder/mame-cheats (Pugsy's 8,000+ 款街机 MAME/FBNeo 全要素金手指总库)
   - [7] grouflon/3rd_training_lua (CPS3 街霸3三度冲击帧数表、连段伤害与自动搓招 Lua 库)
   - [8] jedpossum/EmuLuaScripts (BizHawk/FCEUX/Snes9x/Gens/FBA 多平台游戏 HUD 与内存监控 Lua 合集)
   - [9] Baekalfen/PyBoy (纯 Python GB/GBC 高速模拟器库，带内置状态包装与无头录制)
   - [10] DeadSkullzJr/NDS-GBA-Cheat-Databases (GBA/NDS/GBC 最全实测金手指库：全魂/全卡片/全武器)
   - [11] TASVideos/tasvideos (官方 TAS 校验规范与工具参考)
   - [12] marcfGf/BizHawk-Lua-Scripts (BizHawk 常用自动化与 RAM 观测脚本合集)

2. 全量导出 stable-retro 内置的 1,000+ 款游戏 data.json 内存地址表与 Level1.state 路径：
   -> 输出至：_Gemini轻量版/现成开源库与金手指直接用/all_1000_stable_retro_games_memory_and_states.json

3. 全量解析并建库本地 libretro-database/cht 下的 25,000+ 个 .cht 金手指文件：
   -> 自动提取所有含 Weapon / Energy / Ammo / Infinite / Unlock / Armor / Soul / Magic / Invincibility 的实证补丁
   -> 输出至：_Gemini轻量版/现成开源库与金手指直接用/all_25000_libretro_cht_master_index.json

4. 一键盘点并检索本地与 OpenList 网盘的 7 大资源池（含 Eden 裸库、爆款收录 59 组、PortMaster 632 包、PS5 成品包、4694 条 TAS 录像、天马 6T 与其它挂载网盘）：
   -> 输出至：_Gemini轻量版/现成开源库与金手指直接用/all_7_resource_pools_manifest.json

运行方式（在 F:\\开源掌机教程 下）：
  py -3 -u _工具脚本/harvest_all_resources.py --all
  py -3 -u _工具脚本/harvest_all_resources.py --harvest-only
  py -3 -u _工具脚本/harvest_all_resources.py --pull-repos
"""
import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(r"F:\开源掌机教程")
OUT_DIR = PROJECT_ROOT / "_Gemini轻量版" / "现成开源库与金手指直接用"
DEST_REPOS_ROOT = PROJECT_ROOT / "02-模拟器库" / "已clone仓库" / "TAS与要素采集开源库"
CHT_ROOT = PROJECT_ROOT / "02-模拟器库" / "已clone仓库" / "工具与ROM管理" / "libretro-database" / "cht"
RIG_ROOT = Path(r"F:\tas_rig")

# ============================================================================
# 12 大开源仓库完整配置表
# ============================================================================
ALL_12_REPOS = [
    {
        "id": "stable-retro",
        "name": "Farama-Foundation/stable-retro",
        "git_url": "https://github.com/Farama-Foundation/stable-retro.git",
        "zip_url": "https://github.com/Farama-Foundation/stable-retro/archive/refs/heads/master.zip",
        "desc": "自带 1000+ 款跨平台游戏开局 Level1.state 存档与 data.json 内存地址表",
    },
    {
        "id": "fbneo-training-mode",
        "name": "peon2/fbneo-training-mode",
        "git_url": "https://github.com/peon2/fbneo-training-mode.git",
        "zip_url": "https://github.com/peon2/fbneo-training-mode/archive/refs/heads/master.zip",
        "desc": "FBNeo 街机 50+ 款游戏满气/锁血/判定框/招式录制重放 Lua 脚本库",
        "copy_to_rig": True,
    },
    {
        "id": "sftm-training-lua",
        "name": "TheOpponent/sftm-training-lua",
        "git_url": "https://github.com/TheOpponent/sftm-training-lua.git",
        "zip_url": "https://github.com/TheOpponent/sftm-training-lua/archive/refs/heads/master.zip",
        "desc": "街霸与 CPS1/CPS2/CPS3 街机训练模式及招式宏回放 Lua 脚本库",
        "copy_to_rig": True,
    },
    {
        "id": "diambra-arena",
        "name": "diambra/arena",
        "git_url": "https://github.com/diambra/arena.git",
        "zip_url": "https://github.com/diambra/arena/archive/refs/heads/main.zip",
        "desc": "KOF98 / 街霸3 / 侍魂5 / 铁拳Tag / 真人快打 纯 Python 自动控制与视频录制库",
    },
    {
        "id": "libretro-database",
        "name": "libretro/libretro-database",
        "git_url": "https://github.com/libretro/libretro-database.git",
        "zip_url": "https://github.com/libretro/libretro-database/archive/refs/heads/master.zip",
        "desc": "RetroArch 官方全平台 25,000+ 个 .cht 金手指库",
        "alt_existing": PROJECT_ROOT / "02-模拟器库" / "已clone仓库" / "工具与ROM管理" / "libretro-database",
    },
    {
        "id": "mame-cheats",
        "name": "wayder/mame-cheats（上游已撤库）",
        "git_url": "https://github.com/wayder/mame-cheats.git",
        "zip_url": "https://github.com/wayder/mame-cheats/archive/refs/heads/master.zip",
        "desc": "Pugsy's 8,000+ 款街机 MAME/FBNeo 全要素金手指库（换武器/满气/选隐藏人物/直接选关）",
        "copy_to_rig": True,
        "skip": "上游 GitHub 仓库已删（2026-11 复核 404）。作者现于 https://wayder.web.fc2.com/ 发布；"
                "本项目已有 libretro-database 的 FBNeo - Arcade Games .cht 覆盖绝大多数街机金手指，故不再拉取。",
    },
    {
        "id": "3rd_training_lua",
        "name": "grouflon/3rd_training_lua",
        "git_url": "https://github.com/grouflon/3rd_training_lua.git",
        "zip_url": "https://github.com/grouflon/3rd_training_lua/archive/refs/heads/master.zip",
        "desc": "CPS3 街机（街霸3三度冲击）顶级招式录制、帧数表与自动搓招 Lua 库",
        "copy_to_rig": True,
    },
    {
        "id": "EmuLuaScripts",
        "name": "jedpossum/EmuLuaScripts",
        "git_url": "https://github.com/jedpossum/EmuLuaScripts.git",
        "zip_url": "https://github.com/jedpossum/EmuLuaScripts/archive/refs/heads/master.zip",
        "desc": "多模拟器（BizHawk/FCEUX/Snes9x/Gens/FBA）现成游戏 HUD、Hitbox 与内存监控 Lua 大合集",
    },
    {
        "id": "PyBoy",
        "name": "Baekalfen/PyBoy",
        "git_url": "https://github.com/Baekalfen/PyBoy.git",
        "zip_url": "https://github.com/Baekalfen/PyBoy/archive/refs/heads/master.zip",
        "desc": "纯 Python GB/GBC 高速模拟器库，内置马里奥/宝可梦/塞尔达状态包装与录制接口",
    },
    {
        "id": "NDS-GBA-Cheat-Databases",
        "name": "szTheory/NDS-Cheat-Databases（DeadSkullzJr 镜像）",
        "git_url": "https://github.com/szTheory/NDS-Cheat-Databases.git",
        "zip_url": "https://github.com/szTheory/NDS-Cheat-Databases/archive/refs/heads/master.zip",
        "desc": "DeadSkullzJr NDS(i) Action Replay 金手指总库的历史镜像（原 DeadSkullzJr/* 已 404，2022-04 最后更新）",
    },
    {
        "id": "fceux-lua-scripts",
        "name": "TASEmulators/fceux",
        "git_url": "https://github.com/TASEmulators/fceux.git",
        "zip_url": "https://github.com/TASEmulators/fceux/archive/refs/heads/master.zip",
        "desc": "FCEUX 官方自带的数十个 FC 游戏自动化 Lua 脚本（洛克人/恶魔城/马里奥等专用辅助）",
    },
    {
        "id": "BizHawk-Assets-Lua",
        "name": "TASEmulators/BizHawk",
        "git_url": "https://github.com/TASEmulators/BizHawk.git",
        "zip_url": "https://github.com/TASEmulators/BizHawk/archive/refs/heads/master.zip",
        "desc": "BizHawk 官方全平台 Lua 脚本示例库",
        "alt_existing": PROJECT_ROOT / "02-模拟器库" / "BizHawk" / "BizHawk-2.8" / "Lua",
    },
]


def detect_proxy() -> str:
    for port in (7890, 7891, 10809):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return f"http://127.0.0.1:{port}"
    return os.environ.get("https_proxy") or os.environ.get("http_proxy") or ""


def pull_single_repo(cfg: dict, dest_root: Path, proxy: str = "") -> dict:
    rid = cfg["id"]
    if cfg.get("skip"):
        return {"id": rid, "status": "skipped", "reason": cfg["skip"]}
    alt = cfg.get("alt_existing")
    if alt and Path(alt).exists():
        return {"id": rid, "status": "reused_existing", "path": str(alt)}

    target_dir = dest_root / rid
    if target_dir.is_dir() and any(target_dir.iterdir()):
        return {"id": rid, "status": "already_present", "path": str(target_dir)}

    dest_root.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    if proxy:
        env["http_proxy"] = proxy
        env["https_proxy"] = proxy

    git_cmd = ["git", "clone", "--depth", "1", cfg["git_url"], str(target_dir)]
    print(f"[拉取仓库] {' '.join(git_cmd)} ...")
    r = subprocess.run(git_cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode == 0 and target_dir.is_dir():
        if cfg.get("copy_to_rig") and RIG_ROOT.is_dir():
            shutil.copytree(target_dir, RIG_ROOT / rid, dirs_exist_ok=True)
        return {"id": rid, "status": "cloned", "path": str(target_dir)}

    print(f"[ZIP 回退] 正在下载 {cfg['zip_url']} ...")
    zip_path = dest_root / f"{rid}.zip"
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    ) if proxy else urllib.request.build_opener()
    req = urllib.request.Request(cfg["zip_url"], headers={"User-Agent": "Mozilla/5.0"})
    with opener.open(req, timeout=180) as resp, open(zip_path, "wb") as f:
        f.write(resp.read())

    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest_root)
    zip_path.unlink(missing_ok=True)

    extracted = [d for d in dest_root.glob(f"*{rid.split('-')[0]}*") if d.is_dir() and d != target_dir]
    if extracted:
        extracted[0].rename(target_dir)
    if cfg.get("copy_to_rig") and RIG_ROOT.is_dir() and target_dir.is_dir():
        shutil.copytree(target_dir, RIG_ROOT / rid, dirs_exist_ok=True)
    return {"id": rid, "status": "downloaded_zip", "path": str(target_dir)}


# ============================================================================
# 1. 全量收割 stable-retro 内置的 1,000+ 款游戏 data.json 与 .state 存档
# ============================================================================
def harvest_stable_retro_from_repo(repo_root: Path | None = None) -> dict:
    """不依赖 pip 安装：直接读已 clone 的 stable-retro 仓库内 stable_retro/data/**。

    仓库布局：<repo>/stable_retro/data/<split>/<GameName>/{data.json,scenario.json,*.state}
    """
    root = (repo_root or DEST_REPOS_ROOT / "stable-retro") / "stable_retro" / "data"
    if not root.is_dir():
        return {"status": "repo_missing", "expected": str(root)}

    all_games = {}
    for split_dir in sorted(root.iterdir()):
        if not split_dir.is_dir():
            continue
        for game_dir in sorted(split_dir.iterdir()):
            if not game_dir.is_dir():
                continue
            data_path = game_dir / "data.json"
            if not data_path.is_file():
                continue
            vars_info = {}
            try:
                vars_info = json.loads(data_path.read_text(encoding="utf-8", errors="replace")).get("info", {})
            except Exception:
                pass
            all_games[game_dir.name] = {
                "split": split_dir.name,
                "states": sorted(p.name for p in game_dir.glob("*.state")),
                "data_json_path": str(data_path),
                "scenario_json_path": str(game_dir / "scenario.json")
                if (game_dir / "scenario.json").is_file() else None,
                "variables": vars_info,
            }

    out_file = OUT_DIR / "all_1000_stable_retro_games_memory_and_states.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(all_games, ensure_ascii=False, indent=2), encoding="utf-8")
    total_states = sum(len(g["states"]) for g in all_games.values())
    return {
        "status": "ok",
        "source": "repo_files",
        "games_exported": len(all_games),
        "states_total": total_states,
        "file": str(out_file),
    }


def harvest_all_stable_retro() -> dict:
    try:
        import stable_retro
    except ImportError:
        # 未 pip 安装时退回「直接读已 clone 的仓库」——1072 款 data.json 已在本地，
        # 不必为了导索引去装 stable-retro（需编译、体积大）
        fallback = harvest_stable_retro_from_repo()
        if fallback.get("status") == "ok":
            fallback["hint"] = "未安装 stable_retro 包，已直接从已 clone 的仓库读取 data.json"
            return fallback
        return {
            "status": "not_installed",
            "hint": "请先运行 py -3 -u _工具脚本/harvest_all_resources.py --pull-repos 拉取 stable-retro 仓库",
            "fallback": fallback,
        }

    all_games = {}
    for split_name in ("stable", "experimental", "contrib"):
        try:
            integrations = getattr(stable_retro.data.Integrations, split_name.upper(), None)
            games = stable_retro.data.list_games(integrations) if integrations else stable_retro.data.list_games()
        except Exception:
            games = stable_retro.data.list_games()
        for game in games:
            if game in all_games:
                continue
            try:
                states = stable_retro.data.list_states(game)
                data_path = stable_retro.data.get_file_path(game, "data.json")
                scen_path = stable_retro.data.get_file_path(game, "scenario.json")
                vars_info = {}
                if data_path and os.path.isfile(data_path):
                    vars_info = json.loads(Path(data_path).read_text(encoding="utf-8")).get("info", {})
                all_games[game] = {
                    "split": split_name,
                    "states": states,
                    "data_json_path": str(data_path) if data_path else None,
                    "scenario_json_path": str(scen_path) if scen_path else None,
                    "variables": vars_info,
                }
            except Exception:
                continue

    out_file = OUT_DIR / "all_1000_stable_retro_games_memory_and_states.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(all_games, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "ok", "games_exported": len(all_games), "file": str(out_file)}


# ============================================================================
# 2. 全量收割并解析本地 libretro-database/cht 下 25,000+ 个 .cht 金手指
# ============================================================================
UNLOCK_RE = re.compile(
    r"weapon|energy|ammo|infinite|all\s+|have\s+|unlock|armor|soul|magic|power|beam|bomb|cutter|fire|ice|thunder|magnet|hadoken|invinc|level\s*select|character|modifier",
    re.I,
)


def _quick_extract_cht_unlocks(cht_path: Path) -> list[dict]:
    try:
        text = cht_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    kv = {}
    for line in text.splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        k, v = line.split("=", 1)
        kv[k.strip()] = v.strip().strip('"')
    total = int(kv.get("cheats", 0) or 0)
    unlocks = []
    for i in range(min(total, 150)):
        desc = kv.get(f"cheat{i}_desc", "")
        if not UNLOCK_RE.search(desc):
            continue
        code = kv.get(f"cheat{i}_code", "")
        addr = kv.get(f"cheat{i}_address", "")
        val = kv.get(f"cheat{i}_value", "")
        unlocks.append({"desc": desc, "code": code, "addr": addr, "val": val})
    return unlocks


def harvest_all_libretro_chts() -> dict:
    if not CHT_ROOT.is_dir():
        return {"status": "missing_cht_root", "path": str(CHT_ROOT)}

    platforms_summary = {}
    extracted_unlock_db = {}
    total_files = 0
    total_unlock_entries = 0

    for plat_dir in sorted(CHT_ROOT.iterdir()):
        if not plat_dir.is_dir():
            continue
        cht_files = sorted(plat_dir.glob("*.cht"))
        if not cht_files:
            continue
        plat_name = plat_dir.name
        platforms_summary[plat_name] = {
            "count": len(cht_files),
            "dir": str(plat_dir),
            "sample_files": [p.name for p in cht_files[:15]],
        }
        total_files += len(cht_files)

        # 提取重点主机平台的全要素解锁条目
        if any(k in plat_name for k in ("Nintendo", "Sega", "Sony", "FBNeo", "NEC", "SNK", "Arcade")):
            plat_unlocks = {}
            for pf in cht_files:
                u = _quick_extract_cht_unlocks(pf)
                if u:
                    plat_unlocks[pf.stem] = u
                    total_unlock_entries += len(u)
            if plat_unlocks:
                extracted_unlock_db[plat_name] = plat_unlocks

    idx_file = OUT_DIR / "all_25000_libretro_cht_master_index.json"
    idx_file.parent.mkdir(parents=True, exist_ok=True)
    idx_file.write_text(
        json.dumps({"total_cht_files": total_files, "platforms": platforms_summary}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    unlock_file = OUT_DIR / "all_platforms_extracted_unlock_cheats.json"
    unlock_file.write_text(
        json.dumps(
            {"total_unlock_entries": total_unlock_entries, "by_platform": extracted_unlock_db},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "status": "ok",
        "total_cht_files": total_files,
        "total_unlock_entries_extracted": total_unlock_entries,
        "master_index_file": str(idx_file),
        "unlock_cheats_file": str(unlock_file),
    }


# ============================================================================
# 3. 扫描除天马6T外的全部 7 大本地与网盘资源池（含 Eden 裸库、爆款收录、PortMaster 等）
# ============================================================================
def _count_tree(root: Path, cap: int = 300000) -> dict:
    """受控遍历：统计文件/子目录数，超过 cap 条即停，避免卡在大目录上。"""
    if not root.is_dir():
        return {"exists": False, "path": str(root)}
    files = dirs = 0
    total_bytes = 0
    truncated = False
    try:
        stack = [str(root)]
        while stack:
            cur = stack.pop()
            try:
                with os.scandir(cur) as it:
                    for e in it:
                        if files + dirs >= cap:
                            truncated = True
                            stack.clear()
                            break
                        try:
                            if e.is_dir(follow_symlinks=False):
                                dirs += 1
                                stack.append(e.path)
                            elif e.is_file(follow_symlinks=False):
                                files += 1
                                total_bytes += e.stat(follow_symlinks=False).st_size
                        except OSError:
                            continue
            except OSError:
                continue
    except Exception as e:
        return {"exists": True, "path": str(root), "error": str(e)[:120]}
    return {
        "exists": True,
        "path": str(root),
        "files": files,
        "dirs": dirs,
        "size_mb": round(total_bytes / 1048576, 1),
        "truncated": truncated,
    }


def scan_all_7_resource_pools() -> dict:
    pools = {
        "1_rescue_pool_including_eden": {
            "dir": str(PROJECT_ROOT / "04-游戏资源库" / "下架抢救"),
            "tsv": str(PROJECT_ROOT / "06-资讯监控" / "下架抢救登记表.tsv"),
            "highlights": [
                "eden-git-bare (git.eden-emu.dev/eden-emu/eden.git 217MB 完整裸库)",
                "citron-neo/emulator",
                "suyu-emu/suyu-v0.0.4",
                "NextendoNetwork/Ryujinx-Nextendo",
                "skyline-dev/skyline",
                "hottabxp/re3 (GTA3/VC)",
                "Cannonball (OutRun Engine)",
            ],
        },
        "2_curated_blockbusters_pool": {
            "dir": str(PROJECT_ROOT / "04-游戏资源库" / "爆款收录"),
            "tsv": str(PROJECT_ROOT / "06-资讯监控" / "合法收录登记表.tsv"),
            "highlights": [
                "Model2 NX / SuperModel NX (世嘉街机移植)",
                "SwitchWaker (塞尔达风之杖重编译)",
                "sa2-nx (索尼克大冒险2)",
                "MarathonRecomp-NX (索尼克06静态重编译)",
                "ioQuake3 五平台成品包",
            ],
        },
        "3_portmaster_legal_pool": {
            "dir": str(PROJECT_ROOT / "04-游戏资源库" / "公版与开源游戏" / "ports全量合法池"),
            "note": "632 个掌机移植包（含 548 个 rtr:true 自带合法游戏素材即开即玩包）",
        },
        "4_ps5_port_store_pool": {
            "dir": str(PROJECT_ROOT / "06-资讯监控" / "PS5移植商店" / "成品包"),
            "tsv": str(PROJECT_ROOT / "06-资讯监控" / "PS5移植商店" / "获取台账.tsv"),
        },
        "5_tas_movies_and_roms_pool": {
            "dir": str(PROJECT_ROOT / "04-游戏资源库" / "TAS输入录像库"),
            "user_roms": str(PROJECT_ROOT / "04-游戏资源库" / "自己ROM放这里"),
            "saves_and_cheats": str(PROJECT_ROOT / "04-游戏资源库" / "存档与金手指"),
        },
        "6_cloned_53_upstream_repos": {
            "dir": str(PROJECT_ROOT / "02-模拟器库" / "已clone仓库"),
        },
        "7_openlist_mounted_netdisks": {
            "endpoint": "http://127.0.0.1:5244",
            "mounts": [],
        },
    }

    # 若本地已有 all_sources_scanner.py，联动探测实际文件数与 OpenList 挂载点
    # 说明：该脚本本轮尚未拿到（在云盘「仍缺 7 个」名单里），故此处做多路径兜底；
    # 找不到时仍会给出本地实测文件数，避免清单变成空壳。
    scanner_py = next(
        (p for p in (PROJECT_ROOT / "all_sources_scanner.py",
                     PROJECT_ROOT / "_工具脚本" / "all_sources_scanner.py")
         if p.is_file()),
        None,
    )
    if scanner_py:
        try:
            r = subprocess.run(
                [sys.executable, "-u", str(scanner_py), "overview"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
            )
            if r.returncode == 0 and r.stdout.strip():
                pools["live_overview"] = json.loads(r.stdout)
        except Exception:
            pass

    # 兜底：直接对每个 pool 的 dir 做一次受控遍历，统计真实文件数
    for key, val in pools.items():
        if isinstance(val, dict) and val.get("dir"):
            val["local_stat"] = _count_tree(Path(val["dir"]))

    out_file = OUT_DIR / "all_7_resource_pools_manifest.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(pools, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "ok",
        "manifest_file": str(out_file),
        "pools_count": 7,
        "live_scan": bool(scanner_py),
        "scanner_used": str(scanner_py) if scanner_py else None,
    }


def install_python_libs(proxy: str = "") -> dict:
    pkgs = ["stable-retro", "gymnasium[other]", "moviepy", "pyboy", "diambra", "diambra-arena"]
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade"] + pkgs
    if proxy:
        cmd += ["--proxy", proxy]
    print(f"[PIP 安装] {' '.join(cmd)} ...")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return {"packages": pkgs, "returncode": r.returncode, "tail": (r.stdout or r.stderr)[-500:]}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true", help="拉取全部 12 个开源仓库 + 导出全量内存表与金手指库 + 扫描 7 大资源池")
    ap.add_argument("--pull-repos", action="store_true", help="拉取全部 12 个开源仓库到本地文件夹")
    ap.add_argument("--pip-install", action="store_true", help="安装 stable-retro / pyboy / diambra 等 Python 现成库")
    ap.add_argument("--harvest-only", action="store_true", help="仅运行本地 stable-retro / libretro-cht / 7大资源池全量导出")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    proxy = detect_proxy()
    report = {"proxy": proxy, "repos": [], "pip": None, "stable_retro": None, "libretro_cht": None, "resource_pools": None}

    if args.all or args.pull_repos:
        for cfg in ALL_12_REPOS:
            try:
                report["repos"].append(pull_single_repo(cfg, DEST_REPOS_ROOT, proxy=proxy))
            except Exception as e:
                report["repos"].append({"id": cfg["id"], "status": "error", "error": str(e)})

    if args.all or args.pip_install:
        report["pip"] = install_python_libs(proxy=proxy)

    if args.all or args.harvest_only or not (args.pull_repos or args.pip_install):
        report["stable_retro"] = harvest_all_stable_retro()
        report["libretro_cht"] = harvest_all_libretro_chts()
        report["resource_pools"] = scan_all_7_resource_pools()

    summary_path = OUT_DIR / "harvest_execution_report.json"
    summary_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
